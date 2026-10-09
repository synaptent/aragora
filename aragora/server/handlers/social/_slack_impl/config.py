"""
Slack integration configuration and lazy singletons.

Module-level constants, environment variables, and lazy-initialized
singleton accessors for audit logging, rate limiting, and workspace management.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any
from re import Pattern
from collections.abc import Callable

logger = logging.getLogger(__name__)

# --- Lazy import for audit logger (avoid circular imports) ---

_slack_audit: Any = None


def _get_audit_logger() -> Any:
    """Get or create Slack audit logger (lazy initialization)."""
    global _slack_audit
    if _slack_audit is None:
        try:
            from aragora.audit.slack_audit import get_slack_audit_logger

            _slack_audit = get_slack_audit_logger()
        except (ImportError, RuntimeError, OSError) as e:
            logger.debug("Slack audit logger not available: %s", e)
            _slack_audit = None
    return _slack_audit


# --- Lazy import for user rate limiter ---

_slack_user_limiter: Any = None


def _get_user_rate_limiter() -> Any:
    """Get or create user rate limiter for per-user rate limiting."""
    global _slack_user_limiter
    if _slack_user_limiter is None:
        try:
            from aragora.server.middleware.rate_limit.user_limiter import (
                get_user_rate_limiter,
            )

            _slack_user_limiter = get_user_rate_limiter()
        except (ImportError, RuntimeError, OSError) as e:
            logger.debug("User rate limiter not available: %s", e)
            _slack_user_limiter = None
    return _slack_user_limiter


# --- Lazy import for workspace rate limiter ---

_slack_workspace_limiter: Any = None

# Configurable workspace rate limit (requests per minute)
SLACK_WORKSPACE_RATE_LIMIT_RPM = int(os.environ.get("SLACK_WORKSPACE_RATE_LIMIT_RPM", "30"))


def _get_workspace_rate_limiter() -> Any:
    """Get or create workspace rate limiter for per-workspace rate limiting."""
    global _slack_workspace_limiter
    if _slack_workspace_limiter is None:
        try:
            from aragora.server.middleware.rate_limit.user_limiter import (
                get_user_rate_limiter,
            )

            # Use the same limiter infrastructure but with workspace-specific configuration
            _slack_workspace_limiter = get_user_rate_limiter()
            if _slack_workspace_limiter:
                _slack_workspace_limiter.action_limits["slack_workspace_command"] = (
                    SLACK_WORKSPACE_RATE_LIMIT_RPM
                )
        except (ImportError, RuntimeError, OSError) as e:
            logger.debug("Workspace rate limiter not available: %s", e)
            _slack_workspace_limiter = None
    return _slack_workspace_limiter


# --- URL validation ---

# Allowed domains for Slack response URLs (SSRF protection)
SLACK_ALLOWED_DOMAINS = frozenset({"hooks.slack.com", "api.slack.com"})

# Base URL for internal API calls (configurable for production)
ARAGORA_API_BASE_URL = os.environ.get("ARAGORA_API_BASE_URL", "http://localhost:8080")


def _validate_slack_url(url: str) -> bool:
    """Validate that a URL is a legitimate Slack endpoint.

    This prevents SSRF attacks by ensuring we only POST to Slack's servers.

    Args:
        url: The URL to validate

    Returns:
        True if the URL is a valid Slack endpoint, False otherwise
    """
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        # Must be HTTPS
        if parsed.scheme != "https":
            return False
        # Must be a Slack domain
        if parsed.netloc not in SLACK_ALLOWED_DOMAINS:
            return False
        return True
    except (ValueError, TypeError) as e:
        logger.debug("URL validation failed for slack: %s", e)
        return False


# --- Task tracking ---

import asyncio
import threading
from collections.abc import Coroutine


def _handle_task_exception(task: asyncio.Task[Any], task_name: str) -> None:
    """Handle exceptions from fire-and-forget async tasks."""
    if task.cancelled():
        logger.debug("Task %s was cancelled", task_name)
    elif task.exception():
        exc = task.exception()
        logger.error("Task %s failed with exception: %s", task_name, exc, exc_info=exc)


TrackedTaskInput = Coroutine[Any, Any, Any] | Callable[[], Coroutine[Any, Any, Any]]


def _resolve_tracked_task_coro(coro_or_factory: TrackedTaskInput) -> Coroutine[Any, Any, Any]:
    """Materialize a coroutine only when the scheduler is actually going to use it."""
    if callable(coro_or_factory):
        return coro_or_factory()
    return coro_or_factory


def create_tracked_task(coro_or_factory: TrackedTaskInput, name: str) -> asyncio.Task[Any]:
    """Schedule a fire-and-forget async task on the server's main event loop.

    In SQLite mode, HTTP handlers run in temporary event loops created by
    ``_run_handler_coroutine`` — those loops die when the handler returns.
    Using ``create_task`` on a temporary loop silently abandons the task.

    This function ALWAYS dispatches to the persistent main server loop
    (set in ``unified_server.start()``) so background tasks survive.

    Accepts either a coroutine object or a no-arg coroutine factory so callers
    can defer coroutine creation until scheduling is certain.
    """
    coro = _resolve_tracked_task_coro(coro_or_factory)

    try:
        current = asyncio.get_running_loop()
    except RuntimeError:
        current = None

    # 1. Find the persistent main server loop
    main_loop: asyncio.AbstractEventLoop | None = None
    try:
        from aragora.server.unified_server import get_main_event_loop

        main_loop = get_main_event_loop()
    except ImportError:
        pass
    if main_loop is None:
        try:
            from aragora.utils.async_utils import get_pool_event_loop

            main_loop = get_pool_event_loop()
        except ImportError:
            pass

    # 2. Dispatch to the main loop if available
    if main_loop is not None and main_loop.is_running():
        if current is main_loop:
            # Already on the main loop — create_task is safe
            task = main_loop.create_task(coro, name=name)
            task.add_done_callback(lambda t: _handle_task_exception(t, name))
            return task

        # Different thread/loop — use threadsafe dispatch
        future = asyncio.run_coroutine_threadsafe(coro, main_loop)
        future.add_done_callback(
            lambda f: (
                logger.error("Task %s failed: %s", name, f.exception(), exc_info=f.exception())
                if f.exception()
                else None
            )
        )

        class _ThreadsafeTask:
            def add_done_callback(self, _cb: Any) -> None:
                return None

        return _ThreadsafeTask()  # type: ignore[return-value]

    # 3. If we're already on a live loop, prefer it over a background thread.
    if current is not None:
        task = current.create_task(coro, name=name)
        task.add_done_callback(lambda t: _handle_task_exception(t, name))
        return task

    # 4. Final fallback: thread with isolated event loop
    def _run_in_thread() -> None:
        try:
            asyncio.run(coro)
        except Exception as exc:
            logger.error("Task %s failed: %s", name, exc, exc_info=exc)

    thread = threading.Thread(target=_run_in_thread, name=f"slack-task-{name}", daemon=True)
    thread.start()

    class _BackgroundTask:
        def add_done_callback(self, _cb: Any) -> None:
            return None

    return _BackgroundTask()  # type: ignore[return-value]


# --- Handler imports ---

# RBAC permission for integration status endpoints
BOTS_READ_PERMISSION = "bots.read"

# Environment variables for Slack integration (fallback for single-workspace mode)
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET")
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

# Log at debug level for unconfigured optional integrations
if not SLACK_SIGNING_SECRET:
    logger.debug("SLACK_SIGNING_SECRET not configured - signature verification disabled")
if not SLACK_BOT_TOKEN:
    logger.debug("SLACK_BOT_TOKEN not configured - Slack API calls disabled")

# --- Multi-workspace support ---

_workspace_store: Any = None


def get_workspace_store() -> Any:
    """Get the Slack workspace store for multi-workspace support."""
    global _workspace_store
    if _workspace_store is None:
        try:
            from aragora.storage.slack_workspace_store import get_slack_workspace_store

            _workspace_store = get_slack_workspace_store()
        except ImportError:
            logger.debug("Slack workspace store not available")
    return _workspace_store


def resolve_workspace(team_id: str) -> Any:
    """Resolve a workspace by team_id.

    Returns workspace object if found, None otherwise.
    Falls back to environment variable configuration if no store configured.
    """
    if not team_id:
        return None

    store = get_workspace_store()
    if store:
        try:
            return store.get(team_id)
        except Exception as e:
            logger.debug("Failed to get workspace %s: %s", team_id, e)

    return None


# --- Command parsing patterns ---

COMMAND_PATTERN: Pattern[str] = re.compile(r"^/aragora\s+(\w+)(?:\s+(.*))?$")
TOPIC_PATTERN: Pattern[str] = re.compile(r'^["\']?(.+?)["\']?$')

# --- Slack integration singleton ---

_slack_integration: Any | None = None


def get_slack_integration() -> Any | None:
    """Get or create the Slack integration singleton."""
    global _slack_integration
    if _slack_integration is None:
        if not SLACK_WEBHOOK_URL:
            logger.debug("Slack integration disabled (no SLACK_WEBHOOK_URL)")
            return None
        try:
            from aragora.integrations.slack import SlackConfig, SlackIntegration

            config = SlackConfig(webhook_url=SLACK_WEBHOOK_URL)
            _slack_integration = SlackIntegration(config)
            logger.info("Slack integration initialized")
        except ImportError as e:
            logger.warning("Slack integration module not available: %s", e)
            return None
        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Invalid Slack configuration: %s", e)
            return None
        except (RuntimeError, OSError, AttributeError) as e:
            logger.exception("Unexpected error initializing Slack integration: %s", e)
            return None
    return _slack_integration


# --- Re-export common handler utilities for backward compatibility ---
# Other modules import these from config.py

# These are typed as Any since we have fallback stubs
HandlerResult: Any
SecureHandler: Any
ForbiddenError: type[Exception]
UnauthorizedError: type[Exception]
error_response: Callable[..., Any]
json_response: Callable[..., Any]
auto_error_response: Callable[[str], Callable[[Any], Any]]
rate_limit: Callable[..., Callable[[Any], Any]]

try:
    from aragora.server.handlers.base import (
        HandlerResult as _HandlerResult,
        error_response as _error_response,
        json_response as _json_response,
    )
    from aragora.server.handlers.secure import SecureHandler as _SecureHandler
    from aragora.server.handlers.utils.auth import (
        ForbiddenError as _ForbiddenError,
        UnauthorizedError as _UnauthorizedError,
    )
    from aragora.server.handlers.utils.decorators import (
        auto_error_response as _auto_error_response,
    )
    from aragora.server.handlers.utils.rate_limit import rate_limit as _rate_limit

    HandlerResult = _HandlerResult
    SecureHandler = _SecureHandler
    ForbiddenError = _ForbiddenError
    UnauthorizedError = _UnauthorizedError
    error_response = _error_response
    json_response = _json_response
    auto_error_response = _auto_error_response
    rate_limit = _rate_limit
except ImportError as e:
    logger.warning("Failed to import handler utilities: %s", e)
    # Define stubs to prevent import errors.
    # SecureHandler MUST be a real class (not None) so that SlackHandler
    # can inherit from it without a TypeError at class-definition time.
    HandlerResult = None
    ForbiddenError = Exception
    UnauthorizedError = Exception

    class _SecureHandlerStub:
        """Minimal stub for SecureHandler when handler utilities are unavailable."""

        def __init__(self, ctx: dict[str, Any] | None = None):
            self.ctx = ctx or {}

        def can_handle(self, path: str, method: str = "GET") -> bool:
            return False

        async def get_auth_context(self, handler: Any, **kwargs: Any) -> Any:
            return None

        def check_permission(self, auth_context: Any, permission: str) -> None:
            pass

    SecureHandler = _SecureHandlerStub

    def error_response(*args: Any, **kwargs: Any) -> Any:
        return None

    def json_response(*args: Any, **kwargs: Any) -> Any:
        return None

    def auto_error_response(operation: str) -> Callable[[Any], Any]:
        def decorator(func: Any) -> Any:
            return func

        return decorator

    def rate_limit(**kwargs: Any) -> Callable[[Any], Any]:
        def decorator(func: Any) -> Any:
            return func

        return decorator
