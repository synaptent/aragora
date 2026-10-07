"""
Centralized Exception Handler Middleware.

Provides consistent exception handling across all server handlers with:
- Exception to HTTP status code mapping
- Sanitized error message generation
- Trace ID propagation
- Support for both sync and async handlers
- Structured logging with context

Usage:
    from aragora.server.middleware.exception_handler import (
        handle_exceptions,
        async_handle_exceptions,
        ExceptionHandler,
    )

    # Decorator style (sync)
    @handle_exceptions("debate creation")
    def create_debate(self, handler):
        ...

    # Decorator style (async)
    @async_handle_exceptions("agent generation")
    async def generate_response(self, prompt):
        ...

    # Context manager style
    with ExceptionHandler("leaderboard query") as ctx:
        result = get_leaderboard()
"""

from __future__ import annotations

import functools
import logging
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, TypeVar, cast
from collections.abc import AsyncGenerator, Callable

import os

from aragora.api_errors import safe_error_message

logger = logging.getLogger(__name__)


def _default_include_traceback() -> bool:
    """Return whether tracebacks should be included by default.

    In production environments, tracebacks are suppressed to avoid leaking
    internal implementation details. In dev/test, they are included for
    easier debugging.
    """
    env = os.getenv("ARAGORA_ENV", "").lower()
    if env in ("production", "prod", "staging", "live"):
        return False
    return True


# =============================================================================
# Exception to HTTP Status Code Mapping
# =============================================================================

# Comprehensive mapping of exception types to HTTP status codes.
# Uses string names for flexibility with dynamic imports.
EXCEPTION_STATUS_MAP: dict[str, int] = {
    # === Python built-in exceptions ===
    "FileNotFoundError": 404,
    "KeyError": 404,
    "ValueError": 400,
    "TypeError": 400,
    "json.JSONDecodeError": 400,
    "JSONDecodeError": 400,
    "PermissionError": 403,
    "TimeoutError": 504,
    "asyncio.TimeoutError": 504,
    "ConnectionError": 502,
    "ConnectionRefusedError": 502,
    "ConnectionResetError": 502,
    "BrokenPipeError": 502,
    "OSError": 500,
    "RuntimeError": 500,
    # === Aragora validation errors (400 Bad Request) ===
    "ValidationError": 400,
    "InputValidationError": 400,
    "SchemaValidationError": 400,
    "VoteValidationError": 400,
    "JSONParseError": 400,
    "DebateConfigurationError": 400,
    "AgentConfigurationError": 400,
    "ModeConfigurationError": 400,
    "ConvergenceThresholdError": 400,
    "CacheKeyError": 400,
    # === Aragora not found errors (404 Not Found) ===
    "DebateNotFoundError": 404,
    "AgentNotFoundError": 404,
    "RecordNotFoundError": 404,
    "ModeNotFoundError": 404,
    "PluginNotFoundError": 404,
    "CheckpointNotFoundError": 404,
    # === Aragora authentication/authorization (401/403) ===
    "AuthenticationError": 401,
    "AuthError": 401,
    "TokenExpiredError": 401,
    "APIKeyError": 401,
    "AuthorizationError": 403,
    # === Aragora approval gate (202/403) ===
    "ApprovalPendingError": 202,  # Accepted, pending approval
    "ApprovalDeniedError": 403,  # Approval denied
    # === Aragora rate limiting (429 Too Many Requests) ===
    "RateLimitExceededError": 429,
    # === Aragora storage/database errors (500/503) ===
    "StorageError": 500,
    "DatabaseError": 500,
    "DatabaseConnectionError": 503,
    "MemoryStorageError": 500,
    "MemoryRetrievalError": 500,
    "CheckpointSaveError": 500,
    "CheckpointCorruptedError": 500,
    "CacheError": 500,
    "CacheCapacityError": 507,  # Insufficient Storage
    # === Aragora agent errors ===
    "AgentTimeoutError": 504,
    "AgentRateLimitError": 429,
    "AgentConnectionError": 502,
    "AgentCircuitOpenError": 503,
    # === Aragora debate errors ===
    "DebateError": 500,
    "ConsensusError": 500,
    "ConsensusTimeoutError": 504,
    "EarlyStopError": 200,  # Not really an error, graceful termination
    "RoundLimitExceededError": 200,  # Graceful limit reached
    "PhaseExecutionError": 500,
    # === Aragora verification/convergence errors ===
    "VerificationError": 500,
    "VerificationTimeoutError": 504,
    "ConvergenceError": 500,
    "ConvergenceBackendError": 503,
    "Z3NotAvailableError": 503,
    "EmbeddingError": 503,
    # === Aragora streaming errors ===
    "StreamingError": 500,
    "StreamConnectionError": 502,
    "StreamTimeoutError": 504,
    "WebSocketError": 502,
    # === Aragora plugin/memory errors ===
    "PluginError": 500,
    "PluginExecutionError": 500,
    "MemoryError": 500,
    "TierTransitionError": 500,
    # === Aragora Nomic loop errors ===
    "NomicError": 500,
    "NomicCycleError": 500,
    "NomicStateError": 500,
    # === SQLite errors (mapped to service unavailable) ===
    "sqlite3.OperationalError": 503,
    "OperationalError": 503,
}


def map_exception_to_status(exc: Exception, default: int = 500) -> int:
    """
    Map an exception to its appropriate HTTP status code.

    Args:
        exc: The exception instance
        default: Default status code if exception type not found

    Returns:
        HTTP status code (int)
    """
    exc_type = type(exc).__name__

    # Check direct type name
    if exc_type in EXCEPTION_STATUS_MAP:
        return EXCEPTION_STATUS_MAP[exc_type]

    # Check with module prefix
    module_type = f"{type(exc).__module__}.{exc_type}"
    if module_type in EXCEPTION_STATUS_MAP:
        return EXCEPTION_STATUS_MAP[module_type]

    # Check base classes
    for base in type(exc).__mro__[1:]:
        base_name = base.__name__
        if base_name in EXCEPTION_STATUS_MAP:
            return EXCEPTION_STATUS_MAP[base_name]

    return default


def generate_trace_id() -> str:
    """Generate a unique trace ID for request tracking."""
    return str(uuid.uuid4())[:8]


# =============================================================================
# Error Response Builder
# =============================================================================


@dataclass
class ErrorResponse:
    """Structured error response data."""

    message: str
    status: int
    trace_id: str
    error_type: str
    context: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "error": self.message,
            "status": self.status,
            "trace_id": self.trace_id,
            "error_type": self.error_type,
            "context": self.context,
        }

    def to_handler_result(self) -> tuple[dict, int, dict]:
        """Convert to handler result tuple (body, status, headers)."""
        return (
            self.to_dict(),
            self.status,
            {"X-Trace-Id": self.trace_id},
        )


def build_error_response(
    exc: Exception,
    context: str,
    trace_id: str | None = None,
    default_status: int = 500,
) -> ErrorResponse:
    """
    Build a structured error response from an exception.

    Args:
        exc: The exception that occurred
        context: Description of the operation (e.g., "debate creation")
        trace_id: Optional trace ID (generated if not provided)
        default_status: Default HTTP status for unknown exceptions

    Returns:
        ErrorResponse with sanitized message and appropriate status
    """
    if trace_id is None:
        trace_id = generate_trace_id()

    status = map_exception_to_status(exc, default_status)
    message = safe_error_message(exc, context)

    return ErrorResponse(
        message=message,
        status=status,
        trace_id=trace_id,
        error_type=type(exc).__name__,
        context=context,
    )


# =============================================================================
# Exception Handler Context Manager
# =============================================================================


class ExceptionHandler:
    """
    Context manager for exception handling with structured logging.

    Usage:
        with ExceptionHandler("debate creation") as ctx:
            result = create_debate()
            ctx.success(result)

        if ctx.error:
            return ctx.error_response
    """

    def __init__(
        self,
        context: str,
        default_status: int = 500,
        log_level: str = "error",
        include_traceback: bool | None = None,
    ):
        self.context = context
        self.default_status = default_status
        self.log_level = log_level
        self.include_traceback = (
            include_traceback if include_traceback is not None else _default_include_traceback()
        )
        self.trace_id = generate_trace_id()
        self.error: ErrorResponse | None = None
        self.exception: Exception | None = None
        self.result: Any = None
        self.start_time: float = 0

    def __enter__(self) -> ExceptionHandler:
        self.start_time = time.time()
        return self

    def __exit__(
        self,
        exc_type: type | None,
        exc_val: Exception | None,
        exc_tb: Any,
    ) -> bool:
        if exc_val is not None:
            self.exception = exc_val
            self.error = build_error_response(
                exc_val,
                self.context,
                self.trace_id,
                self.default_status,
            )

            # Log the error
            duration_ms = round((time.time() - self.start_time) * 1000, 2)
            log_msg = (
                f"[{self.trace_id}] Error in {self.context} "
                f"({duration_ms}ms): {type(exc_val).__name__}: {exc_val}"
            )

            if self.log_level == "error":
                logger.error(log_msg, exc_info=self.include_traceback)
            elif self.log_level == "warning":
                logger.warning(log_msg)
            else:
                logger.info(log_msg)

            return True  # Suppress exception

        return False

    def success(self, result: Any) -> None:
        """Mark operation as successful."""
        self.result = result
        duration_ms = round((time.time() - self.start_time) * 1000, 2)
        logger.debug("[%s] %s: success in %sms", self.trace_id, self.context, duration_ms)

    @property
    def error_response(self) -> dict[str, Any] | None:
        """Get error response dict if error occurred."""
        return self.error.to_dict() if self.error else None

    @property
    def status_code(self) -> int:
        """Get HTTP status code (200 if success, error status otherwise)."""
        return self.error.status if self.error else 200


@asynccontextmanager
async def async_exception_handler(
    context: str,
    default_status: int = 500,
    log_level: str = "error",
    include_traceback: bool | None = None,
) -> AsyncGenerator[ExceptionHandler, None]:
    """
    Async context manager for exception handling.

    Usage:
        async with async_exception_handler("agent generation") as ctx:
            result = await agent.generate(prompt)
            ctx.success(result)
    """
    resolved_traceback = (
        include_traceback if include_traceback is not None else _default_include_traceback()
    )
    ctx = ExceptionHandler(context, default_status, log_level, resolved_traceback)
    ctx.start_time = time.time()

    try:
        yield ctx
    except (
        Exception  # noqa: BLE001 - central handler maps all exceptions to HTTP status
    ) as exc:
        ctx.exception = exc
        ctx.error = build_error_response(exc, context, ctx.trace_id, default_status)

        duration_ms = round((time.time() - ctx.start_time) * 1000, 2)
        log_msg = (
            f"[{ctx.trace_id}] Error in {context} ({duration_ms}ms): {type(exc).__name__}: {exc}"
        )

        if log_level == "error":
            logger.error(log_msg, exc_info=resolved_traceback)
        elif log_level == "warning":
            logger.warning(log_msg)
        else:
            logger.info(log_msg)


# =============================================================================
# Decorator-based Exception Handling
# =============================================================================

F = TypeVar("F", bound=Callable[..., Any])


def handle_exceptions(
    context: str,
    default_status: int = 500,
    log_level: str = "error",
    include_traceback: bool | None = None,
    reraise: bool = False,
) -> Callable[[F], F]:
    """
    Decorator for consistent exception handling in sync handlers.

    Wraps handler functions to:
    - Generate unique trace IDs for debugging
    - Log full exception details server-side
    - Return sanitized error messages to clients
    - Map exceptions to appropriate HTTP status codes

    Args:
        context: Description of the operation (e.g., "debate creation")
        default_status: Default HTTP status for unrecognized exceptions
        log_level: Logging level ("error", "warning", "info")
        include_traceback: Include traceback in logs
        reraise: If True, re-raise exception after logging

    Returns:
        Decorator function that wraps handler methods.

    Usage:
        @handle_exceptions("leaderboard retrieval")
        def get_leaderboard(self, query_params):
            ...
    """

    resolved_traceback = (
        include_traceback if include_traceback is not None else _default_include_traceback()
    )

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            trace_id = generate_trace_id()
            start_time = time.time()

            try:
                return func(*args, **kwargs)
            except (
                Exception  # noqa: BLE001 - central handler maps all exceptions to HTTP status
            ) as exc:
                duration_ms = round((time.time() - start_time) * 1000, 2)
                log_msg = (
                    f"[{trace_id}] Error in {context} "
                    f"({duration_ms}ms): {type(exc).__name__}: {exc}"
                )

                if log_level == "error":
                    logger.error(log_msg, exc_info=resolved_traceback)
                elif log_level == "warning":
                    logger.warning(log_msg)
                else:
                    logger.info(log_msg)

                if reraise:
                    raise

                error_resp = build_error_response(exc, context, trace_id, default_status)
                return error_resp.to_dict(), error_resp.status, {"X-Trace-Id": trace_id}

        return cast(F, wrapper)

    return decorator


def async_handle_exceptions(
    context: str,
    default_status: int = 500,
    log_level: str = "error",
    include_traceback: bool | None = None,
    reraise: bool = False,
) -> Callable[[F], F]:
    """
    Decorator for consistent exception handling in async handlers.

    Same as handle_exceptions but for async functions.

    Usage:
        @async_handle_exceptions("agent generation")
        async def generate_response(self, prompt):
            ...
    """
    resolved_traceback = (
        include_traceback if include_traceback is not None else _default_include_traceback()
    )

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            trace_id = generate_trace_id()
            start_time = time.time()

            try:
                return await func(*args, **kwargs)
            except (
                Exception  # noqa: BLE001 - central handler maps all exceptions to HTTP status
            ) as exc:
                duration_ms = round((time.time() - start_time) * 1000, 2)
                log_msg = (
                    f"[{trace_id}] Error in {context} "
                    f"({duration_ms}ms): {type(exc).__name__}: {exc}"
                )

                if log_level == "error":
                    logger.error(log_msg, exc_info=resolved_traceback)
                elif log_level == "warning":
                    logger.warning(log_msg)
                else:
                    logger.info(log_msg)

                if reraise:
                    raise

                error_resp = build_error_response(exc, context, trace_id, default_status)
                return error_resp.to_dict(), error_resp.status, {"X-Trace-Id": trace_id}

        return cast(F, wrapper)

    return decorator


# =============================================================================
# Exception Type Checker Utilities
# =============================================================================


def is_client_error(exc: Exception) -> bool:
    """Check if exception represents a client error (4xx)."""
    status = map_exception_to_status(exc, 500)
    return 400 <= status < 500


def is_server_error(exc: Exception) -> bool:
    """Check if exception represents a server error (5xx)."""
    status = map_exception_to_status(exc, 500)
    return status >= 500


def is_retryable(exc: Exception) -> bool:
    """
    Check if exception represents a retryable error.

    Retryable errors are typically temporary conditions:
    - 429 Rate Limit
    - 503 Service Unavailable
    - 504 Gateway Timeout
    - Connection errors
    """
    status = map_exception_to_status(exc, 500)
    return status in (429, 502, 503, 504)


def is_authentication_error(exc: Exception) -> bool:
    """Check if exception is an authentication/authorization error."""
    status = map_exception_to_status(exc, 500)
    return status in (401, 403)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Status mapping
    "EXCEPTION_STATUS_MAP",
    "map_exception_to_status",
    "generate_trace_id",
    # Error response
    "ErrorResponse",
    "build_error_response",
    # Context managers
    "ExceptionHandler",
    "async_exception_handler",
    # Decorators
    "handle_exceptions",
    "async_handle_exceptions",
    # Utilities
    "is_client_error",
    "is_server_error",
    "is_retryable",
    "is_authentication_error",
]
