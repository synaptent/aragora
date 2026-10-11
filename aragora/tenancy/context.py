"""
Tenant context management using context variables.

Provides thread-safe and async-safe tenant context for request handling.

Usage:
    from aragora.tenancy import TenantContext, get_current_tenant

    with TenantContext(tenant_id="acme-corp"):
        # All operations scoped to this tenant
        tenant = get_current_tenant()
        print(tenant.name)  # "Acme Corp"
"""

from __future__ import annotations

import asyncio
import logging
from contextvars import ContextVar, Token
from dataclasses import dataclass
from functools import wraps
from typing import (
    TYPE_CHECKING,
    Any,
    ParamSpec,
    TypeVar,
    cast,
    overload,
)
from collections.abc import Awaitable, Callable

# The context variables and their plain getters/setters live in the config
# layer; re-exported here so both import paths share one tenant state.
from aragora.config.tenant_context import (
    _current_tenant as _current_tenant,
    _current_tenant_id as _current_tenant_id,
    get_current_tenant as get_current_tenant,
    get_current_tenant_id as get_current_tenant_id,
    set_tenant as set_tenant,
    set_tenant_id as set_tenant_id,
)

if TYPE_CHECKING:
    from aragora.tenancy.tenant import Tenant

logger = logging.getLogger(__name__)

T = TypeVar("T")
P = ParamSpec("P")


class TenantNotSetError(Exception):
    """Raised when tenant is required but not set."""

    pass


class TenantMismatchError(Exception):
    """Raised when tenant context doesn't match expected tenant."""

    pass


@dataclass
class TenantContextInfo:
    """Information about the current tenant context."""

    tenant_id: str | None
    tenant: Tenant | None
    is_set: bool
    depth: int


class TenantContext:
    """
    Context manager for tenant-scoped operations.

    Supports both sync and async code. Thread-safe via context variables.

    Usage:
        # Sync context
        with TenantContext(tenant_id="acme"):
            do_work()

        # Async context
        async with TenantContext(tenant_id="acme"):
            await do_async_work()

        # With full tenant object
        with TenantContext(tenant=tenant_obj):
            do_work()
    """

    _depth: int = 0

    def __init__(
        self,
        tenant_id: str | None = None,
        tenant: Tenant | None = None,
    ):
        """
        Initialize tenant context.

        Args:
            tenant_id: Tenant ID to set
            tenant: Full tenant object (takes precedence)
        """
        if tenant is not None:
            self._tenant = tenant
            self._tenant_id = tenant.id
        else:
            self._tenant = None
            self._tenant_id = tenant_id

        self._token_id: Token[str | None] | None = None
        self._token_tenant: Token[Tenant | None] | None = None
        self._previous_tenant: Tenant | None = None
        self._previous_tenant_id: str | None = None

    def __enter__(self) -> TenantContext:
        """Enter sync context."""
        self._previous_tenant_id = _current_tenant_id.get()
        self._previous_tenant = _current_tenant.get()

        self._token_id = _current_tenant_id.set(self._tenant_id)
        self._token_tenant = _current_tenant.set(self._tenant)

        TenantContext._depth += 1
        logger.debug("Entered tenant context: %s (depth=%s)", self._tenant_id, TenantContext._depth)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit sync context."""
        if self._token_id is None or self._token_tenant is None:
            raise RuntimeError("TenantContext exited before it was entered")
        _current_tenant_id.reset(self._token_id)
        _current_tenant.reset(self._token_tenant)

        TenantContext._depth -= 1
        logger.debug("Exited tenant context: %s (depth=%s)", self._tenant_id, TenantContext._depth)

    async def __aenter__(self) -> TenantContext:
        """Enter async context."""
        return self.__enter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context."""
        self.__exit__(exc_type, exc_val, exc_tb)

    @property
    def tenant_id(self) -> str | None:
        """Get the tenant ID for this context."""
        return self._tenant_id

    @property
    def tenant(self) -> Tenant | None:
        """Get the tenant object for this context."""
        return self._tenant


def require_tenant() -> Tenant:
    """
    Get the current tenant, raising if not set.

    Returns:
        Current tenant

    Raises:
        TenantNotSetError: If no tenant is set in context
    """
    tenant = _current_tenant.get()
    if tenant is None:
        raise TenantNotSetError("No tenant set in current context")
    return tenant


def require_tenant_id() -> str:
    """
    Get the current tenant ID, raising if not set.

    Returns:
        Current tenant ID

    Raises:
        TenantNotSetError: If no tenant ID is set in context
    """
    tenant_id = _current_tenant_id.get()
    if tenant_id is None:
        raise TenantNotSetError("No tenant ID set in current context")
    return tenant_id


def get_context_info() -> TenantContextInfo:
    """
    Get information about the current tenant context.

    Returns:
        Context information including depth and tenant details
    """
    return TenantContextInfo(
        tenant_id=_current_tenant_id.get(),
        tenant=_current_tenant.get(),
        is_set=_current_tenant_id.get() is not None,
        depth=TenantContext._depth,
    )


@overload
def tenant_required(
    func: Callable[P, Awaitable[T]],
) -> Callable[P, Awaitable[T]]: ...


@overload
def tenant_required(
    func: Callable[P, T],
) -> Callable[P, T]: ...


# Overload impl signature overlaps unavoidable for sync/async decorator pattern
def tenant_required(  # type: ignore[misc]
    func: Callable[P, T] | Callable[P, Awaitable[T]],
) -> Callable[P, T] | Callable[P, Awaitable[T]]:
    """
    Decorator that requires a tenant to be set.

    Usage:
        @tenant_required
        def my_function():
            tenant = get_current_tenant()
            # tenant is guaranteed to exist
    """

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        if _current_tenant_id.get() is None:
            raise TenantNotSetError(f"Function {func.__name__} requires a tenant context")
        return cast(T, func(*args, **kwargs))

    @wraps(func)
    async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        if _current_tenant_id.get() is None:
            raise TenantNotSetError(f"Function {func.__name__} requires a tenant context")
        result = await cast(Awaitable[T], func(*args, **kwargs))
        return result

    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    return wrapper


@overload
def for_tenant(
    tenant_id: str,
) -> Callable[
    [Callable[P, Awaitable[T]]],
    Callable[P, Awaitable[T]],
]: ...


# Sync overload has identical param signature to async; needed for documentation but cannot match
@overload
def for_tenant(  # type: ignore[overload-cannot-match]
    tenant_id: str,
) -> Callable[
    [Callable[P, T]],
    Callable[P, T],
]: ...


# Overload impl signature overlaps unavoidable for sync/async decorator pattern
def for_tenant(  # type: ignore[misc]
    tenant_id: str,
) -> Callable[
    [Callable[P, T] | Callable[P, Awaitable[T]]],
    Callable[P, T] | Callable[P, Awaitable[T]],
]:
    """
    Decorator that runs a function in a specific tenant context.

    Usage:
        @for_tenant("acme-corp")
        def my_function():
            # Always runs in acme-corp context
    """

    def decorator(
        func: Callable[P, T] | Callable[P, Awaitable[T]],
    ) -> Callable[P, T] | Callable[P, Awaitable[T]]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            with TenantContext(tenant_id=tenant_id):
                return cast(T, func(*args, **kwargs))

        @wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            async with TenantContext(tenant_id=tenant_id):
                result = await cast(Awaitable[T], func(*args, **kwargs))
                return result

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return wrapper

    return decorator


def verify_tenant(expected_tenant_id: str) -> None:
    """
    Verify the current tenant matches expected.

    Args:
        expected_tenant_id: Expected tenant ID

    Raises:
        TenantNotSetError: If no tenant is set
        TenantMismatchError: If tenant doesn't match
    """
    current = _current_tenant_id.get()
    if current is None:
        raise TenantNotSetError("No tenant set in current context")
    if current != expected_tenant_id:
        raise TenantMismatchError(f"Expected tenant {expected_tenant_id}, got {current}")


class TenantContextStack:
    """
    Stack-based tenant context for complex scenarios.

    Maintains a stack of tenant contexts for nested operations.
    """

    def __init__(self):
        self._stack: list[str] = []

    def push(self, tenant_id: str) -> None:
        """Push a tenant onto the stack."""
        self._stack.append(tenant_id)
        set_tenant_id(tenant_id)

    def pop(self) -> str | None:
        """Pop a tenant from the stack."""
        if not self._stack:
            return None

        popped = self._stack.pop()
        new_current = self._stack[-1] if self._stack else None
        set_tenant_id(new_current)
        return popped

    def current(self) -> str | None:
        """Get current tenant from stack."""
        return self._stack[-1] if self._stack else None

    def depth(self) -> int:
        """Get stack depth."""
        return len(self._stack)

    def clear(self) -> None:
        """Clear the stack."""
        self._stack.clear()
        set_tenant_id(None)


# Audit backend management
# Used for tenant-aware audit logging

_audit_backend: ContextVar[Any | None] = ContextVar("audit_backend", default=None)


def get_audit_backend() -> Any | None:
    """
    Get the configured audit backend.

    Returns:
        The audit backend instance, or None if not configured.
    """
    return _audit_backend.get()


def set_audit_backend(backend: Any | None) -> None:
    """
    Set the audit backend.

    Args:
        backend: The audit backend instance to use, or None to clear.
    """
    _audit_backend.set(backend)
