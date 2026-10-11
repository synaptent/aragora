"""
Tests for OrganizationStore - Database backend for organization and invitation persistence.

Tests cover:
- OrganizationStore initialization with SQLite backend
- Organization CRUD operations (create, read, update, reset usage)
- Organization queries (by ID, slug, Stripe customer, subscription)
- Invitation management (create, get, update status, delete)
- Invitation queries (by ID, token, email, org)
- Pending invitation retrieval
- Expired invitation cleanup
- User-to-org operations (add/remove user)
- Data integrity and persistence
- Factory functions (get_organization_store, reset_organization_store)
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aragora.billing.models import Organization, OrganizationInvitation, SubscriptionTier
from aragora.storage.organization_store import (
    OrganizationStore,
    get_organization_store,
    reset_organization_store,
)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def temp_db_path():
    """Create a temporary database path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "test_organizations.db"


@pytest.fixture
def org_store(temp_db_path):
    """Create an organization store for testing with schema initialized."""
    # Initialize schema directly in SQLite
    conn = sqlite3.connect(str(temp_db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS organizations (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            tier TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            stripe_customer_id TEXT,
            stripe_subscription_id TEXT,
            debates_used_this_month INTEGER DEFAULT 0,
            billing_cycle_start TEXT NOT NULL,
            settings TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS org_invitations (
            id TEXT PRIMARY KEY,
            org_id TEXT NOT NULL,
            email TEXT NOT NULL,
            role TEXT NOT NULL,
            token TEXT UNIQUE NOT NULL,
            invited_by TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            expires_at TEXT,
            accepted_by TEXT,
            accepted_at TEXT
        )
    """)
    conn.commit()
    conn.close()

    store = OrganizationStore(db_path=temp_db_path, backend="sqlite")
    yield store
    store.close()


@pytest.fixture
def sample_org_data():
    """Create sample organization data."""
    return {
        "name": "Test Organization",
        "owner_id": "user-001",
        "slug": "test-org",
        "tier": SubscriptionTier.FREE,
    }


@pytest.fixture
def populated_store(org_store):
    """Organization store with sample data."""
    # Create organizations
    org1 = org_store.create_organization(
        name="Organization One",
        owner_id="user-001",
        slug="org-one",
        tier=SubscriptionTier.FREE,
    )

    org2 = org_store.create_organization(
        name="Organization Two",
        owner_id="user-002",
        slug="org-two",
        tier=SubscriptionTier.PROFESSIONAL,
    )

    # Update one org with Stripe IDs
    org_store.update_organization(
        org_id=org1.id,
        stripe_customer_id="cus_test123",
        stripe_subscription_id="sub_test456",
    )

    # Create invitations
    invite1 = OrganizationInvitation(
        org_id=org1.id,
        email="invite1@example.com",
        role="member",
        invited_by="user-001",
    )
    org_store.create_invitation(invite1)

    invite2 = OrganizationInvitation(
        org_id=org1.id,
        email="invite2@example.com",
        role="admin",
        invited_by="user-001",
    )
    org_store.create_invitation(invite2)

    invite3 = OrganizationInvitation(
        org_id=org2.id,
        email="invite3@example.com",
        role="member",
        invited_by="user-002",
    )
    org_store.create_invitation(invite3)

    return org_store, org1, org2, invite1, invite2, invite3


# =============================================================================
# OrganizationStore Initialization Tests
# =============================================================================


class TestOrganizationStoreInit:
    """Tests for OrganizationStore initialization."""

    def test_init_with_sqlite_backend(self, temp_db_path):
        """Should initialize with SQLite backend."""
        # Create schema first
        conn = sqlite3.connect(str(temp_db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS organizations (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                slug TEXT UNIQUE NOT NULL,
                tier TEXT NOT NULL,
                owner_id TEXT NOT NULL,
                stripe_customer_id TEXT,
                stripe_subscription_id TEXT,
                debates_used_this_month INTEGER DEFAULT 0,
                billing_cycle_start TEXT NOT NULL,
                settings TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()

        store = OrganizationStore(db_path=temp_db_path, backend="sqlite")

        assert store.backend_type == "sqlite"

        store.close()

    def test_init_postgresql_requires_url(self, temp_db_path):
        """PostgreSQL backend requires database_url."""
        with pytest.raises(ValueError, match="PostgreSQL backend requires database_url"):
            OrganizationStore(db_path=temp_db_path, backend="postgresql")

    def test_init_with_external_connection(self, temp_db_path):
        """Should accept external connection factory."""
        # Create schema first
        conn = sqlite3.connect(str(temp_db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE IF NOT EXISTS organizations (
                id TEXT PRIMARY KEY, name TEXT, slug TEXT, tier TEXT, owner_id TEXT,
                stripe_customer_id TEXT, stripe_subscription_id TEXT,
                debates_used_this_month INTEGER, billing_cycle_start TEXT,
                settings TEXT, created_at TEXT, updated_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS org_invitations (
                id TEXT PRIMARY KEY, org_id TEXT, email TEXT, role TEXT, token TEXT,
                invited_by TEXT, status TEXT, created_at TEXT, expires_at TEXT,
                accepted_by TEXT, accepted_at TEXT
            )
        """)
        conn.commit()

        get_conn_called = []

        def get_connection():
            get_conn_called.append(True)
            return conn

        store = OrganizationStore(
            db_path=temp_db_path, get_connection=get_connection, backend="sqlite"
        )

        # Operations should use external connection
        store.create_organization(
            name="External Test",
            owner_id="user-ext",
            slug="external-test",
        )

        assert len(get_conn_called) > 0
        conn.close()


# =============================================================================
# Organization CRUD Tests
# =============================================================================


class TestOrganizationCRUD:
    """Tests for organization CRUD operations."""

    def test_create_organization(self, org_store, sample_org_data):
        """Test create organization returns Organization object."""
        org = org_store.create_organization(**sample_org_data)

        assert org is not None
        assert org.name == "Test Organization"
        assert org.owner_id == "user-001"
        assert org.slug == "test-org"
        assert org.tier == SubscriptionTier.FREE
        assert org.id is not None

    def test_create_organization_auto_generates_slug(self, org_store):
        """Should auto-generate slug if not provided."""
        org = org_store.create_organization(name="My New Organization", owner_id="user-002")

        assert org.slug.startswith("my-new-organization")

    def test_create_organization_unique_slug_on_collision(self, org_store):
        """Should generate unique slug on collision."""
        org1 = org_store.create_organization(
            name="Duplicate Name", owner_id="user-001", slug="duplicate"
        )

        org2 = org_store.create_organization(name="Duplicate Name", owner_id="user-002")

        assert org1.slug != org2.slug
        assert org2.slug.startswith("duplicate-")

    def test_get_organization_by_id(self, org_store, sample_org_data):
        """Test retrieve organization by ID."""
        created = org_store.create_organization(**sample_org_data)

        retrieved = org_store.get_organization_by_id(created.id)

        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.name == "Test Organization"

    def test_get_organization_by_id_nonexistent(self, org_store):
        """Should return None for nonexistent ID."""
        result = org_store.get_organization_by_id("nonexistent-id")
        assert result is None

    def test_get_organization_by_slug(self, org_store, sample_org_data):
        """Test retrieve organization by slug."""
        created = org_store.create_organization(**sample_org_data)

        retrieved = org_store.get_organization_by_slug("test-org")

        assert retrieved is not None
        assert retrieved.slug == "test-org"
        assert retrieved.id == created.id

    def test_get_organization_by_slug_nonexistent(self, org_store):
        """Should return None for nonexistent slug."""
        result = org_store.get_organization_by_slug("nonexistent-slug")
        assert result is None

    def test_get_organization_by_stripe_customer(self, populated_store):
        """Test retrieve organization by Stripe customer ID."""
        store, org1, org2, *_ = populated_store

        retrieved = store.get_organization_by_stripe_customer("cus_test123")

        assert retrieved is not None
        assert retrieved.id == org1.id

    def test_get_organization_by_stripe_customer_nonexistent(self, org_store):
        """Should return None for nonexistent Stripe customer."""
        result = org_store.get_organization_by_stripe_customer("cus_nonexistent")
        assert result is None

    def test_get_organization_by_subscription(self, populated_store):
        """Test retrieve organization by Stripe subscription ID."""
        store, org1, org2, *_ = populated_store

        retrieved = store.get_organization_by_subscription("sub_test456")

        assert retrieved is not None
        assert retrieved.id == org1.id

    def test_get_organization_by_subscription_nonexistent(self, org_store):
        """Should return None for nonexistent subscription."""
        result = org_store.get_organization_by_subscription("sub_nonexistent")
        assert result is None


# =============================================================================
# Organization Update Tests
# =============================================================================


class TestOrganizationUpdate:
    """Tests for organization update operations."""

    def test_update_organization_name(self, org_store, sample_org_data):
        """Test update organization name."""
        org = org_store.create_organization(**sample_org_data)

        result = org_store.update_organization(org.id, name="Updated Name")

        assert result is True

        updated = org_store.get_organization_by_id(org.id)
        assert updated.name == "Updated Name"

    def test_update_organization_tier(self, org_store, sample_org_data):
        """Test update organization tier."""
        org = org_store.create_organization(**sample_org_data)

        result = org_store.update_organization(org.id, tier=SubscriptionTier.PROFESSIONAL)

        assert result is True

        updated = org_store.get_organization_by_id(org.id)
        assert updated.tier == SubscriptionTier.PROFESSIONAL

    def test_update_organization_stripe_ids(self, org_store, sample_org_data):
        """Test update Stripe customer and subscription IDs."""
        org = org_store.create_organization(**sample_org_data)

        result = org_store.update_organization(
            org.id, stripe_customer_id="cus_new123", stripe_subscription_id="sub_new456"
        )

        assert result is True

        updated = org_store.get_organization_by_id(org.id)
        assert updated.stripe_customer_id == "cus_new123"
        assert updated.stripe_subscription_id == "sub_new456"

    def test_update_organization_settings(self, org_store, sample_org_data):
        """Test update organization settings."""
        org = org_store.create_organization(**sample_org_data)

        new_settings = {"feature_flags": {"dark_mode": True}, "max_users": 50}
        result = org_store.update_organization(org.id, settings=new_settings)

        assert result is True

        updated = org_store.get_organization_by_id(org.id)
        assert updated.settings["feature_flags"]["dark_mode"] is True
        assert updated.settings["max_users"] == 50

    def test_update_organization_multiple_fields(self, org_store, sample_org_data):
        """Test update multiple fields at once."""
        org = org_store.create_organization(**sample_org_data)

        result = org_store.update_organization(
            org.id, name="New Name", tier=SubscriptionTier.ENTERPRISE, debates_used_this_month=10
        )

        assert result is True

        updated = org_store.get_organization_by_id(org.id)
        assert updated.name == "New Name"
        assert updated.tier == SubscriptionTier.ENTERPRISE
        assert updated.debates_used_this_month == 10

    def test_update_organization_nonexistent(self, org_store):
        """Should return False for nonexistent organization."""
        result = org_store.update_organization("nonexistent-id", name="New Name")
        assert result is False

    def test_update_organization_empty_fields(self, org_store, sample_org_data):
        """Should return False when no fields to update."""
        org = org_store.create_organization(**sample_org_data)

        result = org_store.update_organization(org.id)

        assert result is False

    def test_update_organization_invalid_field_ignored(self, org_store, sample_org_data):
        """Should ignore unknown fields."""
        org = org_store.create_organization(**sample_org_data)

        result = org_store.update_organization(org.id, invalid_field="value", name="Valid Update")

        assert result is True

        updated = org_store.get_organization_by_id(org.id)
        assert updated.name == "Valid Update"


# =============================================================================
# Organization Usage Tests
# =============================================================================


class TestOrganizationUsage:
    """Tests for organization usage tracking."""

    def test_reset_org_usage(self, org_store, sample_org_data):
        """Test reset monthly usage for organization."""
        org = org_store.create_organization(**sample_org_data)
        org_store.update_organization(org.id, debates_used_this_month=50)

        result = org_store.reset_org_usage(org.id)

        assert result is True

        updated = org_store.get_organization_by_id(org.id)
        assert updated.debates_used_this_month == 0

    def test_reset_org_usage_updates_billing_cycle(self, org_store, sample_org_data):
        """Should update billing cycle start when resetting usage."""
        org = org_store.create_organization(**sample_org_data)
        original_cycle = org.billing_cycle_start

        # Wait a moment to ensure timestamp difference
        import time

        time.sleep(0.01)

        org_store.reset_org_usage(org.id)

        updated = org_store.get_organization_by_id(org.id)
        assert updated.billing_cycle_start > original_cycle

    def test_reset_org_usage_nonexistent(self, org_store):
        """Should return False for nonexistent organization."""
        result = org_store.reset_org_usage("nonexistent-id")
        assert result is False


# =============================================================================
# Invitation CRUD Tests
# =============================================================================


class TestInvitationCRUD:
    """Tests for invitation CRUD operations."""

    def test_create_invitation(self, org_store, sample_org_data):
        """Test create invitation."""
        org = org_store.create_organization(**sample_org_data)

        invitation = OrganizationInvitation(
            org_id=org.id,
            email="test@example.com",
            role="member",
            invited_by="user-001",
        )

        result = org_store.create_invitation(invitation)

        assert result is True

    def test_get_invitation_by_id(self, populated_store):
        """Test retrieve invitation by ID."""
        store, org1, org2, invite1, *_ = populated_store

        retrieved = store.get_invitation_by_id(invite1.id)

        assert retrieved is not None
        assert retrieved.id == invite1.id
        assert retrieved.email == "invite1@example.com"

    def test_get_invitation_by_id_nonexistent(self, org_store):
        """Should return None for nonexistent ID."""
        result = org_store.get_invitation_by_id("nonexistent-id")
        assert result is None

    def test_get_invitation_by_token(self, populated_store):
        """Test retrieve invitation by token."""
        store, org1, org2, invite1, *_ = populated_store

        retrieved = store.get_invitation_by_token(invite1.token)

        assert retrieved is not None
        assert retrieved.token == invite1.token
        assert retrieved.email == invite1.email

    def test_get_invitation_by_token_nonexistent(self, org_store):
        """Should return None for nonexistent token."""
        result = org_store.get_invitation_by_token("nonexistent-token")
        assert result is None

    def test_get_invitation_by_email(self, populated_store):
        """Test retrieve invitation by email and org."""
        store, org1, org2, invite1, *_ = populated_store

        retrieved = store.get_invitation_by_email("invite1@example.com", org1.id, status="pending")

        assert retrieved is not None
        assert retrieved.email == "invite1@example.com"
        assert retrieved.org_id == org1.id

    def test_get_invitation_by_email_nonexistent(self, populated_store):
        """Should return None for nonexistent email in org."""
        store, org1, *_ = populated_store

        result = store.get_invitation_by_email("nonexistent@example.com", org1.id)
        assert result is None


# =============================================================================
# Invitation Query Tests
# =============================================================================


class TestInvitationQueries:
    """Tests for invitation query operations."""

    def test_get_invitations_for_org(self, populated_store):
        """Test get all invitations for an organization."""
        store, org1, org2, *_ = populated_store

        invitations = store.get_invitations_for_org(org1.id)

        assert len(invitations) == 2
        assert all(inv.org_id == org1.id for inv in invitations)

    def test_get_invitations_for_org_empty(self, org_store, sample_org_data):
        """Should return empty list for org with no invitations."""
        org = org_store.create_organization(**sample_org_data)

        invitations = org_store.get_invitations_for_org(org.id)

        assert invitations == []

    def test_get_invitations_ordered_by_created_at(self, org_store, sample_org_data):
        """Invitations should be ordered by created_at desc."""
        org = org_store.create_organization(**sample_org_data)

        # Create invitations with slight delay
        import time

        inv1 = OrganizationInvitation(
            org_id=org.id, email="first@example.com", role="member", invited_by="user-001"
        )
        org_store.create_invitation(inv1)

        time.sleep(0.01)

        inv2 = OrganizationInvitation(
            org_id=org.id, email="second@example.com", role="member", invited_by="user-001"
        )
        org_store.create_invitation(inv2)

        invitations = org_store.get_invitations_for_org(org.id)

        assert len(invitations) == 2
        # Most recent first
        assert invitations[0].email == "second@example.com"
        assert invitations[1].email == "first@example.com"

    def test_get_pending_invitations_by_email(self, populated_store):
        """Test get all pending invitations for an email."""
        store, org1, org2, invite1, invite2, invite3 = populated_store

        # Create another invitation for same email in different org
        invite4 = OrganizationInvitation(
            org_id=org2.id, email="invite1@example.com", role="member", invited_by="user-002"
        )
        store.create_invitation(invite4)

        invitations = store.get_pending_invitations_by_email("invite1@example.com")

        assert len(invitations) == 2


# =============================================================================
# Invitation Status Update Tests
# =============================================================================


class TestInvitationStatusUpdate:
    """Tests for invitation status updates."""

    def test_update_invitation_status(self, populated_store):
        """Test update invitation status."""
        store, org1, org2, invite1, *_ = populated_store

        result = store.update_invitation_status(invite1.id, "cancelled")

        assert result is True

        updated = store.get_invitation_by_id(invite1.id)
        assert updated.status == "cancelled"

    def test_update_invitation_status_to_accepted(self, populated_store):
        """Test update invitation to accepted with user info."""
        store, org1, org2, invite1, *_ = populated_store
        now = datetime.now(timezone.utc)

        result = store.update_invitation_status(
            invite1.id, "accepted", accepted_by="new-user-123", accepted_at=now
        )

        assert result is True

        updated = store.get_invitation_by_id(invite1.id)
        assert updated.status == "accepted"
        assert updated.accepted_by == "new-user-123"
        assert updated.accepted_at is not None

    def test_update_invitation_status_nonexistent(self, org_store):
        """Should return False for nonexistent invitation."""
        result = org_store.update_invitation_status("nonexistent-id", "cancelled")
        assert result is False


# =============================================================================
# Invitation Delete Tests
# =============================================================================


class TestInvitationDelete:
    """Tests for invitation deletion."""

    def test_delete_invitation(self, populated_store):
        """Test delete invitation."""
        store, org1, org2, invite1, *_ = populated_store

        result = store.delete_invitation(invite1.id)

        assert result is True

        deleted = store.get_invitation_by_id(invite1.id)
        assert deleted is None

    def test_delete_invitation_nonexistent(self, org_store):
        """Should return False for nonexistent invitation."""
        result = org_store.delete_invitation("nonexistent-id")
        assert result is False


# =============================================================================
# Expired Invitation Cleanup Tests
# =============================================================================


class TestExpiredInvitationCleanup:
    """Tests for expired invitation cleanup."""

    def test_cleanup_expired_invitations(self, org_store, sample_org_data):
        """Test cleanup removes expired invitations."""
        org = org_store.create_organization(**sample_org_data)

        # Create expired invitation directly in database
        import sqlite3

        conn = sqlite3.connect(str(org_store.db_path))
        past_date = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        conn.execute(
            """
            INSERT INTO org_invitations
            (id, org_id, email, role, token, invited_by, status, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "expired-inv",
                org.id,
                "expired@example.com",
                "member",
                "expired-token",
                "user-001",
                "pending",
                past_date,
                past_date,
            ),
        )
        conn.commit()
        conn.close()

        # Create valid invitation
        valid_inv = OrganizationInvitation(
            org_id=org.id, email="valid@example.com", role="member", invited_by="user-001"
        )
        org_store.create_invitation(valid_inv)

        count = org_store.cleanup_expired_invitations()

        assert count == 1

        # Verify expired is deleted
        deleted = org_store.get_invitation_by_id("expired-inv")
        assert deleted is None

        # Verify valid still exists
        valid = org_store.get_invitation_by_id(valid_inv.id)
        assert valid is not None

    def test_cleanup_expired_returns_zero_when_none_expired(self, populated_store):
        """Should return 0 when no invitations are expired."""
        store, *_ = populated_store

        count = store.cleanup_expired_invitations()

        assert count == 0


# =============================================================================
# NULL Expiry Row Tests
# =============================================================================


def _insert_null_expiry_invitation(store, org_id, inv_id="null-exp-inv", token="null-exp-token"):
    conn = sqlite3.connect(str(store.db_path))
    conn.execute(
        """
        INSERT INTO org_invitations
        (id, org_id, email, role, token, invited_by, status, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        (
            inv_id,
            org_id,
            "legacy@example.com",
            "member",
            token,
            "user-001",
            "pending",
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    conn.close()


class TestInvitationNullExpiry:
    """Rows whose expires_at is NULL load without errors and are never pending."""

    def test_sqlite_null_expiry_row_by_id(self, org_store, sample_org_data):
        org = org_store.create_organization(**sample_org_data)
        _insert_null_expiry_invitation(org_store, org.id)

        inv = org_store.get_invitation_by_id("null-exp-inv")

        assert inv is not None
        assert inv.expires_at is None
        assert inv.is_expired is True
        assert inv.is_pending is False
        assert inv.to_dict()["expires_at"] is None

    def test_sqlite_null_expiry_row_by_token_and_lists(self, org_store, sample_org_data):
        org = org_store.create_organization(**sample_org_data)
        _insert_null_expiry_invitation(org_store, org.id)

        by_token = org_store.get_invitation_by_token("null-exp-token")
        by_email = org_store.get_invitation_by_email("legacy@example.com", org.id)
        for_org = org_store.get_invitations_for_org(org.id)
        pending = org_store.get_pending_invitations_by_email("legacy@example.com")

        assert by_token is not None and by_token.expires_at is None
        assert by_email is not None and by_email.is_pending is False
        assert [inv.expires_at for inv in for_org] == [None]
        assert [inv.is_pending for inv in pending] == [False]

    def test_create_invitation_with_null_expiry_round_trips(self, org_store, sample_org_data):
        org = org_store.create_organization(**sample_org_data)
        invitation = OrganizationInvitation(
            org_id=org.id,
            email="noexpiry@example.com",
            invited_by="user-001",
            expires_at=None,
        )

        assert org_store.create_invitation(invitation) is True
        stored = org_store.get_invitation_by_id(invitation.id)

        assert stored is not None
        assert stored.expires_at is None
        assert stored.is_pending is False

    def test_dated_invitation_row_keeps_expiry(self, org_store, sample_org_data):
        org = org_store.create_organization(**sample_org_data)
        invitation = OrganizationInvitation(
            org_id=org.id, email="dated@example.com", invited_by="user-001"
        )
        org_store.create_invitation(invitation)

        stored = org_store.get_invitation_by_id(invitation.id)

        assert stored is not None
        assert stored.expires_at == invitation.expires_at
        assert stored.is_pending is True

    def test_cleanup_leaves_null_expiry_rows(self, org_store, sample_org_data):
        org = org_store.create_organization(**sample_org_data)
        _insert_null_expiry_invitation(org_store, org.id)

        assert org_store.cleanup_expired_invitations() == 0
        assert org_store.get_invitation_by_id("null-exp-inv") is not None

    def _postgres_row(self, store, *, expires_at, accepted_at=None):
        created_at = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        values = {
            "id": "pg-inv",
            "org_id": "org-pg",
            "email": "pg@example.com",
            "role": "member",
            "token": "pg-token",
            "invited_by": "user-001",
            "status": "pending",
            "created_at": created_at,
            "expires_at": expires_at,
            "accepted_by": None,
            "accepted_at": accepted_at,
        }
        columns = [c.strip() for c in store._INVITATION_COLUMNS.split(",")]
        return tuple(values[column] for column in columns)

    def test_postgres_row_with_null_expiry(self, org_store):
        row = self._postgres_row(org_store, expires_at=None)

        inv = org_store._row_to_invitation(org_store._invitation_tuple_to_dict(row))

        assert inv.created_at == datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        assert inv.expires_at is None
        assert inv.accepted_at is None
        assert inv.is_pending is False

    def test_postgres_row_with_datetime_expiry(self, org_store):
        expires_at = datetime.now(timezone.utc) + timedelta(days=3)
        accepted_at = datetime(2026, 1, 2, 8, 30, tzinfo=timezone.utc)
        row = self._postgres_row(org_store, expires_at=expires_at, accepted_at=accepted_at)

        inv = org_store._row_to_invitation(org_store._invitation_tuple_to_dict(row))

        assert inv.expires_at == expires_at
        assert inv.accepted_at == accepted_at
        assert inv.is_pending is True


# =============================================================================
# User-to-Org Operations Tests
# =============================================================================


class TestUserToOrgOperations:
    """Tests for user-to-org operations (add/remove)."""

    def test_add_user_to_org_requires_callback(self, org_store, sample_org_data):
        """Should raise ConfigurationError without update_user callback."""
        from aragora.exceptions import ConfigurationError

        org = org_store.create_organization(**sample_org_data)

        with pytest.raises(ConfigurationError, match="update_user callback required"):
            org_store.add_user_to_org("user-123", org.id)

    def test_add_user_to_org_with_callback(self, temp_db_path):
        """Should call update_user callback when adding user."""
        # Create schema
        conn = sqlite3.connect(str(temp_db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS organizations (
                id TEXT PRIMARY KEY, name TEXT, slug TEXT UNIQUE, tier TEXT, owner_id TEXT,
                stripe_customer_id TEXT, stripe_subscription_id TEXT,
                debates_used_this_month INTEGER, billing_cycle_start TEXT,
                settings TEXT, created_at TEXT, updated_at TEXT
            )
        """)
        conn.commit()
        conn.close()

        update_user_called = []

        def mock_update_user(user_id, **kwargs):
            update_user_called.append((user_id, kwargs))
            return True

        store = OrganizationStore(
            db_path=temp_db_path, update_user=mock_update_user, backend="sqlite"
        )

        org = store.create_organization(name="Test", owner_id="owner-1")
        result = store.add_user_to_org("user-123", org.id, role="member")

        assert result is True
        assert len(update_user_called) == 2  # Once for owner, once for add
        assert update_user_called[1] == ("user-123", {"org_id": org.id, "role": "member"})

        store.close()

    def test_remove_user_from_org_requires_callback(self, org_store, sample_org_data):
        """Should raise ConfigurationError without update_user callback."""
        from aragora.exceptions import ConfigurationError

        org = org_store.create_organization(**sample_org_data)

        with pytest.raises(ConfigurationError, match="update_user callback required"):
            org_store.remove_user_from_org("user-123")

    def test_remove_user_from_org_with_callback(self, temp_db_path):
        """Should call update_user callback when removing user."""
        # Create schema
        conn = sqlite3.connect(str(temp_db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS organizations (
                id TEXT PRIMARY KEY, name TEXT, slug TEXT UNIQUE, tier TEXT, owner_id TEXT,
                stripe_customer_id TEXT, stripe_subscription_id TEXT,
                debates_used_this_month INTEGER, billing_cycle_start TEXT,
                settings TEXT, created_at TEXT, updated_at TEXT
            )
        """)
        conn.commit()
        conn.close()

        update_user_called = []

        def mock_update_user(user_id, **kwargs):
            update_user_called.append((user_id, kwargs))
            return True

        store = OrganizationStore(
            db_path=temp_db_path, update_user=mock_update_user, backend="sqlite"
        )

        result = store.remove_user_from_org("user-123")

        assert result is True
        # Last call should be remove (org_id=None, role="member")
        assert update_user_called[-1] == ("user-123", {"org_id": None, "role": "member"})

        store.close()

    def test_get_org_members_requires_callback(self, org_store, sample_org_data):
        """Should raise ConfigurationError without row_to_user callback."""
        from aragora.exceptions import ConfigurationError

        org = org_store.create_organization(**sample_org_data)

        with pytest.raises(ConfigurationError, match="row_to_user callback required"):
            org_store.get_org_members(org.id)


# =============================================================================
# Data Integrity Tests
# =============================================================================


class TestDataIntegrity:
    """Tests for data integrity."""

    def test_organization_data_integrity(self, org_store, sample_org_data):
        """Test save then retrieve returns same data."""
        created = org_store.create_organization(**sample_org_data)

        retrieved = org_store.get_organization_by_id(created.id)

        assert retrieved.id == created.id
        assert retrieved.name == created.name
        assert retrieved.slug == created.slug
        assert retrieved.tier == created.tier
        assert retrieved.owner_id == created.owner_id

    def test_invitation_data_integrity(self, org_store, sample_org_data):
        """Test invitation data integrity."""
        org = org_store.create_organization(**sample_org_data)

        invitation = OrganizationInvitation(
            org_id=org.id,
            email="integrity@example.com",
            role="admin",
            invited_by="user-001",
        )
        org_store.create_invitation(invitation)

        retrieved = org_store.get_invitation_by_id(invitation.id)

        assert retrieved.id == invitation.id
        assert retrieved.org_id == invitation.org_id
        assert retrieved.email == invitation.email
        assert retrieved.role == invitation.role
        assert retrieved.invited_by == invitation.invited_by
        assert retrieved.token == invitation.token


# =============================================================================
# Persistence Tests
# =============================================================================


class TestPersistence:
    """Tests for data persistence across store instances."""

    def test_data_persists_across_instances(self, temp_db_path):
        """Data should persist after store is recreated."""
        # Create schema and first store
        conn = sqlite3.connect(str(temp_db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS organizations (
                id TEXT PRIMARY KEY, name TEXT, slug TEXT UNIQUE, tier TEXT, owner_id TEXT,
                stripe_customer_id TEXT, stripe_subscription_id TEXT,
                debates_used_this_month INTEGER, billing_cycle_start TEXT,
                settings TEXT, created_at TEXT, updated_at TEXT
            )
        """)
        conn.commit()
        conn.close()

        store1 = OrganizationStore(db_path=temp_db_path, backend="sqlite")
        org = store1.create_organization(
            name="Persist Test", owner_id="user-001", slug="persist-test"
        )
        org_id = org.id
        store1.close()

        # Create new store instance
        store2 = OrganizationStore(db_path=temp_db_path, backend="sqlite")

        # Verify data persists
        retrieved = store2.get_organization_by_id(org_id)
        assert retrieved is not None
        assert retrieved.name == "Persist Test"

        store2.close()


# =============================================================================
# Factory Functions Tests
# =============================================================================


class TestFactoryFunctions:
    """Tests for factory functions."""

    def test_reset_organization_store(self, temp_db_path):
        """Should reset the default store instance."""
        reset_organization_store()

        # Mock dependencies
        with patch.dict(
            "os.environ",
            {
                "ARAGORA_DATA_DIR": str(temp_db_path.parent),
                "ARAGORA_ENVIRONMENT": "development",
                "ARAGORA_ORGANIZATION_STORE_BACKEND": "sqlite",
            },
        ):
            with patch(
                "aragora.storage.connection_factory.resolve_database_config"
            ) as mock_resolve:
                from aragora.storage.connection_factory import StorageBackendType

                mock_config = MagicMock()
                mock_config.backend_type = StorageBackendType.SQLITE
                mock_config.dsn = None
                mock_resolve.return_value = mock_config

                with patch("aragora.storage.production_guards.require_distributed_store"):
                    # Create tables
                    conn = sqlite3.connect(str(temp_db_path.parent / "organizations.db"))
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS organizations (
                            id TEXT PRIMARY KEY, name TEXT, slug TEXT UNIQUE, tier TEXT,
                            owner_id TEXT, stripe_customer_id TEXT, stripe_subscription_id TEXT,
                            debates_used_this_month INTEGER, billing_cycle_start TEXT,
                            settings TEXT, created_at TEXT, updated_at TEXT
                        )
                    """)
                    conn.commit()
                    conn.close()

                    store1 = get_organization_store(
                        db_path=str(temp_db_path.parent / "organizations.db")
                    )
                    reset_organization_store()
                    store2 = get_organization_store(
                        db_path=str(temp_db_path.parent / "organizations.db")
                    )

                    # Should be different instances
                    assert store1 is not store2

        reset_organization_store()


# =============================================================================
# Close Tests
# =============================================================================


class TestClose:
    """Tests for close method."""

    def test_close_backend(self, temp_db_path):
        """Should close backend connection."""
        # Create schema
        conn = sqlite3.connect(str(temp_db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS organizations (
                id TEXT PRIMARY KEY, name TEXT, slug TEXT UNIQUE, tier TEXT, owner_id TEXT,
                stripe_customer_id TEXT, stripe_subscription_id TEXT,
                debates_used_this_month INTEGER, billing_cycle_start TEXT,
                settings TEXT, created_at TEXT, updated_at TEXT
            )
        """)
        conn.commit()
        conn.close()

        store = OrganizationStore(db_path=temp_db_path, backend="sqlite")
        store.create_organization(name="Close Test", owner_id="user-001")

        store.close()
        assert store._backend is None


# =============================================================================
# Module Exports Tests
# =============================================================================


class TestModuleExports:
    """Tests for module __all__ exports."""

    def test_all_exports_importable(self):
        """All items in __all__ should be importable."""
        import aragora.storage.organization_store as module

        for name in module.__all__:
            assert hasattr(module, name), f"Missing export: {name}"

    def test_key_exports(self):
        """Key exports should be available."""
        from aragora.storage.organization_store import (
            OrganizationStore,
            get_organization_store,
            reset_organization_store,
        )

        assert OrganizationStore is not None
        assert callable(get_organization_store)
        assert callable(reset_organization_store)


# =============================================================================
# Concurrent Operations Tests
# =============================================================================


class TestConcurrentOperations:
    """Tests for concurrent access handling."""

    def test_concurrent_organization_creates(self, temp_db_path):
        """Concurrent creates should be thread-safe."""
        # Create schema
        conn = sqlite3.connect(str(temp_db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS organizations (
                id TEXT PRIMARY KEY, name TEXT, slug TEXT UNIQUE, tier TEXT, owner_id TEXT,
                stripe_customer_id TEXT, stripe_subscription_id TEXT,
                debates_used_this_month INTEGER, billing_cycle_start TEXT,
                settings TEXT, created_at TEXT, updated_at TEXT
            )
        """)
        conn.commit()
        conn.close()

        store = OrganizationStore(db_path=temp_db_path, backend="sqlite")
        errors = []
        orgs_created = []

        def create_orgs(thread_id):
            try:
                for i in range(5):
                    org = store.create_organization(
                        name=f"Org-{thread_id}-{i}",
                        owner_id=f"user-{thread_id}",
                    )
                    orgs_created.append(org.id)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=create_orgs, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(orgs_created) == 15

        store.close()
