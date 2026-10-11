"""
Error monitoring integration for Aragora.

Provides centralized error tracking with optional Sentry integration.
Captures exceptions, performance data, and custom events.

Configuration via environment variables:
    SENTRY_DSN: Sentry DSN for error reporting (optional)
    SENTRY_ENVIRONMENT: Environment name (default: "development")
    SENTRY_TRACES_SAMPLE_RATE: Percentage of requests to trace (default: 0.1)

Usage:
    from aragora.server.error_monitoring import init_monitoring, capture_exception

    # Initialize at startup
    init_monitoring()

    # Capture exceptions
    try:
        risky_operation()
    except Exception as e:
        capture_exception(e, context={"debate_id": "123"})
"""

import logging
import os
import threading
from functools import wraps
from typing import Any, Literal, TypeVar, cast
from collections.abc import Callable

logger = logging.getLogger(__name__)

# Type variable for generic function signatures
F = TypeVar("F", bound=Callable[..., Any])

# Sentry log level type
SentryLevel = Literal["fatal", "critical", "error", "warning", "info", "debug"]

# Global state (protected by _init_lock)
_init_lock = threading.Lock()
_initialized = False
_sentry_available = False


def _get_release_version() -> str:
    """Get the release version from package metadata."""
    try:
        from aragora import __version__

        return f"aragora@{__version__}"
    except (ImportError, AttributeError):
        return "aragora@unknown"


def _before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """Filter and sanitize events before sending to Sentry.

    Removes sensitive data, adds context, and improves error grouping.
    """
    # Remove any API keys that might leak
    if "extra" in event:
        for key in list(event["extra"].keys()):
            key_lower = key.lower()
            if any(s in key_lower for s in ("key", "token", "secret", "password", "credential")):
                event["extra"][key] = "[REDACTED]"

    # Sanitize request headers
    if "request" in event and "headers" in event["request"]:
        headers = event["request"]["headers"]
        for sensitive in ("Authorization", "Cookie", "X-API-Key"):
            if sensitive in headers:
                headers[sensitive] = "[REDACTED]"

    # Improve error grouping with custom fingerprinting
    exception_info = hint.get("exc_info")
    if exception_info:
        exc_type, exc_value, _ = exception_info
        exc_type_name = exc_type.__name__ if exc_type else "Unknown"

        # Group by exception type and message pattern for common errors
        if "rate limit" in str(exc_value).lower():
            event["fingerprint"] = ["rate-limit-error", exc_type_name]
        elif "timeout" in str(exc_value).lower():
            event["fingerprint"] = ["timeout-error", exc_type_name]
        elif "circuit breaker" in str(exc_value).lower():
            event["fingerprint"] = ["circuit-breaker-error", exc_type_name]
        elif "agent" in str(exc_value).lower() and "failed" in str(exc_value).lower():
            event["fingerprint"] = ["agent-failure", exc_type_name]

    return event


def init_monitoring() -> bool:
    """Initialize error monitoring.

    Returns:
        True if Sentry was initialized, False otherwise.
    """
    global _initialized, _sentry_available

    # Fast path: already initialized
    if _initialized:
        return _sentry_available

    # Thread-safe initialization
    with _init_lock:
        if _initialized:
            return _sentry_available

        dsn = os.environ.get("SENTRY_DSN")
        if not dsn:
            logger.info("SENTRY_DSN not set, error monitoring disabled")
            _initialized = True
            return False

        try:
            import sentry_sdk
            from sentry_sdk.integrations.aiohttp import AioHttpIntegration
            from sentry_sdk.integrations.logging import LoggingIntegration

            environment = os.environ.get("SENTRY_ENVIRONMENT", "development")
            traces_sample_rate = float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1"))
            profiles_sample_rate = float(os.environ.get("SENTRY_PROFILES_SAMPLE_RATE", "0.1"))
            server_name = os.environ.get("SENTRY_SERVER_NAME", None)
            release = _get_release_version()

            sentry_sdk.init(
                dsn=dsn,
                environment=environment,
                release=release,
                server_name=server_name,
                traces_sample_rate=traces_sample_rate,
                profiles_sample_rate=profiles_sample_rate,
                integrations=[
                    AioHttpIntegration(),
                    LoggingIntegration(
                        level=logging.INFO,
                        event_level=logging.ERROR,
                    ),
                ],
                # Don't send PII by default
                send_default_pii=False,
                # Attach stack trace to log messages
                attach_stacktrace=True,
                # Sanitize events before sending
                before_send=_before_send,
                # Filter out health check transactions
                before_send_transaction=_filter_health_checks,
                # Enable source context
                include_source_context=True,
                # Max breadcrumbs to capture
                max_breadcrumbs=50,
            )

            _sentry_available = True
            logger.info("Sentry initialized: env=%s, release=%s", environment, release)

        except ImportError:
            logger.debug("sentry-sdk not installed, error monitoring disabled")
            _sentry_available = False
        except (ValueError, TypeError, RuntimeError) as e:
            # Configuration errors (invalid DSN, bad sample rates, SDK runtime issues)
            logger.error("Failed to initialize Sentry: %s", e)
            _sentry_available = False

        _initialized = True
        return _sentry_available


def _filter_health_checks(event: Any, hint: dict[str, Any]) -> Any:
    """Filter out health check endpoints from transaction sampling."""
    if event.get("transaction", "").startswith("/api/health"):
        return None
    return event


def capture_exception(
    exception: Exception,
    context: dict[str, Any] | None = None,
    level: str = "error",
) -> str | None:
    """Capture an exception for error monitoring.

    Args:
        exception: The exception to capture.
        context: Additional context to attach to the event.
        level: Severity level (error, warning, info).

    Returns:
        Event ID if captured, None otherwise.
    """
    if not _sentry_available:
        logger.exception("Uncaptured exception: %s", exception)
        return None

    try:
        import sentry_sdk

        with sentry_sdk.push_scope() as scope:
            if context:
                for key, value in context.items():
                    scope.set_extra(key, value)
            scope.level = level
            event_id: str | None = sentry_sdk.capture_exception(exception)
            return event_id
    except Exception as e:  # noqa: BLE001 - Intentional catch-all: error monitoring must never crash the main application
        logger.error("Failed to capture exception: %s", e)
        return None


def capture_message(
    message: str,
    level: SentryLevel = "info",
    context: dict[str, Any] | None = None,
) -> str | None:
    """Capture a message for error monitoring.

    Args:
        message: The message to capture.
        level: Severity level (error, warning, info).
        context: Additional context to attach to the event.

    Returns:
        Event ID if captured, None otherwise.
    """
    if not _sentry_available:
        logger.log(
            logging.ERROR if level == "error" else logging.INFO, "Uncaptured message: %s", message
        )
        return None

    try:
        import sentry_sdk

        with sentry_sdk.push_scope() as scope:
            if context:
                for key, value in context.items():
                    scope.set_extra(key, value)
            event_id: str | None = sentry_sdk.capture_message(message, level=level)
            return event_id
    except Exception as e:  # noqa: BLE001 - Intentional catch-all: error monitoring must never crash the main application
        logger.error("Failed to capture message: %s", e)
        return None


def set_user(
    user_id: str,
    ip_address: str | None = None,
    org_id: str | None = None,
    email: str | None = None,
    tier: str | None = None,
):
    """Set user context for error tracking.

    Args:
        user_id: User identifier (can be hashed/anonymized).
        ip_address: Optional IP address.
        org_id: Optional organization ID for multi-tenant context.
        email: Optional email (will be hashed if send_default_pii is False).
        tier: Optional subscription tier for context.
    """
    if not _sentry_available:
        return

    try:
        import sentry_sdk

        user_data = {
            "id": user_id,
            "ip_address": ip_address,
        }
        if email:
            # Hash email for privacy unless PII is enabled
            import hashlib

            user_data["email"] = hashlib.sha256(email.encode()).hexdigest()[:16]

        sentry_sdk.set_user(user_data)

        # Set org context as tags for filtering
        if org_id:
            sentry_sdk.set_tag("org_id", org_id)
        if tier:
            sentry_sdk.set_tag("tier", tier)

        # Set business context
        sentry_sdk.set_context(
            "business",
            {
                "org_id": org_id,
                "tier": tier,
            },
        )

    except Exception as e:  # noqa: BLE001 - Intentional catch-all: error monitoring must never crash the main application
        logger.error("Failed to set user: %s", e)


def set_tag(key: str, value: str):
    """Set a tag on the current scope.

    Args:
        key: Tag key.
        value: Tag value.
    """
    if not _sentry_available:
        return

    try:
        import sentry_sdk

        sentry_sdk.set_tag(key, value)
    except Exception as e:  # noqa: BLE001 - Intentional catch-all: error monitoring must never crash the main application
        logger.error("Failed to set tag: %s", e)


def set_debate_context(
    debate_id: str,
    domain: str | None = None,
    agent_names: list[str] | None = None,
    round_number: int | None = None,
):
    """Set debate-specific context for error tracking.

    Convenience function to set common debate tags.

    Args:
        debate_id: Unique debate identifier.
        domain: Debate domain (security, performance, etc.).
        agent_names: List of participating agent names.
        round_number: Current round number.
    """
    if not _sentry_available:
        return

    try:
        import sentry_sdk

        sentry_sdk.set_tag("debate_id", debate_id)
        if domain:
            sentry_sdk.set_tag("debate_domain", domain)
        if agent_names:
            sentry_sdk.set_tag("agents", ",".join(agent_names[:5]))  # Limit to 5
        if round_number is not None:
            sentry_sdk.set_tag("round", str(round_number))
        sentry_sdk.set_context(
            "debate",
            {
                "debate_id": debate_id,
                "domain": domain,
                "agents": agent_names,
                "round": round_number,
            },
        )
    except Exception as e:  # noqa: BLE001 - Intentional catch-all: error monitoring must never crash the main application
        logger.error("Failed to set debate context: %s", e)


def monitor_errors(func: F) -> F:
    """Decorator to automatically capture exceptions from a function.

    Usage:
        @monitor_errors
        async def risky_operation():
            ...
    """

    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 - Intentional catch-all: decorator captures any exception for monitoring then re-raises
            capture_exception(e, context={"function": func.__name__})
            raise

    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 - Intentional catch-all: decorator captures any exception for monitoring then re-raises
            capture_exception(e, context={"function": func.__name__})
            raise

    import asyncio

    if asyncio.iscoroutinefunction(func):
        return cast(F, async_wrapper)
    return cast(F, sync_wrapper)


def track_error_recovery(
    error_type: str,
    recovery_strategy: str,
    success: bool,
    duration_ms: float | None = None,
    context: dict[str, Any] | None = None,
):
    """Track error recovery attempts for telemetry.

    Useful for understanding which recovery strategies work best.

    Args:
        error_type: Type of error (agent_failure, timeout, rate_limit, etc.)
        recovery_strategy: Strategy used (fallback, retry, circuit_breaker, etc.)
        success: Whether recovery succeeded
        duration_ms: How long the recovery took
        context: Additional context
    """
    if not _sentry_available:
        logger.info(
            "Error recovery: type=%s, strategy=%s, success=%s, duration_ms=%s",
            error_type,
            recovery_strategy,
            success,
            duration_ms,
        )
        return

    try:
        import sentry_sdk

        # Track as a breadcrumb for debugging
        sentry_sdk.add_breadcrumb(
            category="error_recovery",
            message=f"Recovery attempt: {error_type} via {recovery_strategy}",
            level="info" if success else "warning",
            data={
                "error_type": error_type,
                "recovery_strategy": recovery_strategy,
                "success": success,
                "duration_ms": duration_ms,
                **(context or {}),
            },
        )

        # Track as metrics via custom event
        if not success:
            capture_message(
                f"Error recovery failed: {error_type}",
                level="warning",
                context={
                    "error_type": error_type,
                    "recovery_strategy": recovery_strategy,
                    "duration_ms": duration_ms,
                    **(context or {}),
                },
            )

    except Exception as e:  # noqa: BLE001 - Intentional catch-all: error monitoring must never crash the main application
        logger.error("Failed to track error recovery: %s", e)


def start_transaction(name: str, op: str = "task") -> Any:
    """Start a performance transaction.

    Args:
        name: Transaction name (e.g., "debate_run")
        op: Operation type (e.g., "task", "http", "db")

    Returns:
        Transaction object to use as context manager, or None if unavailable
    """
    if not _sentry_available:
        return None

    try:
        import sentry_sdk

        return sentry_sdk.start_transaction(name=name, op=op)
    except Exception as e:  # noqa: BLE001 - Intentional catch-all: error monitoring must never crash the main application
        logger.error("Failed to start transaction: %s", e)
        return None


def get_status() -> dict[str, Any]:
    """Get error monitoring status.

    Returns:
        Status dictionary with monitoring state.
    """
    return {
        "initialized": _initialized,
        "sentry_available": _sentry_available,
        "dsn_configured": bool(os.environ.get("SENTRY_DSN")),
        "environment": os.environ.get("SENTRY_ENVIRONMENT", "development"),
    }
