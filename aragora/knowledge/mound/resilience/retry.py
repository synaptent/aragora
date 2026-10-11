"""Retry logic with exponential backoff for transient failures."""

from __future__ import annotations

import asyncio
import functools
import logging
import random
from dataclasses import dataclass
from enum import Enum
from typing import Any, cast
from collections.abc import Awaitable, Callable

from aragora.knowledge.mound.resilience._common import T, asyncio_timeout

logger = logging.getLogger(__name__)


def _emit_retry_exhausted(func_name: str, total_attempts: int, args: tuple) -> None:
    """Emit KM_RETRY_EXHAUSTED event if the caller has an event_emitter."""
    try:
        # Check if first arg (self) has an event emitter via circuit breaker
        if args:
            obj = args[0]
            emitter = getattr(getattr(obj, "_circuit_breaker", None), "_event_emitter", None)
            if emitter is None:
                emitter = getattr(obj, "_event_emitter", None)
            if emitter is None:
                return
            from aragora.events.types import StreamEvent, StreamEventType

            adapter_name = getattr(obj, "_adapter_name", getattr(obj, "adapter_name", "unknown"))
            emitter.emit(
                StreamEvent(
                    type=StreamEventType.KM_RETRY_EXHAUSTED,
                    data={
                        "adapter": adapter_name,
                        "function": func_name,
                        "total_attempts": total_attempts,
                    },
                )
            )
    except (ImportError, AttributeError, TypeError):
        pass


class RetryStrategy(str, Enum):
    """Retry strategies for transient failures."""

    EXPONENTIAL = "exponential"  # 2^n * base_delay with jitter
    LINEAR = "linear"  # n * base_delay
    CONSTANT = "constant"  # base_delay always


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""

    max_retries: int = 3
    base_delay: float = 0.1  # seconds
    max_delay: float = 10.0  # seconds
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL
    jitter: bool = True  # Add randomness to prevent thundering herd
    timeout_seconds: float | None = None  # Per-attempt timeout
    retryable_exceptions: tuple[type[Exception], ...] = (
        ConnectionError,
        TimeoutError,
        OSError,
    )

    def calculate_delay(self, attempt: int) -> float:
        """Calculate delay for a given attempt number."""
        if self.strategy == RetryStrategy.EXPONENTIAL:
            delay = self.base_delay * (2**attempt)
        elif self.strategy == RetryStrategy.LINEAR:
            delay = self.base_delay * (attempt + 1)
        else:
            delay = self.base_delay

        delay = min(delay, self.max_delay)

        if self.jitter:
            # Add ±25% jitter
            delay = delay * (0.75 + random.random() * 0.5)  # noqa: S311 -- retry jitter

        return delay


def with_retry(
    config: RetryConfig | None = None,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """
    Decorator for adding retry logic to async functions.

    Supports:
    - Configurable retry strategies (exponential, linear, constant)
    - Per-attempt timeout enforcement
    - Jitter to prevent thundering herd

    Usage:
        @with_retry(RetryConfig(max_retries=3, timeout_seconds=30.0))
        async def save_node(...):
            ...
    """
    if config is None:
        config = RetryConfig()

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception: Exception | None = None
            total_attempts = config.max_retries + 1

            for attempt in range(total_attempts):
                try:
                    if config.timeout_seconds is not None:
                        async with asyncio_timeout(config.timeout_seconds):
                            return await func(*args, **kwargs)
                    else:
                        return await func(*args, **kwargs)
                except asyncio.TimeoutError as e:
                    last_exception = e
                    if attempt < config.max_retries:
                        delay = config.calculate_delay(attempt)
                        logger.warning(
                            "Timeout in %s (attempt %s/%s): exceeded %ss. Retrying in %.2fs",
                            func.__name__,
                            attempt + 1,
                            total_attempts,
                            config.timeout_seconds,
                            delay,
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error("Max retries exceeded for %s after timeout", func.__name__)
                except config.retryable_exceptions as e:
                    last_exception = e
                    if attempt < config.max_retries:
                        delay = config.calculate_delay(attempt)
                        logger.warning(
                            "Retryable error in %s (attempt %s/%s): %s. Retrying in %.2fs",
                            func.__name__,
                            attempt + 1,
                            total_attempts,
                            e,
                            delay,
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error("Max retries exceeded for %s: %s", func.__name__, e)

            if last_exception:
                _emit_retry_exhausted(func.__name__, total_attempts, args)
                raise last_exception
            raise RuntimeError(f"Unexpected retry loop exit in {func.__name__}")

        return wrapper

    return decorator


def with_timeout(
    timeout_seconds: float,
    fallback: Callable[..., Any] | None = None,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """
    Decorator for adding timeout to async functions.

    Args:
        timeout_seconds: Maximum execution time
        fallback: Optional fallback function to call on timeout

    Usage:
        @with_timeout(5.0)
        async def my_operation():
            ...

        @with_timeout(5.0, fallback=lambda: [])
        async def get_items():
            ...
    """

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            try:
                return await asyncio.wait_for(
                    func(*args, **kwargs),
                    timeout=timeout_seconds,
                )
            except asyncio.TimeoutError:
                if fallback is not None:
                    result = fallback(*args, **kwargs)
                    if asyncio.iscoroutine(result):
                        return cast(T, await result)
                    return cast(T, result)
                raise

        return wrapper

    return decorator
