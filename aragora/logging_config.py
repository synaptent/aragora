"""
Structured logging configuration for aragora.

Provides JSON-formatted logging with automatic context propagation,
trace ID injection, and configurable output handlers.

Usage:
    from aragora.logging_config import configure_logging, get_logger

    # Configure at application entry point
    configure_logging(level="INFO", json_output=True)

    # Get a structured logger
    logger = get_logger(__name__)
    logger.info("Processing request", request_id="abc123", user="alice")

    # Automatic context propagation
    with logger.context(debate_id="d123", agent="claude"):
        logger.info("Starting debate round")  # Includes debate_id and agent
"""

import json
import logging
import logging.handlers
import os
import sys
import threading
import time
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps
from typing import Any
from collections.abc import Callable

# Context variables for automatic field injection
_log_context: ContextVar[dict[str, Any]] = ContextVar("log_context", default={})


def _get_trace_context() -> dict[str, str | None]:
    """Get trace context from tracing middleware if available.

    This integrates the logging system with the distributed tracing middleware,
    automatically injecting trace_id and span_id into log records.

    Returns:
        Dict with trace_id and span_id (may be None if not in trace context)
    """
    try:
        from aragora.observability.middleware.tracing import get_span_id, get_trace_id

        return {
            "trace_id": get_trace_id(),
            "span_id": get_span_id(),
        }
    except ImportError:
        # Tracing middleware not available (e.g., in standalone scripts)
        return {"trace_id": None, "span_id": None}


# Import safe env helpers (no circular imports - env_helpers only uses 'os')
from aragora.config.env_helpers import env_int

# Environment configuration
LOG_LEVEL = os.environ.get("ARAGORA_LOG_LEVEL", "INFO").upper()
LOG_FORMAT = os.environ.get("ARAGORA_LOG_FORMAT", "json")  # "json" or "text"
LOG_FILE = os.environ.get("ARAGORA_LOG_FILE", "")

# Log rotation configuration (for file logging) - using safe int parsing
LOG_MAX_BYTES = env_int("ARAGORA_LOG_MAX_BYTES", 10 * 1024 * 1024)  # 10MB default
LOG_BACKUP_COUNT = env_int("ARAGORA_LOG_BACKUP_COUNT", 5)  # Keep 5 backups


@dataclass
class LogRecord:
    """Structured log record with all context fields."""

    timestamp: str
    level: str
    logger: str
    message: str
    fields: dict[str, Any] = field(default_factory=dict)
    trace_id: str | None = None
    span_id: str | None = None
    debate_id: str | None = None
    exception: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result: dict[str, Any] = {
            "ts": self.timestamp,
            "level": self.level,
            "logger": self.logger,
            "msg": self.message,
        }
        # Add context fields
        if self.trace_id:
            result["trace_id"] = self.trace_id
        if self.span_id:
            result["span_id"] = self.span_id
        if self.debate_id:
            result["debate_id"] = self.debate_id
        # Add custom fields
        if self.fields:
            result.update(self.fields)
        # Add exception info
        if self.exception:
            result["exception"] = self.exception
        return result

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), default=str)

    def to_text(self) -> str:
        """Format as human-readable text."""
        parts = [
            self.timestamp,
            f"[{self.level}]",
            f"[{self.logger}]",
        ]
        if self.trace_id:
            parts.append(f"[{self.trace_id[:8]}]")
        if self.debate_id:
            parts.append(f"[{self.debate_id}]")
        parts.append(self.message)
        if self.fields:
            field_str = " ".join(f"{k}={v}" for k, v in self.fields.items())
            parts.append(field_str)
        if self.exception:
            parts.append(f"\n{self.exception.get('traceback', '')}")
        return " ".join(parts)


class JSONFormatter(logging.Formatter):
    """JSON log formatter with structured field support."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        # Get context from ContextVar
        ctx = _log_context.get()

        # Get trace context from tracing middleware (fallback if not in local context)
        trace_ctx = _get_trace_context()

        # Build structured record (priority: local context > tracing middleware > record attr)
        log_record = LogRecord(
            timestamp=datetime.now(timezone.utc).isoformat() + "Z",
            level=record.levelname,
            logger=record.name,
            message=record.getMessage(),
            fields=getattr(record, "structured_fields", {}),
            trace_id=ctx.get("trace_id")
            or trace_ctx.get("trace_id")
            or getattr(record, "trace_id", None),
            span_id=ctx.get("span_id")
            or trace_ctx.get("span_id")
            or getattr(record, "span_id", None),
            debate_id=ctx.get("debate_id") or getattr(record, "debate_id", None),
        )

        # Add exception info if present
        if record.exc_info:
            log_record.exception = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else "Unknown",
                "message": str(record.exc_info[1]) if record.exc_info[1] else "",
                "traceback": self.formatException(record.exc_info),
            }

        return log_record.to_json()


class TextFormatter(logging.Formatter):
    """Human-readable text formatter with structured field support."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as text."""
        ctx = _log_context.get()

        # Get trace context from tracing middleware (fallback if not in local context)
        trace_ctx = _get_trace_context()

        log_record = LogRecord(
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            level=record.levelname,
            logger=record.name.split(".")[-1],  # Short name
            message=record.getMessage(),
            fields=getattr(record, "structured_fields", {}),
            trace_id=ctx.get("trace_id")
            or trace_ctx.get("trace_id")
            or getattr(record, "trace_id", None),
            span_id=ctx.get("span_id")
            or trace_ctx.get("span_id")
            or getattr(record, "span_id", None),
            debate_id=ctx.get("debate_id") or getattr(record, "debate_id", None),
        )

        if record.exc_info:
            log_record.exception = {
                "traceback": self.formatException(record.exc_info),
            }

        return log_record.to_text()


class StructuredLogger:
    """
    Structured logger wrapper with automatic context propagation.

    Provides methods for logging with structured fields that are
    automatically serialized to JSON or text format.
    """

    def __init__(self, name: str):
        self._logger = logging.getLogger(name)
        self._name = name

    def _log(
        self,
        level: int,
        message: str,
        *args: Any,
        exc_info: bool = False,
        **fields: Any,
    ) -> None:
        """Internal log method with structured fields."""
        if not self._logger.isEnabledFor(level):
            return

        # Apply %-formatting if positional args provided
        if args:
            message = message % args

        # Create log record with extra fields
        extra = {"structured_fields": fields}
        self._logger.log(level, message, exc_info=exc_info, extra=extra)

    def debug(self, message: str, *args: Any, **fields: Any) -> None:
        """Log at DEBUG level with optional structured fields."""
        self._log(logging.DEBUG, message, *args, **fields)

    def info(self, message: str, *args: Any, **fields: Any) -> None:
        """Log at INFO level with optional structured fields."""
        self._log(logging.INFO, message, *args, **fields)

    def warning(self, message: str, *args: Any, **fields: Any) -> None:
        """Log at WARNING level with optional structured fields."""
        self._log(logging.WARNING, message, *args, **fields)

    def error(self, message: str, *args: Any, exc_info: bool = False, **fields: Any) -> None:
        """Log at ERROR level with optional structured fields and exception."""
        self._log(logging.ERROR, message, *args, exc_info=exc_info, **fields)

    def exception(self, message: str, *args: Any, **fields: Any) -> None:
        """Log at ERROR level with exception info."""
        self._log(logging.ERROR, message, *args, exc_info=True, **fields)

    def critical(self, message: str, *args: Any, exc_info: bool = False, **fields: Any) -> None:
        """Log at CRITICAL level with optional structured fields."""
        self._log(logging.CRITICAL, message, *args, exc_info=exc_info, **fields)

    @property
    def level(self) -> int:
        """Get current log level."""
        return self._logger.level

    def isEnabledFor(self, level: int) -> bool:
        """Check if logger is enabled for level."""
        return self._logger.isEnabledFor(level)


class LogContext:
    """
    Context manager for setting log context fields.

    All logs within the context will automatically include the specified fields.
    """

    def __init__(self, **fields: Any):
        self._fields = fields
        self._token: Token[dict[str, Any]] | None = None

    def __enter__(self) -> "LogContext":
        # Merge with existing context
        current = _log_context.get()
        merged = {**current, **self._fields}
        self._token = _log_context.set(merged)
        return self

    def __exit__(self, *args) -> None:
        if self._token is not None:
            _log_context.reset(self._token)


def set_context(**fields: Any) -> None:
    """Set log context fields for the current async context."""
    current = _log_context.get()
    _log_context.set({**current, **fields})


def get_context() -> dict[str, Any]:
    """Get current log context fields."""
    return _log_context.get()


def clear_context() -> None:
    """Clear all log context fields."""
    _log_context.set({})


# Logger cache (thread-safe)
_loggers: dict[str, StructuredLogger] = {}
_loggers_lock = threading.Lock()


def get_logger(name: str) -> StructuredLogger:
    """
    Get or create a structured logger by name (thread-safe).

    Args:
        name: Logger name (typically __name__)

    Returns:
        StructuredLogger instance
    """
    with _loggers_lock:
        if name not in _loggers:
            _loggers[name] = StructuredLogger(name)
        return _loggers[name]


def configure_logging(
    level: str | None = None,
    json_output: bool | None = None,
    log_file: str | None = None,
    propagate: bool = True,
) -> None:
    """
    Configure logging for the application.

    Should be called once at application startup.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_output: If True, output JSON format; if False, text format
        log_file: Optional file path for log output
        propagate: Whether to propagate to root logger
    """
    # Resolve configuration
    log_level = getattr(logging, (level or LOG_LEVEL).upper(), logging.INFO)
    use_json = json_output if json_output is not None else (LOG_FORMAT == "json")
    file_path = log_file or LOG_FILE

    # Create formatter
    formatter = JSONFormatter() if use_json else TextFormatter()

    # Configure root logger
    root = logging.getLogger()
    root.setLevel(log_level)

    # Remove existing handlers
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    # Add console handler
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(log_level)
    root.addHandler(console_handler)

    # Add file handler with rotation if specified
    if file_path:
        file_handler = logging.handlers.RotatingFileHandler(
            file_path,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(log_level)
        root.addHandler(file_handler)

    # Configure aragora loggers
    aragora_logger = logging.getLogger("aragora")
    aragora_logger.setLevel(log_level)
    aragora_logger.propagate = propagate


# Integration with tracing module
def inject_trace_context() -> None:
    """
    Inject trace context from the tracing module into log context.

    Call this to sync trace IDs from spans into structured logs.
    """
    try:
        from aragora.debate.tracing import get_debate_id, get_tracer

        tracer = get_tracer()
        span = tracer.get_current_span()
        debate_id = get_debate_id()

        ctx = {}
        if span:
            ctx["trace_id"] = span.trace_id
            ctx["span_id"] = span.span_id
        if debate_id:
            ctx["debate_id"] = debate_id

        if ctx:
            current = _log_context.get()
            _log_context.set({**current, **ctx})
    except ImportError:
        pass  # Tracing module not available


# Decorators for automatic logging
def log_function(
    level: str = "DEBUG",
    log_args: bool = False,
    log_result: bool = False,
    log_duration: bool = True,
):
    """
    Decorator to log function entry, exit, and duration.

    Args:
        level: Log level for function logging
        log_args: Whether to log function arguments
        log_result: Whether to log function result
        log_duration: Whether to log execution duration
    """
    log_level = getattr(logging, level.upper(), logging.DEBUG)

    def decorator(func: Callable) -> Callable:
        logger = get_logger(func.__module__)

        @wraps(func)
        def wrapper(*args, **kwargs):
            fields: dict[str, Any] = {"function": func.__name__}
            if log_args:
                fields["args_count"] = len(args)
                fields["kwargs_keys"] = list(kwargs.keys())

            start = time.monotonic()
            try:
                result = func(*args, **kwargs)
                if log_duration:
                    fields["duration_ms"] = (time.monotonic() - start) * 1000
                if log_result and result is not None:
                    fields["result_type"] = type(result).__name__
                logger._log(log_level, f"Function completed: {func.__name__}", **fields)
                return result
            except (KeyboardInterrupt, SystemExit, GeneratorExit):
                raise
            except BaseException as e:
                fields["duration_ms"] = (time.monotonic() - start) * 1000
                fields["error"] = str(e)
                logger.error("Function failed: %s", func.__name__, exc_info=True, **fields)
                raise

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            fields: dict[str, Any] = {"function": func.__name__}
            if log_args:
                fields["args_count"] = len(args)
                fields["kwargs_keys"] = list(kwargs.keys())

            start = time.monotonic()
            try:
                result = await func(*args, **kwargs)
                if log_duration:
                    fields["duration_ms"] = (time.monotonic() - start) * 1000
                if log_result and result is not None:
                    fields["result_type"] = type(result).__name__
                logger._log(log_level, f"Function completed: {func.__name__}", **fields)
                return result
            except (KeyboardInterrupt, SystemExit, GeneratorExit):
                raise
            except BaseException as e:
                fields["duration_ms"] = (time.monotonic() - start) * 1000
                fields["error"] = str(e)
                logger.error("Function failed: %s", func.__name__, exc_info=True, **fields)
                raise

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return wrapper

    return decorator


def log_request(logger: StructuredLogger | None = None):
    """
    Decorator to log HTTP request handling.

    Logs request start, completion, and any errors with timing.
    """

    def decorator(func: Callable) -> Callable:
        _logger = logger or get_logger(func.__module__)

        @wraps(func)
        def wrapper(self, path: str, query_params: dict, *args, **kwargs):
            request_id = f"req_{int(time.time() * 1000) % 1000000:06d}"

            with LogContext(request_id=request_id, path=path):
                start = time.monotonic()
                _logger.info(
                    "Request started",
                    method=getattr(self, "method", "GET"),
                    query_params=list(query_params.keys()) if query_params else [],
                )
                try:
                    result = func(self, path, query_params, *args, **kwargs)
                    duration_ms = (time.monotonic() - start) * 1000
                    _logger.info(
                        "Request completed",
                        duration_ms=round(duration_ms, 2),
                        status="success",
                    )
                    return result
                except (KeyboardInterrupt, SystemExit, GeneratorExit):
                    raise
                except BaseException as e:
                    duration_ms = (time.monotonic() - start) * 1000
                    _logger.error(
                        "Request failed",
                        duration_ms=round(duration_ms, 2),
                        error=str(e),
                        exc_info=True,
                    )
                    raise

        return wrapper

    return decorator
