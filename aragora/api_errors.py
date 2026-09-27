"""
Standardized API error handling for Aragora.

This module provides:
1. Base exception hierarchy for API errors (inherits from AragoraError)
2. Error response formatting
3. Error logging utilities
4. HTTP status code mapping

The API error hierarchy inherits from AragoraError (from aragora.exceptions),
unifying the error handling across the entire codebase. This allows catching
all Aragora errors with `except AragoraError` while still enabling specific
handling of API errors with `except AragoraAPIError`.

Usage:
    from aragora.api_errors import (
        AragoraAPIError,
        NotFoundError,
        ValidationError,
        AuthenticationError,
        RateLimitError,
        format_error_response,
    )

    # Raise specific errors
    raise NotFoundError("Debate not found", debate_id="abc123")

    # Format error for API response
    response = format_error_response(error, include_trace=False)
"""

from __future__ import annotations

import logging
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from aragora.exceptions import AragoraError

logger = logging.getLogger(__name__)

# =============================================================================
# Error Codes
# =============================================================================


class ErrorCode(str, Enum):
    """Standardized error codes for API responses.

    Consolidated from error_utils.py and errors.py for consistent error handling.
    """

    # Client errors (4xx)
    BAD_REQUEST = "BAD_REQUEST"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_REQUEST = "INVALID_REQUEST"
    MISSING_PARAMETER = "MISSING_PARAMETER"
    INVALID_FORMAT = "INVALID_FORMAT"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    CONFLICT = "CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    UNPROCESSABLE_ENTITY = "UNPROCESSABLE_ENTITY"

    # Server errors (5xx)
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    GATEWAY_TIMEOUT = "GATEWAY_TIMEOUT"
    DATABASE_ERROR = "DATABASE_ERROR"
    EXTERNAL_SERVICE_ERROR = "EXTERNAL_SERVICE_ERROR"

    # Domain-specific errors
    DEBATE_ERROR = "DEBATE_ERROR"
    AGENT_ERROR = "AGENT_ERROR"
    VERIFICATION_ERROR = "VERIFICATION_ERROR"
    MEMORY_ERROR = "MEMORY_ERROR"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"

    # Agent-specific errors
    INVALID_API_KEY = "INVALID_API_KEY"
    AGENT_TIMEOUT = "AGENT_TIMEOUT"
    AGENT_RATE_LIMITED = "AGENT_RATE_LIMITED"
    AGENT_NOT_FOUND = "AGENT_NOT_FOUND"
    CONFIG_ERROR = "CONFIG_ERROR"


# =============================================================================
# Base Exception Classes
# =============================================================================


@dataclass
class ErrorContext:
    """Context information for error tracking."""

    error_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    path: str | None = None
    method: str | None = None
    user_id: str | None = None
    org_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class AragoraAPIError(AragoraError):
    """Base exception for all Aragora API errors.

    Inherits from AragoraError to unify the error hierarchy across the codebase.
    This allows catching all Aragora errors with `except AragoraError` while
    still enabling specific handling of API errors with `except AragoraAPIError`.

    Attributes:
        message: Human-readable error message
        code: Machine-readable error code
        status_code: HTTP status code
        details: Additional error details
        suggestion: Suggested fix for the user
        context: Error tracking context
    """

    default_message = "An error occurred"
    default_code = ErrorCode.INTERNAL_ERROR
    default_status_code = 500

    def __init__(
        self,
        message: str | None = None,
        code: ErrorCode | None = None,
        status_code: int | None = None,
        details: str | None = None,
        suggestion: str | None = None,
        context: ErrorContext | None = None,
        **extra: Any,
    ):
        self.message = message or self.default_message
        self.code = code or self.default_code
        self.status_code = status_code or self.default_status_code
        self._detail_message = details  # Store as separate attribute to avoid type conflict
        self.suggestion = suggestion
        self.context = context or ErrorContext(extra=extra)

        # Merge extra into context
        if extra:
            self.context.extra.update(extra)

        # Initialize AragoraError with message and context.extra as details (dict)
        super().__init__(self.message, self.context.extra)

    def to_dict(self, include_trace: bool = False) -> dict[str, Any]:
        """Convert error to dictionary for API response."""
        result: dict[str, Any] = {
            "error": self.code.value if isinstance(self.code, ErrorCode) else self.code,
            "message": self.message,
            "error_id": self.context.error_id,
        }

        if self._detail_message:
            result["details"] = self._detail_message
        if self.suggestion:
            result["suggestion"] = self.suggestion
        if self.context.extra:
            result["context"] = self.context.extra

        if include_trace:
            result["trace"] = traceback.format_exc()

        return result

    def log(self, level: int = logging.ERROR) -> None:
        """Log the error with context."""
        logger.log(
            level,
            f"[{self.context.error_id}] {self.code.value}: {self.message}",
            extra={
                "error_id": self.context.error_id,
                "error_code": self.code.value,
                "status_code": self.status_code,
                "context": self.context.extra,
            },
        )


# =============================================================================
# Client Errors (4xx)
# =============================================================================


class BadRequestError(AragoraAPIError):
    """Invalid request format or parameters."""

    default_message = "Invalid request"
    default_code = ErrorCode.BAD_REQUEST
    default_status_code = 400


class ValidationError(AragoraAPIError):
    """Request validation failed."""

    default_message = "Validation failed"
    default_code = ErrorCode.VALIDATION_ERROR
    default_status_code = 400

    def __init__(
        self,
        message: str | None = None,
        field: str | None = None,
        value: Any = None,
        **kwargs: Any,
    ):
        super().__init__(message, **kwargs)
        if field:
            self.context.extra["field"] = field
        if value is not None:
            self.context.extra["value"] = str(value)[:100]


class AuthenticationError(AragoraAPIError):
    """Authentication required or failed."""

    default_message = "Authentication required"
    default_code = ErrorCode.UNAUTHORIZED
    default_status_code = 401


class ForbiddenError(AragoraAPIError):
    """Access denied to resource."""

    default_message = "Access denied"
    default_code = ErrorCode.FORBIDDEN
    default_status_code = 403


class NotFoundError(AragoraAPIError):
    """Requested resource not found."""

    default_message = "Resource not found"
    default_code = ErrorCode.NOT_FOUND
    default_status_code = 404

    def __init__(
        self,
        message: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        **kwargs: Any,
    ):
        super().__init__(message, **kwargs)
        if resource_type:
            self.context.extra["resource_type"] = resource_type
        if resource_id:
            self.context.extra["resource_id"] = resource_id


class MethodNotAllowedError(AragoraAPIError):
    """HTTP method not allowed for this endpoint."""

    default_message = "Method not allowed"
    default_code = ErrorCode.METHOD_NOT_ALLOWED
    default_status_code = 405


class ConflictError(AragoraAPIError):
    """Resource conflict (e.g., duplicate)."""

    default_message = "Resource conflict"
    default_code = ErrorCode.CONFLICT
    default_status_code = 409


class RateLimitError(AragoraAPIError):
    """Rate limit exceeded."""

    default_message = "Rate limit exceeded"
    default_code = ErrorCode.RATE_LIMITED
    default_status_code = 429

    def __init__(
        self,
        message: str | None = None,
        retry_after: int | None = None,
        limit: int | None = None,
        **kwargs: Any,
    ):
        super().__init__(message, **kwargs)
        if retry_after:
            self.context.extra["retry_after_seconds"] = retry_after
        if limit:
            self.context.extra["limit"] = limit


class PayloadTooLargeError(AragoraAPIError):
    """Request payload too large."""

    default_message = "Payload too large"
    default_code = ErrorCode.PAYLOAD_TOO_LARGE
    default_status_code = 413


# =============================================================================
# Server Errors (5xx)
# =============================================================================


class InternalError(AragoraAPIError):
    """Internal server error."""

    default_message = "Internal server error"
    default_code = ErrorCode.INTERNAL_ERROR
    default_status_code = 500


class ServiceUnavailableError(AragoraAPIError):
    """Service temporarily unavailable."""

    default_message = "Service temporarily unavailable"
    default_code = ErrorCode.SERVICE_UNAVAILABLE
    default_status_code = 503


class GatewayTimeoutError(AragoraAPIError):
    """Upstream service timeout."""

    default_message = "Gateway timeout"
    default_code = ErrorCode.GATEWAY_TIMEOUT
    default_status_code = 504


class DatabaseError(AragoraAPIError):
    """Database operation failed."""

    default_message = "Database error"
    default_code = ErrorCode.DATABASE_ERROR
    default_status_code = 500


class ExternalServiceError(AragoraAPIError):
    """External service (API, connector) failed."""

    default_message = "External service error"
    default_code = ErrorCode.EXTERNAL_SERVICE_ERROR
    default_status_code = 502

    def __init__(
        self,
        message: str | None = None,
        service: str | None = None,
        **kwargs: Any,
    ):
        super().__init__(message, **kwargs)
        if service:
            self.context.extra["service"] = service


# =============================================================================
# Domain-Specific Errors
# =============================================================================


class DebateError(AragoraAPIError):
    """Debate-related error."""

    default_message = "Debate error"
    default_code = ErrorCode.DEBATE_ERROR
    default_status_code = 500

    def __init__(
        self,
        message: str | None = None,
        debate_id: str | None = None,
        **kwargs: Any,
    ):
        super().__init__(message, **kwargs)
        if debate_id:
            self.context.extra["debate_id"] = debate_id


class VerificationError(AragoraAPIError):
    """Formal verification error."""

    default_message = "Verification error"
    default_code = ErrorCode.VERIFICATION_ERROR
    default_status_code = 500


class MemoryError(AragoraAPIError):
    """Memory system error."""

    default_message = "Memory system error"
    default_code = ErrorCode.MEMORY_ERROR
    default_status_code = 500


# =============================================================================
# Error Formatting
# =============================================================================


def format_error_response(
    error: Exception,
    include_trace: bool = False,
    path: str | None = None,
    method: str | None = None,
) -> dict[str, Any]:
    """Format any exception as a standardized API error response.

    Args:
        error: The exception to format
        include_trace: Whether to include stack trace (dev mode only)
        path: Request path for context
        method: HTTP method for context

    Returns:
        Dictionary suitable for JSON response
    """
    if isinstance(error, AragoraAPIError):
        if path:
            error.context.path = path
        if method:
            error.context.method = method
        return error.to_dict(include_trace=include_trace)

    # Convert unknown exceptions to InternalError.
    # Log the real error server-side but return a sanitized message to
    # prevent leaking internal details (file paths, SQL, stack info).
    error_msg = str(error) if str(error) else "An unexpected error occurred"
    logger.error("Internal error (%s): %s", type(error).__name__, error_msg, exc_info=True)
    internal = InternalError(
        message="An internal error occurred. Please try again later.",
        details=type(error).__name__,
    )
    if path:
        internal.context.path = path
    if method:
        internal.context.method = method

    return internal.to_dict(include_trace=include_trace)


def get_status_code(error: Exception) -> int:
    """Get HTTP status code for an exception."""
    if isinstance(error, AragoraAPIError):
        return error.status_code
    return 500


# =============================================================================
# Error Mapping
# =============================================================================

# Map common exception types to API errors
EXCEPTION_MAP: dict[type[Exception], type[AragoraAPIError]] = {
    ValueError: ValidationError,
    KeyError: NotFoundError,
    PermissionError: ForbiddenError,
    TimeoutError: GatewayTimeoutError,
    ConnectionError: ExternalServiceError,
}


def wrap_exception(
    error: Exception,
    default_class: type[AragoraAPIError] = InternalError,
) -> AragoraAPIError:
    """Wrap a standard exception in an AragoraAPIError.

    Args:
        error: The exception to wrap
        default_class: Default error class if no mapping found

    Returns:
        An AragoraAPIError instance
    """
    if isinstance(error, AragoraAPIError):
        return error

    error_class = EXCEPTION_MAP.get(type(error), default_class)
    return error_class(message=str(error), details=type(error).__name__)


# =============================================================================
# Logging Helpers
# =============================================================================


def log_error(
    error: Exception,
    level: int = logging.ERROR,
    context: dict[str, Any] | None = None,
) -> str:
    """Log an error with context and return the error ID.

    Args:
        error: The exception to log
        level: Logging level
        context: Additional context to include

    Returns:
        Error ID for tracking
    """
    if isinstance(error, AragoraAPIError):
        if context:
            error.context.extra.update(context)
        error.log(level)
        return error.context.error_id

    # Create error ID for non-API errors
    error_id = str(uuid.uuid4())[:8]
    logger.log(
        level,
        f"[{error_id}] {type(error).__name__}: {error}",
        extra={"error_id": error_id, "context": context or {}},
        exc_info=True,
    )
    return error_id


# =============================================================================
# Error Suggestions Registry (from error_utils.py)
# =============================================================================

ERROR_SUGGESTIONS: dict[ErrorCode, dict[str, str]] = {
    ErrorCode.INVALID_API_KEY: {
        "message": "Invalid or missing API key",
        "suggestion": "Check your API key configuration",
        "cli_help": "Run `aragora doctor` to verify API keys",
        "docs": "See docs/ENVIRONMENT.md for configuration",
    },
    ErrorCode.AGENT_TIMEOUT: {
        "message": "Agent timed out",
        "suggestion": "Increase timeout or use fewer agents",
        "cli_help": "Set ARAGORA_DEBATE_TIMEOUT=1200 in .env",
        "docs": "See docs/TROUBLESHOOTING.md",
    },
    ErrorCode.AGENT_RATE_LIMITED: {
        "message": "Agent rate limited by provider",
        "suggestion": "Wait and retry, or use fallback provider",
        "cli_help": "Set OPENROUTER_API_KEY for fallback access",
        "docs": "See docs/ENVIRONMENT.md for fallback configuration",
    },
    ErrorCode.AGENT_NOT_FOUND: {
        "message": "Agent not found",
        "suggestion": "Check agent name spelling",
        "cli_help": "Run `aragora status` to list available agents",
        "docs": "See docs/CUSTOM_AGENTS.md for agent configuration",
    },
    ErrorCode.CONFIG_ERROR: {
        "message": "Configuration error",
        "suggestion": "Check your configuration file",
        "cli_help": "Run `aragora config show` to view current settings",
        "docs": "See docs/ENVIRONMENT.md for configuration options",
    },
    ErrorCode.UNAUTHORIZED: {
        "message": "Authentication required",
        "suggestion": "Provide valid authentication token",
        "cli_help": "Set ARAGORA_API_TOKEN in .env",
        "docs": "See docs/API_REFERENCE.md for authentication",
    },
    ErrorCode.RATE_LIMITED: {
        "message": "Rate limit exceeded",
        "suggestion": "Wait before retrying",
        "cli_help": "Rate limits reset after 60 seconds",
        "docs": "See docs/API_REFERENCE.md for rate limit details",
    },
    ErrorCode.NOT_FOUND: {
        "message": "Resource not found",
        "suggestion": "Verify the resource ID exists",
        "cli_help": "Use `aragora status` to check available resources",
        "docs": "Check the API endpoint path",
    },
    ErrorCode.DATABASE_ERROR: {
        "message": "Database error",
        "suggestion": "Check database connectivity",
        "cli_help": "Run `aragora doctor` to check database status",
        "docs": "See docs/TROUBLESHOOTING.md for database issues",
    },
    ErrorCode.TIMEOUT: {
        "message": "Operation timed out",
        "suggestion": "Increase timeout or reduce complexity",
        "cli_help": "Set ARAGORA_DEBATE_TIMEOUT to a higher value",
        "docs": "See docs/ENVIRONMENT.md for timeout configuration",
    },
    ErrorCode.SERVICE_UNAVAILABLE: {
        "message": "Service temporarily unavailable",
        "suggestion": "Wait and retry",
        "cli_help": "Check server status with `aragora doctor`",
        "docs": "See docs/TROUBLESHOOTING.md",
    },
}


def get_error_suggestion(code: ErrorCode) -> dict[str, str]:
    """Get suggestion details for an error code.

    Returns:
        Dict with 'message', 'suggestion', 'cli_help', and 'docs' keys
    """
    return ERROR_SUGGESTIONS.get(
        code,
        {
            "message": "An error occurred",
            "suggestion": "Check the error details",
            "cli_help": "Run `aragora doctor` for diagnostics",
            "docs": "See docs/TROUBLESHOOTING.md",
        },
    )


def format_cli_error(code: ErrorCode, details: str = "") -> str:
    """Format an error message for CLI output with actionable suggestions.

    Args:
        code: Error code
        details: Additional error details

    Returns:
        Formatted error string for terminal output
    """
    info = get_error_suggestion(code)
    lines = [
        f"[{code.value}] {info['message']}",
    ]
    if details:
        lines.append(f"  Details: {details}")
    lines.append(f"  -> {info['suggestion']}")
    lines.append(f"  -> Try: {info['cli_help']}")
    return "\n".join(lines)


# =============================================================================
# Safe Error Message (from error_utils.py)
# =============================================================================


def safe_error_message(e: Exception, context: str = "") -> str:
    """Return a sanitized error message for client responses.

    Logs the full error server-side while returning a generic message to clients.
    This prevents information disclosure of internal details like file paths,
    stack traces, or sensitive configuration.

    Args:
        e: The exception that occurred
        context: Optional context string for logging (e.g., "debate creation")

    Returns:
        User-friendly error message safe to return to clients
    """
    # Log full details server-side for debugging
    logger.error("Error in %s: %s: %s", context, type(e).__name__, e, exc_info=True)

    # Map common exceptions to user-friendly messages
    error_type = type(e).__name__
    if error_type in ("FileNotFoundError", "OSError"):
        return "Resource not found"
    elif error_type in ("json.JSONDecodeError", "ValueError"):
        return "Invalid data format"
    elif error_type in ("PermissionError",):
        return "Access denied"
    elif error_type in ("TimeoutError", "asyncio.TimeoutError"):
        return "Operation timed out"
    else:
        return "An error occurred"


# =============================================================================
# Error Formatter Class (from error_utils.py)
# =============================================================================

# Map HTTP status codes to error codes
_STATUS_TO_CODE: dict[int, ErrorCode] = {
    400: ErrorCode.INVALID_REQUEST,
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.CONFLICT,
    413: ErrorCode.PAYLOAD_TOO_LARGE,
    429: ErrorCode.RATE_LIMITED,
    500: ErrorCode.INTERNAL_ERROR,
    502: ErrorCode.EXTERNAL_SERVICE_ERROR,
    503: ErrorCode.SERVICE_UNAVAILABLE,
    504: ErrorCode.TIMEOUT,
}


class ErrorFormatter:
    """Unified error formatter for consistent API responses.

    Provides a single interface for formatting both client and server errors
    with automatic classification, sanitization, and trace ID generation.

    Example:
        formatter = ErrorFormatter()

        # Format client error (bad input)
        response = formatter.format_client_error(
            "Invalid agent name",
            field="agent",
            trace_id="abc123"
        )

        # Format server error (internal failure)
        response = formatter.format_server_error(
            exception,
            context="debate creation",
            trace_id="abc123"
        )

        # Auto-classify an exception
        api_error = formatter.classify_exception(exception, "debate creation")
    """

    # Map exception types to (status_code, error_code, default_message)
    EXCEPTION_TYPE_MAP: dict[str, tuple] = {
        "FileNotFoundError": (404, ErrorCode.NOT_FOUND, "Resource not found"),
        "OSError": (500, ErrorCode.INTERNAL_ERROR, "System error"),
        "JSONDecodeError": (400, ErrorCode.INVALID_FORMAT, "Invalid JSON format"),
        "ValueError": (400, ErrorCode.VALIDATION_ERROR, "Invalid value"),
        "KeyError": (400, ErrorCode.MISSING_PARAMETER, "Missing required field"),
        "PermissionError": (403, ErrorCode.FORBIDDEN, "Access denied"),
        "TimeoutError": (504, ErrorCode.TIMEOUT, "Operation timed out"),
        "ConnectionError": (502, ErrorCode.EXTERNAL_SERVICE_ERROR, "Connection failed"),
        "sqlite3.OperationalError": (503, ErrorCode.DATABASE_ERROR, "Database error"),
    }

    @classmethod
    def format_client_error(
        cls,
        message: str,
        status: int = 400,
        code: ErrorCode | None = None,
        field: str | None = None,
        trace_id: str | None = None,
        suggestion: str | None = None,
    ) -> dict[str, Any]:
        """Format a client error (4xx) response.

        Use for validation failures, bad requests, and missing resources.

        Args:
            message: Human-readable error message
            status: HTTP status code (default 400)
            code: Error code (auto-detected from status if not provided)
            field: Field that caused the error (for validation errors)
            trace_id: Request trace ID for correlation
            suggestion: Helpful suggestion for the user

        Returns:
            Formatted error response dict
        """
        error_code = code or _STATUS_TO_CODE.get(status, ErrorCode.INVALID_REQUEST)
        error_dict: dict[str, Any] = {
            "error": error_code.value,
            "message": message,
        }
        if trace_id:
            error_dict["trace_id"] = trace_id
        if field:
            error_dict["field"] = field
        if suggestion:
            error_dict["suggestion"] = suggestion
        return error_dict

    @classmethod
    def format_server_error(
        cls,
        exception: Exception,
        context: str = "",
        trace_id: str | None = None,
        log_full: bool = True,
    ) -> dict[str, Any]:
        """Format a server error (5xx) response.

        Logs full details server-side, returns sanitized message to client.

        Args:
            exception: The exception that occurred
            context: Context for logging (e.g., "debate creation")
            trace_id: Request trace ID for correlation
            log_full: Whether to log full exception with traceback

        Returns:
            Formatted error response dict with sanitized message
        """
        # Log full details server-side
        if log_full:
            logger.exception(
                "[%s] Error in %s: %s: %s",
                trace_id or "no-trace",
                context,
                type(exception).__name__,
                exception,
            )

        # Get classification
        status, code, message = cls._classify_exception_type(exception)

        error_dict: dict[str, Any] = {
            "error": code.value,
            "message": message,
        }
        if trace_id:
            error_dict["trace_id"] = trace_id
            error_dict["suggestion"] = "If this persists, contact support with the trace ID"
        return error_dict

    @classmethod
    def classify_exception(
        cls,
        exception: Exception,
        context: str = "",
        trace_id: str | None = None,
    ) -> AragoraAPIError:
        """Classify an exception into an AragoraAPIError.

        Args:
            exception: The exception to classify
            context: Context for the error
            trace_id: Request trace ID

        Returns:
            AragoraAPIError instance with appropriate classification
        """
        status, code, message = cls._classify_exception_type(exception)

        # Log for debugging
        logger.debug("Classified %s as %s (%s)", type(exception).__name__, code.value, status)

        return AragoraAPIError(
            code=code,
            message=message,
            status_code=status,
            context=ErrorContext(extra={"context": context} if context else {}),
        )

    @classmethod
    def _classify_exception_type(cls, exception: Exception) -> tuple:
        """Classify exception type to (status, code, message)."""
        exception_type = type(exception).__name__

        # Check direct mapping
        if exception_type in cls.EXCEPTION_TYPE_MAP:
            return cls.EXCEPTION_TYPE_MAP[exception_type]

        # Check fully qualified name for nested types
        full_type = f"{type(exception).__module__}.{exception_type}"
        if full_type in cls.EXCEPTION_TYPE_MAP:
            return cls.EXCEPTION_TYPE_MAP[full_type]

        # Check base classes
        for base_type, mapping in cls.EXCEPTION_TYPE_MAP.items():
            if base_type in str(type(exception).__mro__):
                return mapping

        # Default to internal error
        return 500, ErrorCode.INTERNAL_ERROR, "An error occurred"

    @classmethod
    def categorize_status(cls, status: int) -> str:
        """Categorize HTTP status code.

        Returns:
            Category string: "success", "redirect", "client_error", "server_error"
        """
        if 200 <= status < 300:
            return "success"
        elif 300 <= status < 400:
            return "redirect"
        elif 400 <= status < 500:
            return "client_error"
        else:
            return "server_error"


__all__ = [
    # Error codes
    "ErrorCode",
    # Context
    "ErrorContext",
    # Base class
    "AragoraAPIError",
    # Client errors
    "BadRequestError",
    "ValidationError",
    "AuthenticationError",
    "ForbiddenError",
    "NotFoundError",
    "MethodNotAllowedError",
    "ConflictError",
    "RateLimitError",
    "PayloadTooLargeError",
    # Server errors
    "InternalError",
    "ServiceUnavailableError",
    "GatewayTimeoutError",
    "DatabaseError",
    "ExternalServiceError",
    # Domain errors
    "DebateError",
    "VerificationError",
    "MemoryError",
    # Utilities
    "format_error_response",
    "get_status_code",
    "wrap_exception",
    "log_error",
    "EXCEPTION_MAP",
    # From error_utils.py consolidation
    "safe_error_message",
    "ERROR_SUGGESTIONS",
    "get_error_suggestion",
    "format_cli_error",
    "ErrorFormatter",
    "_STATUS_TO_CODE",
]
