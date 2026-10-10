"""
Resilience decorator for async functions.

Combines retry logic with circuit breaker protection.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, TypeVar
from collections.abc import Awaitable, Callable

from .circuit_breaker import CircuitOpenError
from .registry import get_circuit_breaker

logger = logging.getLogger(__name__)

T = TypeVar("T")


def with_resilience(
    circuit_name: str | None = None,
    retries: int = 3,
    backoff: str = "exponential",
    use_circuit_breaker: bool = True,
    failure_threshold: int = 3,
    cooldown_seconds: float = 60.0,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """
    Decorator for adding resilience patterns to async functions.

    Combines retry logic with circuit breaker protection for robust error handling.

    Args:
        circuit_name: Name for circuit breaker (auto-generated from function name if None)
        retries: Maximum retry attempts before giving up
        backoff: Backoff strategy ("exponential", "linear", "constant")
        use_circuit_breaker: Whether to use circuit breaker protection
        failure_threshold: Failures before opening circuit (if use_circuit_breaker)
        cooldown_seconds: Cooldown after opening circuit (if use_circuit_breaker)

    Returns:
        Decorated function with resilience patterns applied.

    Example:
        @with_resilience(circuit_name="api_call", retries=3)
        async def call_external_api(prompt: str) -> str:
            return await api.generate(prompt)
    """

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        name = circuit_name or f"func_{func.__name__}"
        circuit_breaker = (
            get_circuit_breaker(name, failure_threshold, cooldown_seconds)
            if use_circuit_breaker
            else None
        )

        async def wrapper(*args: Any, **kwargs: Any) -> T:
            # Check circuit breaker
            if circuit_breaker and not circuit_breaker.can_proceed():
                remaining = circuit_breaker.cooldown_remaining()
                raise CircuitOpenError(name, remaining)

            last_exception: Exception | None = None
            for attempt in range(retries):
                try:
                    result = await func(*args, **kwargs)
                    if circuit_breaker:
                        circuit_breaker.record_success()
                    return result
                except Exception as e:  # noqa: BLE001 - resilience wrapper must catch all to decide retry
                    last_exception = e
                    if circuit_breaker:
                        circuit_breaker.record_failure()

                    # Calculate backoff delay
                    if backoff == "exponential":
                        delay = min(2**attempt, 30.0)  # Cap at 30s
                    elif backoff == "linear":
                        delay = attempt + 1
                    else:  # constant
                        delay = 1.0

                    if attempt < retries - 1:
                        logger.warning(
                            "[resilience] %s attempt %s/%s failed: %s. Retrying in %.1fs",
                            name,
                            attempt + 1,
                            retries,
                            e,
                            delay,
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            "[resilience] %s failed after %s attempts: %s", name, retries, e
                        )

            # All retries exhausted
            if last_exception:
                raise last_exception
            raise RuntimeError(f"Unexpected: no result after {retries} attempts")

        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper

    return decorator


__all__ = ["with_resilience"]
