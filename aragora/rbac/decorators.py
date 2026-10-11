"""
RBAC Decorators - Easy permission enforcement for handlers.

Provides decorators for enforcing role-based access control (RBAC) on
handler methods and functions. These decorators check permissions or roles
before executing the decorated function, raising appropriate errors if
access is denied.

Main decorators:
- require_permission: Requires a specific permission (e.g., "debates:create")
- require_role: Requires specific role(s) (e.g., "admin")
- require_owner: Requires the "owner" role
- require_admin: Requires "admin" or "owner" role
- require_org_access: Requires access to a specific organization
- require_self_or_admin: Requires user is acting on self or has admin role
- with_permission_context: Builds AuthorizationContext from request data

Exceptions:
- PermissionDeniedError: Raised when a permission check fails
- RoleRequiredError: Raised when a required role is missing

Usage:
    from aragora.rbac.decorators import require_permission, require_role

    @require_permission("debates:create")
    async def create_debate(context: AuthorizationContext, ...):
        ...

    @require_role("admin")
    async def admin_action(context: AuthorizationContext, ...):
        ...
"""

from __future__ import annotations

import functools
import inspect
import logging
from typing import Any, TypeVar, ParamSpec, cast
from collections.abc import Callable, Coroutine

from .checker import get_permission_checker, PermissionChecker
from .models import AuthorizationContext, AuthorizationDecision

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")


def _default_audit_on_denied(decision: AuthorizationDecision) -> None:
    """Default handler to audit permission denials for security compliance.

    This is called automatically when auto_audit=True (the default) and
    a permission check fails. It logs the denial to the audit system.
    """
    try:
        from aragora.observability.unified_audit import audit_access

        audit_access(
            user_id=decision.context.user_id if decision.context else "unknown",
            permission=decision.permission_key,
            resource_id=decision.resource_id,
            granted=False,
            reason=decision.reason,
        )
    except ImportError:
        logger.exception("Failed to import permission denial audit emitter")
        return
    except (OSError, RuntimeError, ValueError, TypeError, AttributeError, KeyError):
        logger.exception("Failed to emit permission denial audit event")
        return


__all__ = [
    # Decorators
    "require_permission",
    "require_role",
    "require_owner",
    "require_admin",
    "require_org_access",
    "require_self_or_admin",
    "require_mfa",
    "with_permission_context",
    # Exceptions
    "MFARequiredError",
    "PermissionDeniedError",
    "RoleRequiredError",
]


class PermissionDeniedError(Exception):
    """Raised when a permission check fails."""

    def __init__(
        self,
        message: str,
        decision: AuthorizationDecision | None = None,
    ) -> None:
        super().__init__(message)
        self.decision = decision
        self.permission_key = decision.permission_key if decision else None
        self.resource_id = decision.resource_id if decision else None


class RoleRequiredError(Exception):
    """Raised when a required role is missing."""

    def __init__(
        self,
        message: str,
        required_roles: set[str],
        actual_roles: set[str],
    ) -> None:
        super().__init__(message)
        self.required_roles = required_roles
        self.actual_roles = actual_roles


class MFARequiredError(Exception):
    """Raised when MFA verification is required but not present.

    Attributes:
        user_id: The user who failed the MFA check.
        roles: The user's roles that triggered the MFA requirement.
        required_action: URL for MFA setup/verification.
        grace_period_remaining_hours: Hours remaining in grace period, if applicable.
    """

    def __init__(
        self,
        message: str,
        user_id: str | None = None,
        roles: set[str] | None = None,
        required_action: str = "/api/auth/mfa/setup",
        grace_period_remaining_hours: int | None = None,
    ) -> None:
        super().__init__(message)
        self.user_id = user_id
        self.roles = roles or set()
        self.required_action = required_action
        self.grace_period_remaining_hours = grace_period_remaining_hours


def _get_context_from_args(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    context_param: str,
) -> AuthorizationContext | None:
    """Extract authorization context from function arguments."""
    # Check kwargs first
    if context_param in kwargs:
        ctx = kwargs[context_param]
        if isinstance(ctx, AuthorizationContext):
            return ctx

    # Check if first arg is context
    if args and isinstance(args[0], AuthorizationContext):
        return args[0]

    # Check if it's a method with self/cls
    if len(args) >= 2 and isinstance(args[1], AuthorizationContext):
        return args[1]

    # Try to find context in kwargs by type
    for value in kwargs.values():
        if isinstance(value, AuthorizationContext):
            return value

    # Check if any arg has _auth_context attribute (e.g., HTTP request handler).
    # Use getattr_static first so AttributeError from descriptor access does not
    # get treated as a missing attribute.
    for arg in args:
        try:
            inspect.getattr_static(arg, "_auth_context")
        except AttributeError:
            continue

        auth_context = arg._auth_context
        if isinstance(auth_context, AuthorizationContext):
            return auth_context

    return None


def require_permission(
    permission_key: str,
    resource_id_param: str | None = None,
    context_param: str = "context",
    checker: PermissionChecker | None = None,
    on_denied: Callable[[AuthorizationDecision], None] | None = None,
    auto_audit: bool = True,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """
    Decorator to require a specific permission.

    Args:
        permission_key: Permission required (e.g., "debates:create")
        resource_id_param: Optional parameter name containing resource ID
        context_param: Parameter name for AuthorizationContext
        checker: Custom permission checker (uses global if None)
        on_denied: Optional callback when permission is denied
        auto_audit: If True (default), automatically audit permission denials
            for security compliance. Uses _default_audit_on_denied unless
            on_denied is provided.

    Usage:
        @require_permission("debates:create")
        async def create_debate(context: AuthorizationContext, ...):
            ...

        @require_permission("debates:update", resource_id_param="debate_id")
        async def update_debate(context: AuthorizationContext, debate_id: str, ...):
            ...

        @require_permission("admin:sensitive", auto_audit=False)  # Disable audit
        async def sensitive_action(context: AuthorizationContext, ...):
            ...
    """
    # Determine the denial handler: use on_denied if provided, else auto_audit
    denial_handler: Callable[[AuthorizationDecision], None] | None = on_denied
    if denial_handler is None and auto_audit:
        denial_handler = _default_audit_on_denied

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            context = _get_context_from_args(args, kwargs, context_param)
            if context is None:
                # When auth is disabled (no ARAGORA_API_TOKEN), allow anonymous access
                from aragora.server.auth import auth_config

                if not auth_config.enabled:
                    return func(*args, **kwargs)
                raise PermissionDeniedError(
                    f"No AuthorizationContext found for permission check: {permission_key}"
                )

            # Get resource ID if specified
            resource_id: str | None = None
            if resource_id_param:
                raw_resource_id = kwargs.get(resource_id_param)
                if raw_resource_id is not None:
                    resource_id = str(raw_resource_id)
                else:
                    # Try positional args - this is fragile but necessary
                    sig = inspect.signature(func)
                    params = list(sig.parameters.keys())
                    if resource_id_param in params:
                        idx = params.index(resource_id_param)
                        if idx < len(args):
                            resource_id = str(args[idx])

            # Check permission
            perm_checker = checker or get_permission_checker()
            decision = perm_checker.check_permission(context, permission_key, resource_id)

            if not decision.allowed:
                if denial_handler:
                    denial_handler(decision)
                raise PermissionDeniedError(decision.reason, decision)

            return func(*args, **kwargs)

        @functools.wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            context = _get_context_from_args(args, kwargs, context_param)
            if context is None:
                from aragora.server.auth import auth_config

                if not auth_config.enabled:
                    return await cast(Coroutine[Any, Any, T], func(*args, **kwargs))
                raise PermissionDeniedError(
                    f"No AuthorizationContext found for permission check: {permission_key}"
                )

            # Get resource ID if specified
            resource_id: str | None = None
            if resource_id_param:
                raw_resource_id = kwargs.get(resource_id_param)
                if raw_resource_id is not None:
                    resource_id = str(raw_resource_id)

            # Check permission
            perm_checker = checker or get_permission_checker()
            decision = perm_checker.check_permission(context, permission_key, resource_id)

            if not decision.allowed:
                if denial_handler:
                    denial_handler(decision)
                raise PermissionDeniedError(decision.reason, decision)

            # Cast to coroutine since we know func is async at runtime
            return await cast(Coroutine[Any, Any, T], func(*args, **kwargs))

        # Return appropriate wrapper based on function type
        import asyncio

        if asyncio.iscoroutinefunction(func):
            return cast(Callable[P, T], async_wrapper)
        return cast(Callable[P, T], sync_wrapper)

    return decorator


def require_role(
    *role_names: str,
    require_all: bool = False,
    context_param: str = "context",
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """
    Decorator to require specific role(s).

    Args:
        *role_names: Role names required
        require_all: If True, all roles required. If False, any role is sufficient.
        context_param: Parameter name for AuthorizationContext

    Usage:
        @require_role("admin")
        async def admin_action(context: AuthorizationContext, ...):
            ...

        @require_role("owner", "admin")  # Either role works
        async def privileged_action(context: AuthorizationContext, ...):
            ...

        @require_role("admin", "billing_manager", require_all=True)  # Both required
        async def billing_admin_action(context: AuthorizationContext, ...):
            ...
    """
    required_roles = set(role_names)

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            context = _get_context_from_args(args, kwargs, context_param)
            if not context:
                raise RoleRequiredError(
                    "No AuthorizationContext found for role check",
                    required_roles,
                    set(),
                )

            if require_all:
                if not required_roles <= context.roles:
                    missing = required_roles - context.roles
                    raise RoleRequiredError(
                        f"Missing required roles: {missing}",
                        required_roles,
                        context.roles,
                    )
            else:
                if not (required_roles & context.roles):
                    raise RoleRequiredError(
                        f"Requires one of roles: {required_roles}",
                        required_roles,
                        context.roles,
                    )

            return func(*args, **kwargs)

        @functools.wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            context = _get_context_from_args(args, kwargs, context_param)
            if not context:
                raise RoleRequiredError(
                    "No AuthorizationContext found for role check",
                    required_roles,
                    set(),
                )

            if require_all:
                if not required_roles <= context.roles:
                    missing = required_roles - context.roles
                    raise RoleRequiredError(
                        f"Missing required roles: {missing}",
                        required_roles,
                        context.roles,
                    )
            else:
                if not (required_roles & context.roles):
                    raise RoleRequiredError(
                        f"Requires one of roles: {required_roles}",
                        required_roles,
                        context.roles,
                    )

            # Cast to coroutine since we know func is async at runtime
            return await cast(Coroutine[Any, Any, T], func(*args, **kwargs))

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return cast(Callable[P, T], async_wrapper)
        return cast(Callable[P, T], sync_wrapper)

    return decorator


def require_owner(
    context_param: str = "context",
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """
    Decorator to require owner role.

    Only users with the "owner" role can access the decorated function.
    This is the most restrictive role check available.

    Args:
        context_param: Parameter name for AuthorizationContext (default: "context")

    Raises:
        RoleRequiredError: If the user does not have the owner role

    Usage:
        @require_owner()
        async def delete_organization(context: AuthorizationContext, org_id: str):
            ...
    """
    return require_role("owner", context_param=context_param)


def require_admin(
    context_param: str = "context",
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """
    Decorator to require admin or owner role.

    Users with either "admin" or "owner" role can access the decorated function.
    This is suitable for administrative operations that shouldn't require
    full owner privileges.

    Args:
        context_param: Parameter name for AuthorizationContext (default: "context")

    Raises:
        RoleRequiredError: If the user has neither admin nor owner role

    Usage:
        @require_admin()
        async def update_workspace_settings(context: AuthorizationContext, ...):
            ...

        @require_admin()
        async def manage_users(context: AuthorizationContext, user_id: str):
            ...
    """
    return require_role("owner", "admin", context_param=context_param)


def require_org_access(
    org_id_param: str = "org_id",
    context_param: str = "context",
    allow_none: bool = False,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """
    Decorator to require access to a specific organization.

    Args:
        org_id_param: Parameter name containing organization ID
        context_param: Parameter name for AuthorizationContext
        allow_none: If True, allow access when org_id is None

    Usage:
        @require_org_access()
        async def org_action(context: AuthorizationContext, org_id: str, ...):
            ...
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            context = _get_context_from_args(args, kwargs, context_param)
            if not context:
                raise PermissionDeniedError("No AuthorizationContext found")

            org_id = kwargs.get(org_id_param)

            if org_id is None and allow_none:
                return func(*args, **kwargs)

            if org_id is None:
                raise PermissionDeniedError("Organization ID required but not provided")

            # Check if user belongs to the organization
            if context.org_id != org_id:
                # Allow if user is a platform admin (no org_id but has admin role)
                if context.org_id is None and "owner" in context.roles:
                    return func(*args, **kwargs)
                raise PermissionDeniedError(f"User does not have access to organization {org_id}")

            return func(*args, **kwargs)

        @functools.wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            context = _get_context_from_args(args, kwargs, context_param)
            if not context:
                raise PermissionDeniedError("No AuthorizationContext found")

            org_id = kwargs.get(org_id_param)

            if org_id is None and allow_none:
                return await cast(Coroutine[Any, Any, T], func(*args, **kwargs))

            if org_id is None:
                raise PermissionDeniedError("Organization ID required but not provided")

            if context.org_id != org_id:
                if context.org_id is None and "owner" in context.roles:
                    return await cast(Coroutine[Any, Any, T], func(*args, **kwargs))
                raise PermissionDeniedError(f"User does not have access to organization {org_id}")

            return await cast(Coroutine[Any, Any, T], func(*args, **kwargs))

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return cast(Callable[P, T], async_wrapper)
        return cast(Callable[P, T], sync_wrapper)

    return decorator


def require_self_or_admin(
    user_id_param: str = "user_id",
    context_param: str = "context",
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """
    Decorator to require either the user is acting on themselves or is an admin.

    Useful for endpoints where users can modify their own data, or admins can
    modify any user's data.

    Usage:
        @require_self_or_admin()
        async def update_user(context: AuthorizationContext, user_id: str, ...):
            ...
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            context = _get_context_from_args(args, kwargs, context_param)
            if not context:
                raise PermissionDeniedError("No AuthorizationContext found")

            target_user_id = kwargs.get(user_id_param)

            # Allow if acting on self
            if target_user_id == context.user_id:
                return func(*args, **kwargs)

            # Allow if admin or owner
            if context.has_any_role("owner", "admin"):
                return func(*args, **kwargs)

            raise PermissionDeniedError("Can only modify own data or requires admin role")

        @functools.wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            context = _get_context_from_args(args, kwargs, context_param)
            if not context:
                raise PermissionDeniedError("No AuthorizationContext found")

            target_user_id = kwargs.get(user_id_param)

            if target_user_id == context.user_id:
                return await cast(Coroutine[Any, Any, T], func(*args, **kwargs))

            if context.has_any_role("owner", "admin"):
                return await cast(Coroutine[Any, Any, T], func(*args, **kwargs))

            raise PermissionDeniedError("Can only modify own data or requires admin role")

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return cast(Callable[P, T], async_wrapper)
        return cast(Callable[P, T], sync_wrapper)

    return decorator


def require_mfa(
    context_param: str = "context",
    policy: Any = None,
    user_store: Any = None,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """
    Decorator to require MFA for admin-role operations.

    Integrates the MFA enforcement policy with the RBAC AuthorizationContext.
    Admin roles (admin, owner, superadmin, org_admin, workspace_admin,
    security_admin, compliance_officer) must have MFA enabled.

    Non-admin users are allowed through without MFA checks.

    SOC 2 Control: CC5-01 - Enforce MFA for administrative access.

    Args:
        context_param: Parameter name for AuthorizationContext (default: "context").
        policy: Optional MFAEnforcementPolicy override. If None, uses defaults.
        user_store: Optional user storage backend for MFA status resolution.

    Raises:
        MFARequiredError: If the user holds an admin role but MFA is not verified.

    Usage:
        @require_mfa()
        async def admin_action(context: AuthorizationContext, ...):
            ...

        @require_permission("admin:system_config")
        @require_mfa()
        async def sensitive_admin_action(context: AuthorizationContext, ...):
            ...
    """
    from aragora.auth.mfa_enforcement import (
        MFAEnforcementMiddleware,
        MFAEnforcementPolicy,
        MFAEnforcementResult,
    )

    enforcement_policy = policy if policy is not None else MFAEnforcementPolicy()
    middleware = MFAEnforcementMiddleware(
        policy=enforcement_policy,
        user_store=user_store,
    )

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            context = _get_context_from_args(args, kwargs, context_param)
            if context is None:
                # When auth is disabled, allow anonymous access
                try:
                    from aragora.server.auth import auth_config

                    if not auth_config.enabled:
                        return func(*args, **kwargs)
                except ImportError as exc:
                    raise MFARequiredError(
                        "Failed to load auth configuration for MFA check",
                    ) from exc
                raise MFARequiredError(
                    "No AuthorizationContext found for MFA check",
                )

            decision = middleware.enforce(context)

            if not decision.allowed:
                logger.warning(
                    "MFA enforcement denied access for user %s (roles: %s): %s",
                    context.user_id,
                    context.roles,
                    decision.reason,
                )
                raise MFARequiredError(
                    decision.reason,
                    user_id=context.user_id,
                    roles=context.roles,
                    required_action=decision.required_action or "/api/auth/mfa/setup",
                    grace_period_remaining_hours=decision.grace_period_remaining_hours,
                )

            if decision.result == MFAEnforcementResult.GRACE_PERIOD:
                logger.info(
                    "MFA grace period active for user %s (%d hours remaining)",
                    context.user_id,
                    decision.grace_period_remaining_hours or 0,
                )

            return func(*args, **kwargs)

        @functools.wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            context = _get_context_from_args(args, kwargs, context_param)
            if context is None:
                try:
                    from aragora.server.auth import auth_config

                    if not auth_config.enabled:
                        return await cast(Coroutine[Any, Any, T], func(*args, **kwargs))
                except ImportError as exc:
                    raise MFARequiredError(
                        "Failed to load auth configuration for MFA check",
                    ) from exc
                raise MFARequiredError(
                    "No AuthorizationContext found for MFA check",
                )

            decision = middleware.enforce(context)

            if not decision.allowed:
                logger.warning(
                    "MFA enforcement denied access for user %s (roles: %s): %s",
                    context.user_id,
                    context.roles,
                    decision.reason,
                )
                raise MFARequiredError(
                    decision.reason,
                    user_id=context.user_id,
                    roles=context.roles,
                    required_action=decision.required_action or "/api/auth/mfa/setup",
                    grace_period_remaining_hours=decision.grace_period_remaining_hours,
                )

            if decision.result == MFAEnforcementResult.GRACE_PERIOD:
                logger.info(
                    "MFA grace period active for user %s (%d hours remaining)",
                    context.user_id,
                    decision.grace_period_remaining_hours or 0,
                )

            return await cast(Coroutine[Any, Any, T], func(*args, **kwargs))

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return cast(Callable[P, T], async_wrapper)
        return cast(Callable[P, T], sync_wrapper)

    return decorator


def with_permission_context(
    user_id_func: Callable[..., str],
    org_id_func: Callable[..., str | None] | None = None,
    roles_func: Callable[..., set[str]] | None = None,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """
    Decorator that builds AuthorizationContext from request data.

    Useful when the handler doesn't receive a context directly but needs
    to build one from request headers or session data.

    Args:
        user_id_func: Function to extract user ID from args/kwargs
        org_id_func: Optional function to extract org ID
        roles_func: Optional function to extract roles

    Usage:
        @with_permission_context(
            user_id_func=lambda request: request.user_id,
            org_id_func=lambda request: request.org_id,
            roles_func=lambda request: request.roles,
        )
        @require_permission("debates:create")
        async def create_debate(context: AuthorizationContext, request: Request):
            ...
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            # Build context
            user_id = user_id_func(*args, **kwargs)
            org_id = org_id_func(*args, **kwargs) if org_id_func else None
            roles = roles_func(*args, **kwargs) if roles_func else set()

            context = AuthorizationContext(
                user_id=user_id,
                org_id=org_id,
                roles=roles,
            )

            # Add context to kwargs
            kwargs["context"] = context

            return func(*args, **kwargs)

        return cast(Callable[P, T], wrapper)

    return decorator
