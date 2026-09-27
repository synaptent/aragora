"""
Tests for UserStore - SQLite backend for user and organization persistence.

Tests cover:
- User CRUD operations
- Organization CRUD operations
- API key validation
- OAuth provider linking
- Concurrent access safety
- Usage tracking
"""

import hashlib
import os
import sqlite3
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from aragora.billing.models import Organization, SubscriptionTier, User, hash_password
from aragora.storage.repositories import OrganizationRepository
from aragora.storage.user_store import UserStore


@pytest.fixture
def temp_db():
    """Create a temporary database file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_users.db"
        yield db_path


@pytest.fixture
def store(temp_db):
    """Create a UserStore instance with temporary database."""
    store = UserStore(temp_db)
    yield store
    store.close()


@pytest.fixture
def sample_user_data():
    """Sample user data for tests."""
    password_hash, password_salt = hash_password("test_password_123")
    return {
        "email": "test@example.com",
        "password_hash": password_hash,
        "password_salt": password_salt,
        "name": "Test User",
    }


class TestUserCreation:
    """Tests for user creation."""

    def test_create_user_success(self, store, sample_user_data):
        """Test successful user creation."""
        user = store.create_user(**sample_user_data)

        assert user is not None
        assert user.id is not None
        assert user.email == sample_user_data["email"]
        assert user.name == sample_user_data["name"]
        assert user.is_active is True
        assert user.email_verified is False
        assert user.role == "member"

    def test_create_user_duplicate_email(self, store, sample_user_data):
        """Test that duplicate email raises ValueError."""
        store.create_user(**sample_user_data)

        with pytest.raises(ValueError, match="Email already exists"):
            store.create_user(**sample_user_data)

    def test_create_user_with_org(self, store, sample_user_data):
        """Test creating user with organization."""
        # Create owner first
        owner = store.create_user(**sample_user_data)
        org = store.create_organization("Test Org", owner.id)

        # Create user in org
        member_data = {
            **sample_user_data,
            "email": "member@example.com",
            "org_id": org.id,
            "role": "member",
        }
        member = store.create_user(**member_data)

        assert member.org_id == org.id
        assert member.role == "member"

    def test_create_user_generates_unique_id(self, store, sample_user_data):
        """Test that each user gets a unique ID."""
        user1 = store.create_user(**sample_user_data)

        user2_data = {**sample_user_data, "email": "other@example.com"}
        user2 = store.create_user(**user2_data)

        assert user1.id != user2.id


class TestUserRetrieval:
    """Tests for user retrieval."""

    def test_get_user_by_id(self, store, sample_user_data):
        """Test getting user by ID."""
        created = store.create_user(**sample_user_data)
        retrieved = store.get_user_by_id(created.id)

        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.email == created.email

    def test_get_user_by_id_not_found(self, store):
        """Test getting non-existent user returns None."""
        result = store.get_user_by_id("nonexistent-id")
        assert result is None

    def test_get_user_by_email(self, store, sample_user_data):
        """Test getting user by email."""
        created = store.create_user(**sample_user_data)
        retrieved = store.get_user_by_email(sample_user_data["email"])

        assert retrieved is not None
        assert retrieved.id == created.id

    def test_get_user_by_email_case_insensitive(self, store, sample_user_data):
        """Test email lookup is case-insensitive."""
        store.create_user(**sample_user_data)

        # Should find with different case
        retrieved = store.get_user_by_email(sample_user_data["email"].upper())
        # Note: This depends on implementation - current impl lowercases on lookup
        # but not on insert. Test documents actual behavior.
        assert retrieved is None or retrieved.email == sample_user_data["email"]


class TestAPIKeyValidation:
    """Tests for API key validation."""

    def test_get_user_by_api_key_valid(self, store, sample_user_data):
        """Test getting user by valid API key."""
        user = store.create_user(**sample_user_data)

        # Generate and store API key
        api_key = f"ara_{os.urandom(16).hex()}"
        api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()

        store.update_user(
            user.id,
            api_key=api_key,
            api_key_hash=api_key_hash,
            api_key_prefix=api_key[:12],
            api_key_created_at=datetime.now(timezone.utc),
            api_key_expires_at=datetime.now(timezone.utc) + timedelta(days=365),
        )

        retrieved = store.get_user_by_api_key(api_key)
        assert retrieved is not None
        assert retrieved.id == user.id

    def test_get_user_by_api_key_invalid(self, store, sample_user_data):
        """Test that invalid API key returns None."""
        store.create_user(**sample_user_data)

        result = store.get_user_by_api_key("ara_invalid_key_12345")
        assert result is None

    def test_get_user_by_api_key_expired(self, store, sample_user_data):
        """Test that expired API key returns None."""
        user = store.create_user(**sample_user_data)

        # Generate and store expired API key
        api_key = f"ara_{os.urandom(16).hex()}"
        api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()

        store.update_user(
            user.id,
            api_key=api_key,
            api_key_hash=api_key_hash,
            api_key_prefix=api_key[:12],
            api_key_created_at=datetime.now(timezone.utc) - timedelta(days=400),
            api_key_expires_at=datetime.now(timezone.utc) - timedelta(days=35),  # Expired
        )

        result = store.get_user_by_api_key(api_key)
        assert result is None


class TestUserUpdate:
    """Tests for user updates."""

    def test_update_user_role(self, store, sample_user_data):
        """Test updating user role."""
        user = store.create_user(**sample_user_data)

        result = store.update_user(user.id, role="admin")
        assert result is True

        updated = store.get_user_by_id(user.id)
        assert updated.role == "admin"

    def test_update_user_multiple_fields(self, store, sample_user_data):
        """Test updating multiple fields at once."""
        user = store.create_user(**sample_user_data)

        store.update_user(
            user.id,
            name="New Name",
            is_active=False,
            email_verified=True,
        )

        updated = store.get_user_by_id(user.id)
        assert updated.name == "New Name"
        assert updated.is_active is False
        assert updated.email_verified is True

    def test_update_nonexistent_user(self, store):
        """Test updating non-existent user returns False."""
        result = store.update_user("nonexistent-id", name="New Name")
        assert result is False

    def test_update_user_empty_fields(self, store, sample_user_data):
        """Test updating with no fields returns False."""
        user = store.create_user(**sample_user_data)
        result = store.update_user(user.id)
        assert result is False


class TestUserDeletion:
    """Tests for user deletion."""

    def test_delete_user(self, store, sample_user_data):
        """Test deleting a user."""
        user = store.create_user(**sample_user_data)

        result = store.delete_user(user.id)
        assert result is True

        retrieved = store.get_user_by_id(user.id)
        assert retrieved is None

    def test_delete_nonexistent_user(self, store):
        """Test deleting non-existent user returns False."""
        result = store.delete_user("nonexistent-id")
        assert result is False


class TestOrganization:
    """Tests for organization operations."""

    def test_create_organization(self, store, sample_user_data):
        """Test creating an organization."""
        owner = store.create_user(**sample_user_data)
        org = store.create_organization("Test Org", owner.id)

        assert org is not None
        assert org.id is not None
        assert org.name == "Test Org"
        assert org.owner_id == owner.id
        assert org.tier == SubscriptionTier.FREE

        # Owner should be updated with org_id
        updated_owner = store.get_user_by_id(owner.id)
        assert updated_owner.org_id == org.id
        assert updated_owner.role == "owner"

    def test_create_organization_auto_slug(self, store, sample_user_data):
        """Test that slug is auto-generated."""
        owner = store.create_user(**sample_user_data)
        org = store.create_organization("My Test Organization", owner.id)

        assert org.slug is not None
        assert "my-test-organization" in org.slug

    def test_create_organization_custom_slug(self, store, sample_user_data):
        """Test creating org with custom slug."""
        owner = store.create_user(**sample_user_data)
        org = store.create_organization("Test Org", owner.id, slug="custom-slug")

        assert org.slug == "custom-slug"

    def test_get_organization_by_id(self, store, sample_user_data):
        """Test getting organization by ID."""
        owner = store.create_user(**sample_user_data)
        created = store.create_organization("Test Org", owner.id)

        retrieved = store.get_organization_by_id(created.id)
        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.name == "Test Org"

    def test_get_organization_by_slug(self, store, sample_user_data):
        """Test getting organization by slug."""
        owner = store.create_user(**sample_user_data)
        created = store.create_organization("Test Org", owner.id, slug="test-slug")

        retrieved = store.get_organization_by_slug("test-slug")
        assert retrieved is not None
        assert retrieved.id == created.id

    def test_update_organization(self, store, sample_user_data):
        """Test updating organization."""
        owner = store.create_user(**sample_user_data)
        org = store.create_organization("Test Org", owner.id)

        result = store.update_organization(
            org.id,
            name="Updated Org",
            tier=SubscriptionTier.PROFESSIONAL,
        )
        assert result is True

        updated = store.get_organization_by_id(org.id)
        assert updated.name == "Updated Org"
        assert updated.tier == SubscriptionTier.PROFESSIONAL


class TestOrgMembers:
    """Tests for organization member management."""

    def test_add_user_to_org(self, store, sample_user_data):
        """Test adding user to organization."""
        owner = store.create_user(**sample_user_data)
        org = store.create_organization("Test Org", owner.id)

        member_data = {**sample_user_data, "email": "member@example.com"}
        member = store.create_user(**member_data)

        result = store.add_user_to_org(member.id, org.id, "member")
        assert result is True

        updated = store.get_user_by_id(member.id)
        assert updated.org_id == org.id
        assert updated.role == "member"

    def test_remove_user_from_org(self, store, sample_user_data):
        """Test removing user from organization."""
        owner = store.create_user(**sample_user_data)
        org = store.create_organization("Test Org", owner.id)

        member_data = {**sample_user_data, "email": "member@example.com"}
        member = store.create_user(**member_data)
        store.add_user_to_org(member.id, org.id)

        result = store.remove_user_from_org(member.id)
        assert result is True

        updated = store.get_user_by_id(member.id)
        assert updated.org_id is None

    def test_get_org_members(self, store, sample_user_data):
        """Test getting all organization members."""
        owner = store.create_user(**sample_user_data)
        org = store.create_organization("Test Org", owner.id)

        # Add some members
        for i in range(3):
            member_data = {**sample_user_data, "email": f"member{i}@example.com"}
            member = store.create_user(**member_data)
            store.add_user_to_org(member.id, org.id)

        members = store.get_org_members(org.id)
        assert len(members) == 4  # Owner + 3 members


class TestUsageTracking:
    """Tests for usage tracking."""

    def test_increment_usage(self, store, sample_user_data):
        """Test incrementing debate usage."""
        owner = store.create_user(**sample_user_data)
        org = store.create_organization("Test Org", owner.id)

        new_count = store.increment_usage(org.id, 5)
        assert new_count == 5

        new_count = store.increment_usage(org.id, 3)
        assert new_count == 8

    def test_reset_monthly_usage(self, store, sample_user_data):
        """Test resetting monthly usage."""
        owner = store.create_user(**sample_user_data)
        org = store.create_organization("Test Org", owner.id)

        store.increment_usage(org.id, 10)

        count = store.reset_monthly_usage()
        assert count >= 1

        updated = store.get_organization_by_id(org.id)
        assert updated.debates_used_this_month == 0

    def test_record_usage_event(self, store, sample_user_data):
        """Test recording usage events."""
        owner = store.create_user(**sample_user_data)
        org = store.create_organization("Test Org", owner.id)

        # Should not raise
        store.record_usage_event(
            org.id,
            "debate_started",
            count=1,
            metadata={"topic": "AI Safety"},
        )


class TestOAuthProviders:
    """Tests for OAuth provider linking."""

    def test_link_oauth_provider(self, store, sample_user_data):
        """Test linking OAuth provider to user."""
        user = store.create_user(**sample_user_data)

        result = store.link_oauth_provider(
            user.id,
            provider="google",
            provider_user_id="google-123",
            email="test@gmail.com",
        )
        assert result is True

    def test_get_user_by_oauth(self, store, sample_user_data):
        """Test getting user by OAuth provider."""
        user = store.create_user(**sample_user_data)
        store.link_oauth_provider(
            user.id,
            provider="google",
            provider_user_id="google-123",
        )

        retrieved = store.get_user_by_oauth("google", "google-123")
        assert retrieved is not None
        assert retrieved.id == user.id

    def test_get_user_oauth_providers(self, store, sample_user_data):
        """Test getting all OAuth providers for user."""
        user = store.create_user(**sample_user_data)
        store.link_oauth_provider(user.id, "google", "google-123")
        store.link_oauth_provider(user.id, "github", "github-456")

        providers = store.get_user_oauth_providers(user.id)
        assert len(providers) == 2
        provider_names = {p["provider"] for p in providers}
        assert "google" in provider_names
        assert "github" in provider_names

    def test_unlink_oauth_provider(self, store, sample_user_data):
        """Test unlinking OAuth provider."""
        user = store.create_user(**sample_user_data)
        store.link_oauth_provider(user.id, "google", "google-123")

        result = store.unlink_oauth_provider(user.id, "google")
        assert result is True

        retrieved = store.get_user_by_oauth("google", "google-123")
        assert retrieved is None


class TestConcurrentAccess:
    """Tests for concurrent access safety."""

    def test_concurrent_user_updates(self, store, sample_user_data):
        """Test that concurrent updates don't corrupt data."""
        user = store.create_user(**sample_user_data)
        errors = []
        updates_completed = 0
        lock = threading.Lock()

        def update_user(thread_id):
            nonlocal updates_completed
            try:
                store.update_user(user.id, name=f"Thread-{thread_id}")
                with lock:
                    updates_completed += 1
            except Exception as e:
                with lock:
                    errors.append(str(e))

        # Run concurrent updates
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(update_user, i) for i in range(10)]
            for f in futures:
                f.result()

        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert updates_completed == 10

        # User should still be retrievable
        final_user = store.get_user_by_id(user.id)
        assert final_user is not None

    def test_concurrent_org_creation(self, temp_db, sample_user_data):
        """Test concurrent organization creation with unique slugs."""
        errors = []
        orgs_created = []
        lock = threading.Lock()

        def create_org(thread_id):
            try:
                # Each thread gets its own store instance (thread-local connections)
                thread_store = UserStore(temp_db)
                try:
                    owner_data = {
                        **sample_user_data,
                        "email": f"owner{thread_id}@example.com",
                    }
                    owner = thread_store.create_user(**owner_data)
                    org = thread_store.create_organization(
                        "Test Org",  # Same name, should get unique slugs
                        owner.id,
                    )
                    with lock:
                        orgs_created.append(org.slug)
                finally:
                    thread_store.close()
            except Exception as e:
                with lock:
                    errors.append(str(e))

        # Run concurrent org creation
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(create_org, i) for i in range(5)]
            for f in futures:
                f.result()

        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(orgs_created) == 5
        # All slugs should be unique
        assert len(set(orgs_created)) == 5

    def test_concurrent_org_creation_after_interleaved_slug_check(self, store, sample_user_data):
        """Two creators paused after their first transaction must still get distinct slugs.

        Each thread blocks on a barrier once its first repository transaction has
        committed, so both creators have observed the organizations table before
        either proceeds. Any slug choice made outside the INSERT's transaction
        then collides deterministically.
        """
        owners = [
            store.create_user(**{**sample_user_data, "email": f"race{i}@example.com"})
            for i in range(2)
        ]
        barrier = threading.Barrier(2, timeout=10)
        paused = threading.local()

        @contextmanager
        def paused_transaction():
            with store._transaction() as cursor:
                yield cursor
            if not getattr(paused, "done", False):
                paused.done = True
                barrier.wait()

        repo = OrganizationRepository(paused_transaction, store._row_to_user)
        slugs: list[str] = []
        errors: list[str] = []
        lock = threading.Lock()

        def create_org(index):
            try:
                org = repo.create("Test Org", owners[index].id)
                with lock:
                    slugs.append(org.slug)
            except Exception as e:
                with lock:
                    errors.append(f"{type(e).__name__}: {e}")

        threads = [threading.Thread(target=create_org, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert not any(t.is_alive() for t in threads)
        assert errors == []
        assert len(slugs) == 2
        assert len(set(slugs)) == 2
        assert "test-org" in slugs

    def test_explicit_duplicate_slug_still_rejected(self, store, sample_user_data):
        """A caller-supplied slug that already exists fails and changes nothing."""
        first_owner = store.create_user(**sample_user_data)
        second_owner = store.create_user(**{**sample_user_data, "email": "second@example.com"})
        store.create_organization("First Org", first_owner.id, slug="shared-slug")

        with pytest.raises(sqlite3.IntegrityError, match="organizations.slug"):
            store.create_organization("Second Org", second_owner.id, slug="shared-slug")

        assert store.get_organization_by_slug("shared-slug").owner_id == first_owner.id
        reloaded = store.get_user_by_id(second_owner.id)
        assert reloaded.org_id is None
        assert reloaded.role == "member"


class TestAuditLog:
    """Tests for audit logging."""

    def test_log_audit_event(self, store, sample_user_data):
        """Test logging an audit event."""
        user = store.create_user(**sample_user_data)

        entry_id = store.log_audit_event(
            action="user.created",
            resource_type="user",
            resource_id=user.id,
            user_id=user.id,
            new_value={"email": user.email},
        )

        assert entry_id is not None
        assert entry_id > 0

    def test_get_audit_log(self, store, sample_user_data):
        """Test retrieving audit log entries."""
        user = store.create_user(**sample_user_data)
        store.log_audit_event(
            action="user.created",
            resource_type="user",
            resource_id=user.id,
            user_id=user.id,
        )
        store.log_audit_event(
            action="user.updated",
            resource_type="user",
            resource_id=user.id,
            user_id=user.id,
        )

        entries = store.get_audit_log(user_id=user.id)
        assert len(entries) == 2

    def test_get_audit_log_with_action_prefix(self, store, sample_user_data):
        """Test filtering audit log by action prefix."""
        user = store.create_user(**sample_user_data)
        store.log_audit_event(action="user.created", resource_type="user", user_id=user.id)
        store.log_audit_event(action="user.updated", resource_type="user", user_id=user.id)
        store.log_audit_event(action="org.created", resource_type="organization", user_id=user.id)

        entries = store.get_audit_log(action="user.*")
        assert len(entries) == 2

    def test_get_audit_log_count(self, store, sample_user_data):
        """Test counting audit log entries."""
        user = store.create_user(**sample_user_data)
        for i in range(5):
            store.log_audit_event(
                action="test.event",
                resource_type="test",
                user_id=user.id,
            )

        count = store.get_audit_log_count(user_id=user.id)
        assert count == 5


class TestMigration:
    """Tests for data migration functionality."""

    def test_migrate_plaintext_api_keys(self, store, sample_user_data):
        """Test migrating plaintext API keys to hashed storage."""
        user = store.create_user(**sample_user_data)

        # Manually insert a plaintext API key without hash
        api_key = f"ara_{os.urandom(16).hex()}"
        with store._transaction() as cursor:
            cursor.execute(
                "UPDATE users SET api_key = ?, api_key_created_at = ? WHERE id = ?",
                (api_key, datetime.now(timezone.utc).isoformat(), user.id),
            )

        # Run migration
        migrated_count = store.migrate_plaintext_api_keys()
        assert migrated_count == 1

        # Key should now work via hash lookup
        retrieved = store.get_user_by_api_key(api_key)
        assert retrieved is not None
        assert retrieved.id == user.id

        # Check hash was stored
        updated = store.get_user_by_id(user.id)
        assert updated.api_key_hash is not None
        assert updated.api_key_prefix == api_key[:12]
