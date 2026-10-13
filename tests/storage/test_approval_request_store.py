"""Tests for ApprovalRequestStore backends."""

import asyncio
import pytest
import tempfile
from pathlib import Path
from datetime import date, datetime, timezone, timedelta

import aragora.storage.approval_request_store as approval_request_store_module
from aragora.storage.approval_request_store import (
    ApprovalRequestItem,
    InMemoryApprovalRequestStore,
    SQLiteApprovalRequestStore,
    get_approval_request_store,
    reset_approval_request_store,
)


@pytest.fixture
def sample_request_data():
    """Sample approval request data for testing."""
    return {
        "request_id": "approval-test-001",
        "workflow_id": "workflow-123",
        "step_id": "step-1",
        "title": "Review deployment plan",
        "status": "pending",
        "description": "Please review the deployment plan for production",
        "request_data": {"deployment_version": "1.0.0", "target_env": "prod"},
        "requester_id": "user-123",
        "workspace_id": "ws-456",
        "priority": 2,
        "tags": ["deployment", "prod"],
    }


@pytest.fixture
def sample_request_data_2():
    """Second sample for listing tests."""
    return {
        "request_id": "approval-test-002",
        "workflow_id": "workflow-456",
        "step_id": "step-2",
        "title": "Approve security change",
        "status": "pending",
        "description": "Security configuration update",
        "request_data": {"change_type": "security"},
        "requester_id": "user-789",
        "workspace_id": "ws-456",
        "priority": 1,
        "tags": ["security"],
    }


class TestApprovalRequestItem:
    """Tests for ApprovalRequestItem dataclass."""

    def test_default_timestamps(self):
        """Test that timestamps are set by default."""
        item = ApprovalRequestItem(
            request_id="test-1",
            workflow_id="wf-1",
            step_id="step-1",
            title="Test request",
        )
        assert item.created_at != ""
        assert item.updated_at != ""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        item = ApprovalRequestItem(
            request_id="test-1",
            workflow_id="wf-1",
            step_id="step-1",
            title="Test request",
            status="approved",
            request_data={"key": "value"},
        )
        d = item.to_dict()
        assert d["request_id"] == "test-1"
        assert d["workflow_id"] == "wf-1"
        assert d["status"] == "approved"
        assert d["request_data"] == {"key": "value"}

    def test_from_dict(self):
        """Test creation from dictionary."""
        data = {
            "request_id": "test-1",
            "workflow_id": "wf-1",
            "step_id": "step-1",
            "title": "Test request",
            "status": "rejected",
            "response_data": {"reason": "Denied"},
        }
        item = ApprovalRequestItem.from_dict(data)
        assert item.request_id == "test-1"
        assert item.status == "rejected"
        assert item.response_data == {"reason": "Denied"}

    def test_json_roundtrip(self):
        """Test JSON serialization roundtrip."""
        item = ApprovalRequestItem(
            request_id="test-1",
            workflow_id="wf-1",
            step_id="step-1",
            title="Test request",
            request_data={"nested": {"data": 123}},
        )
        json_str = item.to_json()
        restored = ApprovalRequestItem.from_json(json_str)
        assert restored.request_id == item.request_id
        assert restored.request_data == item.request_data


class TestInMemoryApprovalRequestStore:
    """Tests for InMemoryApprovalRequestStore."""

    @pytest.fixture
    def store(self):
        """Create a fresh in-memory store."""
        return InMemoryApprovalRequestStore()

    @pytest.mark.asyncio
    async def test_save_and_get(self, store, sample_request_data):
        """Test saving and retrieving a request."""
        await store.save(sample_request_data)
        result = await store.get(sample_request_data["request_id"])
        assert result is not None
        assert result["request_id"] == sample_request_data["request_id"]
        assert result["title"] == sample_request_data["title"]

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, store):
        """Test getting a non-existent request."""
        result = await store.get("nonexistent-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_save_requires_request_id(self, store):
        """Test that save requires request_id."""
        with pytest.raises(ValueError, match="request_id is required"):
            await store.save({"workflow_id": "test"})

    @pytest.mark.asyncio
    async def test_delete(self, store, sample_request_data):
        """Test deleting a request."""
        await store.save(sample_request_data)
        deleted = await store.delete(sample_request_data["request_id"])
        assert deleted is True
        result = await store.get(sample_request_data["request_id"])
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, store):
        """Test deleting a non-existent request."""
        deleted = await store.delete("nonexistent-id")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_list_all(self, store, sample_request_data, sample_request_data_2):
        """Test listing all requests."""
        await store.save(sample_request_data)
        await store.save(sample_request_data_2)
        all_requests = await store.list_all()
        assert len(all_requests) == 2

    @pytest.mark.asyncio
    async def test_list_by_status(self, store, sample_request_data, sample_request_data_2):
        """Test listing requests by status."""
        await store.save(sample_request_data)  # pending
        sample_request_data_2["status"] = "approved"
        await store.save(sample_request_data_2)
        pending = await store.list_by_status("pending")
        assert len(pending) == 1
        assert pending[0]["request_id"] == sample_request_data["request_id"]

    @pytest.mark.asyncio
    async def test_list_by_workflow(self, store, sample_request_data, sample_request_data_2):
        """Test listing requests by workflow."""
        await store.save(sample_request_data)
        await store.save(sample_request_data_2)
        workflow_requests = await store.list_by_workflow("workflow-123")
        assert len(workflow_requests) == 1
        assert workflow_requests[0]["request_id"] == sample_request_data["request_id"]

    @pytest.mark.asyncio
    async def test_list_pending(self, store, sample_request_data, sample_request_data_2):
        """Test listing pending requests."""
        await store.save(sample_request_data)
        sample_request_data_2["status"] = "approved"
        await store.save(sample_request_data_2)
        pending = await store.list_pending()
        assert len(pending) == 1
        assert pending[0]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_list_expired(self, store, sample_request_data):
        """Test listing expired requests."""
        # Set expires_at in the past
        past_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        sample_request_data["expires_at"] = past_time
        await store.save(sample_request_data)

        expired = await store.list_expired()
        assert len(expired) == 1
        assert expired[0]["request_id"] == sample_request_data["request_id"]

    @pytest.mark.asyncio
    async def test_list_expired_excludes_responded(self, store, sample_request_data):
        """Test that expired list excludes already-responded requests."""
        past_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        sample_request_data["expires_at"] = past_time
        sample_request_data["status"] = "approved"  # Already responded
        await store.save(sample_request_data)

        expired = await store.list_expired()
        assert len(expired) == 0

    @pytest.mark.asyncio
    async def test_respond(self, store, sample_request_data):
        """Test responding to a request."""
        await store.save(sample_request_data)
        response_data = {"comment": "Looks good"}
        responded = await store.respond(
            sample_request_data["request_id"],
            "approved",
            "reviewer-123",
            response_data=response_data,
        )
        assert responded is True
        result = await store.get(sample_request_data["request_id"])
        assert result["status"] == "approved"
        assert result["responder_id"] == "reviewer-123"
        assert result["responded_at"] is not None
        assert result["response_data"] == response_data

    @pytest.mark.asyncio
    async def test_respond_reject(self, store, sample_request_data):
        """Test rejecting a request."""
        await store.save(sample_request_data)
        responded = await store.respond(
            sample_request_data["request_id"],
            "rejected",
            "reviewer-456",
            response_data={"reason": "Not ready for production"},
        )
        assert responded is True
        result = await store.get(sample_request_data["request_id"])
        assert result["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_respond_nonexistent(self, store):
        """Test responding to non-existent request."""
        responded = await store.respond("nonexistent-id", "approved", "user-1")
        assert responded is False


FROZEN_NOW = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
PLUS_FIVE = timezone(timedelta(hours=5))
MINUS_FIVE = timezone(timedelta(hours=-5))
CANONICAL = "2026-03-01T12:30:00+00:00"

SUPPORTED_TIMESTAMP_INPUTS = [
    pytest.param(CANONICAL, CANONICAL, id="canonical-string"),
    pytest.param("2026-03-01T12:30:00Z", CANONICAL, id="z-suffix"),
    pytest.param("2026-03-01T17:30:00+05:00", CANONICAL, id="positive-offset-string"),
    pytest.param("2026-03-01T07:30:00-05:00", CANONICAL, id="negative-offset-string"),
    pytest.param(
        "2026-03-01T12:30:00.250000+00:00",
        "2026-03-01T12:30:00.250000+00:00",
        id="microseconds",
    ),
    pytest.param("2026-03-01T12:30:00", CANONICAL, id="naive-string-read-as-utc"),
    pytest.param(datetime(2026, 3, 1, 12, 30, tzinfo=timezone.utc), CANONICAL, id="utc-datetime"),
    pytest.param(datetime(2026, 3, 1, 17, 30, tzinfo=PLUS_FIVE), CANONICAL, id="offset-datetime"),
    pytest.param(datetime(2026, 3, 1, 12, 30), CANONICAL, id="naive-datetime-read-as-utc"),
]

INVALID_TIMESTAMP_INPUTS = [
    pytest.param("", id="empty-string"),
    pytest.param("not-a-timestamp", id="garbage"),
    pytest.param("2026-02-30T12:00:00+00:00", id="impossible-date"),
    pytest.param("2026-03-01", id="date-only-string"),
    pytest.param(date(2026, 3, 1), id="date-object"),
    pytest.param(1772368200, id="epoch-int"),
    pytest.param(1772368200.5, id="epoch-float"),
    pytest.param(True, id="bool"),
    pytest.param([CANONICAL], id="list"),
    pytest.param("9999-12-31T23:00:00-05:00", id="beyond-utc-range"),
]


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return FROZEN_NOW.astimezone(tz) if tz is not None else FROZEN_NOW.replace(tzinfo=None)


@pytest.fixture
def frozen_now(monkeypatch):
    """Pin the store module's clock so expiry boundaries are exact."""
    monkeypatch.setattr(approval_request_store_module, "datetime", _FrozenDatetime)
    return FROZEN_NOW


class TestInMemoryApprovalRequestExpiry:
    """expires_at is stored as canonical UTC text and compared as an instant."""

    @pytest.fixture
    def store(self):
        return InMemoryApprovalRequestStore()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("raw", "expected"), SUPPORTED_TIMESTAMP_INPUTS)
    async def test_save_stores_canonical_utc_expires_at(
        self, store, sample_request_data, raw, expected
    ):
        sample_request_data["expires_at"] = raw
        await store.save(sample_request_data)

        stored = await store.get(sample_request_data["request_id"])
        assert stored["expires_at"] == expected
        assert set(stored) == set(sample_request_data)
        assert sample_request_data["expires_at"] is raw

    @pytest.mark.asyncio
    async def test_save_keeps_absent_and_null_expires_at(self, store, sample_request_data):
        request_id = sample_request_data["request_id"]
        await store.save(sample_request_data)
        assert "expires_at" not in await store.get(request_id)

        sample_request_data["expires_at"] = None
        await store.save(sample_request_data)
        assert (await store.get(request_id))["expires_at"] is None
        assert await store.list_expired() == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("raw", INVALID_TIMESTAMP_INPUTS)
    async def test_save_rejects_invalid_expires_at(self, store, sample_request_data, raw):
        await store.save(sample_request_data)
        replacement = {**sample_request_data, "title": "Replacement", "expires_at": raw}

        with pytest.raises(ValueError, match="expires_at"):
            await store.save(replacement)

        stored = await store.get(sample_request_data["request_id"])
        assert stored["title"] == sample_request_data["title"]
        assert "expires_at" not in stored

    @pytest.mark.asyncio
    async def test_list_expired_compares_instants_across_offsets(
        self, store, sample_request_data, frozen_now
    ):
        cases = {
            "past-plus-five": (frozen_now - timedelta(minutes=1)).astimezone(PLUS_FIVE).isoformat(),
            "future-minus-five": (frozen_now + timedelta(minutes=1))
            .astimezone(MINUS_FIVE)
            .isoformat(),
            "past-naive-string": (frozen_now - timedelta(minutes=1))
            .replace(tzinfo=None)
            .isoformat(),
            "past-datetime": frozen_now - timedelta(seconds=1),
            "future-datetime": (frozen_now + timedelta(hours=1)).astimezone(PLUS_FIVE),
        }
        for request_id, expires_at in cases.items():
            await store.save(
                {**sample_request_data, "request_id": request_id, "expires_at": expires_at}
            )

        expired = await store.list_expired()

        assert {r["request_id"] for r in expired} == {
            "past-plus-five",
            "past-naive-string",
            "past-datetime",
        }

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("delta", "is_expired"),
        [
            pytest.param(timedelta(microseconds=-1), True, id="just-before-now"),
            pytest.param(timedelta(0), False, id="exactly-now"),
            pytest.param(timedelta(microseconds=1), False, id="just-after-now"),
        ],
    )
    async def test_list_expired_boundary_is_strict(
        self, store, sample_request_data, frozen_now, delta, is_expired
    ):
        sample_request_data["expires_at"] = (frozen_now + delta).astimezone(MINUS_FIVE)
        await store.save(sample_request_data)

        expired = await store.list_expired()

        assert [r["request_id"] for r in expired] == (
            [sample_request_data["request_id"]] if is_expired else []
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", ["approved", "rejected", "expired"])
    async def test_list_expired_only_reports_pending(
        self, store, sample_request_data, frozen_now, status
    ):
        sample_request_data["status"] = status
        sample_request_data["expires_at"] = frozen_now - timedelta(hours=1)
        await store.save(sample_request_data)

        assert await store.list_expired() == []

    @pytest.mark.asyncio
    async def test_respond_keeps_canonical_expires_at(self, store, sample_request_data, frozen_now):
        request_id = sample_request_data["request_id"]
        sample_request_data["expires_at"] = (frozen_now - timedelta(hours=1)).astimezone(PLUS_FIVE)
        await store.save(sample_request_data)
        assert [r["request_id"] for r in await store.list_expired()] == [request_id]

        await store.respond(request_id, "approved", "reviewer-1")

        stored = await store.get(request_id)
        assert stored["expires_at"] == (frozen_now - timedelta(hours=1)).isoformat()
        assert await store.list_expired() == []

    @pytest.mark.asyncio
    async def test_list_expired_tolerates_edits_that_bypass_save(
        self, store, sample_request_data, frozen_now
    ):
        await store.save({**sample_request_data, "request_id": "edited-to-datetime"})
        await store.save({**sample_request_data, "request_id": "edited-to-garbage"})
        (await store.get("edited-to-datetime"))["expires_at"] = frozen_now - timedelta(minutes=5)
        (await store.get("edited-to-garbage"))["expires_at"] = "garbage"

        expired = await store.list_expired()

        assert [r["request_id"] for r in expired] == ["edited-to-datetime"]


class TestSQLiteApprovalRequestStore:
    """Tests for SQLiteApprovalRequestStore."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a SQLite store with temp database."""
        db_path = tmp_path / "test_approval_requests.db"
        return SQLiteApprovalRequestStore(db_path=db_path)

    @pytest.mark.asyncio
    async def test_save_and_get(self, store, sample_request_data):
        """Test saving and retrieving a request."""
        await store.save(sample_request_data)
        result = await store.get(sample_request_data["request_id"])
        assert result is not None
        assert result["request_id"] == sample_request_data["request_id"]

    @pytest.mark.asyncio
    async def test_persistence(self, tmp_path, sample_request_data):
        """Test that data persists across store instances."""
        db_path = tmp_path / "persistence_test.db"

        # Save with first instance
        store1 = SQLiteApprovalRequestStore(db_path=db_path)
        await store1.save(sample_request_data)

        # Retrieve with second instance
        store2 = SQLiteApprovalRequestStore(db_path=db_path)
        result = await store2.get(sample_request_data["request_id"])
        assert result is not None
        assert result["request_id"] == sample_request_data["request_id"]

    @pytest.mark.asyncio
    async def test_list_pending_ordered_by_priority(
        self, store, sample_request_data, sample_request_data_2
    ):
        """Test that list_pending returns results ordered by priority."""
        await store.save(sample_request_data)  # priority 2
        await store.save(sample_request_data_2)  # priority 1
        pending = await store.list_pending()
        assert len(pending) == 2
        # Priority 1 (higher priority) should be first
        assert pending[0]["priority"] == 1

    @pytest.mark.asyncio
    async def test_respond_full_cycle(self, store, sample_request_data):
        """Test full respond cycle with SQLite persistence."""
        await store.save(sample_request_data)

        # Respond
        await store.respond(
            sample_request_data["request_id"],
            "approved",
            "reviewer-999",
            response_data={"approval_note": "Ship it!"},
        )

        # Verify
        result = await store.get(sample_request_data["request_id"])
        assert result["status"] == "approved"
        assert result["responder_id"] == "reviewer-999"
        assert result["response_data"]["approval_note"] == "Ship it!"


class TestGlobalStoreAccessor:
    """Tests for global store accessor functions."""

    def setup_method(self):
        """Reset store before each test."""
        reset_approval_request_store()

    def teardown_method(self):
        """Reset store after each test."""
        reset_approval_request_store()

    def test_get_default_store(self, monkeypatch, tmp_path):
        """Test getting default store uses SQLite."""
        monkeypatch.setenv("ARAGORA_DATA_DIR", str(tmp_path))
        store = get_approval_request_store()
        assert isinstance(store, SQLiteApprovalRequestStore)

    def test_get_memory_store(self, monkeypatch):
        """Test getting memory store via env var."""
        monkeypatch.setenv("ARAGORA_APPROVAL_STORE_BACKEND", "memory")
        store = get_approval_request_store()
        assert isinstance(store, InMemoryApprovalRequestStore)

    def test_singleton_behavior(self, monkeypatch):
        """Test that get_approval_request_store returns singleton."""
        monkeypatch.setenv("ARAGORA_APPROVAL_STORE_BACKEND", "memory")
        store1 = get_approval_request_store()
        store2 = get_approval_request_store()
        assert store1 is store2
