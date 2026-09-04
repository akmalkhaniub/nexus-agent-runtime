"""
convo_runtime.api.routes_tools
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

FastAPI endpoints for dynamic tool discovery, registration, execution,
and official Model Context Protocol (MCP) JSON-RPC bridge.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from convo_registry.contracts import (
    ToolDefinition,
    ToolCallRequest,
    ToolCallResult,
    MCPRequest,
    MCPResponse,
)
from convo_registry.mcp_adapter import MCPProtocolAdapter


router = APIRouter(prefix="/api/v1/tools", tags=["Tool Registry & MCP"])


class ApproveTokenRequest(BaseModel):
    token: str


class DynamicToolRegisterRequest(BaseModel):
    definition: ToolDefinition
    mock_return_value: Optional[Dict[str, Any]] = None


@router.get("", response_model=List[ToolDefinition])
async def list_tools(
    request: Request,
    tag: Optional[str] = Query(None, description="Filter tools by category tag"),
    mcp_format: bool = Query(False, description="Return tools formatted in standard MCP schema"),
):
    """Lists registered tools with optional tag filtering."""
    registry = request.app.state.tool_registry
    tools = registry.list_tools(tag=tag)
    if mcp_format:
        return [t.to_mcp_format() for t in tools]
    return tools


@router.post("")
async def register_tool_dynamically(
    req: DynamicToolRegisterRequest,
    request: Request,
):
    """Registers a new tool contract dynamically into the shared registry."""
    registry = request.app.state.tool_registry

    async def dynamic_handler(**kwargs):
        return req.mock_return_value or {"status": "success", "args_received": kwargs}

    registry.register(req.definition, dynamic_handler)
    return {"status": "registered", "tool": req.definition.name, "version": req.definition.version}


@router.post("/{tool_name}/execute", response_model=ToolCallResult)
async def execute_tool(
    tool_name: str,
    payload: Dict[str, Any],
    request: Request,
    approval_token: Optional[str] = Query(None),
):
    """Directly executes a tool with security policy and circuit breaker protection."""
    registry = request.app.state.tool_registry
    tenant_id = request.headers.get("X-Tenant-ID", "tenant-default")

    call_req = ToolCallRequest(
        tool_name=tool_name,
        arguments=payload,
        approval_token=approval_token,
    )
    result = await registry.execute(call_req, tenant_id=tenant_id)
    return result


@router.post("/approve")
async def approve_hitl_token(
    req: ApproveTokenRequest,
    request: Request,
):
    """Authorizes a human-in-the-loop approval token to allow execution of sensitive tools."""
    policy_engine = request.app.state.tool_registry.policy_engine
    policy_engine.authorize_token(req.token)
    return {"status": "authorized", "token": req.token}


@router.post("/mcp/rpc", response_model=MCPResponse)
async def mcp_jsonrpc_endpoint(
    req: MCPRequest,
    request: Request,
):
    """
    Standard Model Context Protocol (MCP) JSON-RPC 2.0 interface.
    Allows Claude Desktop, Cursor, or external LLMs to interact with Convo's Tool Registry.
    """
    registry = request.app.state.tool_registry
    tenant_id = request.headers.get("X-Tenant-ID", "tenant-default")

    if req.method == "tools/list":
        tools = registry.list_tools()
        return MCPProtocolAdapter.format_mcp_tools_list_response(req.id, tools)

    elif req.method == "tools/call":
        params = req.params or {}
        tool_name = params.get("name")
        args = params.get("arguments", {})

        if not tool_name:
            return MCPResponse(id=req.id, error={"code": -32602, "message": "Missing 'name' in parameters"})

        call_req = ToolCallRequest(tool_name=tool_name, arguments=args)
        result = await registry.execute(call_req, tenant_id=tenant_id)
        return MCPProtocolAdapter.format_mcp_tool_call_response(req.id, result)

    else:
        return MCPResponse(id=req.id, error={"code": -32601, "message": f"Method '{req.method}' not implemented"})
