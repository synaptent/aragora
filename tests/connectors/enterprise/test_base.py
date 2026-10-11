"""
Tests for Enterprise Connector Base Class.

Comprehensive tests covering:
1. Abstract base class behavior
2. Authentication methods (credential providers)
3. Sync state management (persistence, serialization)
4. Circuit breaker integration
5. Sync operations (full sync, incremental, cancellation)
6. Webhook handling
7. SyncItem and SyncResult dataclasses
8. Content hash change detection
"""

import asyncio
import json
import hashlib
import hmac
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.connectors.enterprise.base import (
    EnterpriseConnector,
    SyncState,
    SyncStatus,
    SyncResult,
    SyncItem,
    EnvCredentialProvider,
    CredentialProvider,
)
from aragora.connectors.base import Evidence
from aragora.reasoning.provenance import SourceType


# =============================================================================
# Concrete Implementation for Testing
# =============================================================================


class MockEnterpriseConnector(EnterpriseConnector):
    """
    Concrete implementation of EnterpriseConnector for testing.

    Implements abstract methods with controllable behavior.
    """

    def __init__(
        self,
        items_to_yield: list[SyncItem] | None = None,
        search_results: list[Evidence] | None = None,
        fetch_result: Evidence | None = None,
        raise_on_sync: Exception | None = None,
        **kwargs,
    ):
        super().__init__(connector_id="test_connector", **kwargs)
        self._items_to_yield = items_to_yield or []
        self._search_results = search_results or []
        self._fetch_result = fetch_result
        self._raise_on_sync = raise_on_sync
        self._sync_call_count = 0

    @property
    def source_type(self) -> SourceType:
        return SourceType.DOCUMENT

    @property
    def name(self) -> str:
        return "Mock Enterprise"

    async def sync_items(
        self,
        state: SyncState,
        batch_size: int = 100,
    ) -> AsyncIterator[SyncItem]:
        """Yield configured items for testing."""
        self._sync_call_count += 1

        if self._raise_on_sync:
            raise self._raise_on_sync

        for item in self._items_to_yield:
            yield item

    async def search(
        self,
        query: str,
        limit: int = 10,
        **kwargs,
    ) -> list[Evidence]:
        return self._search_results[:limit]

    async def fetch(self, evidence_id: str) -> Evidence | None:
        return self._fetch_result


# =============================================================================
# SyncStatus Enum Tests
# =============================================================================


class TestSyncStatus:
    """Tests for SyncStatus enum."""

    def test_status_values(self):
        """Test all status values exist."""
        assert SyncStatus.IDLE.value == "idle"
        assert SyncStatus.RUNNING.value == "running"
        assert SyncStatus.COMPLETED.value == "completed"
        assert SyncStatus.FAILED.value == "failed"
        assert SyncStatus.CANCELLED.value == "cancelled"

    def test_status_from_string(self):
        """Test creating status from string."""
        assert SyncStatus("idle") == SyncStatus.IDLE
        assert SyncStatus("running") == SyncStatus.RUNNING
        assert SyncStatus("completed") == SyncStatus.COMPLETED
        assert SyncStatus("failed") == SyncStatus.FAILED
        assert SyncStatus("cancelled") == SyncStatus.CANCELLED


# =============================================================================
# SyncState Tests
# =============================================================================


class TestSyncState:
    """Tests for SyncState dataclass."""

    def test_default_values(self):
        """Test SyncState default values."""
        state = SyncState(connector_id="test")

        assert state.connector_id == "test"
        assert state.tenant_id == "default"
        assert state.cursor is None
        assert state.last_sync_at is None
        assert state.last_item_id is None
        assert state.last_item_timestamp is None
        assert state.items_synced == 0
        assert state.items_total == 0
        assert state.errors == []
        assert state.status == SyncStatus.IDLE
        assert state.started_at is None
        assert state.completed_at is None

    def test_to_dict_serialization(self):
        """Test serializing SyncState to dictionary."""
        now = datetime.now(timezone.utc)
        state = SyncState(
            connector_id="test",
            tenant_id="tenant_1",
            cursor="cursor_abc",
            last_sync_at=now,
            last_item_id="item_100",
            last_item_timestamp=now,
            items_synced=50,
            items_total=100,
            errors=["error1", "error2"],
            status=SyncStatus.COMPLETED,
            started_at=now - timedelta(minutes=5),
            completed_at=now,
        )

        data = state.to_dict()

        assert data["connector_id"] == "test"
        assert data["tenant_id"] == "tenant_1"
        assert data["cursor"] == "cursor_abc"
        assert data["items_synced"] == 50
        assert data["items_total"] == 100
        assert data["status"] == "completed"
        assert len(data["errors"]) == 2

    def test_to_dict_truncates_errors(self):
        """Test that to_dict keeps only last 10 errors."""
        state = SyncState(
            connector_id="test",
            errors=[f"error_{i}" for i in range(20)],
        )

        data = state.to_dict()

        assert len(data["errors"]) == 10
        assert data["errors"][0] == "error_10"  # Last 10 errors
        assert data["errors"][-1] == "error_19"

    def test_from_dict_deserialization(self):
        """Test deserializing SyncState from dictionary."""
        data = {
            "connector_id": "test",
            "tenant_id": "tenant_2",
            "cursor": "cursor_xyz",
            "last_sync_at": "2024-01-15T10:30:00+00:00",
            "last_item_id": "item_50",
            "last_item_timestamp": "2024-01-15T10:25:00+00:00",
            "items_synced": 25,
            "items_total": 50,
            "errors": ["err1"],
            "status": "running",
            "started_at": "2024-01-15T10:00:00+00:00",
            "completed_at": None,
        }

        state = SyncState.from_dict(data)

        assert state.connector_id == "test"
        assert state.tenant_id == "tenant_2"
        assert state.cursor == "cursor_xyz"
        assert state.last_sync_at is not None
        assert state.last_sync_at.year == 2024
        assert state.items_synced == 25
        assert state.status == SyncStatus.RUNNING

    def test_from_dict_with_defaults(self):
        """Test from_dict handles missing optional fields."""
        data = {"connector_id": "minimal"}

        state = SyncState.from_dict(data)

        assert state.connector_id == "minimal"
        assert state.tenant_id == "default"
        assert state.cursor is None
        assert state.status == SyncStatus.IDLE

    def test_save_and_load(self, tmp_path):
        """Test persisting and loading state from file."""
        state = SyncState(
            connector_id="test",
            cursor="persisted_cursor",
            items_synced=42,
            status=SyncStatus.COMPLETED,
        )

        path = tmp_path / "state.json"
        state.save(path)

        assert path.exists()

        loaded = SyncState.load(path)

        assert loaded is not None
        assert loaded.connector_id == "test"
        assert loaded.cursor == "persisted_cursor"
        assert loaded.items_synced == 42

    def test_load_nonexistent_file(self, tmp_path):
        """Test loading from nonexistent file returns None."""
        path = tmp_path / "nonexistent.json"

        result = SyncState.load(path)

        assert result is None

    def test_load_invalid_json(self, tmp_path):
        """Test loading invalid JSON returns None."""
        path = tmp_path / "invalid.json"
        path.write_text("not valid json {")

        result = SyncState.load(path)

        assert result is None

    def test_save_creates_parent_directories(self, tmp_path):
        """Test save creates parent directories if needed."""
        state = SyncState(connector_id="test")
        path = tmp_path / "nested" / "dirs" / "state.json"

        state.save(path)

        assert path.exists()


# =============================================================================
# SyncResult Tests
# =============================================================================


class TestSyncResult:
    """Tests for SyncResult dataclass."""

    def test_creation_and_properties(self):
        """Test SyncResult creation and computed properties."""
        result = SyncResult(
            connector_id="test",
            success=True,
            items_synced=10,
            items_updated=5,
            items_skipped=3,
            items_failed=2,
            duration_ms=1500.5,
            errors=["warning1"],
            new_cursor="cursor_new",
        )

        assert result.connector_id == "test"
        assert result.success is True
        assert result.items_total == 20  # 10 + 5 + 3 + 2
        assert result.duration_ms == 1500.5
        assert result.new_cursor == "cursor_new"

    def test_to_dict(self):
        """Test SyncResult serialization."""
        result = SyncResult(
            connector_id="test",
            success=False,
            items_synced=0,
            items_updated=0,
            items_skipped=0,
            items_failed=1,
            duration_ms=100.0,
            errors=["Connection failed"],
        )

        data = result.to_dict()

        assert data["connector_id"] == "test"
        assert data["success"] is False
        assert data["items_failed"] == 1
        assert "Connection failed" in data["errors"]


# =============================================================================
# SyncItem Tests
# =============================================================================


class TestSyncItem:
    """Tests for SyncItem dataclass."""

    def test_creation_with_defaults(self):
        """Test SyncItem creation with default values."""
        item = SyncItem(
            id="item_1",
            content="Test content",
            source_type="document",
            source_id="doc_123",
        )

        assert item.id == "item_1"
        assert item.content == "Test content"
        assert item.title == ""
        assert item.url == ""
        assert item.author == ""
        assert item.domain == "general"
        assert item.confidence == 0.7
        assert item.metadata == {}
        assert item.content_hash is None

    def test_to_evidence_conversion(self):
        """Test converting SyncItem to Evidence."""
        item = SyncItem(
            id="item_1",
            content="Evidence content",
            source_type="document",
            source_id="doc_123",
            title="Evidence Title",
            url="https://example.com/doc",
            author="Author Name",
            created_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
            confidence=0.9,
            metadata={"key": "value"},
        )

        evidence = item.to_evidence(SourceType.DOCUMENT)

        assert evidence.id == "item_1"
        assert evidence.content == "Evidence content"
        assert evidence.source_type == SourceType.DOCUMENT
        assert evidence.source_id == "doc_123"
        assert evidence.title == "Evidence Title"
        assert evidence.url == "https://example.com/doc"
        assert evidence.confidence == 0.9

    def test_has_changed_new_item(self):
        """Test has_changed returns True for new items."""
        item = SyncItem(
            id="item_1",
            content="Content",
            source_type="document",
            source_id="doc_1",
            content_hash="abc123",
        )

        assert item.has_changed(None) is True

    def test_has_changed_no_current_hash(self):
        """Test has_changed returns True when no current hash."""
        item = SyncItem(
            id="item_1",
            content="Content",
            source_type="document",
            source_id="doc_1",
        )

        assert item.has_changed("previous_hash") is True

    def test_has_changed_same_hash(self):
        """Test has_changed returns False for matching hash."""
        item = SyncItem(
            id="item_1",
            content="Content",
            source_type="document",
            source_id="doc_1",
            content_hash="abc123",
        )

        assert item.has_changed("abc123") is False

    def test_has_changed_different_hash(self):
        """Test has_changed returns True for different hash."""
        item = SyncItem(
            id="item_1",
            content="Content",
            source_type="document",
            source_id="doc_1",
            content_hash="abc123",
        )

        assert item.has_changed("xyz789") is True

    def test_compute_content_hash(self):
        """Test computing content hash."""
        item = SyncItem(
            id="item_1",
            content="Test content for hashing",
            source_type="document",
            source_id="doc_1",
        )

        hash_value = item.compute_content_hash()

        # Verify it's a valid SHA-256 hash
        assert len(hash_value) == 64
        assert all(c in "0123456789abcdef" for c in hash_value)

        # Verify it's deterministic
        assert hash_value == item.compute_content_hash()

    def test_compute_content_hash_uses_existing(self):
        """Test compute_content_hash returns existing hash if present."""
        item = SyncItem(
            id="item_1",
            content="Content",
            source_type="document",
            source_id="doc_1",
            content_hash="precomputed_hash",
        )

        assert item.compute_content_hash() == "precomputed_hash"


# =============================================================================
# EnvCredentialProvider Tests
# =============================================================================


class TestEnvCredentialProvider:
    """Tests for EnvCredentialProvider."""

    @pytest.mark.asyncio
    async def test_get_credential_from_env(self):
        """Test getting credential from environment."""
        provider = EnvCredentialProvider(prefix="TEST_")

        with patch.dict("os.environ", {"TEST_API_KEY": "secret123"}):
            value = await provider.get_credential("API_KEY")
            assert value == "secret123"

    @pytest.mark.asyncio
    async def test_get_credential_missing(self):
        """Test getting missing credential returns None."""
        provider = EnvCredentialProvider(prefix="MISSING_")

        value = await provider.get_credential("NONEXISTENT_KEY")

        assert value is None

    @pytest.mark.asyncio
    async def test_get_credential_default_prefix(self):
        """Test default ARAGORA_ prefix."""
        provider = EnvCredentialProvider()

        with patch.dict("os.environ", {"ARAGORA_SECRET": "value123"}):
            value = await provider.get_credential("SECRET")
            assert value == "value123"

    @pytest.mark.asyncio
    async def test_set_credential(self):
        """Test setting credential in environment."""
        provider = EnvCredentialProvider(prefix="SET_")

        await provider.set_credential("NEW_KEY", "new_value")

        import os

        assert os.environ.get("SET_NEW_KEY") == "new_value"
        # Cleanup
        del os.environ["SET_NEW_KEY"]


# =============================================================================
# EnterpriseConnector Initialization Tests
# =============================================================================


class TestEnterpriseConnectorInit:
    """Tests for EnterpriseConnector initialization."""

    def test_init_with_defaults(self, tmp_path):
        """Test initialization with default values."""
        with patch(
            "aragora.persistence.db_config.get_nomic_dir",
            return_value=tmp_path,
        ):
            connector = MockEnterpriseConnector()

            assert connector.connector_id == "test_connector"
            assert connector.tenant_id == "default"
            assert connector._enable_circuit_breaker is True
            assert connector._is_syncing is False

    def test_init_with_custom_values(self, tmp_path):
        """Test initialization with custom values."""
        credentials = EnvCredentialProvider(prefix="CUSTOM_")

        connector = MockEnterpriseConnector(
            tenant_id="custom_tenant",
            credentials=credentials,
            state_dir=tmp_path / "custom_state",
            enable_circuit_breaker=False,
        )

        assert connector.tenant_id == "custom_tenant"
        assert connector.credentials == credentials
        assert connector.state_dir == tmp_path / "custom_state"
        assert connector._enable_circuit_breaker is False

    def test_state_path_property(self, tmp_path):
        """Test state_path property."""
        connector = MockEnterpriseConnector(
            tenant_id="tenant_a",
            state_dir=tmp_path,
        )

        expected = tmp_path / "test_connector_tenant_a.json"
        assert connector.state_path == expected


# =============================================================================
# Circuit Breaker Tests
# =============================================================================


class TestCircuitBreaker:
    """Tests for circuit breaker integration."""

    def test_check_circuit_breaker_disabled(self, tmp_path):
        """Test circuit breaker check when disabled."""
        connector = MockEnterpriseConnector(
            state_dir=tmp_path,
            enable_circuit_breaker=False,
        )

        assert connector.check_circuit_breaker() is True

    def test_check_circuit_breaker_enabled(self, tmp_path):
        """Test circuit breaker check when enabled."""
        mock_cb = MagicMock()
        mock_cb.can_proceed.return_value = True

        connector = MockEnterpriseConnector(
            state_dir=tmp_path,
            enable_circuit_breaker=True,
        )
        connector._circuit_breaker = mock_cb

        assert connector.check_circuit_breaker() is True
        mock_cb.can_proceed.assert_called_once()

    def test_record_success(self, tmp_path):
        """Test recording successful API call."""
        mock_cb = MagicMock()

        connector = MockEnterpriseConnector(state_dir=tmp_path)
        connector._circuit_breaker = mock_cb

        connector.record_success()

        mock_cb.record_success.assert_called_once()

    def test_record_failure(self, tmp_path):
        """Test recording failed API call."""
        mock_cb = MagicMock()

        connector = MockEnterpriseConnector(state_dir=tmp_path)
        connector._circuit_breaker = mock_cb

        connector.record_failure()

        mock_cb.record_failure.assert_called_once()

    def test_get_circuit_breaker_status_disabled(self, tmp_path):
        """Test getting status when circuit breaker disabled."""
        connector = MockEnterpriseConnector(
            state_dir=tmp_path,
            enable_circuit_breaker=False,
        )
        connector._circuit_breaker = None

        status = connector.get_circuit_breaker_status()

        assert status == {"enabled": False}

    def test_get_circuit_breaker_status_enabled(self, tmp_path):
        """Test getting status when circuit breaker enabled."""
        mock_cb = MagicMock()
        mock_cb.get_status.return_value = "closed"
        mock_cb.failures = 2
        mock_cb.failure_threshold = 5
        mock_cb.cooldown_seconds = 60.0

        connector = MockEnterpriseConnector(state_dir=tmp_path)
        connector._circuit_breaker = mock_cb

        status = connector.get_circuit_breaker_status()

        assert status["enabled"] is True
        assert status["status"] == "closed"
        assert status["failures"] == 2
        assert status["failure_threshold"] == 5

    @pytest.mark.asyncio
    async def test_execute_with_circuit_breaker_open(self, tmp_path):
        """Test execution when circuit breaker is open."""
        from aragora.connectors.exceptions import ConnectorAPIError

        connector = MockEnterpriseConnector(state_dir=tmp_path)
        connector._circuit_breaker = MagicMock()
        connector._circuit_breaker.can_proceed.return_value = False

        with pytest.raises(ConnectorAPIError) as exc_info:
            await connector.execute_with_circuit_breaker(
                AsyncMock(),
                operation="test_op",
            )

        assert "Circuit breaker open" in str(exc_info.value)


# =============================================================================
# Sync State Management Tests
# =============================================================================


class TestSyncStateManagement:
    """Tests for sync state loading and saving."""

    def test_load_state_creates_new(self, tmp_path):
        """Test load_state creates new state if file doesn't exist."""
        connector = MockEnterpriseConnector(
            tenant_id="new_tenant",
            state_dir=tmp_path,
        )

        state = connector.load_state()

        assert state.connector_id == "test_connector"
        assert state.tenant_id == "new_tenant"
        assert state.status == SyncStatus.IDLE

    def test_load_state_uses_cached(self, tmp_path):
        """Test load_state returns cached state."""
        connector = MockEnterpriseConnector(state_dir=tmp_path)

        state1 = connector.load_state()
        state1.cursor = "modified"

        state2 = connector.load_state()

        assert state2 is state1
        assert state2.cursor == "modified"

    def test_load_state_from_file(self, tmp_path):
        """Test load_state loads from existing file."""
        # Create state file
        state_file = tmp_path / "test_connector_default.json"
        state_file.write_text(
            json.dumps(
                {
                    "connector_id": "test_connector",
                    "tenant_id": "default",
                    "cursor": "existing_cursor",
                    "items_synced": 100,
                    "status": "completed",
                }
            )
        )

        connector = MockEnterpriseConnector(state_dir=tmp_path)
        state = connector.load_state()

        assert state.cursor == "existing_cursor"
        assert state.items_synced == 100

    def test_save_state(self, tmp_path):
        """Test save_state persists to file."""
        connector = MockEnterpriseConnector(state_dir=tmp_path)
        state = connector.load_state()
        state.cursor = "new_cursor"
        state.items_synced = 50

        connector.save_state()

        # Verify file contents
        state_file = tmp_path / "test_connector_default.json"
        assert state_file.exists()

        data = json.loads(state_file.read_text())
        assert data["cursor"] == "new_cursor"
        assert data["items_synced"] == 50


# =============================================================================
# Sync Operation Tests
# =============================================================================


class TestSyncOperations:
    """Tests for sync method functionality."""

    @pytest.mark.asyncio
    async def test_sync_full_sync(self, tmp_path):
        """Test full sync clears cursor."""
        items = [
            SyncItem(
                id="item_1",
                content="Content 1",
                source_type="doc",
                source_id="doc_1",
            ),
        ]

        connector = MockEnterpriseConnector(
            items_to_yield=items,
            state_dir=tmp_path,
        )

        # Set existing cursor
        state = connector.load_state()
        state.cursor = "old_cursor"

        with patch.object(
            connector, "_ingest_item", new_callable=AsyncMock, return_value="created"
        ):
            result = await connector.sync(full_sync=True)

        assert result.success is True
        assert result.items_synced == 1

    @pytest.mark.asyncio
    async def test_sync_already_running(self, tmp_path):
        """Test sync returns early if already running."""
        connector = MockEnterpriseConnector(state_dir=tmp_path)
        connector._is_syncing = True

        result = await connector.sync()

        assert result.success is False
        assert "already in progress" in result.errors[0]

    @pytest.mark.asyncio
    async def test_sync_with_max_items(self, tmp_path):
        """Test sync respects max_items limit."""
        items = [
            SyncItem(
                id=f"item_{i}",
                content=f"Content {i}",
                source_type="doc",
                source_id=f"doc_{i}",
            )
            for i in range(10)
        ]

        connector = MockEnterpriseConnector(
            items_to_yield=items,
            state_dir=tmp_path,
        )

        with patch.object(
            connector, "_ingest_item", new_callable=AsyncMock, return_value="created"
        ):
            result = await connector.sync(max_items=3)

        assert result.items_synced == 3

    @pytest.mark.asyncio
    async def test_sync_cancellation(self, tmp_path):
        """Test sync can be cancelled during processing."""
        items = [
            SyncItem(
                id=f"item_{i}",
                content=f"Content {i}",
                source_type="doc",
                source_id=f"doc_{i}",
            )
            for i in range(100)
        ]

        connector = MockEnterpriseConnector(
            items_to_yield=items,
            state_dir=tmp_path,
        )

        items_processed = []

        async def ingest_and_maybe_cancel(item):
            items_processed.append(item)
            # Cancel after processing a few items
            if len(items_processed) >= 5:
                connector.cancel_sync()
            return "created"

        with patch.object(connector, "_ingest_item", side_effect=ingest_and_maybe_cancel):
            result = await connector.sync()

        state = connector.load_state()
        assert state.status == SyncStatus.CANCELLED
        # Should have processed some items but not all 100
        assert 5 <= len(items_processed) < 100

    @pytest.mark.asyncio
    async def test_sync_handles_item_errors(self, tmp_path):
        """Test sync handles individual item errors gracefully."""
        items = [
            SyncItem(id="item_1", content="Content 1", source_type="doc", source_id="doc_1"),
            SyncItem(id="item_2", content="Content 2", source_type="doc", source_id="doc_2"),
        ]

        connector = MockEnterpriseConnector(
            items_to_yield=items,
            state_dir=tmp_path,
        )

        # First item succeeds, second fails
        ingest_mock = AsyncMock(side_effect=["created", ValueError("Ingest failed")])

        with patch.object(connector, "_ingest_item", ingest_mock):
            result = await connector.sync()

        assert result.items_synced == 1
        assert result.items_failed == 1
        assert len(result.errors) == 1

    @pytest.mark.asyncio
    async def test_sync_exception_handling(self, tmp_path):
        """Test sync handles exceptions gracefully."""
        connector = MockEnterpriseConnector(
            raise_on_sync=RuntimeError("Sync exploded"),
            state_dir=tmp_path,
        )

        result = await connector.sync()

        assert result.success is False
        assert "Sync failed" in result.errors[0]

        state = connector.load_state()
        assert state.status == SyncStatus.FAILED

    @pytest.mark.asyncio
    async def test_sync_updates_state_timestamps(self, tmp_path):
        """Test sync updates item timestamps in state."""
        item_time = datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc)
        items = [
            SyncItem(
                id="item_1",
                content="Content",
                source_type="doc",
                source_id="doc_1",
                updated_at=item_time,
            ),
        ]

        connector = MockEnterpriseConnector(
            items_to_yield=items,
            state_dir=tmp_path,
        )

        with patch.object(
            connector, "_ingest_item", new_callable=AsyncMock, return_value="created"
        ):
            await connector.sync()

        state = connector.load_state()
        assert state.last_item_id == "item_1"
        assert state.last_item_timestamp == item_time


# =============================================================================
# SyncResult.errors Tests
# =============================================================================


class RecordingErrorsConnector(MockEnterpriseConnector):
    """Records per-source failures in state.errors, as the database and storage connectors do."""

    def __init__(
        self,
        recorded_errors: list[str],
        raise_after_items: Exception | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._recorded_errors = recorded_errors
        self._raise_after_items = raise_after_items

    async def sync_items(
        self,
        state: SyncState,
        batch_size: int = 100,
    ) -> AsyncIterator[SyncItem]:
        state.errors.extend(self._recorded_errors)
        for item in self._items_to_yield:
            yield item
        if self._raise_after_items:
            raise self._raise_after_items


class TestSyncResultErrors:
    """SyncResult.errors reports the failures recorded during the run."""

    @pytest.mark.asyncio
    async def test_reports_errors_recorded_by_sync_items(self, tmp_path):
        items = [
            SyncItem(id="orders:1", content="Content", source_type="doc", source_id="orders:1"),
        ]
        connector = RecordingErrorsConnector(
            recorded_errors=["users: sync failed"],
            items_to_yield=items,
            state_dir=tmp_path,
        )

        with patch.object(
            connector, "_ingest_item", new_callable=AsyncMock, return_value="created"
        ):
            result = await connector.sync()

        state = connector.load_state()
        assert result.success is True
        assert result.items_synced == 1
        assert result.items_failed == 0
        assert result.errors == ["users: sync failed"]
        assert state.errors == ["users: sync failed"]
        assert result.errors is not state.errors

    @pytest.mark.asyncio
    async def test_reports_recorded_and_ingest_errors_once_in_order(self, tmp_path):
        items = [
            SyncItem(id="item_1", content="Content 1", source_type="doc", source_id="doc_1"),
            SyncItem(id="item_2", content="Content 2", source_type="doc", source_id="doc_2"),
        ]
        connector = RecordingErrorsConnector(
            recorded_errors=["users: sync failed"],
            items_to_yield=items,
            state_dir=tmp_path,
        )
        ingest_mock = AsyncMock(side_effect=["created", ValueError("Ingest failed")])

        with patch.object(connector, "_ingest_item", ingest_mock):
            result = await connector.sync()

        assert result.success is True
        assert result.items_synced == 1
        assert result.items_failed == 1
        assert result.errors == [
            "users: sync failed",
            "Failed to ingest item_2: Ingest failed",
        ]

    @pytest.mark.asyncio
    async def test_failed_run_reports_recorded_error_then_run_failure(self, tmp_path):
        connector = RecordingErrorsConnector(
            recorded_errors=["Failed to process key: boom"],
            raise_after_items=RuntimeError("Failed to process key: boom"),
            state_dir=tmp_path,
        )

        result = await connector.sync()

        assert result.success is False
        assert result.errors == [
            "Failed to process key: boom",
            "Sync failed: Failed to process key: boom",
        ]
        assert connector.load_state().status == SyncStatus.FAILED

    @pytest.mark.asyncio
    async def test_excludes_errors_saved_by_a_previous_run(self, tmp_path):
        previous = RecordingErrorsConnector(
            recorded_errors=["users: sync failed"],
            state_dir=tmp_path,
        )
        await previous.sync()

        items = [
            SyncItem(id="item_1", content="Content", source_type="doc", source_id="doc_1"),
        ]
        connector = RecordingErrorsConnector(
            recorded_errors=[],
            items_to_yield=items,
            state_dir=tmp_path,
        )
        assert connector.load_state().errors == ["users: sync failed"]

        with patch.object(
            connector, "_ingest_item", new_callable=AsyncMock, return_value="created"
        ):
            result = await connector.sync()

        assert result.success is True
        assert result.errors == []


# =============================================================================
# Callback Tests
# =============================================================================


class TestCallbacks:
    """Tests for sync callbacks."""

    @pytest.mark.asyncio
    async def test_on_item_synced_callback(self, tmp_path):
        """Test on_item_synced callback is called."""
        items = [
            SyncItem(id="item_1", content="Content", source_type="doc", source_id="doc_1"),
        ]

        connector = MockEnterpriseConnector(
            items_to_yield=items,
            state_dir=tmp_path,
        )

        callback_calls = []
        connector.on_item_synced(lambda item: callback_calls.append(item))

        with patch.object(
            connector, "_ingest_item", new_callable=AsyncMock, return_value="created"
        ):
            await connector.sync()

        assert len(callback_calls) == 1
        assert callback_calls[0].id == "item_1"

    @pytest.mark.asyncio
    async def test_on_progress_callback(self, tmp_path):
        """Test on_progress callback is called."""
        items = [
            SyncItem(
                id=f"item_{i}", content=f"Content {i}", source_type="doc", source_id=f"doc_{i}"
            )
            for i in range(3)
        ]

        connector = MockEnterpriseConnector(
            items_to_yield=items,
            state_dir=tmp_path,
        )

        progress_calls = []
        connector.on_progress(lambda synced, total: progress_calls.append((synced, total)))

        with patch.object(
            connector, "_ingest_item", new_callable=AsyncMock, return_value="created"
        ):
            await connector.sync()

        assert len(progress_calls) == 3


# =============================================================================
# Sync Status Tests
# =============================================================================


class TestGetSyncStatus:
    """Tests for get_sync_status method."""

    @pytest.mark.asyncio
    async def test_get_sync_status(self, tmp_path):
        """Test getting sync status."""
        connector = MockEnterpriseConnector(
            tenant_id="status_tenant",
            state_dir=tmp_path,
        )

        state = connector.load_state()
        state.cursor = "test_cursor"
        state.items_synced = 42
        state.errors = ["error1", "error2"]

        status = await connector.get_sync_status()

        assert status["connector_id"] == "test_connector"
        assert status["connector_name"] == "Mock Enterprise"
        assert status["tenant_id"] == "status_tenant"
        assert status["cursor"] == "test_cursor"
        assert status["items_synced"] == 42
        assert len(status["errors"]) == 2


# =============================================================================
# Webhook Tests
# =============================================================================


class TestWebhookHandling:
    """Tests for webhook functionality."""

    @pytest.mark.asyncio
    async def test_handle_webhook_default(self, tmp_path):
        """Test default webhook handler returns False."""
        connector = MockEnterpriseConnector(state_dir=tmp_path)

        result = await connector.handle_webhook({"event": "test"})

        assert result is False

    def test_get_webhook_secret_default(self, tmp_path):
        """Test default webhook secret is None."""
        connector = MockEnterpriseConnector(state_dir=tmp_path)

        assert connector.get_webhook_secret() is None

    def test_verify_webhook_signature_no_secret(self, tmp_path):
        """Test signature verification skipped when no secret."""
        connector = MockEnterpriseConnector(state_dir=tmp_path)

        result = connector.verify_webhook_signature(b"payload", "signature")

        assert result is True  # Verification skipped

    def test_verify_webhook_signature_valid(self, tmp_path):
        """Test valid signature verification."""
        connector = MockEnterpriseConnector(state_dir=tmp_path)

        secret = "test_secret"
        payload = b"test_payload"
        expected_sig = hmac.new(
            secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()

        with patch.object(connector, "get_webhook_secret", return_value=secret):
            result = connector.verify_webhook_signature(payload, expected_sig)

        assert result is True

    def test_verify_webhook_signature_invalid(self, tmp_path):
        """Test invalid signature verification."""
        connector = MockEnterpriseConnector(state_dir=tmp_path)

        with patch.object(connector, "get_webhook_secret", return_value="secret"):
            result = connector.verify_webhook_signature(b"payload", "invalid_sig")

        assert result is False


# =============================================================================
# Abstract Method Tests
# =============================================================================


class TestAbstractMethods:
    """Tests for abstract method implementations."""

    @pytest.mark.asyncio
    async def test_search_method(self, tmp_path):
        """Test search method implementation."""
        evidence = Evidence(
            id="ev_1",
            source_type=SourceType.DOCUMENT,
            source_id="doc_1",
            content="Search result",
            title="Result Title",
        )

        connector = MockEnterpriseConnector(
            search_results=[evidence],
            state_dir=tmp_path,
        )

        results = await connector.search("test query", limit=5)

        assert len(results) == 1
        assert results[0].id == "ev_1"

    @pytest.mark.asyncio
    async def test_fetch_method(self, tmp_path):
        """Test fetch method implementation."""
        evidence = Evidence(
            id="ev_1",
            source_type=SourceType.DOCUMENT,
            source_id="doc_1",
            content="Fetched content",
            title="Fetched Title",
        )

        connector = MockEnterpriseConnector(
            fetch_result=evidence,
            state_dir=tmp_path,
        )

        result = await connector.fetch("ev_1")

        assert result is not None
        assert result.id == "ev_1"

    def test_source_type_property(self, tmp_path):
        """Test source_type property."""
        connector = MockEnterpriseConnector(state_dir=tmp_path)

        assert connector.source_type == SourceType.DOCUMENT

    def test_name_property(self, tmp_path):
        """Test name property."""
        connector = MockEnterpriseConnector(state_dir=tmp_path)

        assert connector.name == "Mock Enterprise"


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntegration:
    """Integration tests for EnterpriseConnector."""

    @pytest.mark.asyncio
    async def test_full_sync_workflow(self, tmp_path):
        """Test complete sync workflow."""
        items = [
            SyncItem(
                id=f"item_{i}",
                content=f"Content {i}",
                source_type="document",
                source_id=f"doc_{i}",
                title=f"Document {i}",
                updated_at=datetime.now(timezone.utc),
            )
            for i in range(5)
        ]

        connector = MockEnterpriseConnector(
            items_to_yield=items,
            tenant_id="integration_test",
            state_dir=tmp_path,
        )

        # Track callbacks
        synced_items = []
        connector.on_item_synced(lambda item: synced_items.append(item))

        with patch.object(
            connector, "_ingest_item", new_callable=AsyncMock, return_value="created"
        ):
            # First sync
            result1 = await connector.sync()

        assert result1.success is True
        assert result1.items_synced == 5
        assert len(synced_items) == 5

        # Verify state persisted
        state = connector.load_state()
        assert state.status == SyncStatus.COMPLETED
        assert state.items_synced == 5

    @pytest.mark.asyncio
    async def test_health_check_available(self, tmp_path):
        """Test health check when connector is available."""
        connector = MockEnterpriseConnector(state_dir=tmp_path)

        health = await connector.health_check()

        assert health.name == "Mock Enterprise"
        assert health.is_available is True
        assert health.is_healthy is True

    @pytest.mark.asyncio
    async def test_connector_repr(self, tmp_path):
        """Test connector string representation."""
        connector = MockEnterpriseConnector(state_dir=tmp_path)

        repr_str = repr(connector)

        assert "MockEnterpriseConnector" in repr_str
        assert "document" in repr_str
