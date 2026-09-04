"""
convo_runtime.api.routes_runs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

FastAPI routes for initiating agent executions, SSE event streaming,
and querying run execution status.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, AsyncIterator, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from convo_runtime.core.state import AgentState
from convo_runtime.core.planner import WorkflowPlanner
from convo_runtime.telemetry.otel import trace_workflow_span
from convo_runtime.telemetry.metrics import runtime_metrics


router = APIRouter(prefix="/api/v1/runs", tags=["Agent Runs"])


class CreateRunRequest(BaseModel):
    intent: str
    context: Dict[str, Any] = Field(default_factory=dict)
    run_id: Optional[str] = None
    max_iterations: int = 50


class RunResponse(BaseModel):
    run_id: str
    status: str
    final_state: Dict[str, Any]
    duration_ms: float
    total_steps: int


def get_platform_components(request: Request):
    return request.app.state


@router.post("", response_model=RunResponse)
async def create_and_execute_run(
    req: CreateRunRequest,
    request: Request,
) -> RunResponse:
    """Executes a workflow to completion synchronously and returns the final state."""
    state = request.app.state
    run_id = req.run_id or f"run_{uuid.uuid4().hex[:12]}"
    tenant_id = request.headers.get("X-Tenant-ID", "tenant-default")

    runtime_metrics.record_run_start(run_id, tenant_id)
    start_time = time.time()

    with trace_workflow_span(f"run:{run_id}", run_id=run_id, tenant_id=tenant_id, attributes={"intent": req.intent}):
        planner = WorkflowPlanner(tool_registry=state.tool_registry)
        plan = await planner.create_plan(req.intent, context=req.context)

        # Tool executor callback linking plan steps to registry
        async def tool_executor(tool_name: str, args: Dict[str, Any], agent_state: AgentState) -> Any:
            from convo_registry.contracts import ToolCallRequest
            call_req = ToolCallRequest(tool_name=tool_name, arguments=args)
            result = await state.tool_registry.execute(call_req, tenant_id=tenant_id)
            if result.status == "approval_required":
                agent_state.set("__pause_requested__", True)
                agent_state.set("__pause_reason__", f"Approval required for {tool_name}")
                agent_state.set("__approval_token__", result.output.get("approval_token"))
            return result.output or result.error

        graph = planner.compile_plan_to_graph(plan, tool_executor=tool_executor)
        compiled = graph.compile(checkpointer=state.checkpointer)

        initial_state = AgentState(values=req.context)
        initial_state.add_message(role="user", content=req.intent)

        try:
            final_state = await compiled.invoke(initial_state, run_id=run_id, max_iterations=req.max_iterations)
            duration_ms = (time.time() - start_time) * 1000

            # Record step in graph store
            state.graph_store.record_execution_step(
                run_id=run_id,
                step_index=len(await state.checkpointer.list_checkpoints(run_id)),
                node_name="COMPLETED",
                state_values=final_state.values,
            )

            # Record in vector memory as episodic memory
            state.vector_store.record_episodic_memory(
                run_id=run_id,
                workflow_name="intent_execution",
                summary=f"Executed intent: {req.intent}",
                resolution_outcome="SUCCESS",
            )

            runtime_metrics.record_run_finish(run_id, success=True, duration_ms=duration_ms)

            checkpoints = await state.checkpointer.list_checkpoints(run_id)
            return RunResponse(
                run_id=run_id,
                status="COMPLETED",
                final_state=final_state.to_dict(),
                duration_ms=duration_ms,
                total_steps=len(checkpoints),
            )
        except Exception as exc:
            duration_ms = (time.time() - start_time) * 1000
            runtime_metrics.record_run_finish(run_id, success=False, duration_ms=duration_ms)
            raise HTTPException(status_code=500, detail=f"Execution error: {str(exc)}")


@router.post("/stream")
async def stream_run_events(
    req: CreateRunRequest,
    request: Request,
):
    """Executes an agent workflow and streams graph events via Server-Sent Events (SSE)."""
    state = request.app.state
    run_id = req.run_id or f"run_{uuid.uuid4().hex[:12]}"
    tenant_id = request.headers.get("X-Tenant-ID", "tenant-default")

    async def sse_event_generator() -> AsyncIterator[str]:
        runtime_metrics.record_run_start(run_id, tenant_id)
        start_time = time.time()

        planner = WorkflowPlanner(tool_registry=state.tool_registry)
        plan = await planner.create_plan(req.intent, context=req.context)

        async def tool_executor(tool_name: str, args: Dict[str, Any], agent_state: AgentState) -> Any:
            from convo_registry.contracts import ToolCallRequest
            call_req = ToolCallRequest(tool_name=tool_name, arguments=args)
            res = await state.tool_registry.execute(call_req, tenant_id=tenant_id)
            if res.status == "approval_required":
                agent_state.set("__pause_requested__", True)
                agent_state.set("__pause_reason__", f"Approval required for {tool_name}")
                agent_state.set("__approval_token__", res.output.get("approval_token"))
            return res.output or res.error

        graph = planner.compile_plan_to_graph(plan, tool_executor=tool_executor)
        compiled = graph.compile(checkpointer=state.checkpointer)

        initial_state = AgentState(values=req.context)
        initial_state.add_message(role="user", content=req.intent)

        try:
            async for event in compiled.stream(initial_state, run_id=run_id, max_iterations=req.max_iterations):
                yield f"event: {event.event_type}\ndata: {event.model_dump_json()}\n\n"

            duration_ms = (time.time() - start_time) * 1000
            runtime_metrics.record_run_finish(run_id, success=True, duration_ms=duration_ms)
        except Exception as exc:
            duration_ms = (time.time() - start_time) * 1000
            runtime_metrics.record_run_finish(run_id, success=False, duration_ms=duration_ms)
            err_data = json.dumps({"error": str(exc), "run_id": run_id})
            yield f"event: workflow_failed\ndata: {err_data}\n\n"

    return StreamingResponse(
        sse_event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/{run_id}")
async def get_run_status(run_id: str, request: Request):
    """Retrieves status and latest checkpoint for a run."""
    state = request.app.state
    latest = await state.checkpointer.get_latest_checkpoint(run_id)
    if not latest:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")

    checkpoints = await state.checkpointer.list_checkpoints(run_id)
    return {
        "run_id": run_id,
        "total_steps": len(checkpoints),
        "latest_step": latest.step_index,
        "latest_node": latest.node_name,
        "snapshot": latest.model_dump(),
    }
