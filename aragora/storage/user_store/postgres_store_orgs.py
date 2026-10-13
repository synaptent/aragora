"""
PostgresUserStore - Organization operations mixin.

Extracted from postgres_store.py for modularity.
Provides organization CRUD, membership management, and usage tracking.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from aragora.billing.models import Organization, SubscriptionTier, User
from aragora.utils.async_utils import run_async

logger = logging.getLogger(__name__)


class OrganizationOperationsMixin:
    """Mixin providing organization operations for PostgresUserStore."""

    if TYPE_CHECKING:
        _pool: Any
        _row_to_user: Any

    # =========================================================================
    # Organization Operations
    # =========================================================================

    def create_organization(
        self,
        name: str,
        owner_id: str,
        slug: str | None = None,
        tier: SubscriptionTier = SubscriptionTier.FREE,
    ) -> Organization:
        """Create a new organization (sync wrapper)."""
        return run_async(self.create_organization_async(name, owner_id, slug, tier))

    async def create_organization_async(
        self,
        name: str,
        owner_id: str,
        slug: str | None = None,
        tier: SubscriptionTier = SubscriptionTier.FREE,
    ) -> Organization:
        """Create a new organization asynchronously."""
        org_id = str(uuid.uuid4())
        if not slug:
            slug = name.lower().replace(" ", "-")[:50] + "-" + org_id[:8]
        now = datetime.now(timezone.utc)

        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO organizations
                   (id, name, slug, tier, owner_id, billing_cycle_start, created_at, updated_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $6, $6)""",
                org_id,
                name,
                slug,
                tier.value if hasattr(tier, "value") else str(tier),
                owner_id,
                now,
            )
            # Update owner's org_id
            await conn.execute(
                "UPDATE users SET org_id = $1, role = 'owner', updated_at = $2 WHERE id = $3",
                org_id,
                now,
                owner_id,
            )

        return Organization(
            id=org_id,
            name=name,
            slug=slug,
            tier=tier,
            owner_id=owner_id,
            billing_cycle_start=now,
            created_at=now,
            updated_at=now,
        )

    def get_organization_by_id(self, org_id: str) -> Organization | None:
        """Get organization by ID (sync wrapper)."""
        return run_async(self.get_organization_by_id_async(org_id))

    async def get_organization_by_id_async(self, org_id: str) -> Organization | None:
        """Get organization by ID asynchronously."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, name, slug, tier, owner_id, stripe_customer_id,
                          stripe_subscription_id, debates_used_this_month,
                          billing_cycle_start, settings, created_at, updated_at
                   FROM organizations WHERE id = $1""",
                org_id,
            )
            if row:
                return self._row_to_org(row)
            return None

    def get_organization_by_slug(self, slug: str) -> Organization | None:
        """Get organization by slug (sync wrapper)."""
        return run_async(self.get_organization_by_slug_async(slug))

    async def get_organization_by_slug_async(self, slug: str) -> Organization | None:
        """Get organization by slug asynchronously."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, name, slug, tier, owner_id, stripe_customer_id,
                          stripe_subscription_id, debates_used_this_month,
                          billing_cycle_start, settings, created_at, updated_at
                   FROM organizations WHERE slug = $1""",
                slug,
            )
            if row:
                return self._row_to_org(row)
            return None

    def get_organization_by_stripe_customer(self, stripe_customer_id: str) -> Organization | None:
        """Get organization by Stripe customer ID (sync wrapper)."""
        return run_async(self.get_organization_by_stripe_customer_async(stripe_customer_id))

    async def get_organization_by_stripe_customer_async(
        self, stripe_customer_id: str
    ) -> Organization | None:
        """Get organization by Stripe customer ID asynchronously."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, name, slug, tier, owner_id, stripe_customer_id,
                          stripe_subscription_id, debates_used_this_month,
                          billing_cycle_start, settings, created_at, updated_at
                   FROM organizations WHERE stripe_customer_id = $1""",
                stripe_customer_id,
            )
            if row:
                return self._row_to_org(row)
            return None

    def get_organization_by_subscription(self, subscription_id: str) -> Organization | None:
        """Get organization by Stripe subscription ID (sync wrapper)."""
        return run_async(self.get_organization_by_subscription_async(subscription_id))

    async def get_organization_by_subscription_async(
        self, subscription_id: str
    ) -> Organization | None:
        """Get organization by Stripe subscription ID asynchronously."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, name, slug, tier, owner_id, stripe_customer_id,
                          stripe_subscription_id, debates_used_this_month,
                          billing_cycle_start, settings, created_at, updated_at
                   FROM organizations WHERE stripe_subscription_id = $1""",
                subscription_id,
            )
            if row:
                return self._row_to_org(row)
            return None

    def update_organization(self, org_id: str, **fields: Any) -> bool:
        """Update organization fields (sync wrapper)."""
        return run_async(self.update_organization_async(org_id, **fields))

    async def update_organization_async(self, org_id: str, **fields: Any) -> bool:
        """Update organization fields asynchronously."""
        if not fields:
            return False

        updates: list[str] = []
        params: list[Any] = []
        param_idx = 1

        for key, value in fields.items():
            if key == "settings" and isinstance(value, dict):
                value = json.dumps(value)
            updates.append(f"{key} = ${param_idx}")
            params.append(value)
            param_idx += 1

        updates.append(f"updated_at = ${param_idx}")
        params.append(datetime.now(timezone.utc))
        param_idx += 1
        params.append(org_id)

        async with self._pool.acquire() as conn:
            result = await conn.execute(
                # dynamic clause from internal state
                f"UPDATE organizations SET {', '.join(updates)} WHERE id = ${param_idx}",
                *params,
            )
            return result != "UPDATE 0"

    def reset_org_usage(self, org_id: str) -> bool:
        """Reset monthly usage for a single organization (sync wrapper)."""
        return run_async(self.reset_org_usage_async(org_id))

    async def reset_org_usage_async(self, org_id: str) -> bool:
        """Reset monthly usage asynchronously."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """UPDATE organizations SET debates_used_this_month = 0,
                   billing_cycle_start = $1, updated_at = $1 WHERE id = $2""",
                datetime.now(timezone.utc),
                org_id,
            )
            return result != "UPDATE 0"

    def add_user_to_org(self, user_id: str, org_id: str, role: str = "member") -> bool:
        """Add user to organization (sync wrapper)."""
        return run_async(self.add_user_to_org_async(user_id, org_id, role))

    async def add_user_to_org_async(self, user_id: str, org_id: str, role: str = "member") -> bool:
        """Add user to organization asynchronously."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE users SET org_id = $1, role = $2, updated_at = $3 WHERE id = $4",
                org_id,
                role,
                datetime.now(timezone.utc),
                user_id,
            )
            return result != "UPDATE 0"

    def remove_user_from_org(self, user_id: str) -> bool:
        """Remove user from organization (sync wrapper)."""
        return run_async(self.remove_user_from_org_async(user_id))

    async def remove_user_from_org_async(self, user_id: str) -> bool:
        """Remove user from organization asynchronously."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE users SET org_id = NULL, role = 'member', updated_at = $1 WHERE id = $2",
                datetime.now(timezone.utc),
                user_id,
            )
            return result != "UPDATE 0"

    def get_org_members(self, org_id: str) -> list[User]:
        """Get all members of an organization (sync wrapper)."""
        return run_async(self.get_org_members_async(org_id))

    async def get_org_members_async(self, org_id: str) -> list[User]:
        """Get all members of an organization asynchronously."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, email, password_hash, password_salt, name, org_id, role,
                          is_active, email_verified, api_key, api_key_hash, api_key_prefix,
                          api_key_created_at, api_key_expires_at, created_at, updated_at,
                          last_login_at, mfa_secret, mfa_enabled, mfa_backup_codes,
                          token_version, failed_login_attempts, lockout_until,
                          last_failed_login_at, preferences
                   FROM users WHERE org_id = $1 ORDER BY created_at""",
                org_id,
            )
            return [self._row_to_user(row) for row in rows]

    def get_org_members_eager(self, org_id: str) -> tuple[Organization | None, list[User]]:
        """Get organization and all its members (sync wrapper)."""
        return run_async(self.get_org_members_eager_async(org_id))

    async def get_org_members_eager_async(
        self, org_id: str
    ) -> tuple[Organization | None, list[User]]:
        """Get organization and all its members asynchronously."""
        org = await self.get_organization_by_id_async(org_id)
        if not org:
            return None, []
        members = await self.get_org_members_async(org_id)
        return org, members

    def get_orgs_with_members_batch(
        self, org_ids: list[str]
    ) -> dict[str, tuple[Organization, list[User]]]:
        """Get multiple organizations with their members (sync wrapper)."""
        return run_async(self.get_orgs_with_members_batch_async(org_ids))

    async def get_orgs_with_members_batch_async(
        self, org_ids: list[str]
    ) -> dict[str, tuple[Organization, list[User]]]:
        """Get multiple organizations with their members asynchronously."""
        result: dict[str, tuple[Organization, list[User]]] = {}
        for org_id in org_ids:
            org, members = await self.get_org_members_eager_async(org_id)
            if org:
                result[org_id] = (org, members)
        return result

    def _row_to_org(self, row: Any) -> Organization:
        """Convert database row to Organization object."""
        settings = row["settings"]
        if isinstance(settings, str):
            settings = json.loads(settings)

        return Organization(
            id=row["id"],
            name=row["name"],
            slug=row["slug"],
            tier=SubscriptionTier(row["tier"]) if row["tier"] else SubscriptionTier.FREE,
            owner_id=row["owner_id"],
            stripe_customer_id=row["stripe_customer_id"],
            stripe_subscription_id=row["stripe_subscription_id"],
            debates_used_this_month=row["debates_used_this_month"] or 0,
            billing_cycle_start=row["billing_cycle_start"],
            settings=settings or {},
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # =========================================================================
    # Usage Tracking
    # =========================================================================

    def increment_usage(self, org_id: str, count: int = 1) -> int:
        """Increment debate usage for an organization (sync wrapper)."""
        return run_async(self.increment_usage_async(org_id, count))

    async def increment_usage_async(self, org_id: str, count: int = 1) -> int:
        """Increment debate usage asynchronously."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE organizations SET debates_used_this_month = debates_used_this_month + $1,
                   updated_at = $2 WHERE id = $3 RETURNING debates_used_this_month""",
                count,
                datetime.now(timezone.utc),
                org_id,
            )
            return row["debates_used_this_month"] if row else 0

    def record_usage_event(
        self,
        org_id: str,
        event_type: str,
        count: int = 1,
        metadata: dict | None = None,
    ) -> None:
        """Record a usage event for analytics (sync wrapper)."""
        run_async(self.record_usage_event_async(org_id, event_type, count, metadata))

    async def record_usage_event_async(
        self,
        org_id: str,
        event_type: str,
        count: int = 1,
        metadata: dict | None = None,
    ) -> None:
        """Record a usage event asynchronously."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO usage_events (org_id, event_type, count, metadata, created_at)
                   VALUES ($1, $2, $3, $4, $5)""",
                org_id,
                event_type,
                count,
                json.dumps(metadata or {}),
                datetime.now(timezone.utc),
            )

    def reset_monthly_usage(self) -> int:
        """Reset monthly usage for all organizations (sync wrapper)."""
        return run_async(self.reset_monthly_usage_async())

    async def reset_monthly_usage_async(self) -> int:
        """Reset monthly usage asynchronously."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """UPDATE organizations SET debates_used_this_month = 0,
                   billing_cycle_start = $1, updated_at = $1""",
                datetime.now(timezone.utc),
            )
            # Parse "UPDATE N" to get count
            parts = result.split()
            return int(parts[1]) if len(parts) > 1 else 0

    def get_usage_summary(self, org_id: str) -> dict:
        """Get usage summary for an organization (sync wrapper)."""
        return run_async(self.get_usage_summary_async(org_id))

    async def get_usage_summary_async(self, org_id: str) -> dict:
        """Get usage summary asynchronously."""
        org = await self.get_organization_by_id_async(org_id)
        if not org:
            return {}

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT event_type, SUM(count) as total
                   FROM usage_events WHERE org_id = $1 GROUP BY event_type""",
                org_id,
            )

        return {
            "org_id": org_id,
            "debates_used_this_month": org.debates_used_this_month,
            "billing_cycle_start": (
                org.billing_cycle_start.isoformat() if org.billing_cycle_start else None
            ),
            "events": {row["event_type"]: row["total"] for row in rows},
        }
