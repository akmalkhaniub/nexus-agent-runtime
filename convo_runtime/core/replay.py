"""
convo_runtime.core.replay
~~~~~~~~~~~~~~~~~~~~~~~~~

Deterministic replay engine for time-travel debugging and workflow reproduction.
Allows rewinding to an arbitrary historical step index and resuming graph execution
with original or patched state parameters.
"""

from __future__ import annotations

import uuid
from typing import Any, AsyncIterator, Dict, Optional, Union
from pydantic import BaseModel, Field

from convo_runtime.core.checkpointer import BaseCheckpointer
from convo_runtime.core.graph import CompiledGraph, GraphEvent
from convo_runtime.core.state import AgentState, StateSnapshot


class ReplayResult(BaseModel):
    original_run_id: str
    replay_run_id: str
    from_step_index: int
    restored_node: str
    final_state: Dict[str, Any]
    total_replay_steps: int


class DeterministicReplayEngine:
    """
    Manages deterministic replay of historical agent runs.
    """

    def __init__(self, checkpointer: BaseCheckpointer) -> None:
        self.checkpointer = checkpointer

    async def get_checkpoints_for_run(self, run_id: str) -> list[StateSnapshot]:
        """Retrieves chronological state checkpoints for inspection."""
        return await self.checkpointer.list_checkpoints(run_id)

    async def replay_from_step(
        self,
        compiled_graph: CompiledGraph,
        original_run_id: str,
        step_index: int,
        state_overrides: Optional[Dict[str, Any]] = None,
        new_run_id: Optional[str] = None,
    ) -> ReplayResult:
        """
        Loads the snapshot at step_index, applies optional state overrides,
        and re-runs the graph from that point onwards to completion.
        """
        snapshot = await self.checkpointer.get_checkpoint(original_run_id, step_index)
        if not snapshot:
            raise ValueError(f"Checkpoint at step {step_index} not found for run '{original_run_id}'.")

        replay_id = new_run_id or f"{original_run_id}_replay_s{step_index}_{uuid.uuid4().hex[:6]}"
        restored_state = AgentState.from_snapshot(snapshot)

        if state_overrides:
            restored_state.update(state_overrides)

        # Clone the compiled graph with entry point set to the restored node
        from convo_runtime.core.graph import StateGraph

        # Build a sub-graph starting from restored node
        start_node = snapshot.node_name if snapshot.node_name in compiled_graph.nodes else compiled_graph.entry_point
        sub_graph = StateGraph()
        for name, fn in compiled_graph.nodes.items():
            sub_graph.add_node(name, fn)
        for src, tgt in compiled_graph.edges.items():
            sub_graph.add_edge(src, tgt)
        for src, (router, path_map) in compiled_graph.conditional_edges.items():
            sub_graph.add_conditional_edges(src, router, path_map)
        for finish in compiled_graph.finish_nodes:
            sub_graph.set_finish_point(finish)

        sub_graph.set_entry_point(start_node)
        replayed_compiled = sub_graph.compile(checkpointer=self.checkpointer)

        final_state = await replayed_compiled.invoke(restored_state, run_id=replay_id)

        # Count replay steps
        replay_snaps = await self.checkpointer.list_checkpoints(replay_id)

        return ReplayResult(
            original_run_id=original_run_id,
            replay_run_id=replay_id,
            from_step_index=step_index,
            restored_node=start_node,
            final_state=final_state.to_dict(),
            total_replay_steps=len(replay_snaps),
        )

    async def stream_replay_from_step(
        self,
        compiled_graph: CompiledGraph,
        original_run_id: str,
        step_index: int,
        state_overrides: Optional[Dict[str, Any]] = None,
        new_run_id: Optional[str] = None,
    ) -> AsyncIterator[GraphEvent]:
        """
        Streams events of a replayed workflow in real-time.
        """
        snapshot = await self.checkpointer.get_checkpoint(original_run_id, step_index)
        if not snapshot:
            raise ValueError(f"Checkpoint at step {step_index} not found for run '{original_run_id}'.")

        replay_id = new_run_id or f"{original_run_id}_replay_s{step_index}_{uuid.uuid4().hex[:6]}"
        restored_state = AgentState.from_snapshot(snapshot)

        if state_overrides:
            restored_state.update(state_overrides)

        from convo_runtime.core.graph import StateGraph

        start_node = snapshot.node_name if snapshot.node_name in compiled_graph.nodes else compiled_graph.entry_point
        sub_graph = StateGraph()
        for name, fn in compiled_graph.nodes.items():
            sub_graph.add_node(name, fn)
        for src, tgt in compiled_graph.edges.items():
            sub_graph.add_edge(src, tgt)
        for src, (router, path_map) in compiled_graph.conditional_edges.items():
            sub_graph.add_conditional_edges(src, router, path_map)
        for finish in compiled_graph.finish_nodes:
            sub_graph.set_finish_point(finish)

        sub_graph.set_entry_point(start_node)
        replayed_compiled = sub_graph.compile(checkpointer=self.checkpointer)

        async for event in replayed_compiled.stream(restored_state, run_id=replay_id):
            yield event
