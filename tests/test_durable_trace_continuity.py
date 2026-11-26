"""Tests for durable OpenTelemetry GenAI trace continuity and replay deduplication."""

from __future__ import annotations

import pytest

from nexus_runtime.core.checkpointer import InMemoryCheckpointer, SQLiteCheckpointer
from nexus_runtime.core.graph import END, StateGraph
from nexus_runtime.core.replay import DeterministicReplayEngine
from nexus_runtime.core.state import AgentState
from nexus_runtime.telemetry.otel import (
    clear_recorded_spans,
    get_recorded_spans,
    trace_tool_span,
    trace_workflow_span,
)


@pytest.mark.asyncio
async def test_traceparent_persists_and_continues_across_sqlite_hitl_resume(tmp_path) -> None:
    clear_recorded_spans()
    db_file = str(tmp_path / "durable_trace.db")
    cp_1 = SQLiteCheckpointer(db_path=db_file)

    def build_graph(cp: SQLiteCheckpointer):
        g = StateGraph()

        def draft(state: AgentState):
            return {"drafted": True}

        def approve_gate(state: AgentState):
            return {"__pause_requested__": True, "__pause_reason__": "HITL signoff"}

        def publish(state: AgentState):
            return {"published": True, "reviewer": state.get("reviewer")}

        g.add_node("draft", draft)
        g.add_node("approve_gate", approve_gate)
        g.add_node("publish", publish)
        g.set_entry_point("draft")
        g.add_edge("draft", "approve_gate")
        g.add_edge("approve_gate", "publish")
        g.add_edge("publish", END)
        return g.compile(checkpointer=cp)

    compiled_1 = build_graph(cp_1)
    events = [ev async for ev in compiled_1.stream({}, run_id="run_otel_hitl_1")]
    assert any(e.event_type == "workflow_paused" for e in events)

    # Verify the checkpoint persisted the W3C traceparent
    paused_snap = await cp_1.get_latest_checkpoint("run_otel_hitl_1")
    assert paused_snap is not None
    saved_tp = paused_snap.metadata.get("trace_context", {}).get("traceparent", "")
    assert saved_tp.startswith("00-")
    original_trace_id = saved_tp.split("-")[1]

    # Simulate fresh process restart with a new checkpointer instance
    cp_2 = SQLiteCheckpointer(db_path=db_file)
    compiled_2 = build_graph(cp_2)
    final_state = await compiled_2.resume("run_otel_hitl_1", state_updates={"reviewer": "staff-eng"})
    assert final_state.get("published") is True

    spans = get_recorded_spans()
    resume_span = next(s for s in spans if s.name == "resume:run_otel_hitl_1")
    publish_span = next(s for s in spans if s.name == "node:publish")

    assert format(resume_span.context.trace_id, "032x") == original_trace_id
    assert format(publish_span.context.trace_id, "032x") == original_trace_id
    assert resume_span.attributes["gen_ai.operation.name"] == "invoke_workflow"
    assert resume_span.attributes["durable.execution.replayed"] is False
    assert publish_span.attributes["gen_ai.operation.name"] == "invoke_agent"
    assert publish_span.attributes["durable.step.idempotency_key"] == "run_otel_hitl_1:step:3"


@pytest.mark.asyncio
async def test_deterministic_replay_links_trace_and_marks_replayed_spans() -> None:
    clear_recorded_spans()
    cp = InMemoryCheckpointer()
    replay_engine = DeterministicReplayEngine(checkpointer=cp)

    g = StateGraph()
    g.add_node("ingest", lambda s: {"score": 40})
    g.add_node("decide", lambda s: {"decision": "PASS" if s.get("score", 0) >= 80 else "FAIL"})
    g.set_entry_point("ingest")
    g.add_edge("ingest", "decide")
    g.add_edge("decide", END)
    compiled = g.compile(checkpointer=cp)

    await compiled.invoke({}, run_id="run_orig_trace")
    orig_snap = await cp.get_checkpoint("run_orig_trace", 2)
    assert orig_snap is not None
    orig_trace_id = orig_snap.metadata["trace_context"]["traceparent"].split("-")[1]

    clear_recorded_spans()
    replay_res = await replay_engine.replay_from_step(
        compiled_graph=compiled,
        original_run_id="run_orig_trace",
        step_index=2,
        state_overrides={"score": 95},
        new_run_id="run_replay_trace",
    )
    assert replay_res.final_state["values"]["decision"] == "PASS"

    replay_spans = get_recorded_spans()
    root_replay = next(s for s in replay_spans if s.name == "replay:run_replay_trace")
    node_replay = next(s for s in replay_spans if s.name == "node:decide")

    assert format(root_replay.context.trace_id, "032x") == orig_trace_id
    assert format(node_replay.context.trace_id, "032x") == orig_trace_id
    assert root_replay.attributes["gen_ai.operation.name"] == "replay_workflow"
    assert root_replay.attributes["durable.execution.replayed"] is True
    assert root_replay.attributes["durable.replay.source_run_id"] == "run_orig_trace"
    assert root_replay.attributes["durable.replay.from_step"] == 2
    assert node_replay.attributes["durable.execution.replayed"] is True


def test_tool_span_emits_genai_semantic_and_idempotency_attributes() -> None:
    clear_recorded_spans()
    with trace_workflow_span("agent.run", run_id="run_tool_1", tenant_id="t1"):
        with trace_tool_span(
            "sql_query",
            call_id="call_99",
            parameters={"limit": 10},
            run_id="run_tool_1",
            step_index=4,
            is_replay=False,
        ):
            pass

    spans = get_recorded_spans()
    tool_span = next(s for s in spans if s.name == "tool:sql_query")
    assert tool_span.attributes["gen_ai.operation.name"] == "execute_tool"
    assert tool_span.attributes["gen_ai.tool.name"] == "sql_query"
    assert tool_span.attributes["gen_ai.tool.call.id"] == "call_99"
    assert tool_span.attributes["durable.execution.replayed"] is False
    assert tool_span.attributes["durable.step.idempotency_key"] == "run_tool_1:step:4:sql_query"
