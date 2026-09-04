"""
tests.test_mcp_registry
~~~~~~~~~~~~~~~~~~~~~~~

Tests for Tool Registry, MCP (Model Context Protocol) compliance,
schema validation, and HITL security policies.
"""

import pytest
from nexus_registry.contracts import ToolDefinition, ToolInputSchema, ToolCallRequest
from nexus_registry.registry import ToolRegistry
from nexus_registry.policy import ToolPolicyEngine
from nexus_registry.mcp_adapter import MCPProtocolAdapter


@pytest.mark.asyncio
async def test_tool_registration_and_execution():
    registry = ToolRegistry()

    tool_def = ToolDefinition(
        name="calculator_add",
        description="Adds two numbers",
        input_schema=ToolInputSchema(
            properties={
                "a": {"type": "number", "description": "first number"},
                "b": {"type": "number", "description": "second number"},
            },
            required=["a", "b"],
        ),
    )

    async def add_handler(a: float, b: float):
        return {"sum": a + b}

    registry.register(tool_def, add_handler)

    call_req = ToolCallRequest(tool_name="calculator_add", arguments={"a": 10, "b": 25})
    result = await registry.execute(call_req)

    assert result.status == "success"
    assert result.output == {"sum": 35}


@pytest.mark.asyncio
async def test_policy_missing_required_param():
    registry = ToolRegistry()

    tool_def = ToolDefinition(
        name="strict_tool",
        description="A strict tool",
        input_schema=ToolInputSchema(
            properties={"mandatory": {"type": "string"}},
            required=["mandatory"],
        ),
    )
    registry.register(tool_def, lambda mandatory: {"ok": True})

    # Call with missing mandatory param
    call_req = ToolCallRequest(tool_name="strict_tool", arguments={})
    result = await registry.execute(call_req)

    assert result.status == "error"
    assert "Missing required parameter" in (result.error or "")


@pytest.mark.asyncio
async def test_policy_injection_sandboxing():
    registry = ToolRegistry()

    tool_def = ToolDefinition(
        name="file_viewer",
        description="Views files",
        input_schema=ToolInputSchema(
            properties={"path": {"type": "string"}},
            required=["path"],
        ),
    )
    registry.register(tool_def, lambda path: {"path": path})

    # Dangerous payload
    call_req = ToolCallRequest(tool_name="file_viewer", arguments={"path": "safe.txt; rm -rf /"})
    result = await registry.execute(call_req)

    assert result.status == "error"
    assert "prohibited instruction pattern" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_human_in_the_loop_approval_policy():
    policy_engine = ToolPolicyEngine()
    registry = ToolRegistry(policy_engine=policy_engine)

    tool_def = ToolDefinition(
        name="delete_database",
        description="Destructive deletion",
        requires_approval=True,
    )
    registry.register(tool_def, lambda: {"status": "DELETED"})

    # First attempt: without approval
    call_req = ToolCallRequest(tool_name="delete_database", arguments={})
    result = await registry.execute(call_req)

    assert result.status == "approval_required"
    token = result.output.get("approval_token")
    assert token is not None

    # Operator approves token
    policy_engine.authorize_token(token)

    # Second attempt: with authorized token
    approved_req = ToolCallRequest(tool_name="delete_database", arguments={}, approval_token=token)
    second_result = await registry.execute(approved_req)

    assert second_result.status == "success"
    assert second_result.output == {"status": "DELETED"}


def test_mcp_format_conversion():
    tool_def = ToolDefinition(
        name="mcp_test_tool",
        description="Tool for testing MCP",
        input_schema=ToolInputSchema(
            properties={"query": {"type": "string"}},
            required=["query"],
        ),
    )
    mcp_tool = tool_def.to_mcp_format()

    assert mcp_tool["name"] == "mcp_test_tool"
    assert mcp_tool["description"] == "Tool for testing MCP"
    assert "inputSchema" in mcp_tool
    assert mcp_tool["inputSchema"]["type"] == "object"

    # Test MCPProtocolAdapter response format
    mcp_resp = MCPProtocolAdapter.format_mcp_tools_list_response("req_1", [tool_def])
    assert mcp_resp.jsonrpc == "2.0"
    assert len(mcp_resp.result["tools"]) == 1
