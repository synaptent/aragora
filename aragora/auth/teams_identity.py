"""
Teams User Identity Bridge.

Maps Microsoft Teams users (identified by Azure AD object IDs) to
Aragora users, enabling:
- Automatic user resolution from Teams activities
- SSO integration with Azure AD
- User sync from Teams to Aragora

Usage:
    from aragora.auth.teams_identity import TeamsUserIdentityBridge

    bridge = TeamsUserIdentityBridge()
    user = await bridge.resolve_user(aad_object_id="...", tenant_id="...")
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.auth.sso import SSOUser

logger = logging.getLogger(__name__)

# Provider name for external identity storage
TEAMS_PROVIDER = "azure_ad"


@dataclass
class TeamsUserInfo:
    """Information about a Teams user."""

    aad_object_id: str
    tenant_id: str
    display_name: str | None = None
    email: str | None = None
    user_principal_name: str | None = None
    given_name: str | None = None
    surname: str | None = None
    job_title: str | None = None
    department: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "aad_object_id": self.aad_object_id,
            "tenant_id": self.tenant_id,
            "display_name": self.display_name,
            "email": self.email,
            "user_principal_name": self.user_principal_name,
            "given_name": self.given_name,
            "surname": self.surname,
            "job_title": self.job_title,
            "department": self.department,
        }


class TeamsUserIdentityBridge:
    """
    Bridge between Microsoft Teams users and Aragora users.

    Provides methods to:
    - Resolve Teams users to Aragora users
    - Sync user data from Teams to Aragora
    - Link Teams identities to existing users
    """

    def __init__(self):
        """Initialize the identity bridge."""
        self._external_identity_repo = None
        self._user_repo = None

    def _get_external_identity_repo(self):
        """Lazy-load external identity repository."""
        if self._external_identity_repo is None:
            from aragora.storage.repositories.external_identity import (
                get_external_identity_repository,
            )

            self._external_identity_repo = get_external_identity_repository()
        return self._external_identity_repo

    def _get_user_repo(self):
        """Lazy-load user repository."""
        if self._user_repo is None:
            try:
                from aragora.storage.repositories.users import get_user_repository

                self._user_repo = get_user_repository()
            except ImportError:
                logger.warning("User repository not available")
        return self._user_repo

    async def resolve_user(
        self,
        aad_object_id: str,
        tenant_id: str,
    ) -> SSOUser | None:
        """
        Resolve a Teams user to an Aragora SSOUser.

        Args:
            aad_object_id: Azure AD object ID from Teams activity
            tenant_id: Azure AD tenant ID

        Returns:
            SSOUser if mapping exists, None otherwise
        """
        from aragora.auth.sso import SSOUser

        repo = self._get_external_identity_repo()
        identity = repo.get_by_external_id(
            provider=TEAMS_PROVIDER,
            external_id=aad_object_id,
            tenant_id=tenant_id,
        )

        if not identity:
            logger.debug(
                "No identity mapping for AAD user: %s in tenant %s", aad_object_id, tenant_id
            )
            return None

        # Update last seen
        repo.update_last_seen(identity.id)

        # Build SSOUser from identity
        user = SSOUser(
            id=identity.user_id,
            email=identity.email or "",
            name=identity.display_name or "",
            display_name=identity.display_name or "",
            azure_object_id=aad_object_id,
            azure_tenant_id=tenant_id,
            provider_type="azure_ad",
            raw_claims=identity.raw_claims,
        )

        # Try to enrich from user repository
        user_repo = self._get_user_repo()
        if user_repo:
            try:
                stored_user = user_repo.get(identity.user_id)
                if stored_user:
                    user.email = stored_user.email or user.email
                    user.name = stored_user.name or user.name
                    user.roles = getattr(stored_user, "roles", [])
            except (AttributeError, KeyError, LookupError) as e:
                logger.debug("Could not enrich user from repo: %s", e)

        return user

    async def sync_user_from_teams(
        self,
        teams_user: TeamsUserInfo,
        aragora_user_id: str | None = None,
        create_if_missing: bool = True,
    ) -> SSOUser | None:
        """
        Sync a Teams user to Aragora.

        Creates or updates the external identity mapping and optionally
        creates a new Aragora user if one doesn't exist.

        Args:
            teams_user: Teams user information
            aragora_user_id: Optional existing Aragora user ID to link to
            create_if_missing: Create Aragora user if not found

        Returns:
            SSOUser representing the synced user
        """
        from aragora.auth.sso import SSOUser

        repo = self._get_external_identity_repo()

        # Check if identity already exists
        existing = repo.get_by_external_id(
            provider=TEAMS_PROVIDER,
            external_id=teams_user.aad_object_id,
            tenant_id=teams_user.tenant_id,
        )

        if existing:
            # Update existing mapping
            existing.email = teams_user.email or existing.email
            existing.display_name = teams_user.display_name or existing.display_name
            existing.raw_claims = teams_user.to_dict()
            existing.last_seen_at = time.time()
            repo.update(existing)
            aragora_user_id = existing.user_id
        else:
            # Need to create or find Aragora user
            if not aragora_user_id:
                aragora_user_id = await self._find_or_create_user(teams_user, create_if_missing)

            if not aragora_user_id:
                logger.warning(
                    "Could not find or create user for Teams user: %s", teams_user.aad_object_id
                )
                return None

            # Create identity mapping
            repo.link_or_update(
                user_id=aragora_user_id,
                provider=TEAMS_PROVIDER,
                external_id=teams_user.aad_object_id,
                tenant_id=teams_user.tenant_id,
                email=teams_user.email,
                display_name=teams_user.display_name,
                raw_claims=teams_user.to_dict(),
            )

        # Build and return SSOUser
        return SSOUser(
            id=aragora_user_id,
            email=teams_user.email or "",
            name=teams_user.display_name or "",
            display_name=teams_user.display_name or "",
            first_name=teams_user.given_name or "",
            last_name=teams_user.surname or "",
            azure_object_id=teams_user.aad_object_id,
            azure_tenant_id=teams_user.tenant_id,
            provider_type="azure_ad",
            raw_claims=teams_user.to_dict(),
        )

    async def _find_or_create_user(
        self,
        teams_user: TeamsUserInfo,
        create_if_missing: bool,
    ) -> str | None:
        """Find existing user or create new one.

        Args:
            teams_user: Teams user info
            create_if_missing: Whether to create if not found

        Returns:
            Aragora user ID
        """
        user_repo = self._get_user_repo()

        if user_repo and teams_user.email:
            # Try to find by email
            try:
                existing = user_repo.get_by_email(teams_user.email)
                if existing:
                    return existing.id
            except (AttributeError, KeyError, LookupError) as e:
                logger.debug("Could not search by email: %s", e)

        if create_if_missing:
            # Generate a user ID
            import uuid

            user_id = f"teams-{uuid.uuid4().hex[:12]}"

            # If we have a user repo, try to create the user
            if user_repo:
                try:
                    import secrets

                    from aragora.billing.models import hash_password

                    # Build name from given_name + surname if display_name not available
                    full_name = teams_user.display_name
                    if not full_name and (teams_user.given_name or teams_user.surname):
                        parts = [teams_user.given_name or "", teams_user.surname or ""]
                        full_name = " ".join(p for p in parts if p)

                    random_password = secrets.token_urlsafe(32)
                    password_hash, password_salt = hash_password(random_password)
                    email = teams_user.email or f"{user_id}@teams.local"

                    user_repo.create(
                        email=email,
                        password_hash=password_hash,
                        password_salt=password_salt,
                        name=full_name or "Teams User",
                    )
                    logger.info("Created Aragora user for Teams user: %s", user_id)
                except (ValueError, TypeError, RuntimeError) as e:
                    logger.warning("Could not create user in repository: %s", e)

            return user_id

        return None

    async def get_user_by_aad_id(
        self,
        aad_object_id: str,
        tenant_id: str | None = None,
    ) -> str | None:
        """
        Get Aragora user ID by Azure AD object ID.

        Args:
            aad_object_id: Azure AD object ID
            tenant_id: Optional tenant filter

        Returns:
            Aragora user ID if found
        """
        repo = self._get_external_identity_repo()
        identity = repo.get_by_external_id(
            provider=TEAMS_PROVIDER,
            external_id=aad_object_id,
            tenant_id=tenant_id,
        )

        if identity:
            return identity.user_id
        return None

    async def link_teams_user(
        self,
        aragora_user_id: str,
        aad_object_id: str,
        tenant_id: str,
        email: str | None = None,
        display_name: str | None = None,
    ) -> bool:
        """
        Link a Teams identity to an existing Aragora user.

        Args:
            aragora_user_id: Existing Aragora user ID
            aad_object_id: Azure AD object ID
            tenant_id: Azure AD tenant ID
            email: Optional email
            display_name: Optional display name

        Returns:
            True if linked successfully
        """
        repo = self._get_external_identity_repo()

        try:
            repo.link_or_update(
                user_id=aragora_user_id,
                provider=TEAMS_PROVIDER,
                external_id=aad_object_id,
                tenant_id=tenant_id,
                email=email,
                display_name=display_name,
            )
            logger.info("Linked Teams user %s to Aragora user %s", aad_object_id, aragora_user_id)
            return True
        except (ValueError, TypeError, RuntimeError) as e:
            logger.error("Failed to link Teams user: %s", e)
            return False

    async def unlink_teams_user(
        self,
        aad_object_id: str,
        tenant_id: str,
    ) -> bool:
        """
        Unlink a Teams identity from Aragora.

        Args:
            aad_object_id: Azure AD object ID
            tenant_id: Azure AD tenant ID

        Returns:
            True if unlinked successfully
        """
        repo = self._get_external_identity_repo()
        identity = repo.get_by_external_id(
            provider=TEAMS_PROVIDER,
            external_id=aad_object_id,
            tenant_id=tenant_id,
        )

        if identity:
            return repo.deactivate(identity.id)
        return False

    def extract_user_info_from_activity(
        self,
        activity: dict[str, Any],
    ) -> TeamsUserInfo | None:
        """
        Extract Teams user info from a Bot Framework activity.

        Args:
            activity: Bot Framework activity dictionary

        Returns:
            TeamsUserInfo if extraction successful
        """
        from_data = activity.get("from", {})
        aad_object_id = from_data.get("aadObjectId")

        if not aad_object_id:
            return None

        # Get tenant from conversation or channelData
        conversation = activity.get("conversation", {})
        channel_data = activity.get("channelData", {})
        tenant_id = conversation.get("tenantId") or channel_data.get("tenant", {}).get("id") or ""

        return TeamsUserInfo(
            aad_object_id=aad_object_id,
            tenant_id=tenant_id,
            display_name=from_data.get("name"),
            # Email often needs Graph API call
        )


# Singleton instance
_bridge: TeamsUserIdentityBridge | None = None


def get_teams_identity_bridge() -> TeamsUserIdentityBridge:
    """Get or create the Teams identity bridge singleton."""
    global _bridge
    if _bridge is None:
        _bridge = TeamsUserIdentityBridge()
    return _bridge
