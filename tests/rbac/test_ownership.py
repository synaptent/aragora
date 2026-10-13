"""
Tests for RBAC Ownership module - comprehensive coverage.

This test file covers:
1. Resource ownership assignment and lookup
2. Owner-based permission checks
3. Ownership transfer between users
4. Ownership hierarchy and index integrity
5. Edge cases (missing owner, invalid resource, concurrent operations, etc.)
6. Cache behavior including TTL expiration
7. Serialization and deserialization
8. Global manager lifecycle
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
import time

from aragora.rbac.ownership import (
    OwnershipRecord,
    OwnershipManager,
    DEFAULT_OWNER_PERMISSIONS,
    get_ownership_manager,
    set_ownership_manager,
    set_resource_owner,
    get_resource_owner,
    is_resource_owner,
    check_owner_permission,
)
from aragora.rbac.models import (
    ResourceType,
    AuthorizationContext,
    AuthorizationDecision,
)


class TestOwnershipRecordCreation:
    """Tests for OwnershipRecord creation and initialization."""

    def test_create_minimal_record(self):
        """Test creating a record with minimal required fields."""
        record = OwnershipRecord.create(
            resource_type=ResourceType.DEBATE,
            resource_id="d-1",
            owner_id="u-1",
            org_id="o-1",
        )

        assert record.id is not None
        assert len(record.id) == 36  # UUID format
        assert record.resource_type == ResourceType.DEBATE
        assert record.resource_id == "d-1"
        assert record.owner_id == "u-1"
        assert record.org_id == "o-1"
        assert record.metadata == {}
        assert record.transferred_from is None

    def test_create_record_with_metadata(self):
        """Test creating a record with metadata."""
        metadata = {
            "created_via": "api",
            "client_ip": "192.168.1.1",
            "tags": ["important", "reviewed"],
        }
        record = OwnershipRecord.create(
            resource_type=ResourceType.WORKFLOW,
            resource_id="wf-123",
            owner_id="user-456",
            org_id="org-789",
            metadata=metadata,
        )

        assert record.metadata == metadata
        assert record.metadata["tags"] == ["important", "reviewed"]

    def test_record_timestamp_is_utc(self):
        """Test that created_at timestamp is in UTC."""
        record = OwnershipRecord.create(
            resource_type=ResourceType.AGENT,
            resource_id="agent-1",
            owner_id="user-1",
            org_id="org-1",
        )

        assert record.created_at.tzinfo == timezone.utc
        # Should be close to now
        delta = datetime.now(timezone.utc) - record.created_at
        assert delta.total_seconds() < 5

    def test_record_ids_are_unique(self):
        """Test that each created record has a unique ID."""
        records = [
            OwnershipRecord.create(
                resource_type=ResourceType.DEBATE,
                resource_id=f"debate-{i}",
                owner_id="user-1",
                org_id="org-1",
            )
            for i in range(100)
        ]

        ids = [r.id for r in records]
        assert len(ids) == len(set(ids))  # All unique


class TestOwnershipRecordSerialization:
    """Tests for OwnershipRecord serialization/deserialization."""

    def test_to_dict_basic(self):
        """Test basic serialization to dictionary."""
        record = OwnershipRecord.create(
            resource_type=ResourceType.EVIDENCE,
            resource_id="ev-1",
            owner_id="user-1",
            org_id="org-1",
        )

        data = record.to_dict()

        assert data["id"] == record.id
        assert data["resource_type"] == "evidence"
        assert data["resource_id"] == "ev-1"
        assert data["owner_id"] == "user-1"
        assert data["org_id"] == "org-1"
        assert data["transferred_from"] is None
        assert data["transferred_at"] is None
        assert data["transferred_by"] is None

    def test_to_dict_with_transfer_info(self):
        """Test serialization with transfer information."""
        record = OwnershipRecord.create(
            resource_type=ResourceType.CONNECTOR,
            resource_id="conn-1",
            owner_id="user-new",
            org_id="org-1",
        )
        record.transferred_from = "user-old"
        record.transferred_at = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        record.transferred_by = "admin-1"

        data = record.to_dict()

        assert data["transferred_from"] == "user-old"
        assert data["transferred_at"] == "2024-06-15T12:00:00+00:00"
        assert data["transferred_by"] == "admin-1"

    def test_from_dict_basic(self):
        """Test basic deserialization from dictionary."""
        data = {
            "id": "rec-123",
            "resource_type": "workflows",
            "resource_id": "wf-456",
            "owner_id": "user-789",
            "org_id": "org-000",
            "created_at": "2024-01-15T10:30:00+00:00",
            "transferred_from": None,
            "transferred_at": None,
            "transferred_by": None,
            "metadata": {"source": "import"},
        }

        record = OwnershipRecord.from_dict(data)

        assert record.id == "rec-123"
        assert record.resource_type == ResourceType.WORKFLOW
        assert record.resource_id == "wf-456"
        assert record.owner_id == "user-789"
        assert record.org_id == "org-000"
        assert record.metadata == {"source": "import"}

    def test_from_dict_with_datetime_objects(self):
        """Test deserialization when datetime is already a datetime object."""
        now = datetime.now(timezone.utc)
        data = {
            "id": "rec-1",
            "resource_type": "debates",
            "resource_id": "d-1",
            "owner_id": "u-1",
            "org_id": "o-1",
            "created_at": now,  # Already a datetime
            "transferred_from": None,
            "transferred_at": None,
            "transferred_by": None,
        }

        record = OwnershipRecord.from_dict(data)

        assert record.created_at == now

    def test_serialization_roundtrip(self):
        """Test full serialization roundtrip maintains data integrity."""
        original = OwnershipRecord.create(
            resource_type=ResourceType.WEBHOOK,
            resource_id="hook-999",
            owner_id="user-abc",
            org_id="org-xyz",
            metadata={"priority": "high", "count": 42},
        )
        original.transferred_from = "user-old"
        original.transferred_at = datetime(2024, 3, 1, 8, 0, 0, tzinfo=timezone.utc)
        original.transferred_by = "admin-sys"

        # Roundtrip
        data = original.to_dict()
        restored = OwnershipRecord.from_dict(data)

        assert restored.id == original.id
        assert restored.resource_type == original.resource_type
        assert restored.resource_id == original.resource_id
        assert restored.owner_id == original.owner_id
        assert restored.org_id == original.org_id
        assert restored.metadata == original.metadata
        assert restored.transferred_from == original.transferred_from
        assert restored.transferred_by == original.transferred_by


class TestOwnershipManagerBasics:
    """Tests for basic OwnershipManager functionality."""

    @pytest.fixture
    def manager(self):
        """Create a fresh ownership manager for each test."""
        return OwnershipManager(enable_cache=False)

    def test_set_and_get_owner(self, manager):
        """Test basic set and get owner operations."""
        manager.set_owner(
            resource_type=ResourceType.DEBATE,
            resource_id="debate-1",
            owner_id="user-1",
            org_id="org-1",
        )

        owner = manager.get_owner(ResourceType.DEBATE, "debate-1")
        assert owner == "user-1"

    def test_set_owner_returns_record(self, manager):
        """Test that set_owner returns the created record."""
        record = manager.set_owner(
            resource_type=ResourceType.AGENT,
            resource_id="agent-1",
            owner_id="user-1",
            org_id="org-1",
            metadata={"version": "1.0"},
        )

        assert isinstance(record, OwnershipRecord)
        assert record.owner_id == "user-1"
        assert record.metadata["version"] == "1.0"

    def test_get_owner_nonexistent_resource(self, manager):
        """Test getting owner for non-existent resource returns None."""
        owner = manager.get_owner(ResourceType.DEBATE, "does-not-exist")
        assert owner is None

    def test_is_owner_positive(self, manager):
        """Test is_owner returns True for actual owner."""
        manager.set_owner(ResourceType.WORKFLOW, "wf-1", "user-1", "org-1")

        assert manager.is_owner("user-1", ResourceType.WORKFLOW, "wf-1") is True

    def test_is_owner_negative(self, manager):
        """Test is_owner returns False for non-owner."""
        manager.set_owner(ResourceType.WORKFLOW, "wf-1", "user-1", "org-1")

        assert manager.is_owner("user-2", ResourceType.WORKFLOW, "wf-1") is False
        assert manager.is_owner("user-1", ResourceType.WORKFLOW, "wf-2") is False

    def test_is_owner_nonexistent_resource(self, manager):
        """Test is_owner returns False for non-existent resource."""
        assert manager.is_owner("user-1", ResourceType.DEBATE, "nonexistent") is False


class TestOwnershipReplacement:
    """Tests for ownership replacement scenarios."""

    @pytest.fixture
    def manager(self):
        """Create a fresh ownership manager."""
        return OwnershipManager(enable_cache=False)

    def test_set_owner_replaces_different_owner(self, manager):
        """Test that setting a new owner replaces the old one."""
        manager.set_owner(ResourceType.DEBATE, "debate-1", "user-old", "org-1")
        manager.set_owner(ResourceType.DEBATE, "debate-1", "user-new", "org-1")

        assert manager.get_owner(ResourceType.DEBATE, "debate-1") == "user-new"
        assert manager.is_owner("user-old", ResourceType.DEBATE, "debate-1") is False

    def test_set_owner_same_owner_returns_existing(self, manager):
        """Test that setting same owner returns existing record without change."""
        record1 = manager.set_owner(ResourceType.DEBATE, "debate-1", "user-1", "org-1")
        record2 = manager.set_owner(ResourceType.DEBATE, "debate-1", "user-1", "org-1")

        assert record1.id == record2.id  # Same record returned

    def test_replacement_updates_owner_index(self, manager):
        """Test that replacement properly updates the owner index."""
        manager.set_owner(ResourceType.DEBATE, "debate-1", "user-old", "org-1")
        manager.set_owner(ResourceType.DEBATE, "debate-1", "user-new", "org-1")

        # Old owner should not have the resource
        old_resources = manager.get_owned_resources("user-old")
        assert len(old_resources) == 0

        # New owner should have it
        new_resources = manager.get_owned_resources("user-new")
        assert len(new_resources) == 1
        assert new_resources[0].resource_id == "debate-1"


class TestOwnershipTransfer:
    """Tests for ownership transfer functionality."""

    @pytest.fixture
    def manager(self):
        """Create a fresh ownership manager."""
        return OwnershipManager(enable_cache=False)

    def test_transfer_ownership_basic(self, manager):
        """Test basic ownership transfer."""
        manager.set_owner(ResourceType.DEBATE, "debate-1", "user-old", "org-1")

        record = manager.transfer_ownership(
            resource_type=ResourceType.DEBATE,
            resource_id="debate-1",
            new_owner_id="user-new",
            transferred_by="admin-1",
            reason="Reassignment request",
        )

        assert record is not None
        assert record.owner_id == "user-new"
        assert record.transferred_from == "user-old"
        assert record.transferred_by == "admin-1"
        assert record.transferred_at is not None

    def test_transfer_nonexistent_returns_none(self, manager):
        """Test transferring non-existent resource returns None."""
        result = manager.transfer_ownership(
            resource_type=ResourceType.DEBATE,
            resource_id="nonexistent",
            new_owner_id="user-1",
        )

        assert result is None

    def test_transfer_to_same_owner_noop(self, manager):
        """Test transferring to same owner is a no-op."""
        manager.set_owner(ResourceType.DEBATE, "debate-1", "user-1", "org-1")

        record = manager.transfer_ownership(
            resource_type=ResourceType.DEBATE,
            resource_id="debate-1",
            new_owner_id="user-1",
        )

        assert record is not None
        assert record.transferred_from is None  # No actual transfer
        assert record.transferred_at is None

    def test_transfer_updates_all_lookups(self, manager):
        """Test that transfer updates get_owner and is_owner."""
        manager.set_owner(ResourceType.WORKFLOW, "wf-1", "user-old", "org-1")
        manager.transfer_ownership(ResourceType.WORKFLOW, "wf-1", "user-new")

        assert manager.get_owner(ResourceType.WORKFLOW, "wf-1") == "user-new"
        assert manager.is_owner("user-new", ResourceType.WORKFLOW, "wf-1") is True
        assert manager.is_owner("user-old", ResourceType.WORKFLOW, "wf-1") is False

    def test_multiple_transfers_chain(self, manager):
        """Test multiple transfers create proper audit trail."""
        manager.set_owner(ResourceType.DEBATE, "debate-1", "user-A", "org-1")
        manager.transfer_ownership(ResourceType.DEBATE, "debate-1", "user-B", reason="First")
        manager.transfer_ownership(ResourceType.DEBATE, "debate-1", "user-C", reason="Second")
        manager.transfer_ownership(ResourceType.DEBATE, "debate-1", "user-D", reason="Third")

        history = manager.get_transfer_history(resource_id="debate-1")

        assert len(history) == 3
        assert history[0]["from_owner"] == "user-A"
        assert history[0]["to_owner"] == "user-B"
        assert history[1]["from_owner"] == "user-B"
        assert history[1]["to_owner"] == "user-C"
        assert history[2]["from_owner"] == "user-C"
        assert history[2]["to_owner"] == "user-D"


class TestTransferHistory:
    """Tests for transfer history functionality."""

    @pytest.fixture
    def manager(self):
        """Create a manager with some transfers."""
        m = OwnershipManager(enable_cache=False)

        # Create several resources and transfers
        m.set_owner(ResourceType.DEBATE, "debate-1", "u1", "org-1")
        m.set_owner(ResourceType.DEBATE, "debate-2", "u1", "org-1")
        m.set_owner(ResourceType.WORKFLOW, "wf-1", "u1", "org-1")

        m.transfer_ownership(ResourceType.DEBATE, "debate-1", "u2", reason="Transfer 1")
        m.transfer_ownership(ResourceType.DEBATE, "debate-2", "u2", reason="Transfer 2")
        m.transfer_ownership(ResourceType.WORKFLOW, "wf-1", "u3", reason="Transfer 3")

        return m

    def test_get_all_history(self, manager):
        """Test getting all transfer history."""
        history = manager.get_transfer_history()
        assert len(history) == 3

    def test_filter_by_resource_type(self, manager):
        """Test filtering history by resource type."""
        debate_history = manager.get_transfer_history(resource_type=ResourceType.DEBATE)
        workflow_history = manager.get_transfer_history(resource_type=ResourceType.WORKFLOW)

        assert len(debate_history) == 2
        assert len(workflow_history) == 1
        assert all(h["resource_type"] == "debates" for h in debate_history)

    def test_filter_by_resource_id(self, manager):
        """Test filtering history by specific resource ID."""
        history = manager.get_transfer_history(resource_id="debate-1")

        assert len(history) == 1
        assert history[0]["resource_id"] == "debate-1"

    def test_history_limit(self, manager):
        """Test history limit parameter."""
        # Add more transfers
        for i in range(10):
            manager.set_owner(ResourceType.AGENT, f"agent-{i}", "u1", "org-1")
            manager.transfer_ownership(ResourceType.AGENT, f"agent-{i}", "u2")

        history = manager.get_transfer_history(limit=5)
        assert len(history) == 5

    def test_history_contains_transfer_details(self, manager):
        """Test that history entries contain all expected fields."""
        history = manager.get_transfer_history()

        for entry in history:
            assert "id" in entry
            assert "resource_type" in entry
            assert "resource_id" in entry
            assert "from_owner" in entry
            assert "to_owner" in entry
            assert "transferred_by" in entry
            assert "transferred_at" in entry
            assert "reason" in entry


class TestOwnershipRemoval:
    """Tests for ownership removal functionality."""

    @pytest.fixture
    def manager(self):
        """Create a fresh ownership manager."""
        return OwnershipManager(enable_cache=False)

    def test_remove_ownership_success(self, manager):
        """Test successful removal of ownership."""
        manager.set_owner(ResourceType.DEBATE, "debate-1", "user-1", "org-1")

        result = manager.remove_ownership(ResourceType.DEBATE, "debate-1")

        assert result is True
        assert manager.get_owner(ResourceType.DEBATE, "debate-1") is None

    def test_remove_nonexistent_returns_false(self, manager):
        """Test removing non-existent ownership returns False."""
        result = manager.remove_ownership(ResourceType.DEBATE, "nonexistent")
        assert result is False

    def test_remove_clears_from_owner_index(self, manager):
        """Test removal clears resource from owner's list."""
        manager.set_owner(ResourceType.DEBATE, "debate-1", "user-1", "org-1")
        manager.set_owner(ResourceType.DEBATE, "debate-2", "user-1", "org-1")

        manager.remove_ownership(ResourceType.DEBATE, "debate-1")

        owned = manager.get_owned_resources("user-1")
        resource_ids = [r.resource_id for r in owned]

        assert "debate-1" not in resource_ids
        assert "debate-2" in resource_ids

    def test_remove_clears_from_org_index(self, manager):
        """Test removal clears resource from organization index."""
        manager.set_owner(ResourceType.DEBATE, "debate-1", "user-1", "org-1")

        manager.remove_ownership(ResourceType.DEBATE, "debate-1")

        # Internal check - org index should be empty or not contain the record
        assert (
            manager._by_org.get("org-1", set()) == set()
            or len([r for r in manager._ownership_records.values() if r.org_id == "org-1"]) == 0
        )


class TestOwnedResourcesQuery:
    """Tests for querying owned resources."""

    @pytest.fixture
    def manager(self):
        """Create a manager with multiple resources."""
        m = OwnershipManager(enable_cache=False)

        m.set_owner(ResourceType.DEBATE, "debate-1", "user-1", "org-1")
        m.set_owner(ResourceType.DEBATE, "debate-2", "user-1", "org-1")
        m.set_owner(ResourceType.WORKFLOW, "wf-1", "user-1", "org-1")
        m.set_owner(ResourceType.DEBATE, "debate-3", "user-1", "org-2")
        m.set_owner(ResourceType.DEBATE, "debate-4", "user-2", "org-1")

        return m

    def test_get_all_owned(self, manager):
        """Test getting all resources owned by a user."""
        owned = manager.get_owned_resources("user-1")
        assert len(owned) == 4

    def test_filter_by_resource_type(self, manager):
        """Test filtering by resource type."""
        debates = manager.get_owned_resources("user-1", resource_type=ResourceType.DEBATE)
        workflows = manager.get_owned_resources("user-1", resource_type=ResourceType.WORKFLOW)

        assert len(debates) == 3
        assert len(workflows) == 1

    def test_filter_by_org(self, manager):
        """Test filtering by organization."""
        org1_resources = manager.get_owned_resources("user-1", org_id="org-1")
        org2_resources = manager.get_owned_resources("user-1", org_id="org-2")

        assert len(org1_resources) == 3
        assert len(org2_resources) == 1

    def test_filter_by_both(self, manager):
        """Test filtering by both type and org."""
        results = manager.get_owned_resources(
            "user-1",
            resource_type=ResourceType.DEBATE,
            org_id="org-1",
        )

        assert len(results) == 2
        for r in results:
            assert r.resource_type == ResourceType.DEBATE
            assert r.org_id == "org-1"

    def test_owned_resources_sorted_by_created_at(self, manager):
        """Test that results are sorted by created_at descending."""
        owned = manager.get_owned_resources("user-1")

        dates = [r.created_at for r in owned]
        assert dates == sorted(dates, reverse=True)

    def test_empty_result_for_no_ownership(self, manager):
        """Test empty list for user with no ownership."""
        owned = manager.get_owned_resources("nonexistent-user")
        assert owned == []


class TestImplicitOwnerPermissions:
    """Tests for implicit owner permission checking."""

    @pytest.fixture
    def manager(self):
        """Create a fresh ownership manager."""
        return OwnershipManager(enable_cache=False)

    @pytest.fixture
    def owner_context(self):
        """Create context for the owner user."""
        return AuthorizationContext(
            user_id="owner-user",
            org_id="org-1",
        )

    @pytest.fixture
    def non_owner_context(self):
        """Create context for a non-owner user."""
        return AuthorizationContext(
            user_id="other-user",
            org_id="org-1",
        )

    def test_owner_gets_implicit_read(self, manager, owner_context):
        """Test owner gets implicit read permission."""
        manager.set_owner(ResourceType.DEBATE, "debate-1", "owner-user", "org-1")

        decision = manager.check_owner_permission(
            context=owner_context,
            resource_type=ResourceType.DEBATE,
            permission_key="debates.read",
            resource_id="debate-1",
        )

        assert decision is not None
        assert decision.allowed is True
        assert "Owner" in decision.reason

    def test_owner_gets_implicit_update(self, manager, owner_context):
        """Test owner gets implicit update permission."""
        manager.set_owner(ResourceType.DEBATE, "debate-1", "owner-user", "org-1")

        decision = manager.check_owner_permission(
            owner_context, ResourceType.DEBATE, "debates.update", "debate-1"
        )

        assert decision is not None
        assert decision.allowed is True

    def test_owner_gets_implicit_delete(self, manager, owner_context):
        """Test owner gets implicit delete permission."""
        manager.set_owner(ResourceType.DEBATE, "debate-1", "owner-user", "org-1")

        decision = manager.check_owner_permission(
            owner_context, ResourceType.DEBATE, "debates.delete", "debate-1"
        )

        assert decision is not None
        assert decision.allowed is True

    def test_non_owner_gets_none(self, manager, non_owner_context):
        """Test non-owner returns None (continue to other checks)."""
        manager.set_owner(ResourceType.DEBATE, "debate-1", "owner-user", "org-1")

        decision = manager.check_owner_permission(
            non_owner_context, ResourceType.DEBATE, "debates.read", "debate-1"
        )

        assert decision is None

    def test_connector_owner_gets_implicit_configure(
        self, manager, owner_context, non_owner_context
    ):
        """Only the connector's owner gets connectors.configure on it."""
        manager.set_owner(ResourceType.CONNECTOR, "conn-1", "owner-user", "org-1")

        decision = manager.check_owner_permission(
            owner_context, ResourceType.CONNECTOR, "connectors.configure", "conn-1"
        )
        assert decision is not None
        assert decision.allowed is True
        assert decision.permission_key == "connectors.configure"

        assert (
            manager.check_owner_permission(
                non_owner_context, ResourceType.CONNECTOR, "connectors.configure", "conn-1"
            )
            is None
        )

    def test_owner_denied_non_implicit_permission(self, manager, owner_context):
        """Test owner doesn't get permissions not in implicit list."""
        manager.set_owner(ResourceType.DEBATE, "debate-1", "owner-user", "org-1")

        # "debates.admin" is not in DEFAULT_OWNER_PERMISSIONS
        decision = manager.check_owner_permission(
            owner_context, ResourceType.DEBATE, "debates.admin", "debate-1"
        )

        assert decision is None

    def test_check_owner_permission_includes_context_info(self, manager, owner_context):
        """Test that decision includes context information."""
        manager.set_owner(ResourceType.WORKFLOW, "wf-1", "owner-user", "org-1")

        decision = manager.check_owner_permission(
            owner_context, ResourceType.WORKFLOW, "workflows.read", "wf-1"
        )

        assert decision.resource_id == "wf-1"
        assert decision.permission_key == "workflows.read"
        assert decision.context == owner_context


class TestCustomOwnerPermissions:
    """Tests for custom owner permission configurations."""

    def test_custom_permissions_override_defaults(self):
        """Test that custom permissions override defaults."""
        custom_perms = {
            ResourceType.DEBATE: ["debates.read"],  # Only read
        }
        manager = OwnershipManager(owner_permissions=custom_perms)

        perms = manager.get_implicit_permissions(ResourceType.DEBATE)

        assert perms == ["debates.read"]
        assert "debates.delete" not in perms

    def test_custom_permissions_for_new_resource_type(self):
        """Test adding permissions for resource types not in defaults."""
        custom_perms = {
            ResourceType.DEBATE: ["debates.custom_action"],
        }
        manager = OwnershipManager(owner_permissions=custom_perms)

        perms = manager.get_implicit_permissions(ResourceType.DEBATE)
        assert "debates.custom_action" in perms

    def test_get_implicit_permissions_empty_for_unknown_type(self):
        """Test getting implicit permissions for type without config."""
        # Create manager with custom permissions that only includes DEBATE
        # This tests that types NOT in the config return empty list
        custom_perms = {
            ResourceType.DEBATE: ["debates.read"],
        }
        manager = OwnershipManager(owner_permissions=custom_perms)

        # WORKFLOW is not in our custom config, should return empty
        perms = manager.get_implicit_permissions(ResourceType.WORKFLOW)
        assert perms == []

        # DEBATE should return what we configured
        debate_perms = manager.get_implicit_permissions(ResourceType.DEBATE)
        assert debate_perms == ["debates.read"]


class TestOwnershipCache:
    """Tests for ownership caching behavior."""

    def test_cache_stores_lookup_result(self):
        """Test that cache stores ownership lookup."""
        manager = OwnershipManager(enable_cache=True, cache_ttl=300)
        manager.set_owner(ResourceType.DEBATE, "debate-1", "user-1", "org-1")

        # First call populates cache
        manager.get_owner(ResourceType.DEBATE, "debate-1")

        assert len(manager._ownership_cache) > 0

    def test_cache_disabled_no_storage(self):
        """Test that disabled cache doesn't store."""
        manager = OwnershipManager(enable_cache=False)
        manager.set_owner(ResourceType.DEBATE, "debate-1", "user-1", "org-1")

        manager.get_owner(ResourceType.DEBATE, "debate-1")

        assert len(manager._ownership_cache) == 0

    def test_cache_invalidated_on_set_owner(self):
        """Test cache is invalidated when owner is set."""
        manager = OwnershipManager(enable_cache=True, cache_ttl=300)
        manager.set_owner(ResourceType.DEBATE, "debate-1", "user-1", "org-1")

        # Populate cache
        manager.get_owner(ResourceType.DEBATE, "debate-1")
        cache_before = dict(manager._ownership_cache)

        # Change owner - should invalidate
        manager.set_owner(ResourceType.DEBATE, "debate-1", "user-2", "org-1")

        # Cache entry should be gone
        cache_key = manager._cache_key(ResourceType.DEBATE, "debate-1")
        assert cache_key not in manager._ownership_cache

    def test_cache_invalidated_on_transfer(self):
        """Test cache is invalidated on ownership transfer."""
        manager = OwnershipManager(enable_cache=True, cache_ttl=300)
        manager.set_owner(ResourceType.DEBATE, "debate-1", "user-1", "org-1")

        # Populate cache
        manager.get_owner(ResourceType.DEBATE, "debate-1")

        # Transfer - should invalidate
        manager.transfer_ownership(ResourceType.DEBATE, "debate-1", "user-2")

        # New get should reflect new owner
        assert manager.get_owner(ResourceType.DEBATE, "debate-1") == "user-2"

    def test_cache_invalidated_on_remove(self):
        """Test cache is invalidated on ownership removal."""
        manager = OwnershipManager(enable_cache=True, cache_ttl=300)
        manager.set_owner(ResourceType.DEBATE, "debate-1", "user-1", "org-1")

        manager.get_owner(ResourceType.DEBATE, "debate-1")
        manager.remove_ownership(ResourceType.DEBATE, "debate-1")

        assert manager.get_owner(ResourceType.DEBATE, "debate-1") is None

    def test_cache_ttl_expiration(self):
        """Test that cache entries expire after TTL."""
        manager = OwnershipManager(enable_cache=True, cache_ttl=1)  # 1 second TTL
        manager.set_owner(ResourceType.DEBATE, "debate-1", "user-1", "org-1")

        # First call populates cache
        manager.get_owner(ResourceType.DEBATE, "debate-1")
        assert len(manager._ownership_cache) == 1

        # Wait for TTL to expire
        time.sleep(1.5)

        # Next call should find cache expired
        # We need to check internal behavior - expired entry should be removed
        cache_key = manager._cache_key(ResourceType.DEBATE, "debate-1")
        cached = manager._get_cached_owner(cache_key)
        assert cached is None

    def test_clear_cache(self):
        """Test clearing the entire cache."""
        manager = OwnershipManager(enable_cache=True)
        manager.set_owner(ResourceType.DEBATE, "debate-1", "user-1", "org-1")
        manager.set_owner(ResourceType.WORKFLOW, "wf-1", "user-1", "org-1")

        manager.get_owner(ResourceType.DEBATE, "debate-1")
        manager.get_owner(ResourceType.WORKFLOW, "wf-1")

        assert len(manager._ownership_cache) == 2

        manager.clear_cache()

        assert len(manager._ownership_cache) == 0

    def test_cache_stores_none_for_nonexistent(self):
        """Test that cache stores None result for non-existent resources."""
        manager = OwnershipManager(enable_cache=True, cache_ttl=300)

        # Query non-existent resource
        result = manager.get_owner(ResourceType.DEBATE, "nonexistent")
        assert result is None

        # Cache should store empty string for None
        cache_key = manager._cache_key(ResourceType.DEBATE, "nonexistent")
        assert cache_key in manager._ownership_cache


class TestOwnershipStats:
    """Tests for ownership statistics."""

    @pytest.fixture
    def manager_with_data(self):
        """Create a manager with various data."""
        m = OwnershipManager(enable_cache=True)

        m.set_owner(ResourceType.DEBATE, "d1", "u1", "org-1")
        m.set_owner(ResourceType.DEBATE, "d2", "u1", "org-1")
        m.set_owner(ResourceType.DEBATE, "d3", "u2", "org-1")
        m.set_owner(ResourceType.WORKFLOW, "w1", "u1", "org-2")
        m.set_owner(ResourceType.AGENT, "a1", "u3", "org-1")

        m.transfer_ownership(ResourceType.DEBATE, "d1", "u2")
        m.transfer_ownership(ResourceType.DEBATE, "d2", "u3")

        # Populate some cache
        m.get_owner(ResourceType.DEBATE, "d3")

        return m

    def test_stats_total_records(self, manager_with_data):
        """Test total records count in stats."""
        stats = manager_with_data.get_stats()
        assert stats["total_records"] == 5

    def test_stats_unique_owners(self, manager_with_data):
        """Test unique owners count."""
        stats = manager_with_data.get_stats()
        assert stats["unique_owners"] == 3  # u1, u2, u3

    def test_stats_unique_orgs(self, manager_with_data):
        """Test unique organizations count."""
        stats = manager_with_data.get_stats()
        assert stats["unique_orgs"] == 2  # org-1, org-2

    def test_stats_by_resource_type(self, manager_with_data):
        """Test counts by resource type."""
        stats = manager_with_data.get_stats()

        assert stats["by_resource_type"]["debates"] == 3
        assert stats["by_resource_type"]["workflows"] == 1
        assert stats["by_resource_type"]["agents"] == 1

    def test_stats_transfer_count(self, manager_with_data):
        """Test transfer count in stats."""
        stats = manager_with_data.get_stats()
        assert stats["transfer_count"] == 2

    def test_stats_cache_info(self, manager_with_data):
        """Test cache information in stats."""
        stats = manager_with_data.get_stats()

        assert stats["cache_enabled"] is True
        assert stats["cache_size"] >= 1


class TestGlobalOwnershipManager:
    """Tests for global ownership manager functions."""

    def setup_method(self):
        """Reset global manager before each test."""
        set_ownership_manager(None)

    def teardown_method(self):
        """Reset global manager after each test."""
        set_ownership_manager(None)

    def test_get_creates_default_manager(self):
        """Test that get_ownership_manager creates a default instance."""
        manager = get_ownership_manager()

        assert manager is not None
        assert isinstance(manager, OwnershipManager)

    def test_get_returns_singleton(self):
        """Test that get_ownership_manager returns the same instance."""
        m1 = get_ownership_manager()
        m2 = get_ownership_manager()

        assert m1 is m2

    def test_set_replaces_manager(self):
        """Test that set_ownership_manager replaces the global instance."""
        custom = OwnershipManager(cache_ttl=999)
        set_ownership_manager(custom)

        retrieved = get_ownership_manager()
        assert retrieved is custom
        assert retrieved._cache_ttl == 999

    def test_set_none_clears_manager(self):
        """Test that setting None clears the global manager."""
        get_ownership_manager()  # Create one
        set_ownership_manager(None)

        # Next get should create a new one
        new_manager = get_ownership_manager()
        assert new_manager is not None


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def setup_method(self):
        """Reset global manager before each test."""
        set_ownership_manager(None)

    def teardown_method(self):
        """Reset global manager after each test."""
        set_ownership_manager(None)

    def test_set_resource_owner(self):
        """Test set_resource_owner convenience function."""
        record = set_resource_owner(
            resource_type=ResourceType.DEBATE,
            resource_id="debate-1",
            owner_id="user-1",
            org_id="org-1",
        )

        assert record.owner_id == "user-1"

    def test_get_resource_owner(self):
        """Test get_resource_owner convenience function."""
        set_resource_owner(ResourceType.DEBATE, "debate-1", "user-1", "org-1")

        owner = get_resource_owner(ResourceType.DEBATE, "debate-1")
        assert owner == "user-1"

    def test_is_resource_owner(self):
        """Test is_resource_owner convenience function."""
        set_resource_owner(ResourceType.DEBATE, "debate-1", "user-1", "org-1")

        assert is_resource_owner("user-1", ResourceType.DEBATE, "debate-1") is True
        assert is_resource_owner("user-2", ResourceType.DEBATE, "debate-1") is False

    def test_check_owner_permission_function(self):
        """Test check_owner_permission convenience function."""
        set_resource_owner(ResourceType.DEBATE, "debate-1", "user-1", "org-1")

        context = AuthorizationContext(user_id="user-1", org_id="org-1")

        decision = check_owner_permission(
            context=context,
            resource_type=ResourceType.DEBATE,
            permission_key="debates.read",
            resource_id="debate-1",
        )

        assert decision is not None
        assert decision.allowed is True


class TestDefaultOwnerPermissions:
    """Tests for DEFAULT_OWNER_PERMISSIONS configuration."""

    def test_debate_permissions(self):
        """Test debate owner permissions are defined."""
        perms = DEFAULT_OWNER_PERMISSIONS[ResourceType.DEBATE]

        assert "debates.read" in perms
        assert "debates.update" in perms
        assert "debates.delete" in perms
        assert "debates.run" in perms
        assert "debates.stop" in perms
        assert "debates.pause" in perms
        assert "debates.resume" in perms
        assert "debates.fork" in perms

    def test_workflow_permissions(self):
        """Test workflow owner permissions are defined."""
        perms = DEFAULT_OWNER_PERMISSIONS[ResourceType.WORKFLOW]

        assert "workflows.read" in perms
        assert "workflows.update" in perms
        assert "workflows.delete" in perms
        assert "workflows.run" in perms

    def test_agent_permissions(self):
        """Test agent owner permissions are defined."""
        perms = DEFAULT_OWNER_PERMISSIONS[ResourceType.AGENT]

        assert "agents.read" in perms
        assert "agents.update" in perms
        assert "agents.delete" in perms
        assert "agents.deploy" in perms
        assert "agents.configure" in perms

    def test_evidence_permissions(self):
        """Test evidence owner permissions are defined."""
        perms = DEFAULT_OWNER_PERMISSIONS[ResourceType.EVIDENCE]

        assert "evidence.read" in perms
        assert "evidence.update" in perms
        assert "evidence.delete" in perms

    def test_connector_permissions(self):
        """Test connector owner permissions are exactly the defined set."""
        perms = DEFAULT_OWNER_PERMISSIONS[ResourceType.CONNECTOR]

        assert set(perms) == {
            "connectors.read",
            "connectors.update",
            "connectors.delete",
            "connectors.test",
            "connectors.configure",
        }

    def test_webhook_permissions(self):
        """Test webhook owner permissions are defined."""
        perms = DEFAULT_OWNER_PERMISSIONS[ResourceType.WEBHOOK]

        assert "webhooks.read" in perms
        assert "webhooks.update" in perms
        assert "webhooks.delete" in perms


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.fixture
    def manager(self):
        """Create a fresh ownership manager."""
        return OwnershipManager(enable_cache=False)

    def test_empty_string_resource_id(self, manager):
        """Test handling of empty string resource ID."""
        record = manager.set_owner(
            resource_type=ResourceType.DEBATE,
            resource_id="",
            owner_id="user-1",
            org_id="org-1",
        )

        assert record.resource_id == ""
        assert manager.get_owner(ResourceType.DEBATE, "") == "user-1"

    def test_special_characters_in_ids(self, manager):
        """Test handling of special characters in IDs."""
        special_id = "debate:with/special-chars_and.dots"
        manager.set_owner(
            resource_type=ResourceType.DEBATE,
            resource_id=special_id,
            owner_id="user-1",
            org_id="org-1",
        )

        assert manager.get_owner(ResourceType.DEBATE, special_id) == "user-1"

    def test_unicode_in_ids(self, manager):
        """Test handling of unicode characters in IDs."""
        unicode_id = "debate-\u4e2d\u6587-\u0440\u0443\u0441\u0441\u043a\u0438\u0439"
        manager.set_owner(
            resource_type=ResourceType.DEBATE,
            resource_id=unicode_id,
            owner_id="user-\u7528\u6237",
            org_id="org-\u043e\u0440\u0433",
        )

        assert manager.get_owner(ResourceType.DEBATE, unicode_id) == "user-\u7528\u6237"

    def test_very_long_resource_id(self, manager):
        """Test handling of very long resource IDs."""
        long_id = "x" * 10000
        manager.set_owner(
            resource_type=ResourceType.DEBATE,
            resource_id=long_id,
            owner_id="user-1",
            org_id="org-1",
        )

        assert manager.get_owner(ResourceType.DEBATE, long_id) == "user-1"

    def test_concurrent_ownership_same_resource(self, manager):
        """Test that only one owner exists per resource."""
        manager.set_owner(ResourceType.DEBATE, "debate-1", "user-1", "org-1")
        manager.set_owner(ResourceType.DEBATE, "debate-1", "user-2", "org-1")
        manager.set_owner(ResourceType.DEBATE, "debate-1", "user-3", "org-1")

        # Only the last owner should exist
        assert manager.get_owner(ResourceType.DEBATE, "debate-1") == "user-3"
        assert manager.is_owner("user-1", ResourceType.DEBATE, "debate-1") is False
        assert manager.is_owner("user-2", ResourceType.DEBATE, "debate-1") is False

    def test_same_resource_id_different_types(self, manager):
        """Test that same resource ID can have different owners by type."""
        manager.set_owner(ResourceType.DEBATE, "shared-id", "user-debate", "org-1")
        manager.set_owner(ResourceType.WORKFLOW, "shared-id", "user-workflow", "org-1")

        assert manager.get_owner(ResourceType.DEBATE, "shared-id") == "user-debate"
        assert manager.get_owner(ResourceType.WORKFLOW, "shared-id") == "user-workflow"

    def test_large_number_of_resources(self, manager):
        """Test handling of large number of resources."""
        num_resources = 1000

        for i in range(num_resources):
            manager.set_owner(
                ResourceType.DEBATE,
                f"debate-{i}",
                f"user-{i % 10}",  # 10 different owners
                "org-1",
            )

        stats = manager.get_stats()
        assert stats["total_records"] == num_resources
        assert stats["unique_owners"] == 10

        # Verify random lookups work
        assert manager.get_owner(ResourceType.DEBATE, "debate-500") == "user-0"
        assert manager.get_owner(ResourceType.DEBATE, "debate-777") == "user-7"

    def test_ownership_record_with_large_metadata(self, manager):
        """Test handling of large metadata objects."""
        large_metadata = {f"key_{i}": f"value_{i}" * 100 for i in range(100)}

        record = manager.set_owner(
            resource_type=ResourceType.DEBATE,
            resource_id="debate-1",
            owner_id="user-1",
            org_id="org-1",
            metadata=large_metadata,
        )

        fetched = manager.get_ownership_record(ResourceType.DEBATE, "debate-1")
        assert fetched.metadata == large_metadata


class TestIndexIntegrity:
    """Tests to verify index integrity after various operations."""

    @pytest.fixture
    def manager(self):
        """Create a fresh ownership manager."""
        return OwnershipManager(enable_cache=False)

    def test_indexes_consistent_after_set(self, manager):
        """Test indexes are consistent after set operations."""
        manager.set_owner(ResourceType.DEBATE, "d1", "u1", "org-1")
        manager.set_owner(ResourceType.DEBATE, "d2", "u1", "org-1")
        manager.set_owner(ResourceType.WORKFLOW, "w1", "u2", "org-2")

        # Verify indexes
        assert len(manager._by_resource) == 3
        assert len(manager._by_owner["u1"]) == 2
        assert len(manager._by_owner["u2"]) == 1
        assert len(manager._by_org["org-1"]) == 2
        assert len(manager._by_org["org-2"]) == 1

    def test_indexes_consistent_after_transfer(self, manager):
        """Test indexes are consistent after transfer."""
        manager.set_owner(ResourceType.DEBATE, "d1", "u1", "org-1")
        manager.transfer_ownership(ResourceType.DEBATE, "d1", "u2")

        # Old owner should not have resource
        assert len(manager._by_owner.get("u1", set())) == 0

        # New owner should have resource
        assert len(manager._by_owner["u2"]) == 1

    def test_indexes_consistent_after_removal(self, manager):
        """Test indexes are consistent after removal."""
        manager.set_owner(ResourceType.DEBATE, "d1", "u1", "org-1")
        manager.set_owner(ResourceType.DEBATE, "d2", "u1", "org-1")
        manager.remove_ownership(ResourceType.DEBATE, "d1")

        # Resource index should only have d2
        assert len(manager._by_resource) == 1

        # Owner index should only have d2's record
        assert len(manager._by_owner["u1"]) == 1

        # Org index should only have d2's record
        assert len(manager._by_org["org-1"]) == 1

    def test_indexes_consistent_after_replacement(self, manager):
        """Test indexes are consistent after owner replacement."""
        manager.set_owner(ResourceType.DEBATE, "d1", "u1", "org-1")
        manager.set_owner(ResourceType.DEBATE, "d1", "u2", "org-1")  # Replace

        # Old owner should have no resources
        assert len(manager._by_owner.get("u1", set())) == 0

        # New owner should have the resource
        assert len(manager._by_owner["u2"]) == 1

        # Resource index should have one entry
        assert len(manager._by_resource) == 1
