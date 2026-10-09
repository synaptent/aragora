"""Tests for InvitationRepository handling of invitations without an expiry."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

from aragora.billing.models import OrganizationInvitation
from aragora.storage.repositories.invitations import InvitationRepository


@pytest.fixture
def repo() -> Iterator[InvitationRepository]:
    # Same nullable expires_at column as the users 001_initial migration.
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE org_invitations (
            id TEXT PRIMARY KEY,
            org_id TEXT NOT NULL,
            email TEXT NOT NULL,
            role TEXT DEFAULT 'member',
            token TEXT UNIQUE NOT NULL,
            invited_by TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT,
            accepted_by TEXT,
            accepted_at TEXT
        )
        """
    )

    @contextmanager
    def transaction() -> Iterator[sqlite3.Cursor]:
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        finally:
            cursor.close()

    yield InvitationRepository(transaction)
    conn.close()


def test_create_and_read_invitation_without_expiry(repo: InvitationRepository) -> None:
    invitation = OrganizationInvitation(
        org_id="org-1", email="legacy@example.com", invited_by="user-1", expires_at=None
    )

    assert repo.create_invitation(invitation) is True
    stored = repo.get_by_id(invitation.id)

    assert stored is not None
    assert stored.expires_at is None
    assert stored.is_pending is False


def test_null_expiry_row_in_lists(repo: InvitationRepository) -> None:
    invitation = OrganizationInvitation(
        org_id="org-1", email="legacy@example.com", invited_by="user-1", expires_at=None
    )
    repo.create_invitation(invitation)

    assert [inv.expires_at for inv in repo.get_for_org("org-1")] == [None]
    assert [inv.is_pending for inv in repo.get_pending_by_email("legacy@example.com")] == [False]
    by_token = repo.get_by_token(invitation.token)
    assert by_token is not None and by_token.is_expired is True


def test_dated_invitation_keeps_expiry(repo: InvitationRepository) -> None:
    expires_at = datetime.now(timezone.utc) + timedelta(days=2)
    invitation = OrganizationInvitation(
        org_id="org-1", email="dated@example.com", invited_by="user-1", expires_at=expires_at
    )
    repo.create_invitation(invitation)

    stored = repo.get_by_id(invitation.id)

    assert stored is not None
    assert stored.expires_at == expires_at
    assert stored.is_pending is True
