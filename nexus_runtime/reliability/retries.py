"""
nexus_runtime.reliability.retries
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Async retry policies with full jitter exponential backoff.
"""

from __future__ import annotations

import asyncio
import functools
import random
import time
from typing import Any, Callable, Optional, Sequence, Type


async def retry_async(
    coro_fn: Callable[..., Any],
    *args: Any,
    max_retries: int = 3,
    initial_delay: float = 0.1,
    backoff_factor: float = 2.0,
    max_delay: float = 5.0,
    jitter: bool = True,
    retryable_exceptions: Sequence[Type[Exception]] = (Exception,),
    on_retry_callback: Optional[Callable[[int, Exception, float], None]] = None,
    **kwargs: Any,
) -> Any:
    """
    Executes an async callable with exponential backoff and jitter on failure.
    """
    attempt = 0
    current_delay = initial_delay

    while True:
        try:
            return await coro_fn(*args, **kwargs)
        except tuple(retryable_exceptions) as exc:
            attempt += 1
            if attempt > max_retries:
                raise exc

            # Compute backoff with full jitter
            sleep_time = min(max_delay, current_delay)
            if jitter:
                sleep_time = random.uniform(0, sleep_time)

            if on_retry_callback:
                on_retry_callback(attempt, exc, sleep_time)

            await asyncio.sleep(sleep_time)
            current_delay *= backoff_factor


def with_retry(
    max_retries: int = 3,
    initial_delay: float = 0.1,
    backoff_factor: float = 2.0,
    max_delay: float = 5.0,
    jitter: bool = True,
    retryable_exceptions: Sequence[Type[Exception]] = (Exception,),
) -> Callable:
    """Decorator version of retry_async."""
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await retry_async(
                fn,
                *args,
                max_retries=max_retries,
                initial_delay=initial_delay,
                backoff_factor=backoff_factor,
                max_delay=max_delay,
                jitter=jitter,
                retryable_exceptions=retryable_exceptions,
                **kwargs,
            )
        return wrapper
    return decorator
