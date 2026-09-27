"""
Error handling decorators and retry logic for agent operations.

Provides:
- Retry decorators with exponential backoff and jitter
- Circuit breaker integration
- Streaming error handling
- Generic error handling decorators
"""

from __future__ import annotations

import asyncio
import functools
import logging
import secrets
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, TypeVar, cast
from collections.abc import Callable

if TYPE_CHECKING:
    import aiohttp
else:
    try:
        import aiohttp
    except ImportError:

        class _MissingAiohttpError(Exception):
            """Fallback exception type when aiohttp is unavailable."""

        class _MissingAiohttpSession:
            """Raise a clear import error if runtime code tries to open an aiohttp session."""

            def __init__(self, *args: Any, **kwargs: Any) -> None:
                raise ImportError("aiohttp is required for API-backed agent networking")

        aiohttp = SimpleNamespace(
            ClientConnectorError=_MissingAiohttpError,
            ServerDisconnectedError=_MissingAiohttpError,
            ClientPayloadError=_MissingAiohttpError,
            ClientResponseError=_MissingAiohttpError,
            ClientSession=_MissingAiohttpSession,
        )

# Generic type variables for decorators
T = TypeVar("T")
P_args = TypeVar("P_args")
P_kwargs = TypeVar("P_kwargs")
from aragora.utils.error_sanitizer import sanitize_error

from .classifier import ErrorAction, ErrorContext
from .exceptions import (
    AgentAPIError,
    AgentCircuitOpenError,
    AgentConnectionError,
    AgentError,
    AgentRateLimitError,
    AgentResponseError,
    AgentStreamError,
    AgentTimeoutError,
)

logger = logging.getLogger(__name__)

# =============================================================================
# Retry Delay Calculation
# =============================================================================


def calculate_retry_delay_with_jitter(
    attempt: int,
    base_delay: float,
    max_delay: float,
    jitter_factor: float = 0.3,
) -> float:
    """
    Calculate retry delay with exponential backoff and random jitter.

    Jitter prevents thundering herd when multiple clients recover simultaneously
    after a provider outage.

    Args:
        attempt: Current retry attempt (0-indexed)
        base_delay: Initial delay in seconds
        max_delay: Maximum delay cap in seconds
        jitter_factor: Fraction of delay to randomize (default: 0.3 = ±30%)

    Returns:
        Delay in seconds with jitter applied
    """
    # Calculate base exponential delay
    delay = min(base_delay * (2**attempt), max_delay)

    # Apply random jitter: delay ± (jitter_factor * delay)
    _secure_rng = secrets.SystemRandom()
    jitter = delay * jitter_factor * _secure_rng.uniform(-1, 1)

    # Ensure minimum delay of 0.1s
    return max(0.1, delay + jitter)


# Backward compatibility alias
_calculate_retry_delay_with_jitter = calculate_retry_delay_with_jitter


def _build_error_action(
    error: AgentError,
    ctx: ErrorContext,
    retryable_exceptions: tuple,
    override_delay: float | None = None,
) -> ErrorAction:
    """
    Build an ErrorAction with consistent retry logic.

    This helper consolidates the repeated pattern of:
    1. Check if error is retryable based on attempt count and exception type
    2. Calculate backoff delay with jitter
    3. Return ErrorAction tuple

    Args:
        error: The agent error that occurred
        ctx: Error context with attempt count and retry settings
        retryable_exceptions: Tuple of exception types that can be retried
        override_delay: Optional fixed delay (e.g., from Retry-After header)

    Returns:
        ErrorAction with retry decision and delay
    """
    should_retry = (
        ctx.max_retries > 0
        and ctx.attempt <= ctx.max_retries
        and isinstance(error, retryable_exceptions)
    )

    if not should_retry:
        delay = 0.0
    elif override_delay is not None:
        delay = override_delay
    else:
        delay = calculate_retry_delay_with_jitter(ctx.attempt - 1, ctx.retry_delay, ctx.max_delay)

    return ErrorAction(error=error, should_retry=should_retry, delay_seconds=delay)


# =============================================================================
# Error Handler Functions
# =============================================================================


def _handle_timeout_error(
    e: asyncio.TimeoutError,
    ctx: ErrorContext,
    retryable_exceptions: tuple,
) -> ErrorAction:
    """Handle timeout errors."""
    error = AgentTimeoutError(
        f"Operation timed out after {ctx.timeout}s",
        agent_name=ctx.agent_name,
        timeout_seconds=ctx.timeout,
        cause=e,
    )
    return _build_error_action(error, ctx, retryable_exceptions)


def _handle_connection_error(
    e: aiohttp.ClientConnectorError | aiohttp.ServerDisconnectedError,
    ctx: ErrorContext,
    retryable_exceptions: tuple,
) -> ErrorAction:
    """Handle connection/network errors."""
    if isinstance(e, aiohttp.ServerDisconnectedError):
        msg = f"Server disconnected: {sanitize_error(str(e))}"
    else:
        msg = f"Connection failed: {sanitize_error(str(e))}"

    error = AgentConnectionError(msg, agent_name=ctx.agent_name, cause=e)
    return _build_error_action(error, ctx, retryable_exceptions)


def _handle_payload_error(
    e: aiohttp.ClientPayloadError,
    ctx: ErrorContext,
    retryable_exceptions: tuple,
) -> ErrorAction:
    """Handle streaming payload errors."""
    error = AgentStreamError(
        f"Payload error during streaming: {sanitize_error(str(e))}",
        agent_name=ctx.agent_name,
        cause=e,
    )
    return _build_error_action(error, ctx, retryable_exceptions)


def _handle_response_error(
    e: aiohttp.ClientResponseError,
    ctx: ErrorContext,
    retryable_exceptions: tuple,
) -> ErrorAction:
    """Handle HTTP response errors (429, 5xx, 4xx)."""
    if e.status == 429:
        # Rate limit - check for Retry-After header
        retry_after = None
        if e.headers and "Retry-After" in e.headers:
            try:
                retry_after = float(e.headers["Retry-After"])
            except (ValueError, TypeError) as parse_err:
                logger.debug("Failed to parse numeric value: %s", parse_err)

        error = AgentRateLimitError(
            "Rate limit exceeded (HTTP 429)",
            agent_name=ctx.agent_name,
            retry_after=retry_after,
            cause=e,
        )

        # Compute override delay from Retry-After with jitter
        override_delay = None
        if retry_after is not None:
            base_wait = min(retry_after, ctx.max_delay)
            override_delay = base_wait + base_wait * 0.1 * secrets.SystemRandom().uniform(0, 1)

        return _build_error_action(error, ctx, retryable_exceptions, override_delay)

    elif e.status >= 500:
        # Server error - create connection error for 5xx
        server_error = AgentConnectionError(
            f"Server error (HTTP {e.status})",
            agent_name=ctx.agent_name,
            status_code=e.status,
            cause=e,
        )
        return _build_error_action(server_error, ctx, retryable_exceptions)

    else:
        # 4xx errors - not retryable
        api_error = AgentAPIError(
            f"API error (HTTP {e.status}): {sanitize_error(str(e))}",
            agent_name=ctx.agent_name,
            status_code=e.status,
            cause=e,
        )
        return ErrorAction(
            error=api_error, should_retry=False, delay_seconds=0.0, log_level="error"
        )


def _handle_agent_error(
    e: AgentError,
    ctx: ErrorContext,
    retryable_exceptions: tuple,
) -> ErrorAction:
    """Handle already-wrapped AgentError exceptions."""
    e.agent_name = e.agent_name or ctx.agent_name

    if not e.recoverable:
        return ErrorAction(error=e, should_retry=False, delay_seconds=0.0, log_level="error")

    return _build_error_action(e, ctx, retryable_exceptions)


def _handle_json_error(e: ValueError, ctx: ErrorContext) -> ErrorAction:
    """Handle JSON decode errors."""
    error = AgentResponseError(
        f"Invalid JSON response: {sanitize_error(str(e))}",
        agent_name=ctx.agent_name,
        cause=e,
    )
    return ErrorAction(error=error, should_retry=False, delay_seconds=0.0, log_level="error")


def _handle_unexpected_error(e: Exception, ctx: ErrorContext) -> ErrorAction:
    """Handle unexpected/unknown errors."""
    error = AgentError(
        f"Unexpected error: {sanitize_error(str(e))}",
        agent_name=ctx.agent_name,
        cause=e,
        recoverable=False,
    )
    return ErrorAction(error=error, should_retry=False, delay_seconds=0.0, log_level="error")


# =============================================================================
# Error Handling Decorators
# =============================================================================


def handle_agent_errors(
    agent_name_attr: str = "name",
    max_retries: int = 0,
    retry_delay: float = 1.0,
    retry_backoff: float = 2.0,
    max_delay: float = 30.0,
    retryable_exceptions: tuple = (AgentConnectionError, AgentTimeoutError, AgentRateLimitError),
    circuit_breaker_attr: str = "_circuit_breaker",
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator for async agent methods that standardizes error handling.

    Wraps aiohttp and other common exceptions in AgentError types,
    logs errors appropriately, and optionally retries transient failures.
    Integrates with CircuitBreaker for graceful failure handling.

    Args:
        agent_name_attr: Attribute name on self containing agent name
        max_retries: Maximum retry attempts for recoverable errors (0 = no retry)
        retry_delay: Initial delay between retries in seconds
        retry_backoff: Multiplier for delay between retries
        max_delay: Maximum delay between retries
        retryable_exceptions: Tuple of AgentError subclasses to retry
        circuit_breaker_attr: Attribute name on self for CircuitBreaker instance.
            If the attribute exists and circuit is open, raises AgentCircuitOpenError.
            Records success/failure to circuit breaker after each attempt.

    Usage:
        @handle_agent_errors(max_retries=3)
        async def generate(self, prompt: str) -> str:
            async with aiohttp.ClientSession() as session:
                ...
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        """Decorator that wraps an async function with error handling.

        Preserves the wrapped function's signature and metadata while adding
        retry logic, circuit breaker integration, and error transformation.
        """

        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs) -> T:
            """Execute the wrapped function with retry and error handling.

            Flow:
            1. Check circuit breaker (raise AgentCircuitOpenError if open)
            2. Execute function in retry loop
            3. On success: record to circuit breaker, return result
            4. On error: transform to AgentError, optionally retry with backoff
            5. After max retries: record failure and raise final error
            """
            agent_name = getattr(self, agent_name_attr, "unknown")
            circuit_breaker = getattr(self, circuit_breaker_attr, None)

            # Check circuit breaker before attempting call
            if circuit_breaker is not None and not circuit_breaker.can_proceed():
                raise AgentCircuitOpenError(
                    "Circuit breaker is open for agent",
                    agent_name=agent_name,
                    cooldown_seconds=circuit_breaker.cooldown_seconds,
                )

            attempt = 0
            ctx = ErrorContext(
                agent_name=agent_name,
                attempt=0,
                max_retries=max_retries,
                retry_delay=retry_delay,
                max_delay=max_delay,
                timeout=getattr(self, "timeout", None),
            )

            while True:
                attempt += 1
                ctx.attempt = attempt

                try:
                    # The decorator is applied to async methods, but Callable[..., T]
                    # cannot express async return types. The await is valid at runtime.
                    result = await cast(Any, func)(self, *args, **kwargs)
                    if circuit_breaker is not None:
                        circuit_breaker.record_success()
                    return result

                except asyncio.TimeoutError as e:
                    action = _handle_timeout_error(e, ctx, retryable_exceptions)

                except (aiohttp.ClientConnectorError, aiohttp.ServerDisconnectedError) as e:
                    action = _handle_connection_error(e, ctx, retryable_exceptions)

                except aiohttp.ClientPayloadError as e:
                    action = _handle_payload_error(e, ctx, retryable_exceptions)

                except aiohttp.ClientResponseError as e:
                    action = _handle_response_error(e, ctx, retryable_exceptions)

                except AgentError as e:
                    action = _handle_agent_error(e, ctx, retryable_exceptions)
                    if not e.recoverable:
                        raise

                except ValueError as e:
                    if "json" in str(e).lower() or "decode" in str(e).lower():
                        action = _handle_json_error(e, ctx)
                        logger.error("[%s] Response parse error: %s", agent_name, action.error)
                        raise action.error from e
                    raise

                except (
                    OSError,
                    RuntimeError,
                    TypeError,
                    AttributeError,
                    KeyError,
                    LookupError,
                ) as e:
                    action = _handle_unexpected_error(e, ctx)
                    logger.error(
                        "[%s] Unexpected error (attempt %s): %s",
                        agent_name,
                        attempt,
                        action.error,
                        exc_info=True,
                    )
                    if circuit_breaker is not None:
                        circuit_breaker.record_failure()
                    raise action.error from e

                # Log the error at appropriate level
                log_method = getattr(logger, action.log_level, logger.debug)
                log_method(
                    f"[{agent_name}] {type(action.error).__name__} (attempt {attempt}): {action.error}"
                )

                # Record failure to circuit breaker
                if circuit_breaker is not None:
                    circuit_breaker.record_failure()

                # Retry if appropriate
                if action.should_retry and action.error.recoverable:
                    logger.debug(
                        f"[{agent_name}] Retrying in {action.delay_seconds:.1f}s "
                        f"(attempt {attempt}/{max_retries + 1})"
                    )
                    await asyncio.sleep(action.delay_seconds)
                    continue

                # No more retries - raise the error
                raise action.error

        # Decorator wrapper preserves original function signature at runtime
        return cast(Callable[..., T], wrapper)

    return decorator


def with_error_handling(
    error_types: tuple[type[Exception], ...] = (Exception,),
    fallback: Any = None,
    log_level: str = "warning",
    reraise: bool = False,
    message_template: str | None = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Simple decorator for standardized exception handling with logging.

    Use this for non-agent functions where you want consistent error
    handling without the full retry/circuit-breaker infrastructure.
    Reduces boilerplate try/except/log patterns throughout the codebase.

    Args:
        error_types: Tuple of exception types to catch (default: all Exception)
        fallback: Value to return when exception is caught (default: None)
        log_level: Logging level for caught errors ("debug", "info", "warning", "error")
        reraise: If True, re-raise after logging (default: False)
        message_template: Custom log message template. Use {func}, {error}, {error_type}

    Usage:
        # Basic usage - log warning and return None on any error
        @with_error_handling()
        def risky_function():
            ...

        # Catch specific errors, return fallback value
        @with_error_handling(error_types=(ValueError, KeyError), fallback=[])
        def parse_data(data):
            ...

        # Log at debug level for expected errors
        @with_error_handling(error_types=(FileNotFoundError,), log_level="debug")
        def load_optional_config():
            ...

        # Log and re-raise for critical paths
        @with_error_handling(reraise=True, log_level="error")
        async def important_operation():
            ...
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> T:
            try:
                return func(*args, **kwargs)
            except error_types as e:
                _log_error(func, e, log_level, message_template)
                if reraise:
                    raise
                return fallback

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> T:
            try:
                # The iscoroutinefunction check below ensures func is async,
                # but Callable[..., T] cannot express async return types.
                return await cast(Any, func)(*args, **kwargs)
            except error_types as e:
                _log_error(func, e, log_level, message_template)
                if reraise:
                    raise
                return fallback

        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return cast(Callable[..., T], async_wrapper)
        return sync_wrapper

    return decorator


def _log_error(
    func: Callable[..., Any],
    error: Exception,
    log_level: str,
    message_template: str | None,
) -> None:
    """Helper to log errors with consistent formatting."""
    if message_template:
        message = message_template.format(
            func=func.__name__,
            error=error,
            error_type=type(error).__name__,
        )
    else:
        message = f"{func.__name__} error: {type(error).__name__}: {error}"

    # Get the appropriate log method
    log_method = getattr(logger, log_level, logger.warning)
    log_method(message)


def handle_stream_errors(
    agent_name_attr: str = "name",
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator specifically for streaming methods.

    Wraps errors that occur during async iteration and attempts to
    preserve any partial content received.

    Usage:
        @handle_stream_errors()
        async def generate_stream(self, prompt: str):
            async for chunk in ...:
                yield chunk
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            agent_name = getattr(self, agent_name_attr, "unknown")
            partial_content = []

            try:
                # This decorator is specifically for async generator methods.
                # Callable[..., T] cannot express async generator types.
                async for chunk in cast(Any, func)(self, *args, **kwargs):
                    if isinstance(chunk, str):
                        partial_content.append(chunk)
                    yield chunk

            except asyncio.TimeoutError as e:
                timeout = getattr(self, "timeout", None)
                raise AgentTimeoutError(
                    f"Stream timed out after {timeout}s",
                    agent_name=agent_name,
                    timeout_seconds=timeout,
                    partial_content="".join(partial_content) if partial_content else None,
                    cause=e,
                ) from e

            except (aiohttp.ClientPayloadError, aiohttp.ServerDisconnectedError) as e:
                raise AgentStreamError(
                    f"Stream interrupted: {sanitize_error(str(e))}",
                    agent_name=agent_name,
                    partial_content="".join(partial_content) if partial_content else None,
                    cause=e,
                ) from e

            except AgentError:
                raise

            except (OSError, RuntimeError, ValueError, TypeError, UnicodeDecodeError) as e:
                raise AgentStreamError(
                    f"Unexpected stream error: {sanitize_error(str(e))}",
                    agent_name=agent_name,
                    partial_content="".join(partial_content) if partial_content else None,
                    cause=e,
                ) from e

        return wrapper

    return decorator


__all__ = [
    # Retry calculation
    "calculate_retry_delay_with_jitter",
    "_calculate_retry_delay_with_jitter",  # Backward compat
    # Handler functions
    "_handle_timeout_error",
    "_handle_connection_error",
    "_handle_payload_error",
    "_handle_response_error",
    "_handle_agent_error",
    "_handle_json_error",
    "_handle_unexpected_error",
    # Decorators
    "handle_agent_errors",
    "with_error_handling",
    "handle_stream_errors",
]
