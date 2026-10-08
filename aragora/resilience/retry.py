"""
Unified Retry Logic for Aragora.

Provides consistent retry behavior across the codebase with configurable
backoff strategies and jitter.

This module consolidates retry patterns from:
- aragora/resilience.py
- aragora/knowledge/mound/resilience.py
- aragora/agents/errors/decorators.py
- aragora/agents/api_agents/rate_limiter.py

Usage:
    from aragora.resilience.retry import RetryConfig, with_retry

    @with_retry(RetryConfig(max_retries=3))
    async def flaky_api_call():
        ...

    # With custom strategy
    config = RetryConfig(
        max_retries=5,
        strategy=RetryStrategy.EXPONENTIAL,
        base_delay=0.1,
        max_delay=30.0,
        jitter_mode="additive",
    )

    @with_retry(config)
    async def resilient_operation():
        ...

    # With circuit breaker integration
    from aragora.resilience import CircuitBreaker

    breaker = CircuitBreaker(failure_threshold=5, cooldown_seconds=60)
    config = RetryConfig(
        max_retries=3,
        circuit_breaker=breaker,
    )

    @with_retry(config)
    async def api_call_with_circuit_breaker():
        ...

    # With per-provider retry policies
    from aragora.resilience.retry import PROVIDER_RETRY_POLICIES

    @with_retry(PROVIDER_RETRY_POLICIES["anthropic"])
    async def anthropic_api_call():
        ...
"""

from __future__ import annotations

import asyncio
import functools
import logging
import random
import time
from dataclasses import dataclass
from enum import Enum
from typing import (
    TYPE_CHECKING,
    Any,
    ParamSpec,
    TypeVar,
)
from collections.abc import Awaitable, Callable

if TYPE_CHECKING:
    from aragora.resilience.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

T = TypeVar("T")
P = ParamSpec("P")


class RetryStrategy(str, Enum):
    """Retry backoff strategies."""

    EXPONENTIAL = "exponential"  # 2^n * base_delay
    LINEAR = "linear"  # n * base_delay
    CONSTANT = "constant"  # base_delay always
    FIBONACCI = "fibonacci"  # Fibonacci sequence * base_delay


class JitterMode(str, Enum):
    """Jitter application modes to prevent thundering herd."""

    NONE = "none"  # No jitter
    ADDITIVE = "additive"  # delay + random(0, jitter_max)
    MULTIPLICATIVE = "multiplicative"  # delay * random(1-jitter_factor, 1+jitter_factor)
    FULL = "full"  # random(0, delay) - decorrelated jitter


# Default exceptions that are considered retryable
DEFAULT_RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
    IOError,
)


@dataclass
class RetryConfig:
    """Configuration for retry behavior.

    Attributes:
        max_retries: Maximum number of retry attempts (not counting initial try)
        base_delay: Base delay in seconds between retries
        max_delay: Maximum delay cap in seconds
        strategy: Backoff strategy to use
        jitter_mode: How to apply jitter to delays
        jitter_factor: Jitter factor (for multiplicative mode, 0.25 = ±25%)
        retryable_exceptions: Tuple of exception types to retry on
        on_retry: Optional callback called on each retry (attempt, exception, delay)
        should_retry: Optional function to determine if specific exception should be retried
        circuit_breaker: Optional circuit breaker for failure tracking
        provider_name: Optional provider name for logging and metrics
        non_retryable_status_codes: HTTP status codes that should not be retried
    """

    max_retries: int = 3
    base_delay: float = 0.1
    max_delay: float = 30.0
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL
    jitter_mode: JitterMode = JitterMode.MULTIPLICATIVE
    jitter_factor: float = 0.25  # ±25% jitter
    retryable_exceptions: tuple[type[Exception], ...] = DEFAULT_RETRYABLE_EXCEPTIONS
    on_retry: Callable[[int, Exception, float], None] | None = None
    should_retry: Callable[[Exception], bool] | None = None
    # Backward-compat alias: jitter=True maps to MULTIPLICATIVE, False to NONE
    jitter: bool | None = None
    # Circuit breaker integration
    circuit_breaker: CircuitBreaker | None = None
    # Provider identification for logging/metrics
    provider_name: str | None = None
    # HTTP status codes that should not be retried (e.g., 400, 401, 403, 404)
    non_retryable_status_codes: tuple[int, ...] = (400, 401, 403, 404, 422)

    def __post_init__(self) -> None:
        """Apply backward-compat jitter alias if set."""
        if self.jitter is not None:
            self.jitter_mode = JitterMode.MULTIPLICATIVE if self.jitter else JitterMode.NONE

    def calculate_delay(self, attempt: int) -> float:
        """Calculate delay for a given attempt number (0-indexed).

        Args:
            attempt: The attempt number (0 = first retry, 1 = second retry, etc.)

        Returns:
            Delay in seconds with jitter applied
        """
        return calculate_backoff_delay(
            attempt=attempt,
            base_delay=self.base_delay,
            max_delay=self.max_delay,
            strategy=self.strategy,
            jitter_mode=self.jitter_mode,
            jitter_factor=self.jitter_factor,
        )

    def is_retryable(self, exception: Exception) -> bool:
        """Check if an exception should trigger a retry.

        Args:
            exception: The exception to check

        Returns:
            True if the exception should be retried
        """
        if self.should_retry is not None:
            return self.should_retry(exception)
        return isinstance(exception, self.retryable_exceptions)

    def check_circuit_breaker(self) -> bool:
        """Check if circuit breaker allows proceeding.

        Returns:
            True if operation can proceed, False if circuit is open
        """
        if self.circuit_breaker is None:
            return True
        return self.circuit_breaker.can_proceed()

    def record_success(self) -> None:
        """Record a successful operation to the circuit breaker."""
        if self.circuit_breaker is not None:
            self.circuit_breaker.record_success()

    def record_failure(self, exception: Exception | None = None) -> None:
        """Record a failed operation to the circuit breaker.

        Args:
            exception: The exception that caused the failure
        """
        if self.circuit_breaker is not None:
            self.circuit_breaker.record_failure()


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open and preventing operations."""

    def __init__(
        self,
        message: str = "Circuit breaker is open",
        provider: str | None = None,
        cooldown_remaining: float | None = None,
    ):
        """Initialize CircuitOpenError.

        Args:
            message: Error message
            provider: Provider name if applicable
            cooldown_remaining: Seconds until circuit breaker may close
        """
        super().__init__(message)
        self.provider = provider
        self.cooldown_remaining = cooldown_remaining


# ============================================================================
# Per-Provider Retry Policies
# ============================================================================
# These policies are tuned for each AI provider's rate limiting behavior
# and error patterns. They can be used directly or as templates.


def _is_rate_limit_exception(exc: Exception) -> bool:
    """Check if exception is a rate limit error."""
    exc_str = str(exc).lower()
    return (
        "rate" in exc_str
        and "limit" in exc_str
        or "429" in exc_str
        or "too many requests" in exc_str
        or "quota" in exc_str
    )


def _is_server_error(exc: Exception) -> bool:
    """Check if exception is a server error (5xx)."""
    exc_str = str(exc)
    return any(f"{code}" in exc_str for code in [500, 502, 503, 504])


def _is_transient_error(exc: Exception) -> bool:
    """Check if exception is transient and worth retrying."""
    return (
        isinstance(exc, (ConnectionError, TimeoutError, OSError, IOError))
        or _is_rate_limit_exception(exc)
        or _is_server_error(exc)
    )


def create_provider_config(
    provider_name: str,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL,
    jitter_factor: float = 0.25,
    circuit_breaker: CircuitBreaker | None = None,
) -> RetryConfig:
    """Create a RetryConfig for a specific provider.

    Args:
        provider_name: Name of the provider (for logging)
        max_retries: Maximum retry attempts
        base_delay: Base delay in seconds
        max_delay: Maximum delay cap
        strategy: Backoff strategy
        jitter_factor: Jitter factor
        circuit_breaker: Optional circuit breaker instance

    Returns:
        RetryConfig configured for the provider
    """
    return RetryConfig(
        max_retries=max_retries,
        base_delay=base_delay,
        max_delay=max_delay,
        strategy=strategy,
        jitter_mode=JitterMode.MULTIPLICATIVE,
        jitter_factor=jitter_factor,
        retryable_exceptions=(
            ConnectionError,
            TimeoutError,
            OSError,
            IOError,
        ),
        should_retry=_is_transient_error,
        circuit_breaker=circuit_breaker,
        provider_name=provider_name,
    )


# Pre-configured retry policies for common providers
# These use default circuit breakers that can be overridden

PROVIDER_RETRY_POLICIES: dict[str, RetryConfig] = {
    # Anthropic: Conservative retries, longer delays (strict rate limits)
    "anthropic": RetryConfig(
        max_retries=3,
        base_delay=2.0,
        max_delay=120.0,
        strategy=RetryStrategy.EXPONENTIAL,
        jitter_mode=JitterMode.MULTIPLICATIVE,
        jitter_factor=0.3,
        retryable_exceptions=(ConnectionError, TimeoutError, OSError),
        should_retry=_is_transient_error,
        provider_name="anthropic",
        non_retryable_status_codes=(400, 401, 403, 404, 422),
    ),
    # OpenAI: Moderate retries, respects Retry-After headers
    "openai": RetryConfig(
        max_retries=4,
        base_delay=1.0,
        max_delay=60.0,
        strategy=RetryStrategy.EXPONENTIAL,
        jitter_mode=JitterMode.MULTIPLICATIVE,
        jitter_factor=0.25,
        retryable_exceptions=(ConnectionError, TimeoutError, OSError),
        should_retry=_is_transient_error,
        provider_name="openai",
        non_retryable_status_codes=(400, 401, 403, 404, 422),
    ),
    # Mistral: Similar to OpenAI
    "mistral": RetryConfig(
        max_retries=3,
        base_delay=1.0,
        max_delay=60.0,
        strategy=RetryStrategy.EXPONENTIAL,
        jitter_mode=JitterMode.MULTIPLICATIVE,
        jitter_factor=0.25,
        retryable_exceptions=(ConnectionError, TimeoutError, OSError),
        should_retry=_is_transient_error,
        provider_name="mistral",
        non_retryable_status_codes=(400, 401, 403, 404, 422),
    ),
    # Grok (xAI): Newer service, conservative approach
    "grok": RetryConfig(
        max_retries=3,
        base_delay=1.5,
        max_delay=90.0,
        strategy=RetryStrategy.EXPONENTIAL,
        jitter_mode=JitterMode.MULTIPLICATIVE,
        jitter_factor=0.3,
        retryable_exceptions=(ConnectionError, TimeoutError, OSError),
        should_retry=_is_transient_error,
        provider_name="grok",
        non_retryable_status_codes=(400, 401, 403, 404, 422),
    ),
    # OpenRouter: Aggregator, may have higher latency
    "openrouter": RetryConfig(
        max_retries=4,
        base_delay=1.5,
        max_delay=120.0,
        strategy=RetryStrategy.EXPONENTIAL,
        jitter_mode=JitterMode.MULTIPLICATIVE,
        jitter_factor=0.3,
        retryable_exceptions=(ConnectionError, TimeoutError, OSError),
        should_retry=_is_transient_error,
        provider_name="openrouter",
        non_retryable_status_codes=(400, 401, 403, 404, 422),
    ),
    # Google Gemini
    "gemini": RetryConfig(
        max_retries=3,
        base_delay=1.0,
        max_delay=60.0,
        strategy=RetryStrategy.EXPONENTIAL,
        jitter_mode=JitterMode.MULTIPLICATIVE,
        jitter_factor=0.25,
        retryable_exceptions=(ConnectionError, TimeoutError, OSError),
        should_retry=_is_transient_error,
        provider_name="gemini",
        non_retryable_status_codes=(400, 401, 403, 404, 422),
    ),
    # Knowledge Mound operations (database/storage)
    "knowledge_mound": RetryConfig(
        max_retries=3,
        base_delay=0.5,
        max_delay=30.0,
        strategy=RetryStrategy.EXPONENTIAL,
        jitter_mode=JitterMode.MULTIPLICATIVE,
        jitter_factor=0.2,
        retryable_exceptions=(ConnectionError, TimeoutError, OSError, IOError),
        should_retry=_is_transient_error,
        provider_name="knowledge_mound",
        non_retryable_status_codes=(),
    ),
    # Control plane operations
    "control_plane": RetryConfig(
        max_retries=3,
        base_delay=0.5,
        max_delay=30.0,
        strategy=RetryStrategy.EXPONENTIAL,
        jitter_mode=JitterMode.MULTIPLICATIVE,
        jitter_factor=0.2,
        retryable_exceptions=(ConnectionError, TimeoutError, OSError),
        should_retry=_is_transient_error,
        provider_name="control_plane",
        non_retryable_status_codes=(),
    ),
    # Memory system operations
    "memory": RetryConfig(
        max_retries=3,
        base_delay=0.3,
        max_delay=15.0,
        strategy=RetryStrategy.EXPONENTIAL,
        jitter_mode=JitterMode.MULTIPLICATIVE,
        jitter_factor=0.2,
        retryable_exceptions=(ConnectionError, TimeoutError, OSError, IOError),
        should_retry=_is_transient_error,
        provider_name="memory",
        non_retryable_status_codes=(),
    ),
    # Slack webhook operations
    "slack": RetryConfig(
        max_retries=3,
        base_delay=1.0,
        max_delay=30.0,
        strategy=RetryStrategy.EXPONENTIAL,
        jitter_mode=JitterMode.MULTIPLICATIVE,
        jitter_factor=0.25,
        retryable_exceptions=(ConnectionError, TimeoutError, OSError),
        should_retry=_is_transient_error,
        provider_name="slack",
        non_retryable_status_codes=(400, 401, 403, 404, 422),
    ),
    # Discord webhook operations
    "discord": RetryConfig(
        max_retries=3,
        base_delay=1.0,
        max_delay=30.0,
        strategy=RetryStrategy.EXPONENTIAL,
        jitter_mode=JitterMode.MULTIPLICATIVE,
        jitter_factor=0.25,
        retryable_exceptions=(ConnectionError, TimeoutError, OSError),
        should_retry=_is_transient_error,
        provider_name="discord",
        non_retryable_status_codes=(400, 401, 403, 404, 422),
    ),
    # Microsoft Teams webhook operations
    "teams": RetryConfig(
        max_retries=3,
        base_delay=1.0,
        max_delay=30.0,
        strategy=RetryStrategy.EXPONENTIAL,
        jitter_mode=JitterMode.MULTIPLICATIVE,
        jitter_factor=0.25,
        retryable_exceptions=(ConnectionError, TimeoutError, OSError),
        should_retry=_is_transient_error,
        provider_name="teams",
        non_retryable_status_codes=(400, 401, 403, 404, 422),
    ),
    # GitHub CLI operations
    "github_cli": RetryConfig(
        max_retries=3,
        base_delay=1.0,
        max_delay=60.0,
        strategy=RetryStrategy.EXPONENTIAL,
        jitter_mode=JitterMode.MULTIPLICATIVE,
        jitter_factor=0.25,
        retryable_exceptions=(ConnectionError, TimeoutError, OSError),
        should_retry=_is_transient_error,
        provider_name="github_cli",
        non_retryable_status_codes=(400, 401, 403, 404, 422),
    ),
}


def get_provider_retry_config(
    provider: str,
    circuit_breaker: CircuitBreaker | None = None,
    **overrides: Any,
) -> RetryConfig:
    """Get a retry config for a provider with optional overrides.

    Args:
        provider: Provider name (e.g., "anthropic", "openai")
        circuit_breaker: Optional circuit breaker to use
        **overrides: Override any RetryConfig attributes

    Returns:
        RetryConfig for the provider

    Example:
        config = get_provider_retry_config(
            "anthropic",
            circuit_breaker=my_breaker,
            max_retries=5,
        )
    """
    base_config = PROVIDER_RETRY_POLICIES.get(provider)
    if base_config is None:
        # Return a sensible default for unknown providers
        base_config = RetryConfig(
            max_retries=3,
            base_delay=1.0,
            max_delay=60.0,
            provider_name=provider,
        )

    # Create new config with overrides applied on top of base values
    config_dict: dict[str, Any] = {
        "max_retries": base_config.max_retries,
        "base_delay": base_config.base_delay,
        "max_delay": base_config.max_delay,
        "strategy": base_config.strategy,
        "jitter_mode": base_config.jitter_mode,
        "jitter_factor": base_config.jitter_factor,
        "retryable_exceptions": base_config.retryable_exceptions,
        "should_retry": base_config.should_retry,
        "provider_name": base_config.provider_name,
        "non_retryable_status_codes": base_config.non_retryable_status_codes,
        "circuit_breaker": circuit_breaker,
    }
    config_dict.update(overrides)

    return RetryConfig(
        max_retries=config_dict["max_retries"],
        base_delay=config_dict["base_delay"],
        max_delay=config_dict["max_delay"],
        strategy=config_dict["strategy"],
        jitter_mode=config_dict["jitter_mode"],
        jitter_factor=config_dict["jitter_factor"],
        retryable_exceptions=config_dict["retryable_exceptions"],
        should_retry=config_dict["should_retry"],
        provider_name=config_dict["provider_name"],
        non_retryable_status_codes=config_dict["non_retryable_status_codes"],
        circuit_breaker=config_dict["circuit_breaker"],
    )


def calculate_backoff_delay(
    attempt: int,
    base_delay: float = 0.1,
    max_delay: float = 30.0,
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL,
    jitter_mode: JitterMode = JitterMode.MULTIPLICATIVE,
    jitter_factor: float = 0.25,
) -> float:
    """Calculate backoff delay with configurable strategy and jitter.

    This is the core delay calculation function used by RetryConfig
    and can be used standalone.

    Args:
        attempt: The attempt number (0-indexed)
        base_delay: Base delay in seconds
        max_delay: Maximum delay cap
        strategy: Backoff strategy
        jitter_mode: Jitter mode
        jitter_factor: Jitter factor for multiplicative mode

    Returns:
        Delay in seconds
    """
    # Calculate base delay based on strategy
    if strategy == RetryStrategy.EXPONENTIAL:
        delay = base_delay * (2**attempt)
    elif strategy == RetryStrategy.LINEAR:
        delay = base_delay * (attempt + 1)
    elif strategy == RetryStrategy.FIBONACCI:
        fib = _fibonacci(attempt + 2)  # Start with fib(2) = 1
        delay = base_delay * fib
    else:  # CONSTANT
        delay = base_delay

    # Cap at max delay
    delay = min(delay, max_delay)

    # Apply jitter
    if jitter_mode == JitterMode.ADDITIVE:
        jitter = random.random() * base_delay * jitter_factor  # noqa: S311 -- retry jitter
        delay = delay + jitter
    elif jitter_mode == JitterMode.MULTIPLICATIVE:
        factor = 1.0 + (random.random() * 2 - 1) * jitter_factor  # noqa: S311 -- retry jitter
        delay = delay * factor
    elif jitter_mode == JitterMode.FULL:
        delay = random.random() * delay  # noqa: S311 -- retry jitter
    # NONE: no jitter applied

    return float(max(0.0, delay))


def _fibonacci(n: int) -> int:
    """Calculate nth Fibonacci number."""
    if n <= 0:
        return 0
    elif n == 1:
        return 1
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b


class ExponentialBackoff:
    """Iterator-based exponential backoff for manual retry loops.

    Usage:
        backoff = ExponentialBackoff(max_retries=3)
        for delay in backoff:
            try:
                result = risky_operation()
                break
            except ConnectionError:
                time.sleep(delay)
        else:
            raise Exception("All retries exhausted")
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 0.1,
        max_delay: float = 30.0,
        jitter: bool = True,
    ):
        """Initialize backoff iterator.

        Args:
            max_retries: Maximum number of retries
            base_delay: Initial delay in seconds
            max_delay: Maximum delay cap
            jitter: Whether to apply jitter
        """
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self._attempt = 0

    def __iter__(self) -> ExponentialBackoff:
        self._attempt = 0
        return self

    def __next__(self) -> float:
        if self._attempt >= self.max_retries:
            raise StopIteration

        delay = calculate_backoff_delay(
            attempt=self._attempt,
            base_delay=self.base_delay,
            max_delay=self.max_delay,
            strategy=RetryStrategy.EXPONENTIAL,
            jitter_mode=JitterMode.MULTIPLICATIVE if self.jitter else JitterMode.NONE,
        )
        self._attempt += 1
        return delay

    def reset(self) -> None:
        """Reset the backoff iterator."""
        self._attempt = 0


def with_retry(
    config: RetryConfig | None = None,
    *,
    max_retries: int = 3,
    base_delay: float = 0.1,
    retryable_exceptions: tuple[type[Exception], ...] | None = None,
    circuit_breaker: CircuitBreaker | None = None,
    provider: str | None = None,
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """Decorator for async functions with retry logic and circuit breaker support.

    Can be used with a RetryConfig, provider name, or keyword arguments.

    Args:
        config: RetryConfig instance (if provided, other args are ignored)
        max_retries: Maximum retry attempts
        base_delay: Base delay between retries
        retryable_exceptions: Exceptions to retry on
        circuit_breaker: Optional circuit breaker for failure tracking
        provider: Provider name to use pre-configured policy (e.g., "anthropic", "openai")

    Returns:
        Decorator function

    Example:
        @with_retry(max_retries=3)
        async def flaky_call():
            ...

        @with_retry(RetryConfig(strategy=RetryStrategy.LINEAR))
        async def another_call():
            ...

        @with_retry(provider="anthropic")
        async def anthropic_call():
            ...

        @with_retry(provider="openai", circuit_breaker=my_breaker)
        async def openai_call():
            ...
    """
    if config is None:
        if provider is not None:
            config = get_provider_retry_config(
                provider,
                circuit_breaker=circuit_breaker,
                max_retries=max_retries,
            )
        else:
            config = RetryConfig(
                max_retries=max_retries,
                base_delay=base_delay,
                retryable_exceptions=retryable_exceptions or DEFAULT_RETRYABLE_EXCEPTIONS,
                circuit_breaker=circuit_breaker,
            )

    def decorator(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            # Check circuit breaker before attempting
            if not config.check_circuit_breaker():
                provider_name = config.provider_name or func.__name__
                raise CircuitOpenError(
                    f"Circuit breaker open for {provider_name}",
                    provider=provider_name,
                )

            last_exception: Exception | None = None

            for attempt in range(config.max_retries + 1):
                try:
                    result = await func(*args, **kwargs)
                    # Record success with circuit breaker
                    config.record_success()
                    return result
                except Exception as e:  # noqa: BLE001 - retry wrapper must catch all to decide retry
                    last_exception = e

                    # Check if this exception type should be retried
                    if not isinstance(e, config.retryable_exceptions):
                        config.record_failure(e)
                        raise

                    if not config.is_retryable(e):
                        config.record_failure(e)
                        raise

                    if attempt >= config.max_retries:
                        provider_name = config.provider_name or func.__name__
                        logger.warning(
                            "Retry exhausted for %s after %s attempts: %s",
                            provider_name,
                            attempt + 1,
                            e,
                        )
                        config.record_failure(e)
                        raise

                    delay = config.calculate_delay(attempt)
                    provider_name = config.provider_name or func.__name__
                    logger.debug(
                        "Retry %s/%s for %s after %.2fs: %s",
                        attempt + 1,
                        config.max_retries,
                        provider_name,
                        delay,
                        e,
                    )

                    if config.on_retry:
                        config.on_retry(attempt, e, delay)

                    await asyncio.sleep(delay)

            # Should not reach here, but for type safety
            if last_exception:
                config.record_failure(last_exception)
                raise last_exception
            raise RuntimeError("Unexpected retry state")

        return wrapper

    return decorator


def with_retry_sync(
    config: RetryConfig | None = None,
    *,
    max_retries: int = 3,
    base_delay: float = 0.1,
    retryable_exceptions: tuple[type[Exception], ...] | None = None,
    circuit_breaker: CircuitBreaker | None = None,
    provider: str | None = None,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Decorator for sync functions with retry logic and circuit breaker support.

    Same as with_retry but for synchronous functions.

    Args:
        config: RetryConfig instance
        max_retries: Maximum retry attempts
        base_delay: Base delay between retries
        retryable_exceptions: Exceptions to retry on
        circuit_breaker: Optional circuit breaker for failure tracking
        provider: Provider name to use pre-configured policy

    Returns:
        Decorator function
    """
    if config is None:
        if provider is not None:
            config = get_provider_retry_config(
                provider,
                circuit_breaker=circuit_breaker,
                max_retries=max_retries,
            )
        else:
            config = RetryConfig(
                max_retries=max_retries,
                base_delay=base_delay,
                retryable_exceptions=retryable_exceptions or DEFAULT_RETRYABLE_EXCEPTIONS,
                circuit_breaker=circuit_breaker,
            )

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            # Check circuit breaker before attempting
            if not config.check_circuit_breaker():
                provider_name = config.provider_name or func.__name__
                raise CircuitOpenError(
                    f"Circuit breaker open for {provider_name}",
                    provider=provider_name,
                )

            last_exception: Exception | None = None

            for attempt in range(config.max_retries + 1):
                try:
                    result = func(*args, **kwargs)
                    config.record_success()
                    return result
                except Exception as e:  # noqa: BLE001 - retry wrapper must catch all to decide retry
                    last_exception = e

                    if not isinstance(e, config.retryable_exceptions):
                        config.record_failure(e)
                        raise

                    if not config.is_retryable(e):
                        config.record_failure(e)
                        raise

                    if attempt >= config.max_retries:
                        provider_name = config.provider_name or func.__name__
                        logger.warning(
                            "Retry exhausted for %s after %s attempts: %s",
                            provider_name,
                            attempt + 1,
                            e,
                        )
                        config.record_failure(e)
                        raise

                    delay = config.calculate_delay(attempt)
                    provider_name = config.provider_name or func.__name__
                    logger.debug(
                        "Retry %s/%s for %s after %.2fs: %s",
                        attempt + 1,
                        config.max_retries,
                        provider_name,
                        delay,
                        e,
                    )

                    if config.on_retry:
                        config.on_retry(attempt, e, delay)

                    time.sleep(delay)

            if last_exception:
                config.record_failure(last_exception)
                raise last_exception
            raise RuntimeError("Unexpected retry state")

        return wrapper

    return decorator


# Alias for backward compatibility
retry_with_backoff = with_retry


__all__ = [
    "RetryStrategy",
    "JitterMode",
    "RetryConfig",
    "ExponentialBackoff",
    "CircuitOpenError",
    "with_retry",
    "with_retry_sync",
    "retry_with_backoff",
    "calculate_backoff_delay",
    "PROVIDER_RETRY_POLICIES",
    "get_provider_retry_config",
    "create_provider_config",
]
