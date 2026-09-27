"""
OrganizationStore - Database backend for organization and invitation persistence.

Supports SQLite (default) and PostgreSQL backends.
Extracted from UserStore to improve modularity.
Provides CRUD operations for:
- Organizations (team management, settings)
- Invitations (member invites, token validation)
"""

from __future__ import annotations

__all__ = [
    "OrganizationStore",
    "get_organization_store",
    "reset_organization_store",
]

import contextvars
import json
import logging
import os
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
from collections.abc import Callable, Iterator

from aragora.config import resolve_db_path
from aragora.billing.models import Organization, OrganizationInvitation, SubscriptionTier, User
from aragora.exceptions import ConfigurationError
from aragora.storage.backends import (
    POSTGRESQL_AVAILABLE,
    DatabaseBackend,
    PostgreSQLBackend,
    SQLiteBackend,
)

logger = logging.getLogger(__name__)


class OrganizationStore:
    """
    Database-backed storage for organizations and invitations.

    Supports SQLite (default) and PostgreSQL backends.
    Can be used standalone or composed with UserStore.
    Thread-safe with connection pooling via thread-local storage.
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
    _INVITATION_COLUMNS = (
        "id, org_id, email, role, token, invited_by, status, "
        "created_at, expires_at, accepted_by, accepted_at"
    )

    def __init__(
        self,
        db_path: Path | str = "organizations.db",
        get_connection: Callable[[], sqlite3.Connection] | None = None,
        update_user: Callable[..., bool] | None = None,
        row_to_user: Callable[[sqlite3.Row], User] | None = None,
        backend: str | None = None,
        database_url: str | None = None,
    ):
        """
        Initialize OrganizationStore.

        Args:
            db_path: Path to SQLite database file (used when backend="sqlite")
            get_connection: Optional connection factory (for sharing with UserStore)
            update_user: Optional user update function (for org membership)
            row_to_user: Optional row-to-user converter (for get_org_members)
            backend: Database backend ("sqlite" or "postgresql")
            database_url: PostgreSQL connection URL
        """
        self.db_path = Path(resolve_db_path(db_path))
        # ContextVar for per-async-context connection (async-safe replacement for threading.local)
        self._conn_var: contextvars.ContextVar[sqlite3.Connection | None] = contextvars.ContextVar(
            f"organization_conn_{id(self)}", default=None
        )
        # Track all connections for proper cleanup
        self._connections: set[sqlite3.Connection] = set()
        self._connections_lock = threading.Lock()
        self._external_get_connection = get_connection
        self._external_update_user = update_user
        self._external_row_to_user = row_to_user

        # Backend selection is now handled by get_organization_store() using resolve_database_config().
        # This __init__ just accepts explicit parameters from the factory function.
        self.backend_type = backend or "sqlite"
        self._backend: DatabaseBackend | None = None

        # Only create backend if not using external connection
        if get_connection is None:
            if self.backend_type == "postgresql":
                if not database_url:
                    raise ValueError("PostgreSQL backend requires database_url parameter")
                if not POSTGRESQL_AVAILABLE:
                    raise ImportError("psycopg2 required for PostgreSQL")
                self._backend = PostgreSQLBackend(database_url)
                logger.info("OrganizationStore using PostgreSQL backend")
            else:
                self._backend = SQLiteBackend(str(db_path))
                logger.info("OrganizationStore using SQLite backend: %s", db_path)

    def _get_connection(self) -> sqlite3.Connection:
        """Get per-context database connection."""
        if self._external_get_connection:
            return self._external_get_connection()

        conn = self._conn_var.get()
        if conn is None:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._conn_var.set(conn)
            with self._connections_lock:
                self._connections.add(conn)
        return conn

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Cursor]:
        """Context manager for database transactions (legacy SQLite mode)."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except (sqlite3.Error, OSError, ValueError) as e:
            conn.rollback()
            logger.debug("Transaction rolled back due to: %s", e)
            raise

    def _org_tuple_to_dict(self, row: tuple) -> dict[str, Any]:
        """Convert organization tuple row to dict for _row_to_org compatibility."""
        cols = [c.strip() for c in self._ORG_COLUMNS.split(",")]
        return dict(zip(cols, row))

    def _invitation_tuple_to_dict(self, row: tuple) -> dict[str, Any]:
        """Convert invitation tuple row to dict for _row_to_invitation compatibility."""
        cols = [c.strip() for c in self._INVITATION_COLUMNS.split(",")]
        return dict(zip(cols, row))

    # =========================================================================
    # Organization Methods
    # =========================================================================

    def create_organization(
        self,
        name: str,
        owner_id: str,
        slug: str | None = None,
        tier: SubscriptionTier = SubscriptionTier.FREE,
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
        if slug is None:
            slug = name.lower().replace(" ", "-").replace("_", "-")
            # Make unique by appending random suffix if needed
            base_slug = slug
            for _ in range(10):
                if self._backend is not None:
                    row = self._backend.fetch_one(
                        "SELECT 1 FROM organizations WHERE slug = ?", (slug,)
                    )
                    if not row:
                        break
                    slug = f"{base_slug}-{secrets.token_hex(4)}"
                else:
                    with self._transaction() as cursor:
                        cursor.execute("SELECT 1 FROM organizations WHERE slug = ?", (slug,))
                        if not cursor.fetchone():
                            break
                        slug = f"{base_slug}-{secrets.token_hex(4)}"

        org = Organization(
            name=name,
            slug=slug,
            tier=tier,
            owner_id=owner_id,
        )

        params = (
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
        )

        if self._backend is not None:
            self._backend.execute_write(
                """
                INSERT INTO organizations (
                    id, name, slug, tier, owner_id, stripe_customer_id,
                    stripe_subscription_id, debates_used_this_month,
                    billing_cycle_start, settings, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                params,
            )
        else:
            with self._transaction() as cursor:
                cursor.execute(
                    """
                    INSERT INTO organizations (
                        id, name, slug, tier, owner_id, stripe_customer_id,
                        stripe_subscription_id, debates_used_this_month,
                        billing_cycle_start, settings, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    params,
                )

        # Update owner's org_id if we have a user updater
        if self._external_update_user:
            self._external_update_user(owner_id, org_id=org.id, role="owner")

        logger.info("organization_created id=%s name=%s owner=%s", org.id, name, owner_id)
        return org

    def get_organization_by_id(self, org_id: str) -> Organization | None:
        """Get organization by ID."""
        if self._backend is not None:
            row = self._backend.fetch_one(
                f"SELECT {self._ORG_COLUMNS} FROM organizations WHERE id = ?",  # noqa: S608 -- column name interpolation, parameterized
                (org_id,),
            )
            if row:
                return self._row_to_org(self._org_tuple_to_dict(row))
            return None

        with self._transaction() as cursor:
            cursor.execute(f"SELECT {self._ORG_COLUMNS} FROM organizations WHERE id = ?", (org_id,))  # noqa: S608 -- column name interpolation, parameterized
            row = cursor.fetchone()
            if row:
                return self._row_to_org(row)
        return None

    def get_organization_by_slug(self, slug: str) -> Organization | None:
        """Get organization by slug."""
        if self._backend is not None:
            row = self._backend.fetch_one(
                f"SELECT {self._ORG_COLUMNS} FROM organizations WHERE slug = ?",  # noqa: S608 -- column name interpolation, parameterized
                (slug,),
            )
            if row:
                return self._row_to_org(self._org_tuple_to_dict(row))
            return None

        with self._transaction() as cursor:
            cursor.execute(f"SELECT {self._ORG_COLUMNS} FROM organizations WHERE slug = ?", (slug,))  # noqa: S608 -- column name interpolation, parameterized
            row = cursor.fetchone()
            if row:
                return self._row_to_org(row)
        return None

    def get_organization_by_stripe_customer(self, stripe_customer_id: str) -> Organization | None:
        """Get organization by Stripe customer ID."""
        if self._backend is not None:
            row = self._backend.fetch_one(
                f"SELECT {self._ORG_COLUMNS} FROM organizations WHERE stripe_customer_id = ?",  # noqa: S608 -- column name interpolation, parameterized
                (stripe_customer_id,),
            )
            if row:
                return self._row_to_org(self._org_tuple_to_dict(row))
            return None

        with self._transaction() as cursor:
            cursor.execute(
                f"SELECT {self._ORG_COLUMNS} FROM organizations WHERE stripe_customer_id = ?",  # noqa: S608 -- column name interpolation, parameterized
                (stripe_customer_id,),
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_org(row)
        return None

    def get_organization_by_subscription(self, subscription_id: str) -> Organization | None:
        """Get organization by Stripe subscription ID."""
        if self._backend is not None:
            row = self._backend.fetch_one(
                f"SELECT {self._ORG_COLUMNS} FROM organizations WHERE stripe_subscription_id = ?",  # noqa: S608 -- column name interpolation, parameterized
                (subscription_id,),
            )
            if row:
                return self._row_to_org(self._org_tuple_to_dict(row))
            return None

        with self._transaction() as cursor:
            cursor.execute(
                f"SELECT {self._ORG_COLUMNS} FROM organizations WHERE stripe_subscription_id = ?",  # noqa: S608 -- column name interpolation, parameterized
                (subscription_id,),
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_org(row)
        return None

    def reset_org_usage(self, org_id: str) -> bool:
        """Reset monthly usage for a single organization."""
        params = (
            datetime.now(timezone.utc).isoformat(),
            datetime.now(timezone.utc).isoformat(),
            org_id,
        )

        if self._backend is not None:
            # Check if org exists first
            row = self._backend.fetch_one("SELECT 1 FROM organizations WHERE id = ?", (org_id,))
            if not row:
                return False
            self._backend.execute_write(
                """
                UPDATE organizations
                SET debates_used_this_month = 0,
                    billing_cycle_start = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                params,
            )
            return True

        with self._transaction() as cursor:
            cursor.execute(
                """
                UPDATE organizations
                SET debates_used_this_month = 0,
                    billing_cycle_start = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                params,
            )
            return cursor.rowcount > 0

    def update_organization(self, org_id: str, **fields) -> bool:
        """Update organization fields."""
        if not fields:
            return False

        column_map = {
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

        updates = []
        values = []
        for field, value in fields.items():
            if field in column_map:
                updates.append(f"{column_map[field]} = ?")
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

        query = f"UPDATE organizations SET {', '.join(updates)} WHERE id = ?"  # nosec B608  # noqa: S608

        if self._backend is not None:
            # Check if org exists first
            row = self._backend.fetch_one("SELECT 1 FROM organizations WHERE id = ?", (org_id,))
            if not row:
                return False
            self._backend.execute_write(query, tuple(values))
            return True

        with self._transaction() as cursor:
            cursor.execute(query, values)
            return cursor.rowcount > 0

    def add_user_to_org(self, user_id: str, org_id: str, role: str = "member") -> bool:
        """Add user to organization."""
        if self._external_update_user:
            return self._external_update_user(user_id, org_id=org_id, role=role)
        raise ConfigurationError(
            component="OrganizationStore",
            reason="update_user callback required for add_user_to_org",
        )

    def remove_user_from_org(self, user_id: str) -> bool:
        """Remove user from organization."""
        if self._external_update_user:
            return self._external_update_user(user_id, org_id=None, role="member")
        raise ConfigurationError(
            component="OrganizationStore",
            reason="update_user callback required for remove_user_from_org",
        )

    def get_org_members(self, org_id: str) -> list[User]:
        """Get all members of an organization."""
        if not self._external_row_to_user:
            raise ConfigurationError(
                component="OrganizationStore",
                reason="row_to_user callback required for get_org_members",
            )

        with self._transaction() as cursor:
            cursor.execute(f"SELECT {self._USER_COLUMNS} FROM users WHERE org_id = ?", (org_id,))  # noqa: S608 -- column name interpolation, parameterized
            return [self._external_row_to_user(row) for row in cursor.fetchall()]

    def _row_to_org(self, row: Any) -> Organization:
        """Convert database row (sqlite3.Row or dict) to Organization object."""
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

    # =========================================================================
    # Invitation Methods
    # =========================================================================

    def create_invitation(self, invitation: OrganizationInvitation) -> bool:
        """Create a new organization invitation."""
        params = (
            invitation.id,
            invitation.org_id,
            invitation.email,
            invitation.role,
            invitation.token,
            invitation.invited_by,
            invitation.status,
            invitation.created_at.isoformat(),
            invitation.expires_at.isoformat() if invitation.expires_at else None,
        )

        if self._backend is not None:
            self._backend.execute_write(
                """
                INSERT INTO org_invitations (
                    id, org_id, email, role, token, invited_by,
                    status, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                params,
            )
            return True

        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO org_invitations (
                    id, org_id, email, role, token, invited_by,
                    status, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                params,
            )
            return cursor.rowcount > 0

    def get_invitation_by_id(self, invitation_id: str) -> OrganizationInvitation | None:
        """Get invitation by ID."""
        if self._backend is not None:
            row = self._backend.fetch_one(
                f"SELECT {self._INVITATION_COLUMNS} FROM org_invitations WHERE id = ?",  # noqa: S608 -- column name interpolation, parameterized
                (invitation_id,),
            )
            if row:
                return self._row_to_invitation(self._invitation_tuple_to_dict(row))
            return None

        with self._transaction() as cursor:
            cursor.execute(
                f"SELECT {self._INVITATION_COLUMNS} FROM org_invitations WHERE id = ?",  # noqa: S608 -- column name interpolation, parameterized
                (invitation_id,),
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_invitation(row)
        return None

    def get_invitation_by_token(self, token: str) -> OrganizationInvitation | None:
        """Get invitation by token."""
        if self._backend is not None:
            row = self._backend.fetch_one(
                f"SELECT {self._INVITATION_COLUMNS} FROM org_invitations WHERE token = ?",  # noqa: S608 -- column name interpolation, parameterized
                (token,),
            )
            if row:
                return self._row_to_invitation(self._invitation_tuple_to_dict(row))
            return None

        with self._transaction() as cursor:
            cursor.execute(
                f"SELECT {self._INVITATION_COLUMNS} FROM org_invitations WHERE token = ?",  # noqa: S608 -- column name interpolation, parameterized
                (token,),
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_invitation(row)
        return None

    def get_invitation_by_email(
        self, email: str, org_id: str, status: str = "pending"
    ) -> OrganizationInvitation | None:
        """Get invitation by email and org."""
        if self._backend is not None:
            row = self._backend.fetch_one(
                f"""
                SELECT {self._INVITATION_COLUMNS} FROM org_invitations
                WHERE email = ? AND org_id = ? AND status = ?
                """,  # noqa: S608 -- column name interpolation, parameterized
                (email, org_id, status),
            )
            if row:
                return self._row_to_invitation(self._invitation_tuple_to_dict(row))
            return None

        with self._transaction() as cursor:
            cursor.execute(
                f"""
                SELECT {self._INVITATION_COLUMNS} FROM org_invitations
                WHERE email = ? AND org_id = ? AND status = ?
                """,  # noqa: S608 -- column name interpolation, parameterized
                (email, org_id, status),
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_invitation(row)
        return None

    def get_invitations_for_org(self, org_id: str) -> list[OrganizationInvitation]:
        """Get all invitations for an organization."""
        if self._backend is not None:
            rows = self._backend.fetch_all(
                f"SELECT {self._INVITATION_COLUMNS} FROM org_invitations WHERE org_id = ? ORDER BY created_at DESC",  # noqa: S608 -- column name interpolation, parameterized
                (org_id,),
            )
            return [self._row_to_invitation(self._invitation_tuple_to_dict(row)) for row in rows]

        with self._transaction() as cursor:
            cursor.execute(
                f"SELECT {self._INVITATION_COLUMNS} FROM org_invitations WHERE org_id = ? ORDER BY created_at DESC",  # noqa: S608 -- column name interpolation, parameterized
                (org_id,),
            )
            return [self._row_to_invitation(row) for row in cursor.fetchall()]

    def get_pending_invitations_by_email(self, email: str) -> list[OrganizationInvitation]:
        """Get all pending invitations for an email address."""
        if self._backend is not None:
            rows = self._backend.fetch_all(
                f"""
                SELECT {self._INVITATION_COLUMNS} FROM org_invitations
                WHERE email = ? AND status = 'pending'
                ORDER BY created_at DESC
                """,  # noqa: S608 -- column name interpolation, parameterized
                (email,),
            )
            return [self._row_to_invitation(self._invitation_tuple_to_dict(row)) for row in rows]

        with self._transaction() as cursor:
            cursor.execute(
                f"""
                SELECT {self._INVITATION_COLUMNS} FROM org_invitations
                WHERE email = ? AND status = 'pending'
                ORDER BY created_at DESC
                """,  # noqa: S608 -- column name interpolation, parameterized
                (email,),
            )
            return [self._row_to_invitation(row) for row in cursor.fetchall()]

    def update_invitation_status(
        self,
        invitation_id: str,
        status: str,
        accepted_by: str | None = None,
        accepted_at: datetime | None = None,
    ) -> bool:
        """Update invitation status."""
        if self._backend is not None:
            # Check if invitation exists
            row = self._backend.fetch_one(
                "SELECT 1 FROM org_invitations WHERE id = ?", (invitation_id,)
            )
            if not row:
                return False

            if status == "accepted" and accepted_by:
                self._backend.execute_write(
                    """
                    UPDATE org_invitations
                    SET status = ?, accepted_by = ?, accepted_at = ?
                    WHERE id = ?
                    """,
                    (
                        status,
                        accepted_by,
                        (
                            accepted_at.isoformat()
                            if accepted_at
                            else datetime.now(timezone.utc).isoformat()
                        ),
                        invitation_id,
                    ),
                )
            else:
                self._backend.execute_write(
                    "UPDATE org_invitations SET status = ? WHERE id = ?",
                    (status, invitation_id),
                )
            return True

        with self._transaction() as cursor:
            if status == "accepted" and accepted_by:
                cursor.execute(
                    """
                    UPDATE org_invitations
                    SET status = ?, accepted_by = ?, accepted_at = ?
                    WHERE id = ?
                    """,
                    (
                        status,
                        accepted_by,
                        (
                            accepted_at.isoformat()
                            if accepted_at
                            else datetime.now(timezone.utc).isoformat()
                        ),
                        invitation_id,
                    ),
                )
            else:
                cursor.execute(
                    "UPDATE org_invitations SET status = ? WHERE id = ?",
                    (status, invitation_id),
                )
            return cursor.rowcount > 0

    def delete_invitation(self, invitation_id: str) -> bool:
        """Delete an invitation."""
        if self._backend is not None:
            # Check if invitation exists
            row = self._backend.fetch_one(
                "SELECT 1 FROM org_invitations WHERE id = ?", (invitation_id,)
            )
            if not row:
                return False
            self._backend.execute_write(
                "DELETE FROM org_invitations WHERE id = ?",
                (invitation_id,),
            )
            return True

        with self._transaction() as cursor:
            cursor.execute(
                "DELETE FROM org_invitations WHERE id = ?",
                (invitation_id,),
            )
            return cursor.rowcount > 0

    def cleanup_expired_invitations(self) -> int:
        """Delete expired invitations."""
        cutoff = datetime.now(timezone.utc).isoformat()

        if self._backend is not None:
            # Count expired invitations first
            row = self._backend.fetch_one(
                """
                SELECT COUNT(*) FROM org_invitations
                WHERE status = 'pending'
                AND expires_at IS NOT NULL
                AND expires_at < ?
                """,
                (cutoff,),
            )
            count = row[0] if row else 0
            if count > 0:
                self._backend.execute_write(
                    """
                    DELETE FROM org_invitations
                    WHERE status = 'pending'
                    AND expires_at IS NOT NULL
                    AND expires_at < ?
                    """,
                    (cutoff,),
                )
                logger.info("Cleaned up %s expired invitations", count)
            return count

        with self._transaction() as cursor:
            cursor.execute(
                """
                DELETE FROM org_invitations
                WHERE status = 'pending'
                AND expires_at IS NOT NULL
                AND expires_at < ?
                """,
                (cutoff,),
            )
            count = cursor.rowcount
            if count > 0:
                logger.info("Cleaned up %s expired invitations", count)
            return count

    def _row_to_invitation(self, row: Any) -> OrganizationInvitation:
        """Convert database row (sqlite3.Row or dict) to OrganizationInvitation object."""
        # Handle both sqlite3.Row and dict
        has_accepted_by = (
            "accepted_by" in row.keys() if hasattr(row, "keys") else "accepted_by" in row
        )
        has_accepted_at = (
            "accepted_at" in row.keys() if hasattr(row, "keys") else "accepted_at" in row
        )

        return OrganizationInvitation(
            id=row["id"],
            org_id=row["org_id"],
            email=row["email"],
            role=row["role"],
            token=row["token"],
            invited_by=row["invited_by"],
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
            expires_at=cast(
                datetime,
                datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
            ),
            accepted_by=row["accepted_by"] if has_accepted_by else None,
            accepted_at=(
                datetime.fromisoformat(row["accepted_at"])
                if (has_accepted_at and row["accepted_at"])
                else None
            ),
        )

    def close(self) -> None:
        """Close database connection if we own it."""
        if self._backend is not None:
            self._backend.close()
            self._backend = None
        elif self._external_get_connection is None:
            # Close all tracked connections
            with self._connections_lock:
                for conn in self._connections:
                    try:
                        conn.close()
                    except (sqlite3.Error, OSError) as e:
                        logger.debug("Error closing connection: %s", e)
                self._connections.clear()


# =============================================================================
# Singleton Instance
# =============================================================================

_organization_store: OrganizationStore | None = None
_store_lock = threading.Lock()


def get_organization_store(
    db_path: str = "organizations.db",
    backend: str | None = None,
    database_url: str | None = None,
) -> OrganizationStore:
    """
    Get the singleton organization store instance.

    Uses unified preference order: Supabase → PostgreSQL → SQLite.

    Args:
        db_path: Path to SQLite database file (used when backend="sqlite")
        backend: Database backend ("sqlite", "postgresql", or "supabase")
        database_url: PostgreSQL connection URL (optional, auto-detected)

    Returns:
        Configured OrganizationStore instance
    """
    global _organization_store
    if _organization_store is None:
        with _store_lock:
            if _organization_store is None:
                # Use connection factory to determine backend and DSN
                from aragora.storage.connection_factory import (
                    resolve_database_config,
                    StorageBackendType,
                )

                # Check for explicit backend override, else use preference order
                store_backend = os.environ.get("ARAGORA_ORGANIZATION_STORE_BACKEND")
                if not store_backend and backend is None:
                    config = resolve_database_config("organization", allow_sqlite=True)
                    if config.backend_type in (
                        StorageBackendType.SUPABASE,
                        StorageBackendType.POSTGRES,
                    ):
                        backend = "postgresql"
                        database_url = database_url or config.dsn
                    else:
                        backend = "sqlite"
                elif store_backend:
                    backend = store_backend.lower()
                    if backend in ("postgres", "postgresql", "supabase"):
                        # Get DSN from connection factory
                        config = resolve_database_config("organization", allow_sqlite=True)
                        database_url = database_url or config.dsn
                        backend = "postgresql"

                _organization_store = OrganizationStore(
                    db_path=db_path,
                    backend=backend,
                    database_url=database_url,
                )

                # Enforce distributed storage in production
                if _organization_store.backend_type == "sqlite":
                    from aragora.storage.production_guards import (
                        require_distributed_store,
                        StorageMode,
                    )

                    require_distributed_store(
                        "organization_store",
                        StorageMode.SQLITE,
                        "Organization data must use distributed storage in production. "
                        "Configure Supabase or PostgreSQL.",
                    )
    return _organization_store


def reset_organization_store() -> None:
    """Reset the singleton store (for testing)."""
    global _organization_store
    with _store_lock:
        if _organization_store is not None:
            _organization_store.close()
            _organization_store = None
