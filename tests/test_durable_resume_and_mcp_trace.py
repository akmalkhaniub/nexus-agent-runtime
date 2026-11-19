"""Tests for durable HITL pause/resume, failure state isolation, and OTel-over-MCP trace propagation."""

from __future__ import annotations

import pytest

from nexus_registry.mcp_adapter import ExternalMCPClientAdapter
from nexus_runtime.core.checkpointer import SQLiteCheckpointer
from nexus_runtime.core.graph import END, StateGraph
from nexus_runtime.core.state import AgentState
from nexus_runtime.telemetry.otel import trace_workflow_span


@pytest.mark.asyncio
async def test_durable_pause_and_resume_across_sqlite_checkpointer(tmp_path) -> None:
    db_file = str(tmp_path / "durable_runs.db")
    checkpointer = SQLiteCheckpointer(db_path=db_file)

    def build_graph(cp: SQLiteCheckpointer):
        graph = StateGraph()

        def prepare(state: AgentState):
            return {"prepared": True, "amount": 4500}

        def hitl_gate(state: AgentState):
            return {
                "__pause_requested__": True,
                "__pause_reason__": "Manager approval required above $1000",
                "awaiting_approval": True,
            }

        def execute_payout(state: AgentState):
            if not state.get("approved"):
                raise RuntimeError("Cannot execute without approval")
            return {"payout_status": "DISBURSED", "approved_by": state.get("approved_by")}

        graph.add_node("prepare", prepare)
        graph.add_node("hitl_gate", hitl_gate)
        graph.add_node("execute_payout", execute_payout)
        graph.set_entry_point("prepare")
        graph.add_edge("prepare", "hitl_gate")
        graph.add_edge("hitl_gate", "execute_payout")
        graph.add_edge("execute_payout", END)
        return graph.compile(checkpointer=cp)

    compiled_1 = build_graph(checkpointer)
    events = [ev async for ev in compiled_1.stream({}, run_id="run_durable_hitl_1")]
    event_types = [e.event_type for e in events]
    assert "workflow_paused" in event_types
    assert "workflow_completed" not in event_types

    # Simulate process restart with a fresh SQLiteCheckpointer & CompiledGraph instance
    checkpointer_2 = SQLiteCheckpointer(db_path=db_file)
    compiled_2 = build_graph(checkpointer_2)
    final_state = await compiled_2.resume(
        "run_durable_hitl_1",
        state_updates={"approved": True, "approved_by": "finance-director"},
    )
    assert final_state.get("prepared") is True
    assert final_state.get("payout_status") == "DISBURSED"
    assert final_state.get("approved_by") == "finance-director"
    assert final_state.get("__pause_requested__") is None


@pytest.mark.asyncio
async def test_failing_node_cannot_corrupt_preserved_state() -> None:
    graph = StateGraph()
    shared_initial = AgentState(values={"counter": 1, "items": ["safe"]})

    def step_ok(state: AgentState):
        return {"counter": state.get("counter", 0) + 1}

    def step_boom(state: AgentState):
        state["items"].append("corrupted_mutation")
        raise ValueError("Simulated node crash")

    graph.add_node("ok", step_ok)
    graph.add_node("boom", step_boom)
    graph.set_entry_point("ok")
    graph.add_edge("ok", "boom")
    graph.add_edge("boom", END)

    compiled = graph.compile()
    with pytest.raises(ValueError, match="Simulated node crash"):
        await compiled.invoke(shared_initial, run_id="run_fail_isolated")

    # Original caller state and last saved checkpoint remain uncorrupted
    assert shared_initial.get("items") == ["safe"]
    latest = await compiled.checkpointer.get_latest_checkpoint("run_fail_isolated")
    assert latest is not None
    assert latest.node_name == "ok"
    assert latest.values["items"] == ["safe"]
    assert latest.values["counter"] == 2


@pytest.mark.asyncio
async def test_external_mcp_client_injects_traceparent_into_meta() -> None:
    captured_payloads: list[dict] = []

    async def mock_transport(payload: dict) -> dict:
        captured_payloads.append(payload)
        return {
            "jsonrpc": "2.0",
            "id": payload.get("id"),
            "result": {"content": [{"type": "text", "text": "ok"}]},
        }

    adapter = ExternalMCPClientAdapter(server_name="mcp-gateway", transport_callable=mock_transport)

    with trace_workflow_span("agent.step", run_id="run_trace_1", tenant_id="tenant-alpha") as span:
        expected_trace_id = format(span.get_span_context().trace_id, "032x")
        res = await adapter.call_tool("attractor_lint_pipeline", {"dot_source": "digraph {}"})
        assert res == "ok"

    assert len(captured_payloads) == 1
    meta = captured_payloads[0]["params"]["_meta"]
    assert "traceparent" in meta
    parts = meta["traceparent"].split("-")
    assert len(parts) == 4
    assert parts[1] == expected_trace_id
