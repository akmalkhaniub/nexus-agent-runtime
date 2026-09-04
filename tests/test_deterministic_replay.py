"""
tests.test_deterministic_replay
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Tests for deterministic replay engine and time-travel state recovery.
"""

import pytest
from nexus_runtime.core.graph import StateGraph, END
from nexus_runtime.core.state import AgentState
from nexus_runtime.core.checkpointer import InMemoryCheckpointer
from nexus_runtime.core.replay import DeterministicReplayEngine


@pytest.mark.asyncio
async def test_deterministic_replay_from_checkpoint():
    checkpointer = InMemoryCheckpointer()
    replay_engine = DeterministicReplayEngine(checkpointer=checkpointer)

    graph = StateGraph()

    def step_collect_metrics(state: AgentState):
        return {"cpu": 95, "status": "high"}

    def step_diagnose(state: AgentState):
        cpu = state.get("cpu", 0)
        diagnosis = "CRITICAL_OVERHEAT" if cpu > 90 else "NORMAL"
        return {"diagnosis": diagnosis}

    def step_remediate(state: AgentState):
        diag = state.get("diagnosis")
        action = "RESTART" if diag == "CRITICAL_OVERHEAT" else "NOOP"
        return {"action": action}

    graph.add_node("collect", step_collect_metrics)
    graph.add_node("diagnose", step_diagnose)
    graph.add_node("remediate", step_remediate)

    graph.set_entry_point("collect")
    graph.add_edge("collect", "diagnose")
    graph.add_edge("diagnose", "remediate")
    graph.add_edge("remediate", END)

    compiled = graph.compile(checkpointer=checkpointer)

    original_run_id = "run_incident_orig_44"
    final_original = await compiled.invoke({}, run_id=original_run_id)

    assert final_original.get("action") == "RESTART"

    checkpoints = await checkpointer.list_checkpoints(original_run_id)
    assert len(checkpoints) == 4  # Start (0), collect (1), diagnose (2), remediate (3)

    # Replay from step 2 (diagnose), but override CPU to 50% (simulating lower reading)
    replay_res = await replay_engine.replay_from_step(
        compiled_graph=compiled,
        original_run_id=original_run_id,
        step_index=2,
        state_overrides={"cpu": 50},
        new_run_id="run_incident_replay_fixed",
    )

    assert replay_res.original_run_id == original_run_id
    assert replay_res.replay_run_id == "run_incident_replay_fixed"
    # Overridden CPU was 50, so diagnosis becomes NORMAL and action becomes NOOP
    assert replay_res.final_state["values"]["action"] == "NOOP"
    assert replay_res.final_state["values"]["diagnosis"] == "NORMAL"
