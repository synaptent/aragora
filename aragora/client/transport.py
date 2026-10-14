"""
HTTP transport utilities for the SDK client.

Provides retry configuration and rate limiting.
"""

from __future__ import annotations

import random
import time as time_module
from dataclasses import dataclass
from typing import Any


@dataclass
class RetryConfig:
    """Configuration for request retry behavior.

    Uses exponential backoff with jitter for resilient API calls.

    Args:
        max_retries: Maximum number of retry attempts (default: 3)
        backoff_factor: Base delay multiplier in seconds (default: 0.5)
        max_backoff: Maximum delay between retries in seconds (default: 30)
        retry_statuses: HTTP status codes that trigger retry (default: 429, 500, 502, 503, 504)
        jitter: Add random jitter to backoff (default: True)
    """

    max_retries: int = 3
    backoff_factor: float = 0.5
    max_backoff: float = 30.0
    retry_statuses: tuple[int, ...] = (429, 500, 502, 503, 504)
    jitter: bool = True

    def get_delay(self, attempt: int) -> float:
        """Calculate delay for a retry attempt with exponential backoff."""
        delay = min(self.backoff_factor * (2**attempt), self.max_backoff)
        if self.jitter:
            delay = delay * (0.5 + random.random())
        return delay


class RateLimiter:
    """Simple token bucket rate limiter for client-side request throttling.

    Implements a sliding window rate limiter that tracks request timestamps
    and enforces a maximum requests-per-second limit.
    """

    def __init__(self, rps: float):
        """Initialize rate limiter.

        Args:
            rps: Maximum requests per second allowed.
        """
        self.rps = rps
        self.min_interval = 1.0 / rps if rps > 0 else 0
        self._last_request: float = 0
        self._lock: Any | None = None

    def wait(self) -> None:
        """Block until a request is allowed (synchronous)."""
        if self.rps <= 0:
            return

        now = time_module.time()
        elapsed = now - self._last_request
        if elapsed < self.min_interval:
            time_module.sleep(self.min_interval - elapsed)
        self._last_request = time_module.time()

    async def wait_async(self) -> None:
        """Block until a request is allowed (asynchronous)."""
        import asyncio

        if self.rps <= 0:
            return

        now = asyncio.get_running_loop().time()
        elapsed = now - self._last_request
        if elapsed < self.min_interval:
            await asyncio.sleep(self.min_interval - elapsed)
        self._last_request = asyncio.get_running_loop().time()


__all__ = [
    "RetryConfig",
    "RateLimiter",
]
