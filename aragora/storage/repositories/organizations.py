"""
OrganizationRepository - Organization and team management operations.

Extracted from UserStore for better modularity. Manages organization CRUD,
member management, and Stripe integration lookups.
"""

from __future__ import annotations

import json
import logging
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from contextlib import AbstractContextManager
from collections.abc import Callable

if TYPE_CHECKING:
    from aragora.billing.models import Organization, SubscriptionTier, User

logger = logging.getLogger(__name__)


class OrganizationRepository:
    """
    Repository for organization and team management operations.

    This class manages:
    - Organization CRUD operations
    - Member management (add/remove users)
    - Stripe integration lookups
    - Batch operations for efficient multi-org queries
    """

    # Explicit columns for SELECT queries - prevents SELECT * data exposure
    _ORG_COLUMNS = (
        "id, name, slug, tier, owner_id, stripe_customer_id, "
        "stripe_subscription_id, debates_used_this_month, billing_cycle_start, "
        "settings, created_at, updated_at"
    )
    _USER_COLUMNS = (
        "id, email, password_hash, password_salt, name, org_id, role, "
        "is_active, email_verified, api_key, api_key_hash, api_key_prefix, "
        "api_key_created_at, api_key_expires_at, created_at, updated_at, "
        "last_login_at, mfa_secret, mfa_enabled, mfa_backup_codes, token_version"
    )

    _COLUMN_MAP = {
        "name": "name",
        "slug": "slug",
        "tier": "tier",
        "owner_id": "owner_id",
        "stripe_customer_id": "stripe_customer_id",
        "stripe_subscription_id": "stripe_subscription_id",
        "debates_used_this_month": "debates_used_this_month",
        "billing_cycle_start": "billing_cycle_start",
        "settings": "settings",
    }

    _AUTO_SLUG_ATTEMPTS = 10
    # sqlite3 names the violated column only in the message text; the extended
    # error code (SQLITE_CONSTRAINT_UNIQUE) does not say which index failed.
    _SLUG_CONFLICT_MESSAGE = "UNIQUE constraint failed: organizations.slug"

    def __init__(
        self,
        transaction_fn: Callable[[], AbstractContextManager[sqlite3.Cursor]],
        row_to_user_fn: Callable[[sqlite3.Row], User] | None = None,
    ) -> None:
        """
        Initialize the organization repository.

        Args:
            transaction_fn: Function that returns a transaction context manager.
            row_to_user_fn: Optional function to convert rows to User objects.
        """
        self._transaction = transaction_fn
        self._row_to_user = row_to_user_fn

    def create(
        self,
        name: str,
        owner_id: str,
        slug: str | None = None,
        tier: SubscriptionTier | None = None,
    ) -> Organization:
        """
        Create a new organization.

        Args:
            name: Organization name
            owner_id: User ID of owner
            slug: URL-friendly slug (auto-generated if not provided)
            tier: Subscription tier

        Returns:
            Created Organization object
        """
        from aragora.billing.models import Organization, SubscriptionTier

        if tier is None:
            tier = SubscriptionTier.FREE

        auto_slug = slug is None
        base_slug = name.lower().replace(" ", "-").replace("_", "-")

        org = Organization(
            name=name,
            slug=base_slug if slug is None else slug,
            tier=tier,
            owner_id=owner_id,
        )

        # The UNIQUE index on organizations.slug is the only atomic arbiter of slug
        # availability: a separate SELECT lets concurrent creators both observe the
        # same free slug before either INSERT commits.
        for attempt in range(self._AUTO_SLUG_ATTEMPTS):
            try:
                with self._transaction() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO organizations (
                            id, name, slug, tier, owner_id, stripe_customer_id,
                            stripe_subscription_id, debates_used_this_month,
                            billing_cycle_start, settings, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            org.id,
                            org.name,
                            org.slug,
                            org.tier.value,
                            org.owner_id,
                            org.stripe_customer_id,
                            org.stripe_subscription_id,
                            org.debates_used_this_month,
                            org.billing_cycle_start.isoformat(),
                            json.dumps(org.settings),
                            org.created_at.isoformat(),
                            org.updated_at.isoformat(),
                        ),
                    )

                    # Update owner's org_id and role
                    cursor.execute(
                        "UPDATE users SET org_id = ?, role = ?, updated_at = ? WHERE id = ?",
                        (org.id, "owner", datetime.now(timezone.utc).isoformat(), owner_id),
                    )
                break
            except sqlite3.IntegrityError as exc:
                if (
                    not auto_slug
                    or self._SLUG_CONFLICT_MESSAGE not in str(exc)
                    or attempt == self._AUTO_SLUG_ATTEMPTS - 1
                ):
                    raise
                org.slug = f"{base_slug}-{secrets.token_hex(4)}"

        logger.info("organization_created id=%s name=%s owner=%s", org.id, name, owner_id)
        return org

    def get_by_id(self, org_id: str) -> Organization | None:
        """Get organization by ID."""
        with self._transaction() as cursor:
            cursor.execute(f"SELECT {self._ORG_COLUMNS} FROM organizations WHERE id = ?", (org_id,))  # noqa: S608 -- column name interpolation, parameterized
            row = cursor.fetchone()
            return self._row_to_org(row) if row else None

    def get_by_slug(self, slug: str) -> Organization | None:
        """Get organization by slug."""
        with self._transaction() as cursor:
            cursor.execute(f"SELECT {self._ORG_COLUMNS} FROM organizations WHERE slug = ?", (slug,))  # noqa: S608 -- column name interpolation, parameterized
            row = cursor.fetchone()
            return self._row_to_org(row) if row else None

    def get_by_stripe_customer(self, stripe_customer_id: str) -> Organization | None:
        """Get organization by Stripe customer ID."""
        with self._transaction() as cursor:
            cursor.execute(
                f"SELECT {self._ORG_COLUMNS} FROM organizations WHERE stripe_customer_id = ?",  # noqa: S608 -- column name interpolation, parameterized
                (stripe_customer_id,),
            )
            row = cursor.fetchone()
            return self._row_to_org(row) if row else None

    def get_by_subscription(self, subscription_id: str) -> Organization | None:
        """Get organization by Stripe subscription ID."""
        with self._transaction() as cursor:
            cursor.execute(
                f"SELECT {self._ORG_COLUMNS} FROM organizations WHERE stripe_subscription_id = ?",  # noqa: S608 -- column name interpolation, parameterized
                (subscription_id,),
            )
            row = cursor.fetchone()
            return self._row_to_org(row) if row else None

    def update(self, org_id: str, **fields: Any) -> bool:
        """
        Update organization fields.

        Args:
            org_id: Organization ID
            **fields: Fields to update

        Returns:
            True if organization was updated
        """
        from aragora.billing.models import SubscriptionTier

        if not fields:
            return False

        updates: list[str] = []
        values: list[Any] = []

        for field, value in fields.items():
            if field in self._COLUMN_MAP:
                updates.append(f"{self._COLUMN_MAP[field]} = ?")
                if field == "tier" and isinstance(value, SubscriptionTier):
                    values.append(value.value)
                elif field == "settings" and isinstance(value, dict):
                    values.append(json.dumps(value))
                elif isinstance(value, datetime):
                    values.append(value.isoformat())
                else:
                    values.append(value)

        if not updates:
            return False

        updates.append("updated_at = ?")
        values.append(datetime.now(timezone.utc).isoformat())
        values.append(org_id)

        with self._transaction() as cursor:
            query = f"UPDATE organizations SET {', '.join(updates)} WHERE id = ?"  # nosec B608  # noqa: S608
            cursor.execute(query, values)
            return cursor.rowcount > 0

    def reset_usage(self, org_id: str) -> bool:
        """Reset monthly usage for an organization."""
        with self._transaction() as cursor:
            cursor.execute(
                """
                UPDATE organizations
                SET debates_used_this_month = 0,
                    billing_cycle_start = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    datetime.now(timezone.utc).isoformat(),
                    org_id,
                ),
            )
            return cursor.rowcount > 0

    def add_member(self, user_id: str, org_id: str, role: str = "member") -> bool:
        """Add user to organization."""
        with self._transaction() as cursor:
            cursor.execute(
                "UPDATE users SET org_id = ?, role = ?, updated_at = ? WHERE id = ?",
                (org_id, role, datetime.now(timezone.utc).isoformat(), user_id),
            )
            return cursor.rowcount > 0

    def remove_member(self, user_id: str) -> bool:
        """Remove user from organization."""
        with self._transaction() as cursor:
            cursor.execute(
                "UPDATE users SET org_id = NULL, role = 'member', updated_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), user_id),
            )
            return cursor.rowcount > 0

    def get_members(self, org_id: str) -> list[User]:
        """Get all members of an organization."""
        if self._row_to_user is None:
            raise RuntimeError("row_to_user_fn not provided to OrganizationRepository")

        with self._transaction() as cursor:
            cursor.execute(f"SELECT {self._USER_COLUMNS} FROM users WHERE org_id = ?", (org_id,))  # noqa: S608 -- column name interpolation, parameterized
            return [self._row_to_user(row) for row in cursor.fetchall()]

    def get_with_members(self, org_id: str) -> tuple[Organization | None, list[User]]:
        """
        Get organization and all its members in a single query operation.

        Args:
            org_id: Organization ID

        Returns:
            Tuple of (Organization or None, list of User members)
        """
        if self._row_to_user is None:
            raise RuntimeError("row_to_user_fn not provided to OrganizationRepository")

        with self._transaction() as cursor:
            cursor.execute(f"SELECT {self._ORG_COLUMNS} FROM organizations WHERE id = ?", (org_id,))  # noqa: S608 -- column name interpolation, parameterized
            org_row = cursor.fetchone()
            if not org_row:
                return None, []

            org = self._row_to_org(org_row)

            cursor.execute(f"SELECT {self._USER_COLUMNS} FROM users WHERE org_id = ?", (org_id,))  # noqa: S608 -- column name interpolation, parameterized
            members = [self._row_to_user(row) for row in cursor.fetchall()]

            return org, members

    def get_batch_with_members(
        self,
        org_ids: list[str],
    ) -> dict[str, tuple[Organization, list[User]]]:
        """
        Get multiple organizations with their members in optimized queries.

        Args:
            org_ids: List of organization IDs

        Returns:
            Dict mapping org_id to (Organization, members list) tuple
        """
        if not org_ids:
            return {}

        if self._row_to_user is None:
            raise RuntimeError("row_to_user_fn not provided to OrganizationRepository")

        unique_ids = list(dict.fromkeys(org_ids))
        result: dict[str, tuple[Organization, list[User]]] = {}

        with self._transaction() as cursor:
            placeholders = ",".join("?" * len(unique_ids))
            query1 = f"SELECT {self._ORG_COLUMNS} FROM organizations WHERE id IN ({placeholders})"  # nosec B608  # noqa: S608
            cursor.execute(query1, unique_ids)
            orgs = {row["id"]: self._row_to_org(row) for row in cursor.fetchall()}

            query2 = f"SELECT {self._USER_COLUMNS} FROM users WHERE org_id IN ({placeholders})"  # nosec B608  # noqa: S608
            cursor.execute(query2, unique_ids)

            members_by_org: dict[str, list[User]] = {oid: [] for oid in orgs}
            for row in cursor.fetchall():
                user = self._row_to_user(row)
                if user.org_id in members_by_org:
                    members_by_org[user.org_id].append(user)

            for org_id, org in orgs.items():
                result[org_id] = (org, members_by_org.get(org_id, []))

        return result

    @staticmethod
    def _row_to_org(row: sqlite3.Row) -> Organization:
        """Convert database row to Organization object."""
        from aragora.billing.models import Organization, SubscriptionTier

        return Organization(
            id=row["id"],
            name=row["name"],
            slug=row["slug"],
            tier=SubscriptionTier(row["tier"]),
            owner_id=row["owner_id"],
            stripe_customer_id=row["stripe_customer_id"],
            stripe_subscription_id=row["stripe_subscription_id"],
            debates_used_this_month=row["debates_used_this_month"],
            billing_cycle_start=datetime.fromisoformat(row["billing_cycle_start"]),
            settings=json.loads(row["settings"]) if row["settings"] else {},
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
