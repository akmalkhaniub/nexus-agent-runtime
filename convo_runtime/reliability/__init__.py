"""
convo_runtime.reliability
~~~~~~~~~~~~~~~~~~~~~~~~~

Distributed failure handling: circuit breakers, retries with jitter,
idempotency, and timeouts.
"""

from convo_runtime.reliability.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError, CircuitState
from convo_runtime.reliability.retries import retry_async, with_retry
from convo_runtime.reliability.idempotency import (
    IdempotencyManager,
    IdempotencyConflictError,
    IdempotencyStatus,
    IdempotencyRecord,
)
from convo_runtime.reliability.timeouts import run_with_timeout, OperationTimeoutError

__all__ = [
    "CircuitBreaker",
    "CircuitBreakerOpenError",
    "CircuitState",
    "retry_async",
    "with_retry",
    "IdempotencyManager",
    "IdempotencyConflictError",
    "IdempotencyStatus",
    "IdempotencyRecord",
    "run_with_timeout",
    "OperationTimeoutError",
]
