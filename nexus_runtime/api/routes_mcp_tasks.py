"""
nexus_runtime.api.routes_mcp_tasks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Durable MCP Tasks (`tasks/start`, `tasks/get`, `tasks/update`, `tasks/cancel`),
HMAC-SHA256 opaque state handle verification, form & URL-mode elicitation,
and `completion/complete` endpoints backed by SQLiteCheckpointer.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from nexus_registry.contracts import MCPRequest, MCPResponse
from nexus_runtime.core.checkpointer import McpTaskRecord
from nexus_runtime.core.state_handles import StateHandleAuthError, StateHandleManager

router = APIRouter(prefix="/api/v1/mcp", tags=["MCP Tasks & Stateless Handles"])


def _caller_identity(request: Request) -> tuple[str, str]:
    tenant_id = request.headers.get("X-Tenant-ID", "tenant-default").strip() or "tenant-default"
    sub = request.headers.get("X-Agent-Principal", "anonymous").strip() or "anonymous"
    return tenant_id, sub


def _authorize_task_and_handle(
    *,
    task: McpTaskRecord,
    params: Dict[str, Any],
    tenant_id: str,
    sub: str,
    handle_mgr: StateHandleManager,
) -> Optional[str]:
    """
    Verify both caller ownership of the task AND any supplied opaque state_handle.

    Returns an error reason string if unauthorized, or None if authorized.
    """
    meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
    raw_handle = params.get("state_handle") or meta.get("state_handle")
    if raw_handle is not None:
        try:
            verified = handle_mgr.verify(
                str(raw_handle),
                expected_tenant_id=tenant_id,
                expected_sub=sub,
            )
            if verified.run_id != task.run_id:
                return "State handle run_id does not match target MCP task."
        except StateHandleAuthError as exc:
            return str(exc)

    if task.tenant_id != tenant_id or task.sub != sub:
        return (
            f"Authorization denied: task '{task.task_id}' belongs to tenant='{task.tenant_id}', "
            f"sub='{task.sub}' (caller is tenant='{tenant_id}', sub='{sub}')."
        )
    return None


@router.post("/tasks/rpc", response_model=MCPResponse)
async def mcp_tasks_rpc(req: MCPRequest, request: Request) -> Any:
    """JSON-RPC 2.0 endpoint for durable MCP Tasks, elicitation resumption, and completions."""
    state = request.app.state
    checkpointer = state.checkpointer
    handle_mgr: StateHandleManager = state.state_handle_manager
    tenant_id, sub = _caller_identity(request)
    params = req.params or {}

    if req.method == "tasks/start":
        intent = str(params.get("intent") or "").strip()
        if not intent:
            return MCPResponse(id=req.id, error={"code": -32602, "message": "Missing 'intent' in tasks/start params."})

        mode = str(params.get("elicitation_mode") or "form").lower()
        requires_approval = bool(params.get("requires_approval", False))
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        run_id = str(params.get("run_id") or f"run_{uuid.uuid4().hex[:12]}")

        elicitation: Optional[Dict[str, Any]] = None
        status = "working"
        message = f"Task queued for intent: {intent}"
        result_payload: Optional[Dict[str, Any]] = None

        if requires_approval and mode == "url":
            status = "input_required"
            message = "Out-of-band OAuth / API key authorization required via URL elicitation."
            elicitation = {
                "mode": "url",
                "elicitationId": f"elicit_{uuid.uuid4().hex[:10]}",
                "url": f"https://auth.nexus.internal/consent?task_id={task_id}&tenant_id={tenant_id}",
                "message": "Complete sensitive credential verification in browser without exposing secrets in chat.",
            }
        elif requires_approval:
            status = "input_required"
            message = "Human-in-the-loop approval required before resuming execution."
            elicitation = {
                "mode": "form",
                "message": f"Approve sensitive execution for '{intent}'?",
                "requestedSchema": {
                    "type": "object",
                    "properties": {
                        "approved": {"type": "boolean"},
                        "reason": {"type": "string", "maxLength": 200},
                    },
                    "required": ["approved"],
                    "additionalProperties": False,
                },
            }
        elif params.get("complete_immediately"):
            status = "completed"
            message = "Task completed."
            result_payload = {
                "content": [{"type": "text", "text": f"Completed: {intent}"}],
                "structuredContent": {"intent": intent, "run_id": run_id, "status": "completed"},
                "resourceLinks": [
                    {
                        "type": "resource_link",
                        "uri": f"nexus://runs/{run_id}/summary",
                        "name": f"Run {run_id} Summary",
                        "mimeType": "application/json",
                    }
                ],
                "isError": False,
            }

        record = McpTaskRecord(
            task_id=task_id,
            run_id=run_id,
            tenant_id=tenant_id,
            sub=sub,
            status=status,
            progress=1 if status == "completed" else 0,
            total=1,
            message=message,
            elicitation=elicitation,
            result=result_payload,
        )
        await checkpointer.save_task(record)
        state_handle = handle_mgr.mint(run_id=run_id, tenant_id=tenant_id, sub=sub, step_index=record.progress)
        return MCPResponse(
            id=req.id,
            result={
                "task": record.to_mcp_task(),
                "_meta": {"state_handle": state_handle, "protocolVersion": "2026-07-28"},
            },
        )

    if req.method == "tasks/get":
        task_id = str(params.get("taskId") or params.get("task_id") or "").strip()
        if not task_id:
            return MCPResponse(id=req.id, error={"code": -32602, "message": "Missing 'taskId' in tasks/get params."})
        task = await checkpointer.get_task(task_id)
        if not task:
            return MCPResponse(id=req.id, error={"code": -32004, "message": f"Task '{task_id}' not found."})

        err = _authorize_task_and_handle(
            task=task,
            params=params,
            tenant_id=tenant_id,
            sub=sub,
            handle_mgr=handle_mgr,
        )
        if err:
            return JSONResponse(
                status_code=403,
                content=MCPResponse(id=req.id, error={"code": -32003, "message": err}).model_dump(),
            )
        refreshed = handle_mgr.mint(run_id=task.run_id, tenant_id=tenant_id, sub=sub, step_index=task.progress)
        return MCPResponse(
            id=req.id,
            result={"task": task.to_mcp_task(), "_meta": {"state_handle": refreshed}},
        )

    if req.method == "tasks/update":
        task_id = str(params.get("taskId") or params.get("task_id") or "").strip()
        if not task_id:
            return MCPResponse(id=req.id, error={"code": -32602, "message": "Missing 'taskId' in tasks/update params."})
        task = await checkpointer.get_task(task_id)
        if not task:
            return MCPResponse(id=req.id, error={"code": -32004, "message": f"Task '{task_id}' not found."})

        err = _authorize_task_and_handle(
            task=task,
            params=params,
            tenant_id=tenant_id,
            sub=sub,
            handle_mgr=handle_mgr,
        )
        if err:
            return JSONResponse(
                status_code=403,
                content=MCPResponse(id=req.id, error={"code": -32003, "message": err}).model_dump(),
            )

        if task.status in {"completed", "cancelled"}:
            return MCPResponse(
                id=req.id,
                error={"code": -32004, "message": f"Task '{task_id}' is already terminal ({task.status})."},
            )

        action = str(params.get("action") or "accept").lower()
        if action not in {"accept", "decline", "cancel"}:
            return MCPResponse(
                id=req.id,
                error={"code": -32602, "message": f"Invalid elicitation action '{action}'. Expected accept, decline, or cancel."},
            )
        elicit_input = params.get("input") if isinstance(params.get("input"), dict) else {}
        if action == "accept" and task.status == "input_required" and isinstance(task.elicitation, dict):
            req_schema = task.elicitation.get("requestedSchema")
            if task.elicitation.get("mode") == "form" and isinstance(req_schema, dict):
                for field in req_schema.get("required", []):
                    if field not in elicit_input:
                        return MCPResponse(
                            id=req.id,
                            error={"code": -32602, "message": f"Missing required elicitation input field '{field}'."},
                        )
                if "approved" in elicit_input and not isinstance(elicit_input["approved"], bool):
                    return MCPResponse(
                        id=req.id,
                        error={"code": -32602, "message": "Elicitation input 'approved' must be a boolean."},
                    )
        if action in {"decline", "cancel"} or elicit_input.get("approved") is False:
            task.status = "cancelled"
            task.message = "Task cancelled by human elicitation decision."
            task.elicitation = None
        else:
            task.status = "completed"
            task.progress = task.total
            task.message = "Resumed from durable checkpoint and completed."
            task.elicitation = None
            task.result = {
                "content": [{"type": "text", "text": f"Task {task.task_id} resumed and completed."}],
                "structuredContent": {
                    "task_id": task.task_id,
                    "run_id": task.run_id,
                    "resumed": True,
                    "decision_input": elicit_input,
                },
                "isError": False,
            }
        task.updated_at = time.time()
        await checkpointer.save_task(task)
        refreshed = handle_mgr.mint(run_id=task.run_id, tenant_id=tenant_id, sub=sub, step_index=task.progress)
        return MCPResponse(
            id=req.id,
            result={"task": task.to_mcp_task(), "_meta": {"state_handle": refreshed}},
        )

    if req.method == "tasks/cancel":
        task_id = str(params.get("taskId") or params.get("task_id") or "").strip()
        if not task_id:
            return MCPResponse(id=req.id, error={"code": -32602, "message": "Missing 'taskId' in tasks/cancel params."})
        task = await checkpointer.get_task(task_id)
        if not task:
            return MCPResponse(id=req.id, error={"code": -32004, "message": f"Task '{task_id}' not found."})

        err = _authorize_task_and_handle(
            task=task,
            params=params,
            tenant_id=tenant_id,
            sub=sub,
            handle_mgr=handle_mgr,
        )
        if err:
            return JSONResponse(
                status_code=403,
                content=MCPResponse(id=req.id, error={"code": -32003, "message": err}).model_dump(),
            )

        if task.status == "completed":
            return MCPResponse(
                id=req.id,
                error={"code": -32004, "message": f"Cannot cancel already completed task '{task_id}'."},
            )
        task.status = "cancelled"
        task.message = "Task cancelled by caller."
        task.elicitation = None
        task.updated_at = time.time()
        await checkpointer.save_task(task)
        return MCPResponse(id=req.id, result={"task": task.to_mcp_task()})

    if req.method == "completion/complete":
        arg = params.get("argument") if isinstance(params.get("argument"), dict) else {}
        arg_name = str(arg.get("name") or "")
        prefix = str(arg.get("value") or "").lower()
        tools = state.tool_registry.list_tools()

        candidates: List[str] = []
        if arg_name in {"tool", "tool_name", "name"}:
            candidates = [t.name for t in tools if t.name.lower().startswith(prefix)]
        elif arg_name in {"cluster", "environment"}:
            candidates = [c for c in ["prod-us-east-1", "prod-eu-west-1", "staging-us-west-2"] if c.startswith(prefix)]
        else:
            candidates = sorted({tag for t in tools for tag in t.tags if tag.lower().startswith(prefix)})

        return MCPResponse(
            id=req.id,
            result={
                "completion": {
                    "values": candidates[:20],
                    "total": len(candidates),
                    "hasMore": len(candidates) > 20,
                }
            },
        )

    return MCPResponse(id=req.id, error={"code": -32601, "message": f"Method '{req.method}' not implemented."})
