"""
Authentication Middleware - High-Level Decorators.

Provides decorator-based authentication for API handlers. This module
provides the simplified decorator interface while user_auth.py contains
the comprehensive authentication implementation (JWT validation, Supabase
integration, user/workspace management).

Module Structure:
- auth.py (this file): Decorators like @require_auth, @optional_auth
- user_auth.py: Full auth implementation (User, Workspace, JWT validation)

Both are exported through __init__.py, so consumers can simply:
    from aragora.server.middleware import require_auth, User, authenticate_request

Usage:
    from aragora.server.middleware import require_auth, optional_auth

    @require_auth
    def sensitive_endpoint(self, handler):
        # Only executed if authenticated
        ...

    @optional_auth
    def public_endpoint(self, handler, auth_context):
        if auth_context.authenticated:
            # Show personalized data
        else:
            # Show public data
        ...
"""

from __future__ import annotations

import logging
import os
import warnings
from dataclasses import dataclass
from functools import wraps
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

from aragora.utils.request_ip import extract_client_ip as _extract_client_ip

if TYPE_CHECKING:
    from aragora.rbac.models import AuthorizationContext
    from aragora.server.handlers.base import HandlerResult

logger = logging.getLogger(__name__)


@dataclass
class AuthContext:
    """
    Authentication context passed to handlers.

    Contains information about the authenticated user/client.

    Note: For new code requiring permissions/RBAC, prefer using
    `AuthorizationContext` from `aragora.rbac.models` which provides:
    - Roles and permissions
    - Org/workspace scoping
    - API key scope validation
    - Permission checking methods

    Use `to_authorization_context()` to upgrade this context when needed.
    """

    authenticated: bool = False
    token: str | None = None
    client_ip: str | None = None
    user_id: str | None = None
    # Extended fields for RBAC compatibility
    org_id: str | None = None
    workspace_id: str | None = None
    roles: set[str] | None = None
    permissions: set[str] | None = None

    @property
    def is_authenticated(self) -> bool:
        """Alias for authenticated."""
        return self.authenticated

    def to_authorization_context(self) -> AuthorizationContext:
        """
        Convert to full AuthorizationContext for RBAC operations.

        If permissions are not already set, resolves them from the user's
        roles using the RBAC defaults. This ensures OAuth-authenticated users
        who have roles but no explicit permissions get the correct default
        permissions for their role.

        Returns:
            AuthorizationContext with this context's fields populated.
        """
        from aragora.rbac.models import AuthorizationContext

        roles = self.roles or set()
        permissions = self.permissions or set()

        # Resolve permissions from roles if not already populated
        if not permissions and roles:
            try:
                from aragora.rbac.defaults import get_role_permissions

                for role in roles:
                    permissions |= get_role_permissions(role, include_inherited=True)
            except (ImportError, Exception) as e:
                logger.debug("Could not resolve RBAC permissions from roles: %s", e)

        return AuthorizationContext(
            user_id=self.user_id or "anonymous",
            org_id=self.org_id,
            workspace_id=self.workspace_id,
            roles=roles,
            permissions=permissions,
            ip_address=self.client_ip,
        )

    def has_permission(self, permission_key: str) -> bool:
        """Check if context has a permission (delegates to RBAC)."""
        if not self.permissions:
            return False
        return permission_key in self.permissions or "*" in self.permissions


# Import token utilities from auth_v2 to avoid duplication
from .user_auth import extract_token


def extract_client_ip(handler: Any) -> str | None:
    """Compatibility wrapper for the foundation request-IP utility."""
    warnings.warn(
        "aragora.server.middleware.auth.extract_client_ip is deprecated; "
        "import aragora.utils.request_ip.extract_client_ip instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return _extract_client_ip(handler)


def validate_token(token: str) -> bool:
    """
    Validate an authentication token.

    Checks both token validity and revocation status.

    Args:
        token: Token to validate.

    Returns:
        True if valid and not revoked, False otherwise.
    """
    from aragora.server.auth import auth_config
    from aragora.server.middleware.token_revocation import is_token_revoked

    if not token:
        return False

    # Check if token is valid
    if not auth_config.validate_token(token):
        return False

    # Check if token has been revoked
    if is_token_revoked(token):
        logger.debug("Token validation failed: token has been revoked")
        return False

    return True


def _extract_handler(*args, **kwargs) -> Any:
    """Extract handler from function arguments."""
    handler = kwargs.get("handler")
    if handler is None:
        for arg in args:
            if hasattr(arg, "headers"):
                handler = arg
                break
    return handler


def _error_response(message: str, status: int = 401) -> HandlerResult:
    """Create an error response."""
    from aragora.server.handlers.base import error_response

    return error_response(message, status)


def require_auth(func: Callable) -> Callable:
    """
    Decorator that ALWAYS requires authentication.

    Use this for sensitive endpoints that must never run without
    authentication, even in development/testing environments.

    Examples of sensitive endpoints:
    - Plugin execution
    - Capability probing
    - Laboratory experiments
    - Admin operations

    Usage:
        @require_auth
        def sensitive_operation(self, handler):
            ...
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        from aragora.server.auth import auth_config

        handler = _extract_handler(*args, **kwargs)

        if handler is None:
            logger.warning("require_auth: No handler provided, denying access")
            return _error_response("Authentication required", 401)

        # Check that API token is configured
        if not auth_config.api_token:
            logger.warning(
                "require_auth: No API token configured, denying access to sensitive endpoint"
            )
            return _error_response(
                "Authentication required. Set ARAGORA_API_TOKEN environment variable.",
                401,
            )

        # Extract and validate token
        token = extract_token(handler)
        if not token or not validate_token(token):
            return _error_response("Invalid or missing authentication token", 401)

        return func(*args, **kwargs)

    return wrapper


def optional_auth(func: Callable) -> Callable:
    """
    Decorator that provides optional authentication context.

    Unlike require_auth, this allows unauthenticated requests but
    provides an AuthContext to the handler indicating auth status.

    The AuthContext is injected as the 'auth_context' keyword argument.

    Usage:
        @optional_auth
        def public_endpoint(self, handler, auth_context: AuthContext):
            if auth_context.authenticated:
                return personalized_response()
            else:
                return public_response()
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        handler = _extract_handler(*args, **kwargs)

        # Build auth context
        token = extract_token(handler)
        authenticated = validate_token(token) if token else False
        client_ip = _extract_client_ip(handler)

        auth_context = AuthContext(
            authenticated=authenticated,
            token=token if authenticated else None,
            client_ip=client_ip,
        )

        # If authenticated, extract user info and resolve permissions
        if authenticated and token:
            try:
                from aragora.billing.auth.tokens import validate_access_token

                payload = validate_access_token(token)
                if payload:
                    auth_context.user_id = payload.user_id
                    role = payload.role or "member"
                    auth_context.roles = {role}
                    # Resolve permissions from role
                    try:
                        from aragora.rbac.defaults import get_role_permissions

                        permissions: set[str] = set()
                        for r in auth_context.roles:
                            permissions |= get_role_permissions(r, include_inherited=True)
                        auth_context.permissions = permissions
                    except (ImportError, Exception) as exc:
                        logger.warning("RBAC permission loading failed: %s", exc)
            except (ImportError, Exception) as exc:
                logger.debug("Token payload extraction failed: %s", exc)

        # Inject auth context
        kwargs["auth_context"] = auth_context

        return func(*args, **kwargs)

    return wrapper


def require_auth_or_localhost(func: Callable) -> Callable:
    """
    Decorator that requires auth OR allows localhost connections.

    Useful for endpoints that should be protected in production but
    accessible for local development without token setup.

    Usage:
        @require_auth_or_localhost
        def dev_friendly_endpoint(self, handler):
            ...
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        handler = _extract_handler(*args, **kwargs)

        if handler is None:
            return _error_response("Authentication required", 401)

        # Check if localhost - only in non-production environments
        # Use client_address directly (not X-Forwarded-For which is spoofable)
        # Check both ARAGORA_ENV and ARAGORA_ENVIRONMENT for compatibility
        env = (
            os.environ.get("ARAGORA_ENV", "") or os.environ.get("ARAGORA_ENVIRONMENT", "")
        ).lower()
        is_production = env in ("production", "prod", "staging", "live")
        if not is_production and hasattr(handler, "client_address"):
            addr = handler.client_address
            if isinstance(addr, tuple) and len(addr) >= 1:
                direct_ip = str(addr[0])
                if direct_ip in ("127.0.0.1", "::1"):
                    logger.debug("Allowing localhost access from %s", direct_ip)
                    return func(*args, **kwargs)

        # Not localhost or in production - require auth
        from aragora.server.auth import auth_config

        if not auth_config.api_token:
            return _error_response(
                "Authentication required for non-localhost requests",
                401,
            )

        token = extract_token(handler)
        if not token or not validate_token(token):
            return _error_response("Invalid or missing authentication token", 401)

        return func(*args, **kwargs)

    return wrapper
