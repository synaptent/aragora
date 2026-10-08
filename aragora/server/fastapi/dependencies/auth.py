"""
FastAPI Authentication & RBAC Dependencies.

Provides dependency injection for auth context extraction and
permission checking, mirroring the legacy handler auth system.

Usage:
    from aragora.server.fastapi.dependencies.auth import (
        get_auth_context,
        require_authenticated,
        require_permission,
    )

    # Optional auth (returns anonymous context if no token)
    @router.get("/public")
    async def public_endpoint(auth: AuthorizationContext = Depends(get_auth_context)):
        ...

    # Required auth (returns 401 if not authenticated)
    @router.get("/private")
    async def private_endpoint(auth: AuthorizationContext = Depends(require_authenticated)):
        ...

    # Required permission (returns 401/403 as appropriate)
    @router.post("/admin")
    async def admin_endpoint(auth: AuthorizationContext = Depends(require_permission("admin:write"))):
        ...
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, HTTPException, Request

from aragora.rbac.models import AuthorizationContext

logger = logging.getLogger(__name__)


async def get_auth_context(request: Request) -> AuthorizationContext:
    """Extract authentication context from the request.

    Returns an AuthorizationContext (possibly anonymous) based on the
    Authorization header. Never raises - returns anonymous context on failure.

    Args:
        request: FastAPI request object.

    Returns:
        AuthorizationContext with user info or anonymous context.
    """
    from aragora.server.handlers.utils.auth import (
        get_auth_context as _extract_auth,
    )

    try:
        return await _extract_auth(request, require_auth=False)
    except (ValueError, TypeError, KeyError, RuntimeError, AttributeError) as e:
        logger.debug("Auth context extraction failed: %s", e)
        return AuthorizationContext(
            user_id="anonymous",
            org_id=None,
            workspace_id=None,
            roles=set(),
            permissions=set(),
        )


async def require_authenticated(
    auth: AuthorizationContext = Depends(get_auth_context),
    request: Request = None,  # type: ignore[assignment]  # FastAPI always injects it
) -> AuthorizationContext:
    """Require an authenticated user.

    Raises 401 if the request is not authenticated, except that a request
    carrying only the static API token on an org-scoped route gets 403
    ``org_required`` (the token identifies no user, so no org). Direct callers
    may omit ``request``.

    Returns:
        AuthorizationContext for the authenticated user.
    """
    if auth.user_id == "anonymous":
        if request is not None:
            from aragora.server.fastapi.middleware.error_handling import APIError
            from aragora.tenancy.record_scope import static_token_denial

            denial = static_token_denial(request.url.path, request.headers)
            if denial is not None:
                raise APIError(denial.message, status_code=denial.status, code=denial.code)
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return auth


def check_permission(auth: AuthorizationContext, permission: str) -> AuthorizationContext:
    """Return ``auth`` when it holds ``permission`` (directly or through its
    roles), else raise 403.

    For routes that must check something else first, such as record ownership,
    so that another org's record answers 404 whatever the caller's role.
    """
    if auth.has_permission(permission):
        return auth
    # Try the RBAC checker for role-based resolution
    try:
        from aragora.rbac.checker import get_permission_checker

        checker = get_permission_checker()
        if checker:
            decision = checker.check_permission(auth, permission)
            if decision.allowed:
                return auth
    except (ValueError, RuntimeError, ImportError, AttributeError) as e:
        logger.debug("RBAC checker error: %s", e)

    raise HTTPException(
        status_code=403,
        detail=f"Permission denied: {permission}",
    )


def require_permission(permission: str) -> Any:
    """Create a dependency that requires a specific RBAC permission.

    Args:
        permission: Permission string (e.g., "debates:create", "admin:write").

    Returns:
        FastAPI dependency function that validates the permission.

    Usage:
        @router.post("/decisions")
        async def create(auth = Depends(require_permission("debates:create"))):
            ...
    """

    async def _check_permission(
        auth: AuthorizationContext = Depends(require_authenticated),
    ) -> AuthorizationContext:
        return check_permission(auth, permission)

    return _check_permission
