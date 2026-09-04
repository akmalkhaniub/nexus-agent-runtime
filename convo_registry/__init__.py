"""
convo_registry
~~~~~~~~~~~~~~

Tool registry, Pydantic v2 contracts, MCP compatibility adapters,
and security policy enforcement.
"""

from convo_registry.contracts import (
    ToolDefinition,
    ToolInputSchema,
    ToolCallRequest,
    ToolCallResult,
    MCPRequest,
    MCPResponse,
)
from convo_registry.policy import (
    ToolPolicyEngine,
    PolicyViolationError,
    ApprovalRequiredError,
)
from convo_registry.mcp_adapter import (
    MCPProtocolAdapter,
    ExternalMCPClientAdapter,
)
from convo_registry.registry import ToolRegistry
from convo_registry.builtin_tools import register_builtin_tools

__all__ = [
    "ToolDefinition",
    "ToolInputSchema",
    "ToolCallRequest",
    "ToolCallResult",
    "MCPRequest",
    "MCPResponse",
    "ToolPolicyEngine",
    "PolicyViolationError",
    "ApprovalRequiredError",
    "MCPProtocolAdapter",
    "ExternalMCPClientAdapter",
    "ToolRegistry",
    "register_builtin_tools",
]
