"""
nexus_runtime.api.routes_replay
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Deterministic replay and time-travel debugging endpoints.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from nexus_runtime.core.state import StateSnapshot, AgentState
from nexus_runtime.core.replay import DeterministicReplayEngine, ReplayResult
from nexus_runtime.core.planner import WorkflowPlanner


router = APIRouter(prefix="/api/v1/runs", tags=["Deterministic Replay"])


class ReplayRequest(BaseModel):
    step_index: int
    state_overrides: Dict[str, Any] = Field(default_factory=dict)
    new_run_id: Optional[str] = None


@router.get("/{run_id}/checkpoints", response_model=List[StateSnapshot])
async def list_checkpoints_for_run(
    run_id: str,
    request: Request,
):
    """Retrieves all saved state checkpoints across the lifecycle of a run."""
    checkpointer = request.app.state.checkpointer
    snaps = await checkpointer.list_checkpoints(run_id)
    if not snaps:
        raise HTTPException(status_code=404, detail=f"No checkpoints found for run '{run_id}'.")
    return snaps


@router.post("/{run_id}/replay", response_model=ReplayResult)
async def replay_from_checkpoint(
    run_id: str,
    req: ReplayRequest,
    request: Request,
):
    """
    Deterministically replays an agent workflow starting from a historical step index.
    Can inject patched state parameters to test bug fixes or failure recoveries.
    """
    state = request.app.state
    replay_engine = DeterministicReplayEngine(checkpointer=state.checkpointer)

    # Reconstruct original graph for the run
    snapshot = await state.checkpointer.get_checkpoint(run_id, req.step_index)
    if not snapshot:
        raise HTTPException(
            status_code=404,
            detail=f"Checkpoint step {req.step_index} not found for run '{run_id}'.",
        )

    # Synthesize execution graph from stored metadata or standard intent
    planner = WorkflowPlanner(tool_registry=state.tool_registry)
    plan = await planner.create_plan("Replay Plan", context=snapshot.values)

    async def tool_executor(tool_name: str, args: Dict[str, Any], agent_state: AgentState) -> Any:
        from nexus_registry.contracts import ToolCallRequest
        call_req = ToolCallRequest(tool_name=tool_name, arguments=args)
        res = await state.tool_registry.execute(call_req)
        return res.output or res.error

    graph = planner.compile_plan_to_graph(plan, tool_executor=tool_executor)
    compiled = graph.compile(checkpointer=state.checkpointer)

    try:
        result = await replay_engine.replay_from_step(
            compiled_graph=compiled,
            original_run_id=run_id,
            step_index=req.step_index,
            state_overrides=req.state_overrides,
            new_run_id=req.new_run_id,
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Replay failed: {str(exc)}")
