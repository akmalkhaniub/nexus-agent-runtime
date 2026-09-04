"""
nexus_runtime.core.graph
~~~~~~~~~~~~~~~~~~~~~~~~

Asynchronous, stateful graph-based orchestration engine.
Supports cyclical workflows, conditional routing, state reduction, checkpointing,
and event-driven streaming.
"""

from __future__ import annotations

import asyncio
import inspect
import time
import uuid
from typing import Any, AsyncIterator, Callable, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field

from nexus_runtime.core.state import AgentState, StateSnapshot
from nexus_runtime.core.checkpointer import BaseCheckpointer, InMemoryCheckpointer


START = "__start__"
END = "__end__"


class GraphEvent(BaseModel):
    """Event emitted during graph execution."""
    event_type: Literal[
        "workflow_started",
        "node_started",
        "node_finished",
        "edge_traversed",
        "workflow_paused",
        "workflow_completed",
        "workflow_failed",
    ]
    run_id: str
    step_index: int
    node_name: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)


NodeCallable = Callable[[AgentState], Union[AgentState, Dict[str, Any], Any]]
RouterCallable = Callable[[AgentState], Union[str, Any]]


class StateGraph:
    """
    Builder for directed, cyclical or acyclic state execution graphs.
    """

    def __init__(self) -> None:
        self._nodes: Dict[str, NodeCallable] = {}
        self._edges: Dict[str, str] = {}
        self._conditional_edges: Dict[str, tuple[RouterCallable, Optional[Dict[str, str]]]] = {}
        self._entry_point: Optional[str] = None
        self._finish_nodes: set[str] = {END}

    def add_node(self, name: str, fn: NodeCallable) -> StateGraph:
        if name in (START, END):
            raise ValueError(f"Reserved node name: {name}")
        self._nodes[name] = fn
        return self

    def add_edge(self, source: str, target: str) -> StateGraph:
        if source == START:
            self._entry_point = target
            return self
        if source not in self._nodes and source != START:
            raise ValueError(f"Source node '{source}' must be registered before adding edges.")
        if target not in self._nodes and target != END:
            raise ValueError(f"Target node '{target}' must be registered or be END.")
        self._edges[source] = target
        return self

    def add_conditional_edges(
        self,
        source: str,
        router: RouterCallable,
        path_map: Optional[Dict[str, str]] = None,
    ) -> StateGraph:
        if source not in self._nodes:
            raise ValueError(f"Source node '{source}' must be registered before adding conditional edges.")
        self._conditional_edges[source] = (router, path_map)
        return self

    def set_entry_point(self, node_name: str) -> StateGraph:
        if node_name not in self._nodes:
            raise ValueError(f"Entry point node '{node_name}' is not registered.")
        self._entry_point = node_name
        return self

    def set_finish_point(self, node_name: str) -> StateGraph:
        self._finish_nodes.add(node_name)
        return self

    def compile(self, checkpointer: Optional[BaseCheckpointer] = None) -> CompiledGraph:
        if not self._entry_point:
            raise ValueError("StateGraph requires an entry point. Call set_entry_point() or add_edge(START, ...).")
        return CompiledGraph(
            nodes=self._nodes,
            edges=self._edges,
            conditional_edges=self._conditional_edges,
            entry_point=self._entry_point,
            finish_nodes=self._finish_nodes,
            checkpointer=checkpointer or InMemoryCheckpointer(),
        )


class CompiledGraph:
    """
    Executable compiled representation of a StateGraph.
    Manages node invocations, conditional routing, loop threshold guards, and state persistence.
    """

    def __init__(
        self,
        nodes: Dict[str, NodeCallable],
        edges: Dict[str, str],
        conditional_edges: Dict[str, tuple[RouterCallable, Optional[Dict[str, str]]]],
        entry_point: str,
        finish_nodes: set[str],
        checkpointer: BaseCheckpointer,
    ) -> None:
        self.nodes = nodes
        self.edges = edges
        self.conditional_edges = conditional_edges
        self.entry_point = entry_point
        self.finish_nodes = finish_nodes
        self.checkpointer = checkpointer

    async def _execute_callable(self, fn: Callable, state: AgentState) -> Any:
        if inspect.iscoroutinefunction(fn):
            return await fn(state)
        return fn(state)

    async def stream(
        self,
        initial_state: Union[AgentState, Dict[str, Any]],
        run_id: Optional[str] = None,
        max_iterations: int = 50,
    ) -> AsyncIterator[GraphEvent]:
        """
        Executes the graph asynchronously and yields GraphEvents in real time.
        """
        run_id = run_id or f"run_{uuid.uuid4().hex[:12]}"
        state = initial_state if isinstance(initial_state, AgentState) else AgentState(values=initial_state)

        step_index = 0
        current_node = self.entry_point

        # Save initial checkpoint
        initial_snap = state.snapshot(step_index=step_index, node_name=START)
        await self.checkpointer.save_checkpoint(run_id, initial_snap)

        yield GraphEvent(
            event_type="workflow_started",
            run_id=run_id,
            step_index=step_index,
            node_name=START,
            data={"entry_point": self.entry_point, "initial_state": state.to_dict()},
        )

        while current_node and current_node != END:
            step_index += 1
            if step_index > max_iterations:
                err_msg = f"Max loop iterations ({max_iterations}) exceeded in run {run_id}."
                yield GraphEvent(
                    event_type="workflow_failed",
                    run_id=run_id,
                    step_index=step_index,
                    node_name=current_node,
                    data={"error": err_msg},
                )
                raise RuntimeError(err_msg)

            if current_node not in self.nodes:
                err_msg = f"Node '{current_node}' not found in compiled graph nodes."
                yield GraphEvent(
                    event_type="workflow_failed",
                    run_id=run_id,
                    step_index=step_index,
                    node_name=current_node,
                    data={"error": err_msg},
                )
                raise KeyError(err_msg)

            yield GraphEvent(
                event_type="node_started",
                run_id=run_id,
                step_index=step_index,
                node_name=current_node,
                data={"values": state.values},
            )

            start_time = time.time()
            node_fn = self.nodes[current_node]

            try:
                result = await self._execute_callable(node_fn, state)
            except Exception as exc:
                yield GraphEvent(
                    event_type="workflow_failed",
                    run_id=run_id,
                    step_index=step_index,
                    node_name=current_node,
                    data={"error": str(exc), "error_type": type(exc).__name__},
                )
                raise

            duration_ms = (time.time() - start_time) * 1000

            # State update reduction
            state_delta: Dict[str, Any] = {}
            if isinstance(result, AgentState):
                state = result
            elif isinstance(result, dict):
                state.update(result)
                state_delta = result

            # Save state checkpoint after node completion
            snap = state.snapshot(step_index=step_index, node_name=current_node)
            await self.checkpointer.save_checkpoint(run_id, snap)

            yield GraphEvent(
                event_type="node_finished",
                run_id=run_id,
                step_index=step_index,
                node_name=current_node,
                data={
                    "duration_ms": duration_ms,
                    "state_delta": state_delta,
                    "current_state": state.to_dict(),
                },
            )

            # Check if workflow pause was requested (e.g. human approval)
            if state.get("__pause_requested__", False):
                yield GraphEvent(
                    event_type="workflow_paused",
                    run_id=run_id,
                    step_index=step_index,
                    node_name=current_node,
                    data={
                        "reason": state.get("__pause_reason__", "Human approval required"),
                        "checkpoint_step": step_index,
                    },
                )
                return

            # Determine next node
            next_node: Optional[str] = None
            if current_node in self.conditional_edges:
                router, path_map = self.conditional_edges[current_node]
                route_key = await self._execute_callable(router, state)
                if path_map:
                    next_node = path_map.get(str(route_key), str(route_key))
                else:
                    next_node = str(route_key)
            elif current_node in self.edges:
                next_node = self.edges[current_node]
            elif current_node in self.finish_nodes:
                next_node = END

            yield GraphEvent(
                event_type="edge_traversed",
                run_id=run_id,
                step_index=step_index,
                node_name=current_node,
                data={"from_node": current_node, "to_node": next_node},
            )

            current_node = next_node

        yield GraphEvent(
            event_type="workflow_completed",
            run_id=run_id,
            step_index=step_index,
            node_name=END,
            data={"final_state": state.to_dict(), "total_steps": step_index},
        )

    async def invoke(
        self,
        initial_state: Union[AgentState, Dict[str, Any]],
        run_id: Optional[str] = None,
        max_iterations: int = 50,
    ) -> AgentState:
        """
        Executes the graph to completion and returns the final AgentState.
        """
        final_state: Optional[AgentState] = None
        state_dict: Dict[str, Any] = {}

        async for event in self.stream(initial_state, run_id=run_id, max_iterations=max_iterations):
            if event.event_type == "node_finished":
                state_dict = event.data.get("current_state", {})
            elif event.event_type == "workflow_completed":
                state_dict = event.data.get("final_state", {})

        if state_dict:
            from nexus_runtime.core.state import Message
            values = state_dict.get("values", {})
            messages = [Message(**m) for m in state_dict.get("messages", [])]
            metadata = state_dict.get("metadata", {})
            final_state = AgentState(values=values, messages=messages, metadata=metadata)
        else:
            final_state = initial_state if isinstance(initial_state, AgentState) else AgentState(values=initial_state)

        return final_state
