"""Tenant context variables shared by the config and tenancy layers.

``aragora.tenancy.context`` re-exports these names and builds ``TenantContext``,
``require_tenant`` and the decorators on top of them, so code in
``aragora.config`` can read the current tenant without importing
``aragora.tenancy``. Both paths see the same ``ContextVar`` objects and
therefore the same per-thread and per-task state.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aragora.tenancy.tenant import Tenant

__all__ = [
    "get_current_tenant",
    "get_current_tenant_id",
    "set_tenant",
    "set_tenant_id",
]

# Context variable for current tenant
_current_tenant: ContextVar[Tenant | None] = ContextVar("current_tenant", default=None)

# Context variable for tenant ID (lighter weight)
_current_tenant_id: ContextVar[str | None] = ContextVar("current_tenant_id", default=None)


def get_current_tenant() -> Tenant | None:
    """
    Get the current tenant from context.

    Returns:
        Current tenant or None if not set
    """
    return _current_tenant.get()


def get_current_tenant_id() -> str | None:
    """
    Get the current tenant ID from context.

    Returns:
        Current tenant ID or None if not set
    """
    return _current_tenant_id.get()


def set_tenant(tenant: Tenant | None) -> None:
    """
    Set the current tenant directly (use with caution).

    Prefer using TenantContext for proper cleanup.

    Args:
        tenant: Tenant to set, or None to clear
    """
    _current_tenant.set(tenant)
    _current_tenant_id.set(tenant.id if tenant else None)


def set_tenant_id(tenant_id: str | None) -> None:
    """
    Set the current tenant ID directly (use with caution).

    Args:
        tenant_id: Tenant ID to set, or None to clear
    """
    _current_tenant_id.set(tenant_id)
