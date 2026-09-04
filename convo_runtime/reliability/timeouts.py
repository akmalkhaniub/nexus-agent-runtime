"""
convo_runtime.reliability.timeouts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Timeout guards and cancellation tokens for async operations and tool calls.
"""

from __future__ import annotations

import asyncio
from typing import Any, Coroutine, TypeVar

T = TypeVar("T")


class OperationTimeoutError(asyncio.TimeoutError):
    def __init__(self, operation_name: str, timeout_seconds: float) -> None:
        super().__init__(f"Operation '{operation_name}' timed out after {timeout_seconds:.2f} seconds.")
        self.operation_name = operation_name
        self.timeout_seconds = timeout_seconds


async def run_with_timeout(
    coro: Coroutine[Any, Any, T],
    timeout_seconds: float,
    operation_name: str = "anonymous_task",
) -> T:
    """Executes a coroutine with strict timeout and clean cancellation handling."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout_seconds)
    except asyncio.TimeoutError:
        raise OperationTimeoutError(operation_name, timeout_seconds)
