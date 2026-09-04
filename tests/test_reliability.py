"""
tests.test_reliability
~~~~~~~~~~~~~~~~~~~~~~

Tests for distributed failure handling: circuit breakers, retries with jitter,
idempotency, and timeouts.
"""

import asyncio
import pytest
from convo_runtime.reliability.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError, CircuitState
from convo_runtime.reliability.retries import retry_async
from convo_runtime.reliability.idempotency import IdempotencyManager, IdempotencyConflictError
from convo_runtime.reliability.timeouts import run_with_timeout, OperationTimeoutError


@pytest.mark.asyncio
async def test_circuit_breaker_transitions():
    cb = CircuitBreaker(name="test_llm_cb", failure_threshold=2, recovery_timeout=0.2)

    async def flaky_service(should_fail: bool):
        if should_fail:
            raise ConnectionResetError("Remote LLM endpoint dropped")
        return "SUCCESS"

    # Call 1: failure 1
    with pytest.raises(ConnectionResetError):
        await cb.call(flaky_service, should_fail=True)
    assert cb.state == CircuitState.CLOSED

    # Call 2: failure 2 -> trips breaker
    with pytest.raises(ConnectionResetError):
        await cb.call(flaky_service, should_fail=True)
    assert cb.state == CircuitState.OPEN

    # Call 3: should fail fast with CircuitBreakerOpenError without invoking service
    with pytest.raises(CircuitBreakerOpenError):
        await cb.call(flaky_service, should_fail=False)

    # Wait for recovery timeout
    await asyncio.sleep(0.25)

    # Breaker enters HALF_OPEN and succeeds
    res = await cb.call(flaky_service, should_fail=False)
    assert res == "SUCCESS"


@pytest.mark.asyncio
async def test_retry_exponential_backoff_with_jitter():
    attempts = 0

    async def flaky_api():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise TimeoutError("Temporary upstream blip")
        return {"data": "ok"}

    result = await retry_async(
        flaky_api,
        max_retries=3,
        initial_delay=0.01,
        backoff_factor=1.5,
        jitter=True,
    )
    assert result == {"data": "ok"}
    assert attempts == 3


@pytest.mark.asyncio
async def test_idempotency_caching_and_duplicate_prevention():
    mgr = IdempotencyManager()
    tenant = "pod-payments"
    key = "order_tx_99812"
    payload = {"amount": 100.0, "currency": "USD"}

    # Acquire lease 1
    is_new, cached = await mgr.acquire_or_get(tenant, key, payload)
    assert is_new is True
    assert cached is None

    # Simulate completed run
    response_data = {"transaction_id": "tx_abc123", "status": "settled"}
    await mgr.complete(tenant, key, response_data)

    # Acquire lease 2 with same payload (retry attempt)
    is_new2, cached2 = await mgr.acquire_or_get(tenant, key, payload)
    assert is_new2 is False
    assert cached2 == response_data

    # Acquire lease 3 with different payload under same key -> IdempotencyConflictError
    diff_payload = {"amount": 250.0, "currency": "EUR"}
    with pytest.raises(IdempotencyConflictError):
        await mgr.acquire_or_get(tenant, key, diff_payload)


@pytest.mark.asyncio
async def test_operation_timeout():
    async def slow_operation():
        await asyncio.sleep(0.2)
        return "finished"

    with pytest.raises(OperationTimeoutError):
        await run_with_timeout(slow_operation(), timeout_seconds=0.05, operation_name="slow_task")
