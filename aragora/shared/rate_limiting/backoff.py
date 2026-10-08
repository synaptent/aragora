"""
Exponential backoff utilities for rate limit recovery.

Provides reusable exponential backoff with jitter for handling
rate limit errors (429/403) from API providers.
"""

from __future__ import annotations

import logging
import random
import threading
from dataclasses import dataclass, field
from typing import cast

logger = logging.getLogger(__name__)


@dataclass
class ExponentialBackoff:
    """Exponential backoff with jitter for rate limit recovery.

    When quota is exhausted (429/403), uses exponential backoff to avoid
    hammering the API. Each consecutive failure doubles the delay up to max_delay.

    Thread-safe for use across concurrent requests.

    Example:
        backoff = ExponentialBackoff(base_delay=1.0, max_delay=60.0)

        # On rate limit error
        delay = backoff.record_failure()
        await asyncio.sleep(delay)

        # On success
        backoff.reset()
    """

    base_delay: float = 1.0  # Initial delay in seconds
    max_delay: float = 60.0  # Maximum delay cap
    jitter: float = 0.1  # Jitter factor (0.1 = 10% random variance)
    failure_count: int = field(default=0, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def get_delay(self) -> float:
        """Calculate next delay with exponential backoff and jitter.

        Returns:
            Delay in seconds, with random jitter applied.
        """
        with self._lock:
            delay = min(self.base_delay * (2**self.failure_count), self.max_delay)
            jitter_amount = delay * self.jitter
            return cast(float, delay + random.uniform(0, jitter_amount))  # noqa: S311 -- retry jitter

    def record_failure(self) -> float:
        """Record a failure and return the delay to wait.

        Call this when an API returns a rate limit error (429/403).
        The failure count is incremented and an appropriate backoff
        delay is calculated.

        Returns:
            The recommended delay before retrying (in seconds).
        """
        with self._lock:
            self.failure_count += 1
            delay = min(self.base_delay * (2**self.failure_count), self.max_delay)
            jitter_amount = delay * self.jitter
            final_delay: float = delay + random.uniform(0, jitter_amount)  # noqa: S311 -- retry jitter
            logger.info("backoff_failure count=%s delay=%.1fs", self.failure_count, final_delay)
            return final_delay

    def reset(self) -> None:
        """Reset failure count after successful request.

        Call this after a request succeeds to restore normal operation.
        """
        with self._lock:
            if self.failure_count > 0:
                logger.debug("backoff_reset previous_failures=%s", self.failure_count)
                self.failure_count = 0

    @property
    def is_backing_off(self) -> bool:
        """Check if currently in backoff state.

        Returns:
            True if there have been recent failures requiring backoff.
        """
        with self._lock:
            return self.failure_count > 0

    @property
    def current_failure_count(self) -> int:
        """Get current failure count (thread-safe).

        Returns:
            Number of consecutive failures recorded.
        """
        with self._lock:
            return self.failure_count


__all__ = ["ExponentialBackoff"]
