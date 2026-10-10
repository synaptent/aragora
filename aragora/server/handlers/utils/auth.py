"""
Unified Authentication Utilities for Handlers.

Provides secure authentication extraction from requests,
replacing header-trust patterns with JWT verification.

Usage:
    from aragora.server.handlers.utils.auth import (
        get_auth_context,
        require_authenticated,
        UnauthorizedError,
    )

    # In a handler method:
    auth_ctx = await get_auth_context(request)
    if not auth_ctx.is_authenticated:
        return error_response("Not authenticated", 401)
"""

from __future__ import annotations

import logging
from functools import wraps
from typing import Any, TypeVar, overload, cast
from collections.abc import Callable, Mapping

from aragora.rbac.models import AuthorizationContext

logger = logging.getLogger(__name__)

T = TypeVar("T")
F = TypeVar("F", bound=Callable[..., Any])


class UnauthorizedError(Exception):
    """Raised when authentication fails."""

    def __init__(self, message: str = "Authentication required"):
        super().__init__(message)
        self.message = message


class ForbiddenError(Exception):
    """Raised when authorization fails."""

    def __init__(self, message: str = "Access denied", permission: str | None = None):
        super().__init__(message)
        self.message = message
        self.permission = permission


async def get_auth_context(
    request: Any,
    require_auth: bool = False,
) -> AuthorizationContext:
    """
    Extract and verify authentication context from request.

    This function replaces the pattern of trusting X-User-ID headers
    with proper JWT verification.

    Args:
        request: HTTP request object (aiohttp request or similar)
        require_auth: If True, raises UnauthorizedError when not authenticated

    Returns:
        AuthorizationContext with user information

    Raises:
        UnauthorizedError: If require_auth=True and authentication fails
    """
    from aragora.billing.jwt_auth import extract_user_from_request, UserAuthContext

    try:
        user_store = _get_request_user_store(request)

        # Extract user from JWT token
        user_ctx: UserAuthContext = extract_user_from_request(request, user_store)

        if not user_ctx.is_authenticated:
            if require_auth:
                raise UnauthorizedError("Valid authentication token required")
            # Return anonymous context
            return AuthorizationContext(
                user_id="anonymous",
                org_id=None,
                workspace_id=None,
                roles=set(),
                permissions=set(),
            )

        # Build authorization context from authenticated user
        return AuthorizationContext(
            user_id=user_ctx.user_id,
            user_email=user_ctx.email,
            org_id=user_ctx.org_id,
            workspace_id=_extract_workspace_id(request),
            roles={user_ctx.role} if user_ctx.role else {"member"},
            permissions=_get_user_permissions(user_ctx),
        )

    except UnauthorizedError:
        raise
    except (TypeError, ValueError, KeyError, AttributeError, ImportError) as e:
        logger.warning("Error extracting auth context: %s", e)
        if require_auth:
            raise UnauthorizedError("Authentication failed")
        return AuthorizationContext(
            user_id="anonymous",
            org_id=None,
            workspace_id=None,
            roles=set(),
            permissions=set(),
        )


def _get_request_user_store(request: Any) -> Any | None:
    """Return the user store for API key validation, if one is available.

    aiohttp applications hold ``user_store`` as a mapping entry. FastAPI keeps
    it in ``app.state.context``; there ``app.get`` is the route decorator, so it
    must never be used as a lookup. The FastAPI lifespan leaves the context
    store as ``None`` while the Postgres pool is not ready, so FastAPI requests
    then use the global store, as ``aragora.server.fastapi.routes.auth`` does.
    """
    if not hasattr(request, "app"):
        return None
    app = request.app
    state_context = getattr(getattr(app, "state", None), "context", None)
    if isinstance(state_context, Mapping) or _is_starlette_app(app):
        store = state_context.get("user_store") if isinstance(state_context, Mapping) else None
        # Only API keys are validated against the store. Creating the global
        # store has side effects, so other requests must not trigger it.
        if store is None and _has_api_key_bearer(request):
            store = _get_global_user_store()
        return store
    if hasattr(app, "get"):
        return app.get("user_store")
    return None


def _has_api_key_bearer(request: Any) -> bool:
    headers = getattr(request, "headers", None)
    auth_header = headers.get("Authorization", "") if headers is not None else ""
    return isinstance(auth_header, str) and auth_header.startswith("Bearer ara_")


def _get_global_user_store() -> Any | None:
    try:
        from aragora.storage.user_store import get_user_store

        return get_user_store()
    except Exception:
        logger.error("Global user store unavailable for API key auth", exc_info=True)
        return None


def _is_starlette_app(app: Any) -> bool:
    try:
        from starlette.applications import Starlette
    except ImportError:
        return False
    return isinstance(app, Starlette)


def _extract_workspace_id(request: Any, user_id: str | None = None) -> str | None:
    """Extract workspace ID from request headers with optional membership validation.

    If user_id is provided and is not anonymous, validates that the workspace
    belongs to the user's memberships (when a workspace_store is available).
    """
    if not hasattr(request, "headers"):
        return None

    workspace_id = request.headers.get("X-Workspace-ID")
    if workspace_id is None:
        return None

    # Anonymous users or no user_id: return header value as-is
    if not user_id or user_id == "anonymous":
        return workspace_id

    # Authenticated user: validate workspace membership if store is available
    try:
        store = request.app.get("workspace_store")
    except (AttributeError, KeyError, TypeError) as e:
        logger.debug("Could not get workspace_store from app: %s", e)
        return workspace_id

    if store is None:
        return workspace_id

    try:
        memberships = store.get_user_workspaces(user_id)
        allowed_ids = set()
        for m in memberships:
            if isinstance(m, dict):
                allowed_ids.add(m.get("workspace_id") or m.get("id"))
            else:
                allowed_ids.add(getattr(m, "workspace_id", None) or getattr(m, "id", None))

        if workspace_id in allowed_ids:
            return workspace_id

        import logging

        logging.getLogger(__name__).warning(
            "User %s attempted workspace %s not in memberships", user_id, workspace_id
        )
        return None
    except (KeyError, ValueError, AttributeError, TypeError, OSError) as e:
        # Graceful degradation: on store errors, allow header through
        logger.warning("Workspace membership check failed, allowing header: %s", e)
        return workspace_id


def _get_user_permissions(user_ctx: Any) -> set[str]:
    """Get permissions for a user based on their roles."""
    from aragora.rbac.checker import get_permission_checker

    try:
        checker = get_permission_checker()
        # Get all permissions for user's roles
        permissions = set()
        roles = {user_ctx.role} if user_ctx.role else {"member"}
        for role in roles:
            role_perms = checker.get_role_permissions(role)
            permissions.update(role_perms)
        return permissions
    except (TypeError, ValueError, KeyError, AttributeError, ImportError) as e:
        logger.warning("Error getting user permissions: %s", e)
        return set()


@overload
def require_authenticated(func: F) -> F:
    """Overload for use without parentheses: @require_authenticated"""
    ...


@overload
def require_authenticated(
    func: None = None,
    *,
    on_failure: Callable[[Exception], Any] | None = None,
) -> Callable[[F], F]:
    """Overload for use with arguments: @require_authenticated(on_failure=...)"""
    ...


def require_authenticated(
    func: F | None = None,
    *,
    on_failure: Callable[[Exception], Any] | None = None,
) -> F | Callable[[F], F]:
    """
    Decorator to require authentication for a handler method.

    Can be used with or without arguments:

        @require_authenticated
        async def my_handler(self, request):
            ...

        @require_authenticated(on_failure=custom_handler)
        async def my_handler(self, request):
            ...

    Args:
        func: The function to wrap (when used without parentheses)
        on_failure: Optional callback when authentication fails

    Returns:
        Decorated function
    """

    def decorator(fn: F) -> F:
        @wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            # Find request in args/kwargs
            request = _find_request(args, kwargs)
            if request is None:
                raise UnauthorizedError("No request found for authentication")

            try:
                auth_ctx = await get_auth_context(request, require_auth=True)
                # Add auth context to kwargs for use by the handler
                kwargs["auth_context"] = auth_ctx
                return await fn(*args, **kwargs)
            except UnauthorizedError as e:
                if on_failure:
                    return on_failure(e)
                raise

        @wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            # For sync functions, we can't do async auth
            # This is a fallback - prefer async handlers
            raise NotImplementedError(
                "require_authenticated requires async handlers. "
                "Use 'async def' for your handler method."
            )

        import asyncio

        if asyncio.iscoroutinefunction(fn):
            return cast(F, async_wrapper)
        return cast(F, sync_wrapper)

    if func is not None:
        # Called without arguments: @require_authenticated
        return decorator(func)
    # Called with arguments: @require_authenticated(...)
    return decorator


def _find_request(args: tuple, kwargs: dict) -> Any | None:
    """Find the request object in function arguments."""
    # Check kwargs first
    if "request" in kwargs:
        return kwargs["request"]

    # Check positional args - typically request is first or second arg
    # (first if standalone function, second if method with self)
    for arg in args:
        if hasattr(arg, "headers") and hasattr(arg, "method"):
            return arg

    return None


def get_user_from_handler(handler: Any) -> tuple[str, str]:
    """
    Extract user ID and name from handler request.

    This is a compatibility function for existing handlers that
    use the old pattern. New code should use get_auth_context().

    Args:
        handler: HTTP request handler with headers

    Returns:
        Tuple of (user_id, user_name)
    """
    import asyncio

    # Try to get auth context asynchronously
    try:
        asyncio.get_running_loop()
        # Can't await in sync context with running loop
        # Fall back to header extraction with warning
        logger.warning(
            "get_user_from_handler called in async context - "
            "consider using await get_auth_context() instead"
        )
        return _extract_user_from_headers(handler)
    except RuntimeError:
        pass

    # Sync fallback - extract from headers with validation
    return _extract_user_from_headers(handler)


def _extract_user_from_headers(handler: Any) -> tuple[str, str]:
    """
    Extract user from JWT token only.

    SECURITY: Header-based authentication fallback has been removed to prevent
    identity spoofing and privilege escalation attacks. Only JWT-verified
    identities are returned.

    Args:
        handler: Request handler with headers

    Returns:
        Tuple of (user_id, user_name) from JWT, or ("anonymous", "Anonymous User")
        if no valid JWT token is present.
    """
    from aragora.billing.jwt_auth import extract_user_from_request

    try:
        # Extract user from JWT token - this is the ONLY trusted source
        user_ctx = extract_user_from_request(handler, None)
        if user_ctx.is_authenticated:
            return user_ctx.user_id, user_ctx.email or user_ctx.user_id
    except (TypeError, ValueError, KeyError, AttributeError, ImportError) as e:
        logger.debug("JWT extraction failed: %s", e)

    # SECURITY: Do NOT fall back to X-User-ID headers - they can be spoofed
    # Return anonymous identity instead
    logger.debug(
        "_extract_user_from_headers: No valid JWT token. "
        "Returning anonymous. X-User-ID headers are NOT trusted."
    )
    return "anonymous", "Anonymous User"
