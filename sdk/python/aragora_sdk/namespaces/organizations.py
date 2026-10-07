"""
Organizations Namespace API

Provides methods for organization management, member management, and invitations.

Features:
- Organization details and settings
- Member listing and role management
- Team invitations
- Multi-organization support
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..client import AragoraAsyncClient, AragoraClient


class OrganizationsAPI:
    """
    Synchronous Organizations API.

    Provides methods for organization management:
    - Get and update organization details
    - List and manage organization members
    - Send and manage invitations
    - Switch between organizations

    Example:
        >>> client = AragoraClient(base_url="https://api.aragora.ai")
        >>> org = client.organizations.get("org-123")
        >>> members = client.organizations.list_members("org-123")
    """

    def __init__(self, client: AragoraClient):
        self._client = client

    # ===========================================================================
    # Organization Details
    # ===========================================================================

    def list_orgs(self) -> dict[str, Any]:
        """
        List all organizations.

        Returns:
            Dict with organizations array.
        """
        return self._client.request("GET", "/api/v1/org")

    def get(self, org_id: str) -> dict[str, Any]:
        """
        Get organization details.

        Args:
            org_id: Organization ID

        Returns:
            Dict with organization info including name, slug, tier, member count
        """
        return self._client.request("GET", f"/api/v1/org/{org_id}")

    def update(
        self,
        org_id: str,
        name: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Update organization settings.

        Args:
            org_id: Organization ID
            name: New organization name
            settings: Settings dict to update

        Returns:
            Updated organization info
        """
        data: dict[str, Any] = {}
        if name is not None:
            data["name"] = name
        if settings is not None:
            data["settings"] = settings

        return self._client.request("PUT", f"/api/v1/org/{org_id}", json=data)

    # ===========================================================================
    # User Organizations
    # ===========================================================================

    def list_user_organizations(self) -> dict[str, Any]:
        """
        List organizations the current user belongs to.

        Returns:
            Dict with organizations array
        """
        return self._client.request("GET", "/api/v1/user/organizations")

    def switch_organization(self, org_id: str) -> dict[str, Any]:
        """
        Switch the active organization for the current user.

        Args:
            org_id: Organization ID to switch to

        Returns:
            Dict with organization info
        """
        return self._client.request(
            "POST", "/api/v1/user/organizations/switch", json={"org_id": org_id}
        )

    def set_default_organization(self, org_id: str) -> dict[str, Any]:
        """
        Set the default organization for the current user.

        Args:
            org_id: Organization ID to set as default

        Returns:
            Dict with success status
        """
        return self._client.request(
            "POST", "/api/v1/user/organizations/default", json={"org_id": org_id}
        )

    def list_members(self, org_id: str) -> dict[str, Any]:
        """
        List organization members.

        Args:
            org_id: Organization ID

        Returns:
            Dict with members array and count
        """
        return self._client.request("GET", f"/api/v1/org/{org_id}/members")

    def remove_member(self, org_id: str, user_id: str) -> dict[str, Any]:
        """
        Remove a member from the organization.

        Args:
            org_id: Organization ID
            user_id: User ID to remove

        Returns:
            Dict with success message
        """
        return self._client.request("DELETE", f"/api/v1/org/{org_id}/members/{user_id}")

    def update_member_role(self, org_id: str, user_id: str, role: str) -> dict[str, Any]:
        """
        Update a member's role in the organization.

        Args:
            org_id: Organization ID
            user_id: User ID to update
            role: New role ('member' or 'admin')

        Returns:
            Dict with updated role info
        """
        return self._client.request(
            "PUT", f"/api/v1/org/{org_id}/members/{user_id}/role", json={"role": role}
        )

    # ===========================================================================
    # Invitations
    # ===========================================================================

    def invite_member(self, org_id: str, email: str, role: str = "member") -> dict[str, Any]:
        """
        Invite a user to the organization.

        Args:
            org_id: Organization ID
            email: Email address to invite
            role: Role for the new member ('member' or 'admin')

        Returns:
            Dict with invitation info including invite link
        """
        return self._client.request(
            "POST", f"/api/v1/org/{org_id}/invite", json={"email": email, "role": role}
        )

    def list_invitations(self, org_id: str) -> dict[str, Any]:
        """
        List pending invitations for an organization.

        Args:
            org_id: Organization ID

        Returns:
            Dict with invitations array and counts
        """
        return self._client.request("GET", f"/api/v1/org/{org_id}/invitations")

    def revoke_invitation(self, org_id: str, invitation_id: str) -> dict[str, Any]:
        """
        Revoke a pending invitation.

        Args:
            org_id: Organization ID
            invitation_id: Invitation ID to revoke

        Returns:
            Dict with success message
        """
        return self._client.request("DELETE", f"/api/v1/org/{org_id}/invitations/{invitation_id}")

    def get_pending_invitations(self) -> dict[str, Any]:
        """
        Get pending invitations for the current user.

        Returns:
            Dict with invitations array
        """
        return self._client.request("GET", "/api/v1/invitations/pending")

    def accept_invitation(self, token: str) -> dict[str, Any]:
        """
        Accept an invitation to join an organization.

        Args:
            token: Invitation token

        Returns:
            Dict with organization info and role
        """
        return self._client.request("POST", f"/api/v1/invitations/{token}/accept")

    # ===========================================================================
    # Tenants
    # ===========================================================================

    def list_tenants(self) -> dict[str, Any]:
        """
        List all tenants.

        Returns:
            Dict with tenants array.
        """
        return self._client.request("GET", "/api/v1/tenants")


class AsyncOrganizationsAPI:
    """
    Asynchronous Organizations API.

    Example:
        >>> async with AragoraAsyncClient(base_url="https://api.aragora.ai") as client:
        ...     org = await client.organizations.get("org-123")
        ...     members = await client.organizations.list_members("org-123")
    """

    def __init__(self, client: AragoraAsyncClient):
        self._client = client

    # ===========================================================================
    # Organization Details
    # ===========================================================================

    async def list_orgs(self) -> dict[str, Any]:
        """List all organizations."""
        return await self._client.request("GET", "/api/v1/org")

    async def get(self, org_id: str) -> dict[str, Any]:
        """Get organization details."""
        return await self._client.request("GET", f"/api/v1/org/{org_id}")

    async def update(
        self,
        org_id: str,
        name: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update organization settings."""
        data: dict[str, Any] = {}
        if name is not None:
            data["name"] = name
        if settings is not None:
            data["settings"] = settings

        return await self._client.request("PUT", f"/api/v1/org/{org_id}", json=data)

    # ===========================================================================
    # User Organizations
    # ===========================================================================

    async def list_user_organizations(self) -> dict[str, Any]:
        """List organizations the current user belongs to."""
        return await self._client.request("GET", "/api/v1/user/organizations")

    async def switch_organization(self, org_id: str) -> dict[str, Any]:
        """Switch the active organization for the current user."""
        return await self._client.request(
            "POST", "/api/v1/user/organizations/switch", json={"org_id": org_id}
        )

    async def set_default_organization(self, org_id: str) -> dict[str, Any]:
        """Set the default organization for the current user."""
        return await self._client.request(
            "POST", "/api/v1/user/organizations/default", json={"org_id": org_id}
        )

    async def list_members(self, org_id: str) -> dict[str, Any]:
        """List organization members."""
        return await self._client.request("GET", f"/api/v1/org/{org_id}/members")

    async def remove_member(self, org_id: str, user_id: str) -> dict[str, Any]:
        """Remove a member from the organization."""
        return await self._client.request("DELETE", f"/api/v1/org/{org_id}/members/{user_id}")

    async def update_member_role(self, org_id: str, user_id: str, role: str) -> dict[str, Any]:
        """Update a member's role in the organization."""
        return await self._client.request(
            "PUT", f"/api/v1/org/{org_id}/members/{user_id}/role", json={"role": role}
        )

    # ===========================================================================
    # Invitations
    # ===========================================================================

    async def invite_member(self, org_id: str, email: str, role: str = "member") -> dict[str, Any]:
        """Invite a user to the organization."""
        return await self._client.request(
            "POST", f"/api/v1/org/{org_id}/invite", json={"email": email, "role": role}
        )

    async def list_invitations(self, org_id: str) -> dict[str, Any]:
        """List pending invitations for an organization."""
        return await self._client.request("GET", f"/api/v1/org/{org_id}/invitations")

    async def revoke_invitation(self, org_id: str, invitation_id: str) -> dict[str, Any]:
        """Revoke a pending invitation."""
        return await self._client.request(
            "DELETE", f"/api/v1/org/{org_id}/invitations/{invitation_id}"
        )

    async def get_pending_invitations(self) -> dict[str, Any]:
        """Get pending invitations for the current user."""
        return await self._client.request("GET", "/api/v1/invitations/pending")

    async def accept_invitation(self, token: str) -> dict[str, Any]:
        """Accept an invitation to join an organization."""
        return await self._client.request("POST", f"/api/v1/invitations/{token}/accept")

    # Tenants
    async def list_tenants(self) -> dict[str, Any]:
        """List all tenants."""
        return await self._client.request("GET", "/api/v1/tenants")
