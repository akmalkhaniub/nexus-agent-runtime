"""
nexus_registry.mcp_adapter
~~~~~~~~~~~~~~~~~~~~~~~~~~

Model Context Protocol (MCP) compatibility adapters.
Supports discovering and executing external MCP tools, as well as exposing internal
Nexus tools via the official MCP JSON-RPC protocol.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Coroutine, Dict, List, Optional
from nexus_registry.contracts import (
    ToolDefinition,
    ToolCallRequest,
    ToolCallResult,
    MCPRequest,
    MCPResponse,
)


class MCPProtocolAdapter:
    """
    Transforms between internal Nexus Tool contracts and external MCP JSON-RPC formats.
    """

    @staticmethod
    def format_mcp_tools_list_response(
        request_id: str,
        tools: List[ToolDefinition],
    ) -> MCPResponse:
        """Formats tools list into MCP tools/list response."""
        return MCPResponse(
            id=request_id,
            result={
                "tools": [t.to_mcp_format() for t in tools],
            },
        )

    @staticmethod
    def format_mcp_tool_call_response(
        request_id: str,
        result: ToolCallResult,
    ) -> MCPResponse:
        """Formats tool result into standard MCP tools/call content envelope."""
        if result.status == "error":
            return MCPResponse(
                id=request_id,
                error={"code": -32000, "message": result.error or "Tool execution failed"},
            )

        content_text = (
            json.dumps(result.output, indent=2)
            if isinstance(result.output, (dict, list))
            else str(result.output)
        )
        return MCPResponse(
            id=request_id,
            result={
                "content": [
                    {
                        "type": "text",
                        "text": content_text,
                    }
                ],
                "isError": False,
            },
        )


class ExternalMCPClientAdapter:
    """
    Client adapter connecting to an external MCP tool server.
    Can query `tools/list` and dispatch `tools/call`.
    """

    def __init__(
        self,
        server_name: str,
        transport_callable: Callable[[Dict[str, Any]], Coroutine[Any, Any, Dict[str, Any]]],
    ) -> None:
        self.server_name = server_name
        self._transport = transport_callable

    async def list_tools(self) -> List[ToolDefinition]:
        """Discovers tools exposed by the external MCP server."""
        req = MCPRequest(method="tools/list")
        res_data = await self._transport(req.model_dump())
        tools_raw = res_data.get("result", {}).get("tools", [])
        return [ToolDefinition.from_mcp_format(t) for t in tools_raw]

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Calls a tool on the external MCP server."""
        req = MCPRequest(
            method="tools/call",
            params={"name": tool_name, "arguments": arguments},
        )
        res_data = await self._transport(req.model_dump())
        if "error" in res_data and res_data["error"]:
            raise RuntimeError(f"MCP Server Error: {res_data['error']}")
        
        result_content = res_data.get("result", {}).get("content", [])
        if result_content and isinstance(result_content, list):
            return result_content[0].get("text")
        return res_data.get("result")
