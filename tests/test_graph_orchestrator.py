"""
tests.test_graph_orchestrator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Unit & integration tests for StateGraph engine, conditional routing,
cyclical loops, and checkpointing.
"""

import pytest
from convo_runtime.core.graph import StateGraph, START, END, GraphEvent
from convo_runtime.core.state import AgentState
from convo_runtime.core.checkpointer import InMemoryCheckpointer


@pytest.mark.asyncio
async def test_linear_graph_execution():
    graph = StateGraph()

    async def step_a(state: AgentState):
        return {"val": state.get("val", 0) + 1}

    async def step_b(state: AgentState):
        return {"val": state.get("val") * 2}

    graph.add_node("A", step_a)
    graph.add_node("B", step_b)
    graph.set_entry_point("A")
    graph.add_edge("A", "B")
    graph.add_edge("B", END)

    compiled = graph.compile()
    final_state = await compiled.invoke({"val": 5})

    # (5 + 1) * 2 = 12
    assert final_state.get("val") == 12


@pytest.mark.asyncio
async def test_conditional_branching():
    graph = StateGraph()

    def node_eval(state: AgentState):
        score = state.get("score", 0)
        return {"category": "high" if score >= 80 else "low"}

    def node_high(state: AgentState):
        return {"action": "auto_approve"}

    def node_low(state: AgentState):
        return {"action": "manual_review"}

    def router(state: AgentState) -> str:
        return state.get("category")

    graph.add_node("eval", node_eval)
    graph.add_node("high", node_high)
    graph.add_node("low", node_low)

    graph.set_entry_point("eval")
    graph.add_conditional_edges("eval", router, {"high": "high", "low": "low"})
    graph.add_edge("high", END)
    graph.add_edge("low", END)

    compiled = graph.compile()

    res_high = await compiled.invoke({"score": 95})
    assert res_high.get("action") == "auto_approve"

    res_low = await compiled.invoke({"score": 40})
    assert res_low.get("action") == "manual_review"


@pytest.mark.asyncio
async def test_cyclical_graph_with_termination():
    graph = StateGraph()

    def loop_node(state: AgentState):
        count = state.get("counter", 0) + 1
        return {"counter": count}

    def should_continue(state: AgentState) -> str:
        if state.get("counter") >= 5:
            return "done"
        return "continue"

    graph.add_node("incrementer", loop_node)
    graph.set_entry_point("incrementer")
    graph.add_conditional_edges(
        "incrementer",
        should_continue,
        {"continue": "incrementer", "done": END},
    )

    compiled = graph.compile()
    final_state = await compiled.invoke({"counter": 0})
    assert final_state.get("counter") == 5


@pytest.mark.asyncio
async def test_checkpointing_during_execution():
    checkpointer = InMemoryCheckpointer()
    graph = StateGraph()

    def step_one(state: AgentState):
        return {"step": 1}

    def step_two(state: AgentState):
        return {"step": 2}

    graph.add_node("one", step_one)
    graph.add_node("two", step_two)
    graph.set_entry_point("one")
    graph.add_edge("one", "two")
    graph.add_edge("two", END)

    compiled = graph.compile(checkpointer=checkpointer)
    run_id = "run_test_chk_123"
    await compiled.invoke({"initial": True}, run_id=run_id)

    checkpoints = await checkpointer.list_checkpoints(run_id)
    assert len(checkpoints) == 3  # Step 0 (START), Step 1 (one), Step 2 (two)
    assert checkpoints[0].node_name == START
    assert checkpoints[1].node_name == "one"
    assert checkpoints[2].node_name == "two"
    assert checkpoints[2].values.get("step") == 2


@pytest.mark.asyncio
async def test_graph_event_streaming():
    graph = StateGraph()

    def work_node(state: AgentState):
        return {"processed": True}

    graph.add_node("work", work_node)
    graph.set_entry_point("work")
    graph.add_edge("work", END)

    compiled = graph.compile()
    events = []
    async for ev in compiled.stream({"processed": False}):
        events.append(ev)

    event_types = [e.event_type for e in events]
    assert "workflow_started" in event_types
    assert "node_started" in event_types
    assert "node_finished" in event_types
    assert "workflow_completed" in event_types
