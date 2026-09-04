"""
nexus_registry.contracts
~~~~~~~~~~~~~~~~~~~~~~~~

Pydantic v2 contracts for tool definitions, schema specifications,
structured tool invocations, and MCP (Model Context Protocol) compliance.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class ToolInputSchema(BaseModel):
    """JSON Schema contract describing the input parameters of a tool."""
    type: Literal["object"] = "object"
    properties: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    required: List[str] = Field(default_factory=list)


class ToolDefinition(BaseModel):
    """Specification of an agent-executable tool."""
    name: str
    description: str
    version: str = "1.0.0"
    input_schema: ToolInputSchema = Field(default_factory=ToolInputSchema)
    requires_approval: bool = False
    timeout_seconds: float = 30.0
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_mcp_format(self) -> Dict[str, Any]:
        """Converts internal tool definition into official Model Context Protocol (MCP) tool schema."""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema.model_dump(),
        }

    @classmethod
    def from_mcp_format(cls, data: Dict[str, Any], version: str = "1.0.0") -> ToolDefinition:
        """Constructs a ToolDefinition from an external MCP tool descriptor."""
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            version=version,
            input_schema=ToolInputSchema(**data.get("inputSchema", {})),
        )


class ToolCallRequest(BaseModel):
    """A structured request to invoke a specific tool."""
    call_id: str = Field(default_factory=lambda: f"call_{uuid.uuid4().hex[:12]}")
    tool_name: str
    version: Optional[str] = None
    arguments: Dict[str, Any] = Field(default_factory=dict)
    approval_token: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)


class ToolCallResult(BaseModel):
    """The structured result returned from a tool execution."""
    call_id: str
    tool_name: str
    status: Literal["success", "error", "approval_required"]
    output: Any = None
    error: Optional[str] = None
    duration_ms: float = 0.0
    timestamp: float = Field(default_factory=time.time)


# MCP JSON-RPC Protocol Envelopes
class MCPRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    method: str
    params: Optional[Dict[str, Any]] = None


class MCPResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: str
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None
