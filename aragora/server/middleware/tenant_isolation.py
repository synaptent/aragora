"""
Tenant Isolation Middleware.

Enforces tenant isolation by validating user membership before processing
tenant-scoped requests. Prevents cross-tenant access by failing closed
on membership check errors.

SECURITY: This middleware removes graceful fallbacks that could allow
unauthorized cross-tenant access. Membership check failures result in
403 Forbidden responses.

Usage:
    from aragora.server.middleware.tenant_isolation import (
        require_tenant_isolation,
        TenantIsolationMiddleware,
    )

    # As a decorator
    @require_tenant_isolation
    async def tenant_endpoint(request, tenant_id: str):
        # Only executed if user belongs to tenant
        ...

    # As middleware class
    middleware = TenantIsolationMiddleware(membership_store)
    result = await middleware.check_access(request)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps
from typing import TYPE_CHECKING, Any, Protocol, TypeVar, cast
from collections.abc import Callable

if TYPE_CHECKING:
    from aragora.server.handlers.base import HandlerResult

logger = logging.getLogger(__name__)

# Security event logger for audit trail
security_logger = logging.getLogger("aragora.security.tenant_isolation")

F = TypeVar("F", bound=Callable[..., Any])


# =============================================================================
# Exceptions
# =============================================================================


class TenantIsolationError(Exception):
    """Base exception for tenant isolation failures."""

    def __init__(self, message: str, tenant_id: str | None = None, user_id: str | None = None):
        super().__init__(message)
        self.tenant_id = tenant_id
        self.user_id = user_id


class TenantAccessDeniedError(TenantIsolationError):
    """Raised when user does not have access to the requested tenant."""

    pass


class TenantMembershipCheckError(TenantIsolationError):
    """Raised when membership check fails (fail closed)."""

    pass


class TenantIdMissingError(TenantIsolationError):
    """Raised when tenant ID is missing from request."""

    pass


# =============================================================================
# Data Models
# =============================================================================


@dataclass
class TenantAccessAttempt:
    """Record of a tenant access attempt for audit logging."""

    timestamp: datetime
    user_id: str
    tenant_id: str
    source_ip: str | None
    request_path: str | None
    allowed: bool
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for logging."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "source_ip": self.source_ip,
            "request_path": self.request_path,
            "allowed": self.allowed,
            "reason": self.reason,
            "metadata": self.metadata,
        }


# =============================================================================
# Membership Store Protocol
# =============================================================================


class MembershipStore(Protocol):
    """Protocol for tenant membership storage."""

    async def is_member(self, user_id: str, tenant_id: str) -> bool:
        """Check if user is a member of the tenant.

        Args:
            user_id: The user ID to check
            tenant_id: The tenant/workspace ID to check membership for

        Returns:
            True if user is a member, False otherwise

        Raises:
            Any exception indicates a check failure (fail closed)
        """
        ...

    async def get_user_tenants(self, user_id: str) -> list[str]:
        """Get all tenants the user belongs to.

        Args:
            user_id: The user ID to look up

        Returns:
            List of tenant IDs the user belongs to
        """
        ...


# =============================================================================
# In-Memory Membership Store (for testing)
# =============================================================================


class InMemoryMembershipStore:
    """In-memory membership store for testing."""

    def __init__(self) -> None:
        # tenant_id -> set of user_ids
        self._memberships: dict[str, set[str]] = {}
        # tenant_id -> owner_id
        self._owners: dict[str, str] = {}

    def add_member(self, tenant_id: str, user_id: str) -> None:
        """Add a user as a member of a tenant."""
        if tenant_id not in self._memberships:
            self._memberships[tenant_id] = set()
        self._memberships[tenant_id].add(user_id)

    def set_owner(self, tenant_id: str, owner_id: str) -> None:
        """Set the owner of a tenant (owners are always members)."""
        self._owners[tenant_id] = owner_id
        self.add_member(tenant_id, owner_id)

    def remove_member(self, tenant_id: str, user_id: str) -> None:
        """Remove a user from a tenant."""
        if tenant_id in self._memberships:
            self._memberships[tenant_id].discard(user_id)

    async def is_member(self, user_id: str, tenant_id: str) -> bool:
        """Check if user is a member of the tenant."""
        # Owner is always a member
        if self._owners.get(tenant_id) == user_id:
            return True
        # Check explicit membership
        return user_id in self._memberships.get(tenant_id, set())

    async def get_user_tenants(self, user_id: str) -> list[str]:
        """Get all tenants the user belongs to."""
        tenants = []
        for tenant_id, members in self._memberships.items():
            if user_id in members:
                tenants.append(tenant_id)
        # Include tenants where user is owner
        for tenant_id, owner_id in self._owners.items():
            if owner_id == user_id and tenant_id not in tenants:
                tenants.append(tenant_id)
        return tenants


# =============================================================================
# Tenant Isolation Middleware
# =============================================================================


class TenantIsolationMiddleware:
    """
    Middleware that enforces tenant isolation.

    SECURITY PROPERTIES:
    1. Fail closed: Any membership check failure results in access denied
    2. No graceful fallbacks: Errors do NOT allow access through
    3. Audit logging: All access attempts (success and failure) are logged
    4. Header validation: Tenant ID from headers is validated against membership

    Usage:
        middleware = TenantIsolationMiddleware(membership_store)

        # Check access for a request
        try:
            tenant_id = await middleware.check_access(request, user_id)
            # Access granted, proceed with tenant_id
        except TenantAccessDeniedError:
            # User not a member of tenant
            return error_response("Access denied", 403)
        except TenantMembershipCheckError:
            # Membership check failed (fail closed)
            return error_response("Access denied", 403)
    """

    # Headers to check for tenant ID (in order of precedence)
    TENANT_HEADERS = ("X-Tenant-ID", "X-Workspace-ID")

    def __init__(
        self,
        membership_store: MembershipStore | None = None,
        audit_enabled: bool = True,
    ) -> None:
        """Initialize the middleware.

        Args:
            membership_store: Store for checking tenant membership
            audit_enabled: Whether to log access attempts
        """
        self._store = membership_store or InMemoryMembershipStore()
        self._audit_enabled = audit_enabled
        self._access_log: list[TenantAccessAttempt] = []

    def extract_tenant_id(self, request: Any) -> str | None:
        """Extract tenant ID from request headers.

        Args:
            request: HTTP request object

        Returns:
            Tenant ID if found, None otherwise
        """
        headers = getattr(request, "headers", {})

        for header in self.TENANT_HEADERS:
            tenant_id = headers.get(header)
            if tenant_id:
                return tenant_id

        return None

    def extract_user_id(self, request: Any) -> str | None:
        """Extract authenticated user ID from request.

        This should be called AFTER authentication middleware has run.
        The user ID should come from a verified JWT, not from headers.

        Args:
            request: HTTP request object

        Returns:
            User ID if authenticated, None otherwise
        """
        # Check for user ID set by authentication middleware
        if hasattr(request, "user_id"):
            return request.user_id

        # Check app state (set by auth middleware)
        if hasattr(request, "state") and hasattr(request.state, "user_id"):
            return request.state.user_id

        # Check for auth context from our auth utilities
        if hasattr(request, "auth_context"):
            ctx = request.auth_context
            if hasattr(ctx, "user_id") and ctx.user_id != "anonymous":
                return ctx.user_id

        return None

    def extract_source_ip(self, request: Any) -> str | None:
        """Extract client IP address from request."""
        # Check common attributes
        if hasattr(request, "client_address"):
            addr = request.client_address
            if isinstance(addr, tuple):
                return addr[0]
            return str(addr)

        # Check headers for proxy scenarios
        headers = getattr(request, "headers", {})
        for header in ("X-Forwarded-For", "X-Real-IP"):
            ip = headers.get(header)
            if ip:
                # X-Forwarded-For may contain multiple IPs
                return ip.split(",")[0].strip()

        return None

    def extract_request_path(self, request: Any) -> str | None:
        """Extract request path from request."""
        if hasattr(request, "path"):
            return request.path
        if hasattr(request, "url"):
            url = request.url
            if hasattr(url, "path"):
                return url.path
            return str(url)
        return None

    async def check_access(
        self,
        request: Any,
        user_id: str | None = None,
    ) -> str:
        """Check if the user has access to the requested tenant.

        SECURITY: This method fails closed. Any error during membership
        checking results in access denial.

        Args:
            request: HTTP request object
            user_id: User ID (if not provided, extracted from request)

        Returns:
            The validated tenant ID

        Raises:
            TenantIdMissingError: If tenant ID is not in request headers
            TenantAccessDeniedError: If user is not a member of tenant
            TenantMembershipCheckError: If membership check fails
        """
        # Extract tenant ID from headers
        tenant_id = self.extract_tenant_id(request)
        if not tenant_id:
            self._audit_attempt(
                request=request,
                user_id=user_id or "unknown",
                tenant_id="missing",
                allowed=False,
                reason="Tenant ID missing from request headers",
            )
            raise TenantIdMissingError(
                "Tenant ID required. Provide X-Tenant-ID or X-Workspace-ID header.",
                tenant_id=None,
                user_id=user_id,
            )

        # Extract user ID if not provided
        if user_id is None:
            user_id = self.extract_user_id(request)

        if not user_id:
            self._audit_attempt(
                request=request,
                user_id="unauthenticated",
                tenant_id=tenant_id,
                allowed=False,
                reason="User not authenticated",
            )
            raise TenantAccessDeniedError(
                "Authentication required for tenant access.",
                tenant_id=tenant_id,
                user_id=None,
            )

        # SECURITY: Check membership - fail closed on any error
        try:
            is_member = await self._store.is_member(user_id, tenant_id)
        except Exception as e:  # noqa: BLE001 - Security fail-closed: membership store may raise DB driver exceptions not in builtins
            # SECURITY: Fail closed - any error denies access
            self._audit_attempt(
                request=request,
                user_id=user_id,
                tenant_id=tenant_id,
                allowed=False,
                reason=f"Membership check failed: {type(e).__name__}",
                metadata={"error": type(e).__name__},
            )
            security_logger.warning(
                "Tenant membership check failed (access denied): user=%s tenant=%s error=%s",
                user_id,
                tenant_id,
                e,
            )
            raise TenantMembershipCheckError(
                "Unable to verify tenant membership. Access denied.",
                tenant_id=tenant_id,
                user_id=user_id,
            ) from e

        if not is_member:
            self._audit_attempt(
                request=request,
                user_id=user_id,
                tenant_id=tenant_id,
                allowed=False,
                reason="User is not a member of tenant",
            )
            security_logger.warning(
                "Cross-tenant access attempt blocked: user=%s tenant=%s", user_id, tenant_id
            )
            raise TenantAccessDeniedError(
                f"User {user_id} does not have access to tenant {tenant_id}.",
                tenant_id=tenant_id,
                user_id=user_id,
            )

        # Access granted
        self._audit_attempt(
            request=request,
            user_id=user_id,
            tenant_id=tenant_id,
            allowed=True,
            reason="Membership verified",
        )

        return tenant_id

    def _audit_attempt(
        self,
        request: Any,
        user_id: str,
        tenant_id: str,
        allowed: bool,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Log a tenant access attempt for audit purposes."""
        if not self._audit_enabled:
            return

        attempt = TenantAccessAttempt(
            timestamp=datetime.now(timezone.utc),
            user_id=user_id,
            tenant_id=tenant_id,
            source_ip=self.extract_source_ip(request),
            request_path=self.extract_request_path(request),
            allowed=allowed,
            reason=reason,
            metadata=metadata or {},
        )

        # Keep in-memory log (bounded)
        self._access_log.append(attempt)
        if len(self._access_log) > 10000:
            self._access_log = self._access_log[-5000:]

        # Log to security logger
        log_level = logging.INFO if allowed else logging.WARNING
        security_logger.log(
            log_level,
            "Tenant access %s: %s",
            "granted" if allowed else "denied",
            attempt.to_dict(),
        )

    def get_audit_log(
        self,
        tenant_id: str | None = None,
        user_id: str | None = None,
        allowed: bool | None = None,
        limit: int = 100,
    ) -> list[TenantAccessAttempt]:
        """Get filtered audit log entries.

        Args:
            tenant_id: Filter by tenant ID
            user_id: Filter by user ID
            allowed: Filter by access result
            limit: Maximum entries to return

        Returns:
            List of matching audit entries (most recent first)
        """
        entries = self._access_log

        if tenant_id is not None:
            entries = [e for e in entries if e.tenant_id == tenant_id]
        if user_id is not None:
            entries = [e for e in entries if e.user_id == user_id]
        if allowed is not None:
            entries = [e for e in entries if e.allowed == allowed]

        # Return most recent entries
        return list(reversed(entries[-limit:]))

    def clear_audit_log(self) -> None:
        """Clear the audit log."""
        self._access_log.clear()


# =============================================================================
# Global Middleware Instance
# =============================================================================

_middleware_instance: TenantIsolationMiddleware | None = None


def get_tenant_isolation_middleware() -> TenantIsolationMiddleware:
    """Get the global tenant isolation middleware instance."""
    global _middleware_instance
    if _middleware_instance is None:
        _middleware_instance = TenantIsolationMiddleware()
    return _middleware_instance


def set_tenant_isolation_middleware(middleware: TenantIsolationMiddleware) -> None:
    """Set the global tenant isolation middleware instance."""
    global _middleware_instance
    _middleware_instance = middleware


def reset_tenant_isolation_middleware() -> None:
    """Reset the global tenant isolation middleware instance."""
    global _middleware_instance
    _middleware_instance = None


# =============================================================================
# Decorator
# =============================================================================


def _extract_handler(*args: Any, **kwargs: Any) -> Any:
    """Extract handler/request from function arguments."""
    # Check kwargs first
    for key in ("request", "handler"):
        if key in kwargs:
            return kwargs[key]

    # Check positional args
    for arg in args:
        if hasattr(arg, "headers"):
            return arg

    return None


def _error_response(message: str, status: int = 403) -> HandlerResult:
    """Create an error response."""
    from aragora.server.handlers.base import error_response

    return error_response(message, status)


def require_tenant_isolation(func: F) -> F:
    """
    Decorator that requires tenant isolation verification.

    Extracts tenant ID from request headers and verifies the authenticated
    user is a member of the tenant. The verified tenant_id is injected
    as a keyword argument.

    SECURITY: This decorator fails closed. If membership cannot be verified,
    access is denied.

    Usage:
        @require_tenant_isolation
        async def tenant_endpoint(request, tenant_id: str):
            # tenant_id is verified
            return await get_tenant_data(tenant_id)

    Args:
        func: The function to wrap

    Returns:
        Decorated function
    """

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        request = _extract_handler(*args, **kwargs)

        if request is None:
            logger.warning("require_tenant_isolation: No request found")
            return _error_response("Internal error: no request", 500)

        middleware = get_tenant_isolation_middleware()

        try:
            tenant_id = await middleware.check_access(request)
            # Inject verified tenant_id
            kwargs["tenant_id"] = tenant_id
            return await func(*args, **kwargs)

        except TenantIdMissingError as e:
            logger.warning("Tenant isolation: %s", e)
            return _error_response("Tenant ID required", 400)

        except TenantAccessDeniedError as e:
            logger.warning("Tenant isolation: %s", e)
            return _error_response("Access denied to tenant", 403)

        except TenantMembershipCheckError as e:
            logger.error("Tenant isolation check failed: %s", e)
            return _error_response("Access denied", 403)

    return cast(F, wrapper)


def require_tenant_isolation_with_config(
    membership_store: MembershipStore | None = None,
    audit_enabled: bool = True,
) -> Callable[[F], F]:
    """
    Decorator factory for tenant isolation with custom configuration.

    Usage:
        @require_tenant_isolation_with_config(
            membership_store=custom_store,
            audit_enabled=True,
        )
        async def tenant_endpoint(request, tenant_id: str):
            ...
    """

    def decorator(func: F) -> F:
        # Create dedicated middleware for this endpoint
        middleware = TenantIsolationMiddleware(
            membership_store=membership_store,
            audit_enabled=audit_enabled,
        )

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request = _extract_handler(*args, **kwargs)

            if request is None:
                logger.warning("require_tenant_isolation: No request found")
                return _error_response("Internal error: no request", 500)

            try:
                tenant_id = await middleware.check_access(request)
                kwargs["tenant_id"] = tenant_id
                return await func(*args, **kwargs)

            except TenantIdMissingError:
                return _error_response("Tenant ID required", 400)

            except TenantAccessDeniedError:
                return _error_response("Access denied to tenant", 403)

            except TenantMembershipCheckError:
                return _error_response("Access denied", 403)

        return cast(F, wrapper)

    return decorator


# =============================================================================
# Utility Functions
# =============================================================================


async def verify_tenant_access(
    user_id: str,
    tenant_id: str,
    membership_store: MembershipStore | None = None,
) -> bool:
    """Verify that a user has access to a tenant.

    This is a standalone utility function for cases where you need
    to check tenant access outside of request handling.

    SECURITY: Fails closed on any error.

    Args:
        user_id: User ID to check
        tenant_id: Tenant ID to verify access to
        membership_store: Optional custom membership store

    Returns:
        True if user has access, False otherwise
    """
    store = membership_store or get_tenant_isolation_middleware()._store

    try:
        return await store.is_member(user_id, tenant_id)
    except Exception as e:  # noqa: BLE001 - Security fail-closed: membership store may raise DB driver exceptions not in builtins
        security_logger.warning(
            "Tenant access verification failed (denied): user=%s tenant=%s error=%s",
            user_id,
            tenant_id,
            e,
        )
        return False


async def get_user_accessible_tenants(
    user_id: str,
    membership_store: MembershipStore | None = None,
) -> list[str]:
    """Get all tenants a user has access to.

    Args:
        user_id: User ID to look up
        membership_store: Optional custom membership store

    Returns:
        List of tenant IDs the user can access
    """
    store = membership_store or get_tenant_isolation_middleware()._store

    try:
        return await store.get_user_tenants(user_id)
    except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, KeyError) as e:
        security_logger.warning("Failed to get user tenants: user=%s error=%s", user_id, e)
        return []


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Exceptions
    "TenantIsolationError",
    "TenantAccessDeniedError",
    "TenantMembershipCheckError",
    "TenantIdMissingError",
    # Data models
    "TenantAccessAttempt",
    # Protocols
    "MembershipStore",
    # Stores
    "InMemoryMembershipStore",
    # Middleware
    "TenantIsolationMiddleware",
    "get_tenant_isolation_middleware",
    "set_tenant_isolation_middleware",
    "reset_tenant_isolation_middleware",
    # Decorators
    "require_tenant_isolation",
    "require_tenant_isolation_with_config",
    # Utilities
    "verify_tenant_access",
    "get_user_accessible_tenants",
]
