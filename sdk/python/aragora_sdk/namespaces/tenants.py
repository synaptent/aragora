"""
Tenants namespace for multi-tenancy management.

Provides API access to manage tenants, tenant isolation,
resource quotas, and tenant-level configuration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..client import AragoraAsyncClient, AragoraClient


_List = list  # Preserve builtin list for type annotations


class TenantsAPI:
    """Synchronous tenants API."""

    def __init__(self, client: AragoraClient) -> None:
        self._client = client

    def list(
        self,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
    ) -> dict[str, Any]:
        """
        List tenants.

        Args:
            limit: Maximum number of tenants to return
            offset: Number of tenants to skip
            status: Filter by status (active, suspended, pending)

        Returns:
            List of tenant records
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status

        return self._client._request("GET", "/api/v1/tenants", params=params)

    def create(
        self,
        name: str,
        slug: str,
        plan: str = "free",
        settings: dict[str, Any] | None = None,
        quotas: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Create a new tenant.

        Args:
            name: Tenant display name
            slug: Unique tenant slug
            plan: Subscription plan
            settings: Tenant settings
            quotas: Resource quotas

        Returns:
            Created tenant record
        """
        data: dict[str, Any] = {
            "name": name,
            "slug": slug,
            "plan": plan,
        }
        if settings:
            data["settings"] = settings
        if quotas:
            data["quotas"] = quotas

        return self._client._request("POST", "/api/v1/tenants", json=data)


class AsyncTenantsAPI:
    """Asynchronous tenants API."""

    def __init__(self, client: AragoraAsyncClient) -> None:
        self._client = client

    async def list(
        self,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
    ) -> dict[str, Any]:
        """List tenants."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status

        return await self._client._request("GET", "/api/v1/tenants", params=params)

    async def create(
        self,
        name: str,
        slug: str,
        plan: str = "free",
        settings: dict[str, Any] | None = None,
        quotas: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new tenant."""
        data: dict[str, Any] = {
            "name": name,
            "slug": slug,
            "plan": plan,
        }
        if settings:
            data["settings"] = settings
        if quotas:
            data["quotas"] = quotas

        return await self._client._request("POST", "/api/v1/tenants", json=data)
