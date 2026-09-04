"""
nexus_sdk.exceptions
~~~~~~~~~~~~~~~~~~~~

Structured exception hierarchy for the Nexus Agent SDK.
"""

from __future__ import annotations
from typing import Optional


class NexusSDKError(Exception):
    """Base exception for all Nexus SDK errors."""
    pass


class NexusAPIError(NexusSDKError):
    """Raised when the runtime API responds with an HTTP error."""
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"Nexus API Error [{status_code}]: {detail}")
        self.status_code = status_code
        self.detail = detail


class ApprovalRequiredSDKError(NexusSDKError):
    """Raised when a tool execution is halted pending human approval."""
    def __init__(self, tool_name: str, approval_token: str) -> None:
        super().__init__(f"Tool '{tool_name}' requires human authorization. Token: {approval_token}")
        self.tool_name = tool_name
        self.approval_token = approval_token


class CircuitBreakerSDKError(NexusSDKError):
    """Raised when a call fails due to an open circuit breaker."""
    pass


class IdempotencySDKError(NexusSDKError):
    """Raised when an idempotency conflict occurs."""
    pass
