"""
PostgresUserStore - Security, OAuth, audit, invitations, and admin operations mixin.

Extracted from postgres_store.py for modularity.
Provides OAuth provider linking, audit logging, organization invitations,
account lockout, and admin statistics.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from aragora.billing.models import Organization, OrganizationInvitation, User
from aragora.utils.async_utils import run_async

logger = logging.getLogger(__name__)


class SecurityOperationsMixin:
    """Mixin providing security, OAuth, audit, invitation, and admin operations."""

    if TYPE_CHECKING:
        _pool: Any
        _AUDIT_LOG_COLUMNS: str
        _INVITATION_COLUMNS: str
        _ORG_COLUMNS: str
        _USER_COLUMNS: str
        _row_to_user: Any
        _row_to_org: Any
        get_user_by_id_async: Any
        LOCKOUT_THRESHOLD_1: int
        LOCKOUT_THRESHOLD_2: int
        LOCKOUT_THRESHOLD_3: int
        LOCKOUT_DURATION_1: Any
        LOCKOUT_DURATION_2: Any
        LOCKOUT_DURATION_3: Any

    # =========================================================================
    # OAuth Provider Operations
    # =========================================================================

    def link_oauth_provider(
        self,
        user_id: str,
        provider: str,
        provider_user_id: str,
        email: str | None = None,
    ) -> bool:
        """Link an OAuth provider to a user account (sync wrapper)."""
        return run_async(self.link_oauth_provider_async(user_id, provider, provider_user_id, email))

    async def link_oauth_provider_async(
        self,
        user_id: str,
        provider: str,
        provider_user_id: str,
        email: str | None = None,
    ) -> bool:
        """Link an OAuth provider asynchronously."""
        async with self._pool.acquire() as conn:
            try:
                await conn.execute(
                    """INSERT INTO oauth_providers (user_id, provider, provider_user_id, email, linked_at)
                       VALUES ($1, $2, $3, $4, $5)
                       ON CONFLICT (provider, provider_user_id) DO NOTHING""",
                    user_id,
                    provider,
                    provider_user_id,
                    email,
                    datetime.now(timezone.utc),
                )
                return True
            except Exception as e:  # noqa: BLE001 - Database errors return False
                logger.debug(
                    "Failed to link OAuth provider %s for user %s: %s", provider, user_id, e
                )
                return False

    def unlink_oauth_provider(self, user_id: str, provider: str) -> bool:
        """Unlink an OAuth provider from a user account (sync wrapper)."""
        return run_async(self.unlink_oauth_provider_async(user_id, provider))

    async def unlink_oauth_provider_async(self, user_id: str, provider: str) -> bool:
        """Unlink an OAuth provider asynchronously."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM oauth_providers WHERE user_id = $1 AND provider = $2",
                user_id,
                provider,
            )
            return result != "DELETE 0"

    def get_user_by_oauth(self, provider: str, provider_user_id: str) -> User | None:
        """Get user by OAuth provider ID (sync wrapper)."""
        return run_async(self.get_user_by_oauth_async(provider, provider_user_id))

    async def get_user_by_oauth_async(self, provider: str, provider_user_id: str) -> User | None:
        """Get user by OAuth provider ID asynchronously."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT user_id FROM oauth_providers WHERE provider = $1 AND provider_user_id = $2",
                provider,
                provider_user_id,
            )
            if row:
                return await self.get_user_by_id_async(row["user_id"])
            return None

    def get_user_oauth_providers(self, user_id: str) -> list[dict]:
        """Get all OAuth providers linked to a user (sync wrapper)."""
        return run_async(self.get_user_oauth_providers_async(user_id))

    async def get_user_oauth_providers_async(self, user_id: str) -> list[dict]:
        """Get all OAuth providers asynchronously."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT provider, provider_user_id, email, linked_at FROM oauth_providers WHERE user_id = $1",
                user_id,
            )
            return [
                {
                    "provider": row["provider"],
                    "provider_user_id": row["provider_user_id"],
                    "email": row["email"],
                    "linked_at": row["linked_at"].isoformat() if row["linked_at"] else None,
                }
                for row in rows
            ]

    # =========================================================================
    # Audit Logging Operations
    # =========================================================================

    def log_audit_event(
        self,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
        user_id: str | None = None,
        org_id: str | None = None,
        old_value: dict | None = None,
        new_value: dict | None = None,
        metadata: dict | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> int:
        """Log an audit event (sync wrapper)."""
        return run_async(
            self.log_audit_event_async(
                action,
                resource_type,
                resource_id,
                user_id,
                org_id,
                old_value,
                new_value,
                metadata,
                ip_address,
                user_agent,
            )
        )

    async def log_audit_event_async(
        self,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
        user_id: str | None = None,
        org_id: str | None = None,
        old_value: dict | None = None,
        new_value: dict | None = None,
        metadata: dict | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> int:
        """Log an audit event asynchronously."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO audit_log
                   (timestamp, user_id, org_id, action, resource_type, resource_id,
                    old_value, new_value, metadata, ip_address, user_agent)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                   RETURNING id""",
                datetime.now(timezone.utc),
                user_id,
                org_id,
                action,
                resource_type,
                resource_id,
                json.dumps(old_value) if old_value else None,
                json.dumps(new_value) if new_value else None,
                json.dumps(metadata or {}),
                ip_address,
                user_agent,
            )
            return row["id"] if row else 0

    def get_audit_log(
        self,
        org_id: str | None = None,
        user_id: str | None = None,
        action: str | None = None,
        resource_type: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Query audit log entries (sync wrapper)."""
        return run_async(
            self.get_audit_log_async(
                org_id, user_id, action, resource_type, since, until, limit, offset
            )
        )

    async def get_audit_log_async(
        self,
        org_id: str | None = None,
        user_id: str | None = None,
        action: str | None = None,
        resource_type: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Query audit log entries asynchronously."""
        # column name interpolation, parameterized
        query = f"SELECT {self._AUDIT_LOG_COLUMNS} FROM audit_log WHERE 1=1"
        params: list[Any] = []
        param_idx = 1

        if org_id:
            query += f" AND org_id = ${param_idx}"
            params.append(org_id)
            param_idx += 1
        if user_id:
            query += f" AND user_id = ${param_idx}"
            params.append(user_id)
            param_idx += 1
        if action:
            query += f" AND action = ${param_idx}"
            params.append(action)
            param_idx += 1
        if resource_type:
            query += f" AND resource_type = ${param_idx}"
            params.append(resource_type)
            param_idx += 1
        if since:
            query += f" AND timestamp >= ${param_idx}"
            params.append(since)
            param_idx += 1
        if until:
            query += f" AND timestamp <= ${param_idx}"
            params.append(until)
            param_idx += 1

        query += f" ORDER BY timestamp DESC LIMIT ${param_idx} OFFSET ${param_idx + 1}"
        params.extend([limit, offset])

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [
                {
                    "id": row["id"],
                    "timestamp": row["timestamp"].isoformat() if row["timestamp"] else None,
                    "user_id": row["user_id"],
                    "org_id": row["org_id"],
                    "action": row["action"],
                    "resource_type": row["resource_type"],
                    "resource_id": row["resource_id"],
                    "old_value": json.loads(row["old_value"]) if row["old_value"] else None,
                    "new_value": json.loads(row["new_value"]) if row["new_value"] else None,
                    "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                    "ip_address": row["ip_address"],
                    "user_agent": row["user_agent"],
                }
                for row in rows
            ]

    def get_audit_log_count(
        self,
        org_id: str | None = None,
        user_id: str | None = None,
        action: str | None = None,
        resource_type: str | None = None,
    ) -> int:
        """Get count of audit log entries (sync wrapper)."""
        return run_async(self.get_audit_log_count_async(org_id, user_id, action, resource_type))

    async def get_audit_log_count_async(
        self,
        org_id: str | None = None,
        user_id: str | None = None,
        action: str | None = None,
        resource_type: str | None = None,
    ) -> int:
        """Get count of audit log entries asynchronously."""
        query = "SELECT COUNT(*) FROM audit_log WHERE 1=1"
        params: list[Any] = []
        param_idx = 1

        if org_id:
            query += f" AND org_id = ${param_idx}"
            params.append(org_id)
            param_idx += 1
        if user_id:
            query += f" AND user_id = ${param_idx}"
            params.append(user_id)
            param_idx += 1
        if action:
            query += f" AND action = ${param_idx}"
            params.append(action)
            param_idx += 1
        if resource_type:
            query += f" AND resource_type = ${param_idx}"
            params.append(resource_type)
            param_idx += 1

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, *params)
            return row[0] if row else 0

    # =========================================================================
    # Organization Invitations
    # =========================================================================

    def create_invitation(self, invitation: OrganizationInvitation) -> bool:
        """Create a new organization invitation (sync wrapper)."""
        return run_async(self.create_invitation_async(invitation))

    async def create_invitation_async(self, invitation: OrganizationInvitation) -> bool:
        """Create a new organization invitation asynchronously."""
        async with self._pool.acquire() as conn:
            try:
                await conn.execute(
                    """INSERT INTO org_invitations
                       (id, org_id, email, role, token, invited_by, status, created_at, expires_at)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
                    invitation.id,
                    invitation.org_id,
                    invitation.email,
                    invitation.role,
                    invitation.token,
                    invitation.invited_by,
                    invitation.status,
                    invitation.created_at,
                    invitation.expires_at,
                )
                return True
            except Exception as e:  # noqa: BLE001 - Database errors return False
                logger.debug("Failed to create invitation for %s: %s", invitation.email, e)
                return False

    def get_invitation_by_id(self, invitation_id: str) -> OrganizationInvitation | None:
        """Get invitation by ID (sync wrapper)."""
        return run_async(self.get_invitation_by_id_async(invitation_id))

    async def get_invitation_by_id_async(self, invitation_id: str) -> OrganizationInvitation | None:
        """Get invitation by ID asynchronously."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                # column name interpolation, parameterized
                f"SELECT {self._INVITATION_COLUMNS} FROM org_invitations WHERE id = $1",
                invitation_id,
            )
            if row:
                return self._row_to_invitation(row)
            return None

    def get_invitation_by_token(self, token: str) -> OrganizationInvitation | None:
        """Get invitation by token (sync wrapper)."""
        return run_async(self.get_invitation_by_token_async(token))

    async def get_invitation_by_token_async(self, token: str) -> OrganizationInvitation | None:
        """Get invitation by token asynchronously."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                # column name interpolation, parameterized
                f"SELECT {self._INVITATION_COLUMNS} FROM org_invitations WHERE token = $1",
                token,
            )
            if row:
                return self._row_to_invitation(row)
            return None

    def get_invitation_by_email(self, org_id: str, email: str) -> OrganizationInvitation | None:
        """Get pending invitation by org and email (sync wrapper)."""
        return run_async(self.get_invitation_by_email_async(org_id, email))

    async def get_invitation_by_email_async(
        self, org_id: str, email: str
    ) -> OrganizationInvitation | None:
        """Get pending invitation asynchronously."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                # column name interpolation, parameterized
                f"""SELECT {self._INVITATION_COLUMNS} FROM org_invitations
                   WHERE org_id = $1 AND email = $2 AND status = 'pending'""",
                org_id,
                email,
            )
            if row:
                return self._row_to_invitation(row)
            return None

    def get_invitations_for_org(self, org_id: str) -> list[OrganizationInvitation]:
        """Get all invitations for an organization (sync wrapper)."""
        return run_async(self.get_invitations_for_org_async(org_id))

    async def get_invitations_for_org_async(self, org_id: str) -> list[OrganizationInvitation]:
        """Get all invitations for an organization asynchronously."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                # column name interpolation, parameterized
                f"SELECT {self._INVITATION_COLUMNS} FROM org_invitations WHERE org_id = $1 ORDER BY created_at DESC",
                org_id,
            )
            return [self._row_to_invitation(row) for row in rows]

    def get_pending_invitations_by_email(self, email: str) -> list[OrganizationInvitation]:
        """Get all pending invitations for an email address (sync wrapper)."""
        return run_async(self.get_pending_invitations_by_email_async(email))

    async def get_pending_invitations_by_email_async(
        self, email: str
    ) -> list[OrganizationInvitation]:
        """Get all pending invitations asynchronously."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                # column name interpolation, parameterized
                f"""SELECT {self._INVITATION_COLUMNS} FROM org_invitations
                   WHERE email = $1 AND status = 'pending' ORDER BY created_at DESC""",
                email,
            )
            return [self._row_to_invitation(row) for row in rows]

    def update_invitation_status(
        self,
        invitation_id: str,
        status: str,
        accepted_at: datetime | None = None,
    ) -> bool:
        """Update invitation status (sync wrapper)."""
        return run_async(self.update_invitation_status_async(invitation_id, status, accepted_at))

    async def update_invitation_status_async(
        self,
        invitation_id: str,
        status: str,
        accepted_at: datetime | None = None,
    ) -> bool:
        """Update invitation status asynchronously."""
        async with self._pool.acquire() as conn:
            if accepted_at:
                result = await conn.execute(
                    "UPDATE org_invitations SET status = $1, accepted_at = $2 WHERE id = $3",
                    status,
                    accepted_at,
                    invitation_id,
                )
            else:
                result = await conn.execute(
                    "UPDATE org_invitations SET status = $1 WHERE id = $2",
                    status,
                    invitation_id,
                )
            return result != "UPDATE 0"

    def delete_invitation(self, invitation_id: str) -> bool:
        """Delete an invitation (sync wrapper)."""
        return run_async(self.delete_invitation_async(invitation_id))

    async def delete_invitation_async(self, invitation_id: str) -> bool:
        """Delete an invitation asynchronously."""
        async with self._pool.acquire() as conn:
            result = await conn.execute("DELETE FROM org_invitations WHERE id = $1", invitation_id)
            return result != "DELETE 0"

    def cleanup_expired_invitations(self) -> int:
        """Mark expired invitations as expired (sync wrapper)."""
        return run_async(self.cleanup_expired_invitations_async())

    async def cleanup_expired_invitations_async(self) -> int:
        """Mark expired invitations asynchronously."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """UPDATE org_invitations SET status = 'expired'
                   WHERE status = 'pending' AND expires_at < $1""",
                datetime.now(timezone.utc),
            )
            parts = result.split()
            return int(parts[1]) if len(parts) > 1 else 0

    def _row_to_invitation(self, row: Any) -> OrganizationInvitation:
        """Convert database row to OrganizationInvitation object."""
        return OrganizationInvitation(
            id=row["id"],
            org_id=row["org_id"],
            email=row["email"],
            role=row["role"] or "member",
            token=row["token"],
            invited_by=row["invited_by"],
            status=row["status"] or "pending",
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            accepted_at=row["accepted_at"],
        )

    # =========================================================================
    # Account Lockout Methods
    # =========================================================================

    def is_account_locked(self, email: str) -> tuple[bool, datetime | None, int]:
        """Check if an account is currently locked (sync wrapper)."""
        return run_async(self.is_account_locked_async(email))

    async def is_account_locked_async(self, email: str) -> tuple[bool, datetime | None, int]:
        """Check if an account is currently locked asynchronously."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT failed_login_attempts, lockout_until FROM users WHERE email = $1",
                email,
            )
            if not row:
                return False, None, 0

            lockout_until = row["lockout_until"]
            attempts = row["failed_login_attempts"] or 0

            if lockout_until and lockout_until > datetime.now(timezone.utc):
                return True, lockout_until, attempts
            return False, None, attempts

    def record_failed_login(self, email: str) -> tuple[int, datetime | None]:
        """Record a failed login attempt (sync wrapper)."""
        return run_async(self.record_failed_login_async(email))

    async def record_failed_login_async(self, email: str) -> tuple[int, datetime | None]:
        """Record a failed login attempt asynchronously."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE users SET
                   failed_login_attempts = failed_login_attempts + 1,
                   last_failed_login_at = $1,
                   updated_at = $1
                   WHERE email = $2
                   RETURNING failed_login_attempts""",
                datetime.now(timezone.utc),
                email,
            )
            if not row:
                return 0, None

            attempts = row["failed_login_attempts"]
            lockout_until = None

            # Determine lockout duration based on attempts
            if attempts >= self.LOCKOUT_THRESHOLD_3:
                lockout_until = datetime.now(timezone.utc) + self.LOCKOUT_DURATION_3
            elif attempts >= self.LOCKOUT_THRESHOLD_2:
                lockout_until = datetime.now(timezone.utc) + self.LOCKOUT_DURATION_2
            elif attempts >= self.LOCKOUT_THRESHOLD_1:
                lockout_until = datetime.now(timezone.utc) + self.LOCKOUT_DURATION_1

            if lockout_until:
                await conn.execute(
                    "UPDATE users SET lockout_until = $1 WHERE email = $2",
                    lockout_until,
                    email,
                )

            return attempts, lockout_until

    def reset_failed_login_attempts(self, email: str) -> bool:
        """Reset failed login attempts (sync wrapper)."""
        return run_async(self.reset_failed_login_attempts_async(email))

    async def reset_failed_login_attempts_async(self, email: str) -> bool:
        """Reset failed login attempts asynchronously."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """UPDATE users SET
                   failed_login_attempts = 0, lockout_until = NULL,
                   last_failed_login_at = NULL, updated_at = $1
                   WHERE email = $2""",
                datetime.now(timezone.utc),
                email,
            )
            return result != "UPDATE 0"

    def get_lockout_info(self, email: str) -> dict:
        """Get detailed lockout information (sync wrapper)."""
        return run_async(self.get_lockout_info_async(email))

    async def get_lockout_info_async(self, email: str) -> dict:
        """Get detailed lockout information asynchronously."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT failed_login_attempts, lockout_until, last_failed_login_at
                   FROM users WHERE email = $1""",
                email,
            )
            if not row:
                return {"exists": False}

            return {
                "exists": True,
                "failed_attempts": row["failed_login_attempts"] or 0,
                "lockout_until": row["lockout_until"].isoformat() if row["lockout_until"] else None,
                "last_failed_at": (
                    row["last_failed_login_at"].isoformat() if row["last_failed_login_at"] else None
                ),
                "is_locked": bool(
                    row["lockout_until"] and row["lockout_until"] > datetime.now(timezone.utc)
                ),
            }

    # =========================================================================
    # Admin Methods
    # =========================================================================

    def list_all_organizations(
        self,
        limit: int = 50,
        offset: int = 0,
        tier_filter: str | None = None,
    ) -> tuple[list[Organization], int]:
        """List all organizations with pagination (sync wrapper)."""
        return run_async(self.list_all_organizations_async(limit, offset, tier_filter))

    async def list_all_organizations_async(
        self,
        limit: int = 50,
        offset: int = 0,
        tier_filter: str | None = None,
    ) -> tuple[list[Organization], int]:
        """List all organizations asynchronously."""
        async with self._pool.acquire() as conn:
            if tier_filter:
                total_row = await conn.fetchrow(
                    "SELECT COUNT(*) FROM organizations WHERE tier = $1", tier_filter
                )
                rows = await conn.fetch(
                    # column name interpolation, parameterized
                    f"""SELECT {self._ORG_COLUMNS} FROM organizations WHERE tier = $1
                       ORDER BY created_at DESC LIMIT $2 OFFSET $3""",
                    tier_filter,
                    limit,
                    offset,
                )
            else:
                total_row = await conn.fetchrow("SELECT COUNT(*) FROM organizations")
                rows = await conn.fetch(
                    # column name interpolation, parameterized
                    f"""SELECT {self._ORG_COLUMNS} FROM organizations
                       ORDER BY created_at DESC LIMIT $1 OFFSET $2""",
                    limit,
                    offset,
                )

            total = total_row[0] if total_row else 0
            return [self._row_to_org(row) for row in rows], total

    def list_all_users(
        self,
        limit: int = 50,
        offset: int = 0,
        org_id_filter: str | None = None,
        role_filter: str | None = None,
        active_only: bool = False,
    ) -> tuple[list[User], int]:
        """List all users with pagination (sync wrapper)."""
        return run_async(
            self.list_all_users_async(limit, offset, org_id_filter, role_filter, active_only)
        )

    async def list_all_users_async(
        self,
        limit: int = 50,
        offset: int = 0,
        org_id_filter: str | None = None,
        role_filter: str | None = None,
        active_only: bool = False,
    ) -> tuple[list[User], int]:
        """List all users asynchronously."""
        # column name interpolation, parameterized
        query = f"SELECT {self._USER_COLUMNS} FROM users WHERE 1=1"
        count_query = "SELECT COUNT(*) FROM users WHERE 1=1"
        params: list[Any] = []
        param_idx = 1

        if org_id_filter:
            query += f" AND org_id = ${param_idx}"
            count_query += f" AND org_id = ${param_idx}"
            params.append(org_id_filter)
            param_idx += 1
        if role_filter:
            query += f" AND role = ${param_idx}"
            count_query += f" AND role = ${param_idx}"
            params.append(role_filter)
            param_idx += 1
        if active_only:
            query += " AND is_active = TRUE"
            count_query += " AND is_active = TRUE"

        async with self._pool.acquire() as conn:
            total_row = await conn.fetchrow(count_query, *params)
            total = total_row[0] if total_row else 0

            query += f" ORDER BY created_at DESC LIMIT ${param_idx} OFFSET ${param_idx + 1}"
            params.extend([limit, offset])
            rows = await conn.fetch(query, *params)

            return [self._row_to_user(row) for row in rows], total

    def get_admin_stats(self) -> dict:
        """Get system-wide statistics (sync wrapper)."""
        return run_async(self.get_admin_stats_async())

    async def get_admin_stats_async(self) -> dict:
        """Get system-wide statistics asynchronously."""
        async with self._pool.acquire() as conn:
            stats: dict[str, Any] = {}

            row = await conn.fetchrow("SELECT COUNT(*) FROM users")
            stats["total_users"] = row[0] if row else 0

            row = await conn.fetchrow("SELECT COUNT(*) FROM users WHERE is_active = TRUE")
            stats["active_users"] = row[0] if row else 0

            row = await conn.fetchrow("SELECT COUNT(*) FROM organizations")
            stats["total_organizations"] = row[0] if row else 0

            rows = await conn.fetch(
                "SELECT tier, COUNT(*) as count FROM organizations GROUP BY tier"
            )
            stats["tier_distribution"] = {row["tier"]: row["count"] for row in rows}

            row = await conn.fetchrow(
                "SELECT SUM(debates_used_this_month) as total FROM organizations"
            )
            stats["total_debates_this_month"] = row["total"] or 0 if row else 0

            row = await conn.fetchrow(
                "SELECT COUNT(*) FROM users WHERE last_login_at > NOW() - INTERVAL '1 day'"
            )
            stats["users_active_24h"] = row[0] if row else 0

            row = await conn.fetchrow(
                "SELECT COUNT(*) FROM users WHERE created_at > NOW() - INTERVAL '7 days'"
            )
            stats["new_users_7d"] = row[0] if row else 0

            row = await conn.fetchrow(
                "SELECT COUNT(*) FROM organizations WHERE created_at > NOW() - INTERVAL '7 days'"
            )
            stats["new_orgs_7d"] = row[0] if row else 0

            return stats
