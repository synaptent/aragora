"""
Structured Logging Middleware.

Provides JSON-structured logging for production environments with:
- JSON-formatted log output for log aggregators (ELK, Datadog, Splunk)
- Automatic correlation ID propagation
- Request/response logging with timing
- Sensitive data redaction
- Log level configuration via environment

Usage:
    from aragora.server.middleware.structured_logging import (
        configure_structured_logging,
        get_logger,
        log_context,
    )

    # Configure at application startup
    configure_structured_logging(level="INFO", json_output=True)

    # Get a logger
    logger = get_logger(__name__)

    # Log with context
    with log_context(request_id="req-123", user_id="user-456"):
        logger.info("Processing request", extra={"action": "debate.create"})
"""

import json
import logging
import os
import sys
import time
import traceback
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from collections.abc import Generator

# Context variables for log context propagation
_log_context: ContextVar[dict[str, Any]] = ContextVar("log_context", default={})

# Environment-based configuration
LOG_LEVEL = os.environ.get("ARAGORA_LOG_LEVEL", "INFO").upper()
LOG_FORMAT = os.environ.get("ARAGORA_LOG_FORMAT", "json")  # "json" or "text"
LOG_INCLUDE_TIMESTAMP = os.environ.get("ARAGORA_LOG_TIMESTAMP", "true").lower() == "true"

# Sensitive fields to redact (field name patterns)
REDACT_FIELDS = frozenset(
    {
        # Authentication
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "api-key",
        "auth_token",
        "access_token",
        "refresh_token",
        "bearer",
        "authorization",
        "credential",
        "credentials",
        # Keys and certificates
        "private_key",
        "privatekey",
        "signing_key",
        "encryption_key",
        "client_secret",
        "client_id",  # Often paired with secret
        "webhook_secret",
        "jwt_secret",
        "session_key",
        # Payment/Financial
        "credit_card",
        "card_number",
        "cvv",
        "cvc",
        "expiry",
        "account_number",
        "routing_number",
        "bank_account",
        "stripe_key",
        "plaid_secret",
        # PII
        "ssn",
        "social_security",
        "tax_id",
        "national_id",
        # Session/Cookie
        "cookie",
        "session",
        "session_id",
        "csrf_token",
        # Database
        "db_password",
        "database_url",
        "connection_string",
        "dsn",
        # Cloud/Provider specific
        "aws_secret",
        "aws_access_key",
        "gcp_key",
        "azure_key",
        "openai_key",
        "anthropic_key",
        "sendgrid_key",
        "twilio_token",
    }
)

# Regex patterns for detecting secrets in string values
import re

SECRET_VALUE_PATTERNS = [
    # API keys (various formats)
    re.compile(r"sk[-_](?:live|test|prod)[-_][a-zA-Z0-9]{20,}"),  # Stripe-style
    re.compile(r"(?:api|key|token)[-_]?[a-zA-Z0-9]{32,}"),  # Generic API keys
    re.compile(r"[a-zA-Z0-9]{32}-us\d+"),  # Mailchimp-style
    # Bearer tokens / JWTs
    re.compile(r"Bearer\s+[a-zA-Z0-9\-_]+\.[a-zA-Z0-9\-_]+\.[a-zA-Z0-9\-_]+"),
    re.compile(r"eyJ[a-zA-Z0-9\-_]+\.eyJ[a-zA-Z0-9\-_]+\.[a-zA-Z0-9\-_]+"),  # JWT
    # AWS credentials
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS Access Key ID
    re.compile(r"aws[-_]?secret[-_]?[a-zA-Z0-9/+=]{40}"),
    # Private keys
    re.compile(r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----"),
    re.compile(r"-----BEGIN OPENSSH PRIVATE KEY-----"),  # nosec
    # Database connection strings
    re.compile(r"(?:postgres|mysql|mongodb|redis)://[^@]+:[^@]+@"),
    # Basic auth in URLs
    re.compile(r"https?://[^:]+:[^@]+@"),
]


def _contains_secret_pattern(value: str) -> bool:
    """Check if a string value matches any secret pattern.

    Args:
        value: String to check

    Returns:
        True if value appears to contain a secret
    """
    if not isinstance(value, str) or len(value) < 16:
        return False
    for pattern in SECRET_VALUE_PATTERNS:
        if pattern.search(value):
            return True
    return False


def redact_string(value: str) -> str:
    """Redact secrets from a string value.

    Preserves structure but masks secret values.

    Args:
        value: String that may contain secrets

    Returns:
        String with secrets redacted
    """
    if not isinstance(value, str):
        return value
    if _contains_secret_pattern(value):
        # Preserve first/last few chars for debugging
        if len(value) > 20:
            return f"{value[:4]}...{value[-4:]}[REDACTED]"
        return "[REDACTED]"
    return value


@dataclass
class LogContext:
    """Structured log context that can be attached to log records."""

    request_id: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    user_id: str | None = None
    org_id: str | None = None
    debate_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        result = {}
        if self.request_id:
            result["request_id"] = self.request_id
        if self.trace_id:
            result["trace_id"] = self.trace_id
        if self.span_id:
            result["span_id"] = self.span_id
        if self.user_id:
            result["user_id"] = self.user_id
        if self.org_id:
            result["org_id"] = self.org_id
        if self.debate_id:
            result["debate_id"] = self.debate_id
        if self.extra:
            result.update(self.extra)
        return result


def redact_sensitive(data: dict[str, Any], depth: int = 0) -> dict[str, Any]:
    """Recursively redact sensitive fields from a dictionary.

    Args:
        data: Dictionary to redact
        depth: Current recursion depth (max 5)

    Returns:
        New dictionary with sensitive values redacted
    """
    if depth > 5:
        return data

    result: dict[str, Any] = {}
    for key, value in data.items():
        key_lower = key.lower()
        is_sensitive_key = any(sensitive in key_lower for sensitive in REDACT_FIELDS)

        # Sensitive keys get fully redacted regardless of value type
        if is_sensitive_key:
            result[key] = "[REDACTED]"
        elif isinstance(value, dict):
            result[key] = redact_sensitive(value, depth + 1)
        elif isinstance(value, list):
            result[key] = [
                (
                    redact_sensitive(item, depth + 1)
                    if isinstance(item, dict)
                    else (redact_string(item) if isinstance(item, str) else item)
                )
                for item in value
            ]
        elif isinstance(value, str):
            # Check string values for secret patterns
            result[key] = redact_string(value)
        else:
            result[key] = value
    return result


class JsonFormatter(logging.Formatter):
    """JSON log formatter for structured logging.

    Outputs logs in JSON format with:
    - ISO timestamp
    - Log level
    - Logger name
    - Message
    - Context (request_id, user_id, etc.)
    - Extra fields
    - Exception info if present
    """

    def __init__(
        self,
        include_timestamp: bool = True,
        include_hostname: bool = True,
        service_name: str = "aragora",
    ):
        super().__init__()
        self.include_timestamp = include_timestamp
        self.include_hostname = include_hostname
        self.service_name = service_name

        self._hostname: str | None
        if include_hostname:
            import socket

            self._hostname = socket.gethostname()
        else:
            self._hostname = None

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_entry: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add timestamp
        if self.include_timestamp:
            log_entry["timestamp"] = datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat()

        # Add service info
        log_entry["service"] = self.service_name
        if self._hostname:
            log_entry["hostname"] = self._hostname

        # Add context from contextvars
        ctx = _log_context.get()
        if ctx:
            log_entry["context"] = ctx

        # Add extra fields from record (excluding standard attributes)
        standard_attrs = {
            "name",
            "msg",
            "args",
            "created",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "exc_info",
            "exc_text",
            "thread",
            "threadName",
            "taskName",
            "message",
        }

        extra = {}
        for key, value in record.__dict__.items():
            if key not in standard_attrs and not key.startswith("_"):
                extra[key] = value

        if extra:
            log_entry["extra"] = redact_sensitive(extra)

        # Add exception info
        if record.exc_info:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else "Unknown",
                "message": str(record.exc_info[1]) if record.exc_info[1] else "",
                "traceback": self.formatException(record.exc_info),
            }

        # Add source location for errors
        if record.levelno >= logging.ERROR:
            log_entry["source"] = {
                "file": record.pathname,
                "line": record.lineno,
                "function": record.funcName,
            }

        return json.dumps(log_entry, default=str)


class TextFormatter(logging.Formatter):
    """Enhanced text formatter with context injection.

    Format: [timestamp] [level] [request_id] logger - message {extra}
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as enhanced text."""
        # Get context
        ctx = _log_context.get()
        request_id = ctx.get("request_id", "-")

        # Format timestamp
        timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S.%f"
        )[:-3]

        # Build base message
        parts = [
            f"[{timestamp}]",
            f"[{record.levelname:8}]",
            f"[{request_id}]",
            f"{record.name}",
            "-",
            record.getMessage(),
        ]

        # Add extra fields
        standard_attrs = {
            "name",
            "msg",
            "args",
            "created",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "exc_info",
            "exc_text",
            "thread",
            "threadName",
            "taskName",
            "message",
        }

        extra = {}
        for key, value in record.__dict__.items():
            if key not in standard_attrs and not key.startswith("_"):
                extra[key] = value

        if extra:
            extra = redact_sensitive(extra)
            parts.append(f"{{{json.dumps(extra)}}}")

        message = " ".join(parts)

        # Add exception
        if record.exc_info:
            message += "\n" + self.formatException(record.exc_info)

        return message


def configure_structured_logging(
    level: str = LOG_LEVEL,
    json_output: bool | None = None,
    service_name: str = "aragora",
) -> None:
    """Configure structured logging for the application.

    Should be called once at application startup.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_output: Whether to output JSON (default: based on ARAGORA_LOG_FORMAT env)
        service_name: Service name to include in logs

    Example:
        # In application startup
        configure_structured_logging(level="INFO", json_output=True)
    """
    # Determine format
    if json_output is None:
        json_output = LOG_FORMAT == "json"

    # Create formatter
    formatter: logging.Formatter
    if json_output:
        formatter = JsonFormatter(
            include_timestamp=LOG_INCLUDE_TIMESTAMP,
            service_name=service_name,
        )
    else:
        formatter = TextFormatter()

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Add new handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    # Suppress noisy loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the given name.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Logger instance
    """
    return logging.getLogger(name)


@contextmanager
def log_context(**kwargs: Any) -> Generator[None, None, None]:
    """Context manager to add fields to all logs within the context.

    Args:
        **kwargs: Fields to add to log context

    Example:
        with log_context(request_id="req-123", user_id="user-456"):
            logger.info("Processing")  # Will include request_id and user_id
    """
    # Get current context and create new one with additional fields
    current = _log_context.get().copy()
    current.update(kwargs)

    token = _log_context.set(current)
    try:
        yield
    finally:
        _log_context.reset(token)


def set_log_context(**kwargs: Any) -> None:
    """Set log context fields (persists until explicitly changed).

    Args:
        **kwargs: Fields to set in log context
    """
    current = _log_context.get().copy()
    current.update(kwargs)
    _log_context.set(current)


def clear_log_context() -> None:
    """Clear all log context fields."""
    _log_context.set({})


def get_log_context() -> dict[str, Any]:
    """Get current log context.

    Returns:
        Dictionary of current context fields
    """
    return _log_context.get().copy()


class RequestLoggingMiddleware:
    """Middleware for logging HTTP requests with structured format.

    Automatically logs:
    - Request start with method, path, client IP
    - Response with status code and timing
    - Errors with stack traces

    Usage:
        middleware = RequestLoggingMiddleware()

        # In request handler
        ctx = middleware.start_request(method, path, client_ip, headers)
        try:
            # ... handle request ...
            middleware.end_request(ctx, status_code)
        except Exception as e:
            middleware.log_error(ctx, e)
            raise
    """

    def __init__(self, slow_threshold_ms: float = 1000.0):
        """Initialize middleware.

        Args:
            slow_threshold_ms: Log warning for requests slower than this
        """
        self.slow_threshold_ms = slow_threshold_ms
        self.logger = get_logger("aragora.http")

    def start_request(
        self,
        method: str,
        path: str,
        client_ip: str,
        headers: dict[str, str] | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Log request start and return context.

        Args:
            method: HTTP method
            path: Request path
            client_ip: Client IP address
            headers: Request headers (sensitive values will be redacted)
            request_id: Optional request ID (generated if not provided)

        Returns:
            Request context dict for end_request
        """
        import uuid

        if not request_id:
            request_id = f"req-{uuid.uuid4().hex[:12]}"

        # Set log context
        set_log_context(
            request_id=request_id,
            method=method,
            path=path,
            client_ip=client_ip,
        )

        ctx = {
            "request_id": request_id,
            "method": method,
            "path": path,
            "client_ip": client_ip,
            "start_time": time.time(),
        }

        # Log request start
        extra: dict[str, Any] = {"event": "request_start"}
        if headers:
            extra["headers"] = redact_sensitive(dict(headers))

        self.logger.info("%s %s", method, path, extra=extra)

        return ctx

    def end_request(
        self,
        ctx: dict[str, Any],
        status_code: int,
        response_size: int | None = None,
    ) -> None:
        """Log request completion.

        Args:
            ctx: Context from start_request
            status_code: HTTP response status code
            response_size: Response body size in bytes
        """
        elapsed_ms = (time.time() - ctx["start_time"]) * 1000

        extra = {
            "event": "request_end",
            "status": status_code,
            "elapsed_ms": round(elapsed_ms, 2),
        }

        if response_size is not None:
            extra["response_size"] = response_size

        # Determine log level
        if status_code >= 500:
            level = logging.ERROR
        elif status_code >= 400:
            level = logging.WARNING
        elif elapsed_ms > self.slow_threshold_ms:
            level = logging.WARNING
            extra["slow_request"] = True
        else:
            level = logging.INFO

        self.logger.log(
            level,
            "%s %s -> %s (%.1fms)",
            ctx["method"],
            ctx["path"],
            status_code,
            elapsed_ms,
            extra=extra,
        )

        # Clear request context
        clear_log_context()

    def log_error(
        self,
        ctx: dict[str, Any],
        error: Exception,
        include_traceback: bool = True,
    ) -> None:
        """Log request error.

        Args:
            ctx: Context from start_request
            error: The exception that occurred
            include_traceback: Whether to include full traceback
        """
        elapsed_ms = (time.time() - ctx["start_time"]) * 1000

        extra = {
            "event": "request_error",
            "status": 500,
            "elapsed_ms": round(elapsed_ms, 2),
            "error_type": type(error).__name__,
            "error_message": str(error)[:500],
        }

        if include_traceback:
            extra["traceback"] = traceback.format_exc()

        self.logger.error(
            "%s %s -> ERROR: %s",
            ctx["method"],
            ctx["path"],
            type(error).__name__,
            extra=extra,
            exc_info=True,
        )


# Convenience function for quick logging setup
def setup_logging(json_output: bool = True, level: str = "INFO") -> None:
    """Quick logging setup for production.

    Args:
        json_output: Whether to output JSON format
        level: Log level
    """
    configure_structured_logging(level=level, json_output=json_output)


__all__ = [
    "configure_structured_logging",
    "get_logger",
    "log_context",
    "set_log_context",
    "clear_log_context",
    "get_log_context",
    "redact_sensitive",
    "redact_string",
    "RequestLoggingMiddleware",
    "JsonFormatter",
    "TextFormatter",
    "LogContext",
    "setup_logging",
]
