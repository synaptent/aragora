"""
InvitationRepository - Organization invitation management.

Extracted from UserStore for better modularity. Manages the lifecycle
of organization invitations including creation, lookup, and status updates.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from contextlib import AbstractContextManager
from collections.abc import Callable

if TYPE_CHECKING:
    from aragora.billing.models import OrganizationInvitation


class InvitationRepository:
    """
    Repository for organization invitation operations.

    This class manages the invitation lifecycle:
    - Creating invitations with secure tokens
    - Looking up invitations by ID, token, email, or organization
    - Updating invitation status (pending, accepted, expired, revoked)
    - Cleaning up expired invitations
    """

    # Explicit columns for SELECT queries - prevents SELECT * data exposure
    _INVITATION_COLUMNS = (
        "id, org_id, email, role, token, invited_by, status, "
        "created_at, expires_at, accepted_by, accepted_at"
    )

    def __init__(
        self, transaction_fn: Callable[[], AbstractContextManager[sqlite3.Cursor]]
    ) -> None:
        """
        Initialize the invitation repository.

        Args:
            transaction_fn: Function that returns a transaction context manager
                           with a cursor. This allows the repository to be
                           composed with the main UserStore's connection management.
        """
        self._transaction = transaction_fn

    def create_invitation(self, invitation: OrganizationInvitation) -> bool:
        """
        Create a new organization invitation.

        Args:
            invitation: OrganizationInvitation instance with all fields populated

        Returns:
            True if created successfully
        """
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO org_invitations
                (id, org_id, email, role, token, invited_by, status, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    invitation.id,
                    invitation.org_id,
                    invitation.email.lower(),
                    invitation.role,
                    invitation.token,
                    invitation.invited_by,
                    invitation.status,
                    invitation.created_at.isoformat(),
                    invitation.expires_at.isoformat() if invitation.expires_at else None,
                ),
            )
        return True

    def get_by_id(self, invitation_id: str) -> OrganizationInvitation | None:
        """Get invitation by ID."""
        with self._transaction() as cursor:
            cursor.execute(
                f"SELECT {self._INVITATION_COLUMNS} FROM org_invitations WHERE id = ?",  # noqa: S608 -- column name interpolation, parameterized
                (invitation_id,),
            )
            row = cursor.fetchone()
            return self._row_to_invitation(row) if row else None

    def get_by_token(self, token: str) -> OrganizationInvitation | None:
        """Get invitation by token."""
        with self._transaction() as cursor:
            cursor.execute(
                f"SELECT {self._INVITATION_COLUMNS} FROM org_invitations WHERE token = ?",  # noqa: S608 -- column name interpolation, parameterized
                (token,),
            )
            row = cursor.fetchone()
            return self._row_to_invitation(row) if row else None

    def get_by_email(self, org_id: str, email: str) -> OrganizationInvitation | None:
        """Get pending invitation by org and email."""
        with self._transaction() as cursor:
            cursor.execute(
                f"""
                SELECT {self._INVITATION_COLUMNS} FROM org_invitations
                WHERE org_id = ? AND email = ? AND status = 'pending'
                ORDER BY created_at DESC LIMIT 1
                """,  # noqa: S608 -- column name interpolation, parameterized
                (org_id, email.lower()),
            )
            row = cursor.fetchone()
            return self._row_to_invitation(row) if row else None

    def get_for_org(self, org_id: str) -> list[OrganizationInvitation]:
        """Get all invitations for an organization."""
        with self._transaction() as cursor:
            cursor.execute(
                f"SELECT {self._INVITATION_COLUMNS} FROM org_invitations WHERE org_id = ? ORDER BY created_at DESC",  # noqa: S608 -- column name interpolation, parameterized
                (org_id,),
            )
            return [self._row_to_invitation(row) for row in cursor.fetchall()]

    def get_pending_by_email(self, email: str) -> list[OrganizationInvitation]:
        """Get all pending invitations for an email address."""
        with self._transaction() as cursor:
            cursor.execute(
                f"""
                SELECT {self._INVITATION_COLUMNS} FROM org_invitations
                WHERE email = ? AND status = 'pending'
                ORDER BY created_at DESC
                """,  # noqa: S608 -- column name interpolation, parameterized
                (email.lower(),),
            )
            return [self._row_to_invitation(row) for row in cursor.fetchall()]

    def update_status(
        self,
        invitation_id: str,
        status: str,
        accepted_at: datetime | None = None,
    ) -> bool:
        """
        Update invitation status.

        Args:
            invitation_id: Invitation ID
            status: New status (pending, accepted, expired, revoked)
            accepted_at: Timestamp when accepted (for accepted status)

        Returns:
            True if updated
        """
        with self._transaction() as cursor:
            if accepted_at:
                cursor.execute(
                    """
                    UPDATE org_invitations
                    SET status = ?, accepted_at = ?
                    WHERE id = ?
                    """,
                    (status, accepted_at.isoformat(), invitation_id),
                )
            else:
                cursor.execute(
                    "UPDATE org_invitations SET status = ? WHERE id = ?",
                    (status, invitation_id),
                )
            return cursor.rowcount > 0

    def delete(self, invitation_id: str) -> bool:
        """Delete an invitation."""
        with self._transaction() as cursor:
            cursor.execute(
                "DELETE FROM org_invitations WHERE id = ?",
                (invitation_id,),
            )
            return cursor.rowcount > 0

    def cleanup_expired(self) -> int:
        """
        Mark expired invitations as expired.

        Returns:
            Number of invitations marked as expired
        """
        with self._transaction() as cursor:
            cursor.execute(
                """
                UPDATE org_invitations
                SET status = 'expired'
                WHERE status = 'pending' AND expires_at < ?
                """,
                (datetime.now(timezone.utc).isoformat(),),
            )
            return cursor.rowcount

    @staticmethod
    def _row_to_invitation(row: sqlite3.Row) -> OrganizationInvitation:
        """Convert database row to OrganizationInvitation object."""
        from aragora.billing.models import OrganizationInvitation

        return OrganizationInvitation(
            id=row["id"],
            org_id=row["org_id"],
            email=row["email"],
            role=row["role"],
            token=row["token"],
            invited_by=row["invited_by"],
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
            accepted_at=datetime.fromisoformat(row["accepted_at"]) if row["accepted_at"] else None,
        )
