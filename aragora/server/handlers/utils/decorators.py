"""
Handler decorators for authentication, validation, and error handling.

Provides reusable decorators for HTTP handlers including:
- Parameter validation (@validate_params)
- Error handling (@handle_errors, @auto_error_response)
- Request logging (@log_request)
- Authentication (@require_auth, @require_user_auth, @require_permission)
- Feature gating (@require_storage, @require_feature)
- Error recovery (@with_error_recovery)
"""

from __future__ import annotations

import json
import functools
import logging
import time
import uuid
from contextlib import contextmanager
from functools import wraps
from typing import Any
from collections.abc import Callable, Generator

from aragora.server.errors import ErrorCode, safe_error_message
from aragora.server.handlers.utils.params import (
    get_bool_param,
    get_float_param,
    get_int_param,
    get_string_param,
)
from aragora.server.handlers.utils.responses import HandlerResult, error_response, json_response

logger = logging.getLogger(__name__)

# =============================================================================
# Trace ID Generation
# =============================================================================


def generate_trace_id() -> str:
    """Generate a unique trace ID for request tracking."""
    return str(uuid.uuid4())[:8]


# =============================================================================
# Exception Handling
# =============================================================================

# Exception to HTTP status code mapping
_EXCEPTION_STATUS_MAP = {
    # Python built-in exceptions
    "FileNotFoundError": 404,
    "KeyError": 404,
    "ValueError": 400,
    "TypeError": 400,
    "json.JSONDecodeError": 400,
    "PermissionError": 403,
    "TimeoutError": 504,
    "asyncio.TimeoutError": 504,
    "ConnectionError": 502,
    "OSError": 500,
    # Aragora validation errors (400 Bad Request)
    "ValidationError": 400,
    "InputValidationError": 400,
    "SchemaValidationError": 400,
    "DebateConfigurationError": 400,
    "AgentConfigurationError": 400,
    "ModeConfigurationError": 400,
    "ConvergenceThresholdError": 400,
    "CacheKeyError": 400,
    # Aragora not found errors (404)
    "DebateNotFoundError": 404,
    "AgentNotFoundError": 404,
    "RecordNotFoundError": 404,
    "ModeNotFoundError": 404,
    "PluginNotFoundError": 404,
    "CheckpointNotFoundError": 404,
    # Aragora auth errors
    "AuthenticationError": 401,
    "TokenExpiredError": 401,
    "AuthorizationError": 403,
    "PermissionDeniedError": 403,
    "RoleRequiredError": 403,
    "MFARequiredError": 403,
    "RateLimitExceededError": 429,
    # Aragora storage errors (500/503)
    "StorageError": 500,
    "DatabaseError": 500,
    "DatabaseConnectionError": 503,
    "MemoryStorageError": 500,
    "CheckpointSaveError": 500,
    # Aragora agent errors
    "AgentTimeoutError": 504,
    "AgentRateLimitError": 429,
    "AgentConnectionError": 502,
    "AgentCircuitOpenError": 503,
    # Aragora verification/convergence errors
    "VerificationTimeoutError": 504,
    "Z3NotAvailableError": 503,
    "ConvergenceBackendError": 503,
    # Handler-specific exceptions (from aragora.server.handlers.exceptions)
    "HandlerError": 500,
    "HandlerValidationError": 400,
    "HandlerNotFoundError": 404,
    "HandlerAuthorizationError": 403,
    "HandlerConflictError": 409,
    "HandlerRateLimitError": 429,
    "HandlerExternalServiceError": 502,
    "HandlerDatabaseError": 500,
}

_EXCEPTION_ERROR_CODE_MAP = {
    "FileNotFoundError": ErrorCode.NOT_FOUND.value,
    "KeyError": ErrorCode.MISSING_PARAMETER.value,
    "ValueError": ErrorCode.VALIDATION_ERROR.value,
    "TypeError": ErrorCode.INVALID_REQUEST.value,
    "PermissionError": ErrorCode.FORBIDDEN.value,
    "TimeoutError": ErrorCode.TIMEOUT.value,
    "ConnectionError": ErrorCode.EXTERNAL_SERVICE_ERROR.value,
}

_STATUS_ERROR_CODE_MAP = {
    400: ErrorCode.INVALID_REQUEST.value,
    401: ErrorCode.UNAUTHORIZED.value,
    403: ErrorCode.FORBIDDEN.value,
    404: ErrorCode.NOT_FOUND.value,
    409: ErrorCode.CONFLICT.value,
    429: ErrorCode.RATE_LIMITED.value,
    500: ErrorCode.INTERNAL_ERROR.value,
    502: ErrorCode.EXTERNAL_SERVICE_ERROR.value,
    503: ErrorCode.SERVICE_UNAVAILABLE.value,
    504: ErrorCode.TIMEOUT.value,
}


def map_exception_to_status(e: Exception, default: int = 500) -> int:
    """Map exception type to appropriate HTTP status code."""
    error_type = type(e).__name__
    return _EXCEPTION_STATUS_MAP.get(error_type, default)


def map_exception_to_error_code(e: Exception, status: int) -> str:
    """Map exception type to machine-readable error code."""
    error_type = type(e).__name__
    return _EXCEPTION_ERROR_CODE_MAP.get(
        error_type,
        _STATUS_ERROR_CODE_MAP.get(status, ErrorCode.INTERNAL_ERROR.value),
    )


def add_error_code(response: HandlerResult, error_code: str) -> HandlerResult:
    """Preserve legacy error payloads while appending a top-level error_code."""
    payload = json.loads(response.body.decode("utf-8"))
    payload["error_code"] = error_code
    return json_response(payload, status=response.status_code, headers=response.headers)


# =============================================================================
# Parameter Validation Decorator
# =============================================================================


def validate_params(
    param_specs: dict[str, tuple],
    query_params_arg: str = "query_params",
) -> Callable[[Callable], Callable]:
    """
    Decorator for automatic query parameter validation and extraction.

    Validates and extracts query parameters into typed function arguments,
    eliminating boilerplate validation code from handler methods.

    Args:
        param_specs: Dict mapping param names to (type, default, min, max) tuples.
                    Types supported: int, float, bool, str.
                    Use None for unbounded min/max.
        query_params_arg: Name of the query_params argument in the function.

    Returns:
        Decorator function that adds validated params to kwargs.
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Find query_params in kwargs or positional args
            params = kwargs.get(query_params_arg)
            if params is None:
                # Try to find it in positional args by introspection
                import inspect

                sig = inspect.signature(func)
                param_names = list(sig.parameters.keys())
                if query_params_arg in param_names:
                    idx = param_names.index(query_params_arg)
                    if idx < len(args):
                        params = args[idx]

            if params is None:
                params = {}

            # Validate and extract each parameter
            extracted = {}
            for name, spec in param_specs.items():
                param_type, default, min_val, max_val = spec
                val: Any
                if param_type is int:
                    val = get_int_param(params, name, default)
                    if min_val is not None:
                        val = max(val, min_val)
                    if max_val is not None:
                        val = min(val, max_val)
                elif param_type is float:
                    val = get_float_param(params, name, default)
                    if min_val is not None:
                        val = max(val, min_val)
                    if max_val is not None:
                        val = min(val, max_val)
                elif param_type is bool:
                    val = get_bool_param(params, name, default)
                elif param_type is str:
                    val = get_string_param(params, name, default)
                    if val is not None and max_val is not None:
                        val = val[:max_val]
                else:
                    val = params.get(name, default)

                extracted[name] = val

            # Merge extracted params into kwargs
            kwargs.update(extracted)
            return func(*args, **kwargs)

        return wrapper

    return decorator


# =============================================================================
# Error Handling Decorators
# =============================================================================


def handle_errors(
    context: str | Callable[..., Any],
    default_status: int = 500,
) -> Callable[[Callable[..., Any]], Callable[..., Any]] | Callable[..., Any]:
    """
    Decorator for consistent exception handling with tracing.

    Wraps handler methods to:
    - Generate unique trace IDs for debugging
    - Log full exception details server-side
    - Return sanitized error messages to clients
    - Map exceptions to appropriate HTTP status codes

    Supports both sync and async handler methods.

    Args:
        context: Description of the operation (e.g., "debate creation"), or
            the decorated function itself when used as ``@handle_errors``.
        default_status: Default HTTP status for unrecognized exceptions

    Returns:
        Decorator function that wraps handler methods with error handling.
    """
    import asyncio

    if not isinstance(default_status, int):
        raise TypeError("default_status must be an int")

    def build_wrapper(func: Callable[..., Any], operation: str) -> Callable[..., Any]:
        if asyncio.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                trace_id = generate_trace_id()
                try:
                    return await func(*args, **kwargs)
                except Exception as e:  # noqa: BLE001 - generic handler decorator: wraps arbitrary handlers, must catch all to return proper HTTP error responses
                    logger.error(
                        "[%s] Error in %s: %s: %s",
                        trace_id,
                        operation,
                        type(e).__name__,
                        e,
                        exc_info=True,
                    )
                    status = map_exception_to_status(e, default_status)
                    message = safe_error_message(e, operation)
                    response = error_response(
                        message,
                        status=status,
                        headers={"X-Trace-Id": trace_id},
                    )
                    return add_error_code(response, map_exception_to_error_code(e, status))

            return async_wrapper
        else:

            @wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                trace_id = generate_trace_id()
                try:
                    return func(*args, **kwargs)
                except Exception as e:  # noqa: BLE001 - generic handler decorator: wraps arbitrary handlers, must catch all to return proper HTTP error responses
                    logger.error(
                        "[%s] Error in %s: %s: %s",
                        trace_id,
                        operation,
                        type(e).__name__,
                        e,
                        exc_info=True,
                    )
                    status = map_exception_to_status(e, default_status)
                    message = safe_error_message(e, operation)
                    response = error_response(
                        message,
                        status=status,
                        headers={"X-Trace-Id": trace_id},
                    )
                    return add_error_code(response, map_exception_to_error_code(e, status))

            return wrapper

    if callable(context):
        operation = getattr(context, "__name__", "handler operation")
        return build_wrapper(context, operation)
    if not isinstance(context, str):
        raise TypeError("context must be a string or callable")

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        return build_wrapper(func, context)

    return decorator


def auto_error_response(
    operation: str,
    log_level: str = "error",
    include_traceback: bool = True,
) -> Callable[[Callable], Callable]:
    """
    Decorator for automatic error response generation.

    Like @handle_errors but with configurable logging levels.

    Args:
        operation: Description of the operation being performed
        log_level: One of "error", "warning"
        include_traceback: Include stack trace in error log

    Returns:
        Decorator function that wraps handler methods.
    """
    import sqlite3

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> HandlerResult:
            try:
                return func(*args, **kwargs)
            except sqlite3.OperationalError as e:
                logger.error("Database error in %s: %s", operation, e)
                return error_response("Database unavailable", 503)
            except PermissionError:
                return error_response("Access denied", 403)
            except ValueError as e:
                logger.warning("Invalid request in %s: %s", operation, e)
                return error_response("Invalid request", 400)
            except Exception as e:  # noqa: BLE001 - generic handler decorator: wraps arbitrary handlers, must catch all to return proper HTTP error responses
                if log_level == "error":
                    logger.error(
                        "Failed to %s: %s",
                        operation,
                        e,
                        exc_info=include_traceback,
                    )
                elif log_level == "warning":
                    logger.warning("Failed to %s: %s", operation, e)
                return error_response(safe_error_message(e, operation), 500)

        return wrapper

    return decorator


def log_request(context: str, log_response: bool = False) -> Callable[[Callable], Callable]:
    """
    Decorator for structured request/response logging.

    Logs request start, completion time, and status code for debugging
    and observability. Use on POST/PUT handlers where detailed logging
    is valuable.

    Args:
        context: Description of the operation (e.g., "debate creation")
        log_response: If True, also log response body (use cautiously for
                     privacy/size reasons)

    Returns:
        Decorator function that wraps handler methods with logging.
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            trace_id = generate_trace_id()
            start_time = time.time()
            logger.info("[%s] %s: started", trace_id, context)

            try:
                result = func(*args, **kwargs)
                duration_ms = round((time.time() - start_time) * 1000, 2)

                # Extract status code from result (supports HandlerResult and dicts)
                status_code = getattr(result, "status_code", 200) if result else 200
                if isinstance(result, dict):
                    status_code = result.get("status", 200)

                log_msg = f"[{trace_id}] {context}: {status_code} in {duration_ms}ms"
                if status_code >= 400:
                    logger.warning(log_msg)
                else:
                    logger.info(log_msg)

                if log_response and result:
                    body = getattr(result, "body", b"")
                    if body and len(body) < 1000:  # Only log small responses
                        logger.debug(
                            "[%s] Response: %s",
                            trace_id,
                            body.decode("utf-8", errors="ignore")[:500],
                        )

                return result

            except Exception as e:  # noqa: BLE001 - logging decorator: captures any exception for timing/tracing then re-raises
                duration_ms = round((time.time() - start_time) * 1000, 2)
                logger.error(
                    "[%s] %s: failed in %sms - %s: %s",
                    trace_id,
                    context,
                    duration_ms,
                    type(e).__name__,
                    e,
                    exc_info=True,
                )
                raise

        return wrapper

    return decorator


# =============================================================================
# Permission / RBAC
# =============================================================================

# Role-Based Access Control permission matrix
# Permission -> list of roles that have access
# Role hierarchy: owner > admin > member (higher roles inherit lower permissions)
PERMISSION_MATRIX: dict[str, list[str]] = {
    # Debate permissions
    "debates:read": ["member", "admin", "owner"],
    "debates:create": ["member", "admin", "owner"],
    "debates:write": ["member", "admin", "owner"],
    "debates:update": ["admin", "owner"],
    "debates:delete": ["admin", "owner"],
    "debates:export": ["member", "admin", "owner"],
    "settlements:read": ["member", "admin", "owner"],
    "settlements:write": ["admin", "owner"],
    # Agent permissions
    "agents:read": ["member", "admin", "owner"],
    "agents:create": ["admin", "owner"],
    "agents:update": ["admin", "owner"],
    "agents:delete": ["admin", "owner"],
    # Organization permissions
    "org:read": ["member", "admin", "owner"],
    "org:settings": ["admin", "owner"],
    "org:members": ["admin", "owner"],
    "org:invite": ["admin", "owner"],
    "org:billing": ["owner"],
    "org:delete": ["owner"],
    # Plugin permissions
    "plugins:read": ["member", "admin", "owner"],
    "plugins:install": ["admin", "owner"],
    "plugins:configure": ["admin", "owner"],
    "plugins:uninstall": ["admin", "owner"],
    "plugins:run": ["member", "admin", "owner"],
    "plugins:execute": ["admin", "owner"],
    "plugins:manage": ["admin", "owner"],
    # Laboratory (experimental features)
    "laboratory:read": ["member", "admin", "owner"],
    "laboratory:execute": ["admin", "owner"],
    # Control Plane permissions
    "controlplane:read": ["member", "admin", "owner"],
    "controlplane:agents": ["admin", "owner"],
    "controlplane:agents.read": ["member", "admin", "owner"],
    "controlplane:agents.register": ["admin", "owner"],
    "controlplane:agents.unregister": ["admin", "owner"],
    "controlplane:tasks": ["admin", "owner"],
    "controlplane:tasks.read": ["member", "admin", "owner"],
    "controlplane:tasks.submit": ["admin", "owner"],
    "controlplane:tasks.claim": ["admin", "owner"],
    "controlplane:tasks.complete": ["admin", "owner"],
    "controlplane:deliberations.read": ["member", "admin", "owner"],
    "controlplane:deliberations.submit": ["admin", "owner"],
    "controlplane:health.read": ["member", "admin", "owner"],
    "controlplane:metrics.read": ["member", "admin", "owner"],
    "controlplane:queue.read": ["member", "admin", "owner"],
    "controlplane:notifications.read": ["member", "admin", "owner"],
    "controlplane:audit.read": ["admin", "owner"],
    "controlplane:audit.verify": ["admin", "owner"],
    "controlplane:violations.read": ["member", "admin", "owner"],
    "controlplane:violations.update": ["admin", "owner"],
    "controlplane:manage": ["owner"],
    # Training permissions
    "training:read": ["member", "admin", "owner"],
    "training:create": ["admin", "owner"],
    "training:export": ["admin", "owner"],
    # ML permissions
    "ml:read": ["member", "admin", "owner"],
    "ml:train": ["admin", "owner"],
    "ml:deploy": ["admin", "owner"],
    "ml:delete": ["admin", "owner"],
    # Connector permissions
    "connectors:read": ["member", "admin", "owner"],
    "connectors:create": ["admin", "owner"],
    "connectors:delete": ["admin", "owner"],
    "connectors:configure": ["admin", "owner"],
    # Webhook permissions
    "webhooks:read": ["member", "admin", "owner"],
    "webhooks:create": ["admin", "owner"],
    "webhooks:update": ["admin", "owner"],
    "webhooks:delete": ["admin", "owner"],
    "webhooks:test": ["admin", "owner"],
    "webhooks:admin": ["admin", "owner"],
    # Admin permissions
    "admin:*": ["owner"],
    "admin:audit": ["admin", "owner"],
    "admin:system": ["owner"],
    "admin:metrics": ["admin", "owner"],
    "admin:users": ["owner"],
    "admin:organizations.read": ["admin", "owner"],
    "admin:users.read": ["admin", "owner"],
    "admin:users.impersonate": ["owner"],
    "admin:users.deactivate": ["owner"],
    "admin:users.activate": ["owner"],
    "admin:users.unlock": ["admin", "owner"],
    "admin:stats.read": ["admin", "owner"],
    "admin:nomic.read": ["admin", "owner"],
    "admin:nomic.write": ["owner"],
    "admin:revenue.read": ["owner"],
    # API key management
    "apikeys:read": ["member", "admin", "owner"],
    "apikeys:create": ["member", "admin", "owner"],
    "apikeys:delete": ["member", "admin", "owner"],
    "apikeys:manage": ["admin", "owner"],
    "apikeys:export": ["owner"],
    # Secrets management
    "secrets:scan": ["admin", "owner"],
    "secrets:read": ["owner"],
    # Budget management
    "budget:read": ["admin", "owner"],
    "budget:set": ["owner"],
    # Billing (financial)
    "billing:read": ["admin", "owner"],
    "billing:cancel": ["owner"],
    "billing:delete": ["owner"],
    # Audit exports
    "audit:export": ["admin", "owner"],
    # Workflow management
    "workflows:read": ["member", "admin", "owner"],
    "workflows:create": ["admin", "owner"],
    "workflows:delete": ["admin", "owner"],
    # Checkpoints
    "checkpoints:read": ["member", "admin", "owner"],
    "checkpoints:delete": ["admin", "owner"],
    # Knowledge Mound permissions (KM checkpoints, knowledge reads)
    "knowledge:read": ["member", "admin", "owner"],
    "knowledge:write": ["admin", "owner"],
    "knowledge:delete": ["admin", "owner"],
    # Ralph campaign observability dashboard (read-only)
    "ralph:read": ["member", "admin", "owner"],
    # Finance/Accounting permissions
    "finance:read": ["member", "admin", "owner"],
    "finance:write": ["admin", "owner"],
    "finance:approve": ["admin", "owner"],
    "finance:export": ["admin", "owner"],
    # Cost visibility
    "costs:read": ["member", "admin", "owner"],
    # Accounts payable / receivable
    "ap:read": ["admin", "owner"],
    "ar:read": ["admin", "owner"],
    # Auth & SSO handlers
    "auth:read": ["member", "admin", "owner"],
    # Payroll permissions
    "payroll:read": ["admin", "owner"],
    "payroll:manage": ["owner"],
    # Payment permissions
    "payments:charge": ["admin", "owner"],
    "payments:authorize": ["admin", "owner"],
    "payments:capture": ["admin", "owner"],
    "payments:refund": ["admin", "owner"],
    "payments:void": ["admin", "owner"],
    "payments:read": ["member", "admin", "owner"],
    "payments:customer:create": ["admin", "owner"],
    "payments:customer:read": ["admin", "owner"],
    "payments:customer:delete": ["owner"],
    "payments:subscription:create": ["admin", "owner"],
    "payments:subscription:cancel": ["admin", "owner"],
    # Audit trail permissions
    "audit:read": ["admin", "owner"],
    "audit:verify": ["admin", "owner"],
    "audit:receipts.read": ["admin", "owner"],
    "audit:receipts.verify": ["admin", "owner"],
    "receipts:share": ["member", "admin", "owner"],
    # Policy/Compliance permissions
    "policies:read": ["member", "admin", "owner"],
    "policies:create": ["admin", "owner"],
    "policies:update": ["admin", "owner"],
    "policies:delete": ["owner"],
    # Metrics permissions
    "metrics:read": ["member", "admin", "owner"],
    # RLM permissions
    "rlm:read": ["member", "admin", "owner"],
    "rlm:create": ["admin", "owner"],
    # Queue permissions
    "queue:read": ["member", "admin", "owner"],
    "queue:create": ["admin", "owner"],
    # Evolution permissions
    "evolution:read": ["member", "admin", "owner"],
    # Gateway permissions (OpenClaw, external agents)
    "gateway:read": ["member", "admin", "owner"],
    "gateway:sessions.read": ["member", "admin", "owner"],
    "gateway:sessions.create": ["admin", "owner"],
    "gateway:sessions.delete": ["admin", "owner"],
    "gateway:actions.read": ["member", "admin", "owner"],
    "gateway:actions.execute": ["admin", "owner"],
    "gateway:actions.cancel": ["admin", "owner"],
    "gateway:credentials.read": ["admin", "owner"],
    "gateway:credentials.create": ["admin", "owner"],
    "gateway:credentials.delete": ["owner"],
    "gateway:credentials.rotate": ["admin", "owner"],
    "gateway:metrics.read": ["admin", "owner"],
    "gateway:audit.read": ["admin", "owner"],
    "gateway:admin": ["owner"],
    "gateway.execute": ["admin", "owner"],
    "gateway.read": ["member", "admin", "owner"],
    "gateway.create": ["admin", "owner"],
    "gateway.delete": ["admin", "owner"],
    "gateway.install": ["admin", "owner"],
    "gateway.uninstall": ["admin", "owner"],
    # Inbox permissions
    "inbox:read": ["member", "admin", "owner"],
    "inbox:update": ["member", "admin", "owner"],
    "inbox:write": ["admin", "owner"],
    # Cross-workspace coordination permissions
    "coordination:read": ["member", "admin", "owner"],
    "coordination:write": ["admin", "owner"],
    "coordination:delete": ["admin", "owner"],
    "coordination:execute": ["admin", "owner"],
    "coordination:admin": ["admin", "owner"],
}


def has_permission(role: str, permission: str) -> bool:
    """
    Check if a role has a specific permission.

    Args:
        role: User's role (member, admin, owner)
        permission: Permission string (e.g., "debates:create")

    Returns:
        True if role has the permission, False otherwise
    """
    if not role or not permission:
        return False

    # Check exact permission
    allowed_roles = PERMISSION_MATRIX.get(permission, [])
    if role in allowed_roles:
        return True

    # Check wildcard permission (e.g., "admin:*")
    permission_category = permission.split(":")[0]
    wildcard = f"{permission_category}:*"
    wildcard_roles = PERMISSION_MATRIX.get(wildcard, [])
    if role in wildcard_roles:
        return True

    return False


# Test hook: when set to a user context object, _check_permission returns it
# directly, bypassing handler lookup and auth checks. Only used by test fixtures.
_test_user_context_override = None


def require_permission(permission: str) -> Callable[[Callable], Callable]:
    """
    Decorator that requires a specific permission.

    First authenticates the user, then checks if they have the required
    permission based on their role.

    Args:
        permission: Required permission (e.g., "debates:create")
    """

    def decorator(func: Callable) -> Callable:
        def _check_permission(*args: Any, **kwargs: Any) -> tuple[Any, HandlerResult | None]:
            """Common permission checking logic, returns (user_ctx, error_response) tuple."""

            from aragora.billing.jwt_auth import extract_user_from_request

            handler = kwargs.get("handler")
            if handler is None and args:
                for arg in args:
                    if hasattr(arg, "headers"):
                        handler = arg
                        break

            if handler is None:
                # Test hook: when no handler is found, use override instead of 401
                if _test_user_context_override is not None:
                    return _test_user_context_override, None
                logger.warning("require_permission(%s): No handler provided", permission)
                return None, error_response("Authentication required", 401)

            user_store = None
            if hasattr(handler, "user_store"):
                user_store = handler.user_store
            elif hasattr(handler.__class__, "user_store"):
                user_store = handler.__class__.user_store

            user_ctx = extract_user_from_request(handler, user_store)

            if not user_ctx.is_authenticated:
                # Test hook: fall back to override when auth extraction fails
                if _test_user_context_override is not None:
                    return _test_user_context_override, None
                error_msg = user_ctx.error_reason or "Authentication required"
                return None, error_response(error_msg, 401)

            if not has_permission(user_ctx.role, permission):
                logger.warning(
                    "Permission denied: user=%s role=%s permission=%s",
                    user_ctx.user_id,
                    user_ctx.role,
                    permission,
                )
                return None, error_response("Permission denied", 403)

            return user_ctx, None

        # Check if the handler accepts a 'user' parameter
        import inspect

        sig = inspect.signature(func)
        accepts_user = "user" in sig.parameters or any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            user_ctx, err = _check_permission(*args, **kwargs)
            if err is not None:
                return err
            if accepts_user:
                kwargs["user"] = user_ctx
            return func(*args, **kwargs)

        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            user_ctx, err = _check_permission(*args, **kwargs)
            if err is not None:
                return err
            if accepts_user:
                kwargs["user"] = user_ctx
            return await func(*args, **kwargs)

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# =============================================================================
# Authentication Decorators
# =============================================================================


def require_user_auth(func: Callable) -> Callable:
    """
    Decorator that requires JWT/API key user authentication.

    Uses the billing JWT auth system to validate Bearer tokens and API keys.
    The authenticated user context is passed as 'user' keyword argument.
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        from aragora.billing.jwt_auth import extract_user_from_request

        handler = kwargs.get("handler")
        if handler is None and args:
            for arg in args:
                if hasattr(arg, "headers"):
                    handler = arg
                    break

        if handler is None:
            logger.warning("require_user_auth: No handler provided")
            return error_response("Authentication required", 401)

        user_store = None
        if hasattr(handler, "user_store"):
            user_store = handler.user_store
        elif hasattr(handler.__class__, "user_store"):
            user_store = handler.__class__.user_store

        user_ctx = extract_user_from_request(handler, user_store)

        if not user_ctx.is_authenticated:
            error_msg = user_ctx.error_reason or "Authentication required"
            return error_response(error_msg, 401)

        kwargs["user"] = user_ctx
        return func(*args, **kwargs)

    return wrapper


def require_auth(func: Callable) -> Callable:
    """
    Decorator that ALWAYS requires authentication via ARAGORA_API_TOKEN.

    Use this for sensitive endpoints that must never run without authentication.
    For JWT/API key authentication, use @require_user_auth instead.
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        from aragora.server.auth import auth_config

        handler = kwargs.get("handler")
        if handler is None and args:
            for arg in args:
                if hasattr(arg, "headers"):
                    handler = arg
                    break

        if handler is None:
            logger.warning("require_auth: No handler provided, denying access")
            return error_response("Authentication required", 401)

        auth_header = None
        if hasattr(handler, "headers"):
            auth_header = handler.headers.get("Authorization", "")

        token = None
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]

        if not auth_config.api_token:
            logger.warning("require_auth: No API token configured, denying access")
            return error_response(
                "Authentication required. Set ARAGORA_API_TOKEN environment variable.", 401
            )

        if not token or not auth_config.validate_token(token):
            return error_response("Invalid or missing authentication token", 401)

        return func(*args, **kwargs)

    return wrapper


# =============================================================================
# Feature Gating Decorators
# =============================================================================


def require_storage(func: Callable) -> Callable:
    """
    Decorator that requires storage to be available.

    Returns 503 Service Unavailable if storage is not configured.
    """

    @wraps(func)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        storage = self.get_storage()
        if not storage:
            return error_response("Storage not available", 503)
        return func(self, *args, **kwargs)

    return wrapper


def require_feature(
    feature_check: Callable[[], bool],
    feature_name: str,
    status_code: int = 503,
) -> Callable[[Callable], Callable]:
    """
    Decorator that requires a feature to be available.

    Args:
        feature_check: Callable that returns True if feature is available
        feature_name: Human-readable name for error message
        status_code: HTTP status code to return if unavailable
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not feature_check():
                return error_response(f"{feature_name} not available", status_code)
            return func(*args, **kwargs)

        return wrapper

    return decorator


# =============================================================================
# Error Recovery
# =============================================================================


@contextmanager
def safe_fetch(
    data_dict: dict[str, Any],
    errors_dict: dict[str, Any],
    key: str,
    fallback: Any,
    log_errors: bool = True,
) -> Generator[None, None, None]:
    """
    Context manager for safe data fetching with graceful fallback.

    Usage:
        with safe_fetch(data, errors, "rankings", {"agents": [], "count": 0}):
            data["rankings"] = self._fetch_rankings(limit)
    """
    try:
        yield
    except Exception as e:  # noqa: BLE001 - safe_fetch context manager: wraps arbitrary data retrieval, must catch all to provide fallback
        if log_errors:
            logger.warning("safe_fetch '%s' failed: %s: %s", key, type(e).__name__, e)
        errors_dict[key] = "Fetch failed"
        data_dict[key] = fallback


def with_error_recovery(
    fallback_value: Any = None,
    log_errors: bool = True,
    metrics_key: str | None = None,
) -> Callable[[Callable], Callable]:
    """
    Decorator for graceful error recovery with fallback values.

    Unlike handle_errors which returns HTTP error responses, this decorator
    returns a fallback value on error, allowing partial success.

    Args:
        fallback_value: Value to return on error
        log_errors: Whether to log errors
        metrics_key: Optional key for metrics tracking
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:  # noqa: BLE001 - error recovery decorator: wraps arbitrary functions, must catch all to return fallback value
                if log_errors:
                    logger.warning(
                        "with_error_recovery '%s' failed: %s: %s",
                        func.__name__,
                        type(e).__name__,
                        e,
                    )
                return fallback_value

        return wrapper

    return decorator


# =============================================================================
# Deprecation Decorator
# =============================================================================


def deprecated_endpoint(
    replacement: str | None = None,
    sunset_date: str | None = None,
    message: str | None = None,
) -> Callable[[Callable], Callable]:
    """
    Decorator for marking endpoints as deprecated.

    Adds RFC 8594 deprecation headers to responses and logs usage warnings.
    Use this on endpoints scheduled for removal.

    Args:
        replacement: URL path of the replacement endpoint (e.g., "/api/v2/debates")
        sunset_date: ISO 8601 date when endpoint will be removed (e.g., "2025-06-01")
        message: Custom deprecation message for logging

    Returns:
        Decorated function that adds deprecation headers to responses.

    Example:
        @deprecated_endpoint(replacement="/api/v1/debates", sunset_date="2025-06-01")
        def _create_debate_legacy(self, handler, user=None):
            ...

    Response Headers Added:
        - Deprecation: true
        - Sunset: Sat, 01 Jun 2025 00:00:00 GMT (if sunset_date provided)
        - Link: </api/debates>; rel="successor-version" (if replacement provided)
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Log deprecation warning
            endpoint_name = func.__name__
            log_msg = message or f"Deprecated endpoint used: {endpoint_name}"
            if replacement:
                log_msg += f". Use {replacement} instead."
            logger.warning(log_msg)

            # Execute the handler
            result = func(*args, **kwargs)

            # Add deprecation headers to result
            if result is not None and isinstance(result, dict):
                # Get or create headers dict
                headers = result.get("headers", {})

                # Add Deprecation header (RFC 8594)
                headers["Deprecation"] = "true"

                # Add Sunset header if date provided
                if sunset_date:
                    try:
                        from datetime import datetime

                        # Parse ISO date and format as HTTP-date
                        dt = datetime.fromisoformat(sunset_date)
                        # Format: Sat, 01 Jun 2025 00:00:00 GMT
                        headers["Sunset"] = dt.strftime("%a, %d %b %Y %H:%M:%S GMT")
                    except ValueError:
                        logger.warning("Invalid sunset_date format: %s", sunset_date)

                # Add Link header for replacement
                if replacement:
                    headers["Link"] = f'<{replacement}>; rel="successor-version"'

                result["headers"] = headers

            return result

        return wrapper

    return decorator


__all__ = [
    # Trace ID
    "generate_trace_id",
    # Exception handling
    "map_exception_to_status",
    # Parameter validation
    "validate_params",
    # Error handling decorators
    "handle_errors",
    "auto_error_response",
    "log_request",
    # Permission/RBAC
    "PERMISSION_MATRIX",
    "has_permission",
    "require_permission",
    # Authentication
    "require_user_auth",
    "require_auth",
    # Feature gating
    "require_storage",
    "require_feature",
    # Error recovery
    "safe_fetch",
    "with_error_recovery",
    # Deprecation
    "deprecated_endpoint",
]
