"""
convo_registry.policy
~~~~~~~~~~~~~~~~~~~~~

Tool sandboxing, parameter validation, security guardrails,
and Human-in-the-loop (HITL) approval policy enforcement.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set
from convo_registry.contracts import ToolDefinition, ToolCallRequest


class PolicyViolationError(Exception):
    """Raised when a tool call violates runtime security or validation policies."""
    pass


class ApprovalRequiredError(PolicyViolationError):
    """Raised when a sensitive tool requires human-in-the-loop authorization."""
    def __init__(self, tool_name: str, approval_token: str) -> None:
        super().__init__(
            f"Tool '{tool_name}' requires human-in-the-loop approval. Approval token: '{approval_token}'."
        )
        self.tool_name = tool_name
        self.approval_token = approval_token


class ToolPolicyEngine:
    """
    Enforces security, schema conformity, and tenant authorizations for tool invocations.
    """

    def __init__(self) -> None:
        self._approved_tokens: Set[str] = set()
        self._forbidden_command_patterns = [
            re.compile(r";\s*rm\s+-rf", re.IGNORECASE),
            re.compile(r"\bdrop\s+table\b", re.IGNORECASE),
            re.compile(r"\bshutdown\b", re.IGNORECASE),
        ]

    def authorize_token(self, token: str) -> None:
        """Approves a human-in-the-loop token."""
        self._approved_tokens.add(token)

    def is_token_approved(self, token: str) -> bool:
        return token in self._approved_tokens

    def validate_request(
        self,
        tool_def: ToolDefinition,
        request: ToolCallRequest,
        tenant_id: Optional[str] = None,
        allowed_tools: Optional[List[str]] = None,
    ) -> None:
        """
        Validates the incoming tool request against tenant rules, schema requirements,
        HITL approval requirements, and dangerous injection patterns.
        """
        # 1. Tenant tool allowlist check
        if allowed_tools is not None and tool_def.name not in allowed_tools:
            raise PolicyViolationError(
                f"Tenant '{tenant_id or 'default'}' is not authorized to execute tool '{tool_def.name}'."
            )

        # 2. Required parameters check
        schema = tool_def.input_schema
        for req_prop in schema.required:
            if req_prop not in request.arguments:
                raise PolicyViolationError(
                    f"Missing required parameter '{req_prop}' for tool '{tool_def.name}'."
                )

        # 3. Guard against dangerous inputs (injection sandboxing)
        for key, value in request.arguments.items():
            if isinstance(value, str):
                for pattern in self._forbidden_command_patterns:
                    if pattern.search(value):
                        raise PolicyViolationError(
                            f"Parameter '{key}' contains prohibited instruction pattern for tool '{tool_def.name}'."
                        )

        # 4. Human-in-the-loop approval check
        if tool_def.requires_approval:
            token = request.approval_token
            if not token or not self.is_token_approved(token):
                generated_token = f"appr_{tool_def.name}_{request.call_id}"
                raise ApprovalRequiredError(tool_def.name, generated_token)
