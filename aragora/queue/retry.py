"""
Retry policy for job processing.

Implements exponential backoff with jitter to prevent thundering herd problems.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from aragora.queue.config import get_queue_config


@dataclass
class RetryPolicy:
    """
    Retry configuration with exponential backoff.

    Attributes:
        max_attempts: Maximum number of retry attempts
        base_delay_seconds: Initial delay before first retry
        max_delay_seconds: Maximum delay cap
        exponential_base: Base for exponential calculation
        jitter: Whether to add randomness to prevent thundering herd
        retryable_exceptions: Exception types that should trigger retry
    """

    max_attempts: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 300.0
    exponential_base: float = 2.0
    jitter: bool = True
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,)

    @classmethod
    def from_config(cls) -> RetryPolicy:
        """Create a RetryPolicy from the global queue config."""
        config = get_queue_config()
        return cls(
            max_attempts=config.retry_max_attempts,
            base_delay_seconds=config.retry_base_delay,
            max_delay_seconds=config.retry_max_delay,
        )

    def get_delay(self, attempt: int) -> float:
        """
        Calculate delay for a given attempt number.

        Uses exponential backoff: delay = base * (exp_base ^ attempt)
        Capped at max_delay_seconds.
        Optionally adds jitter (±20%) to prevent thundering herd.

        Args:
            attempt: The attempt number (0-indexed)

        Returns:
            Delay in seconds before next retry
        """
        # Calculate exponential delay
        delay = self.base_delay_seconds * (self.exponential_base**attempt)

        # Cap at maximum
        delay = min(delay, self.max_delay_seconds)

        # Add jitter if enabled (±20%)
        if self.jitter:
            jitter_factor = random.uniform(0.8, 1.2)
            delay *= jitter_factor

        return delay

    def should_retry(self, attempt: int, error: Exception | None = None) -> bool:
        """
        Determine if a job should be retried.

        Args:
            attempt: Current attempt number (1-indexed, after failure)
            error: The exception that caused the failure

        Returns:
            True if should retry, False otherwise
        """
        # Check attempt limit
        if attempt >= self.max_attempts:
            return False

        # If error provided, check if it's retryable
        if error is not None:
            # Don't retry validation errors
            if isinstance(error, (ValueError, TypeError, KeyError)):
                return False

            # Check against retryable exceptions
            if not isinstance(error, self.retryable_exceptions):
                return False

        return True

    def get_remaining_attempts(self, current_attempt: int) -> int:
        """
        Get number of remaining retry attempts.

        Args:
            current_attempt: Current attempt number (1-indexed)

        Returns:
            Number of attempts remaining
        """
        return max(0, self.max_attempts - current_attempt)


# Non-retryable exceptions (validation, configuration errors)
NON_RETRYABLE_EXCEPTIONS = (
    ValueError,
    TypeError,
    KeyError,
    AttributeError,
    ImportError,
    SyntaxError,
)


def is_retryable_error(error: Exception) -> bool:
    """
    Check if an error is retryable.

    Args:
        error: The exception to check

    Returns:
        True if the error is retryable
    """
    # Non-retryable: validation and configuration errors
    if isinstance(error, NON_RETRYABLE_EXCEPTIONS):
        return False

    # Check for specific error messages that indicate non-retryable conditions
    error_msg = str(error).lower()
    non_retryable_patterns = [
        "invalid",
        "not found",
        "unauthorized",
        "forbidden",
        "bad request",
        "validation",
    ]

    for pattern in non_retryable_patterns:
        if pattern in error_msg:
            return False

    return True
