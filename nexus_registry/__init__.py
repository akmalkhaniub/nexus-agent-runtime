"""
nexus_registry
~~~~~~~~~~~~~~

Tool registry, Pydantic v2 contracts, MCP compatibility adapters,
and security policy enforcement.
"""

from nexus_registry.contracts import (
    ToolDefinition,
    ToolInputSchema,
    ToolCallRequest,
    ToolCallResult,
    MCPRequest,
    MCPResponse,
)
from nexus_registry.policy import (
    ToolPolicyEngine,
    PolicyViolationError,
    ApprovalRequiredError,
)
from nexus_registry.mcp_adapter import (
    MCPProtocolAdapter,
    ExternalMCPClientAdapter,
)
from nexus_registry.registry import ToolRegistry
from nexus_registry.builtin_tools import register_builtin_tools

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
