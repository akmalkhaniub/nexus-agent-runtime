"""
convo_runtime.reliability.circuit_breaker
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Circuit Breaker pattern for protecting LLM calls and external MCP tool executions
against cascading downstream outages.
"""

from __future__ import annotations

import asyncio
import enum
import inspect
import time
from typing import Any, Callable, Optional


class CircuitState(str, enum.Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerOpenError(Exception):
    """Raised when an operation is attempted while the circuit is in OPEN state."""
    def __init__(self, name: str, reset_in_seconds: float) -> None:
        super().__init__(f"Circuit breaker '{name}' is OPEN. Retry after {reset_in_seconds:.1f}s.")
        self.name = name
        self.reset_in_seconds = reset_in_seconds


class CircuitBreaker:
    """
    Async-aware, state-machine based Circuit Breaker.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 2,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self._state: CircuitState = CircuitState.CLOSED
        self._failure_count: int = 0
        self._last_state_change: float = time.time()
        self._half_open_success_count: int = 0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        return self._state

    async def _check_state_transition(self) -> None:
        now = time.time()
        if self._state == CircuitState.OPEN:
            elapsed = now - self._last_state_change
            if elapsed >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._last_state_change = now
                self._half_open_success_count = 0

    async def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Executes the callable guarded by the circuit breaker."""
        async with self._lock:
            await self._check_state_transition()

            if self._state == CircuitState.OPEN:
                remaining = self.recovery_timeout - (time.time() - self._last_state_change)
                raise CircuitBreakerOpenError(self.name, max(0.0, remaining))

        try:
            if inspect.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)

            await self._on_success()
            return result
        except CircuitBreakerOpenError:
            raise
        except Exception as exc:
            await self._on_failure()
            raise exc

    async def _on_success(self) -> None:
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_success_count += 1
                if self._half_open_success_count >= self.half_open_max_calls:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._last_state_change = time.time()
            elif self._state == CircuitState.CLOSED:
                self._failure_count = 0

    async def _on_failure(self) -> None:
        async with self._lock:
            self._failure_count += 1
            if self._state == CircuitState.HALF_OPEN or self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                self._last_state_change = time.time()
