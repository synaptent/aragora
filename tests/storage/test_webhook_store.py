"""
Tests for Webhook Idempotency Storage.

Tests cover:
- Mark event as processed
- Check if event was already processed (duplicate detection)
- TTL expiration (old events should be cleaned up)
- Concurrent processing of same event (race condition handling)
- SQLite backend initialization
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aragora.storage.webhook_store import (
    InMemoryWebhookStore,
    SQLiteWebhookStore,
    WebhookStoreBackend,
    get_webhook_store,
    set_webhook_store,
    reset_webhook_store,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def in_memory_store():
    """Create an in-memory webhook store with short TTL for testing."""
    return InMemoryWebhookStore(ttl_seconds=60, cleanup_interval=10)


@pytest.fixture
def sqlite_store(tmp_path):
    """Create a SQLite webhook store in a temporary directory."""
    db_path = tmp_path / "webhook_test.db"
    store = SQLiteWebhookStore(
        db_path=db_path,
        ttl_seconds=60,
        cleanup_interval=10,
    )
    yield store
    store.close()


@pytest.fixture(autouse=True)
def reset_global_store():
    """Reset global webhook store after each test."""
    yield
    reset_webhook_store()


# =============================================================================
# Test: Mark event as processed
# =============================================================================


class TestMarkEventAsProcessed:
    """Tests for marking webhook events as processed."""

    def test_mark_processed_in_memory(self, in_memory_store):
        """Should mark event as processed in in-memory store."""
        event_id = "evt_test_123"
        in_memory_store.mark_processed(event_id)

        assert in_memory_store.is_processed(event_id) is True

    def test_mark_processed_sqlite(self, sqlite_store):
        """Should mark event as processed in SQLite store."""
        event_id = "evt_test_456"
        sqlite_store.mark_processed(event_id)

        assert sqlite_store.is_processed(event_id) is True

    def test_mark_processed_with_result(self, in_memory_store):
        """Should store result along with event."""
        event_id = "evt_result_test"
        in_memory_store.mark_processed(event_id, result="success")

        assert in_memory_store.is_processed(event_id) is True

    def test_mark_processed_with_error_result(self, sqlite_store):
        """Should store error results."""
        event_id = "evt_error_test"
        sqlite_store.mark_processed(event_id, result="error: payment failed")

        assert sqlite_store.is_processed(event_id) is True

    def test_mark_processed_overwrites_previous(self, in_memory_store):
        """Re-marking an event should update timestamp."""
        event_id = "evt_overwrite_test"

        in_memory_store.mark_processed(event_id, result="first")
        time.sleep(0.01)
        in_memory_store.mark_processed(event_id, result="second")

        # Should still be marked as processed
        assert in_memory_store.is_processed(event_id) is True

    def test_mark_processed_increments_size(self, in_memory_store):
        """Marking events should increment store size."""
        initial_size = in_memory_store.size()

        in_memory_store.mark_processed("evt_1")
        in_memory_store.mark_processed("evt_2")
        in_memory_store.mark_processed("evt_3")

        assert in_memory_store.size() == initial_size + 3


# =============================================================================
# Test: Check if event was already processed (duplicate detection)
# =============================================================================


class TestDuplicateDetection:
    """Tests for checking if events were already processed."""

    def test_is_processed_returns_false_for_new_event(self, in_memory_store):
        """Should return False for events that were never processed."""
        assert in_memory_store.is_processed("evt_unknown") is False

    def test_is_processed_returns_true_for_processed_event(self, sqlite_store):
        """Should return True for events that were processed."""
        event_id = "evt_already_done"
        sqlite_store.mark_processed(event_id)

        assert sqlite_store.is_processed(event_id) is True

    def test_duplicate_detection_prevents_reprocessing(self, in_memory_store):
        """Should detect duplicates to prevent reprocessing."""
        event_id = "evt_duplicate"

        # First time: not processed
        assert in_memory_store.is_processed(event_id) is False

        # Mark as processed
        in_memory_store.mark_processed(event_id)

        # Second time: detected as duplicate
        assert in_memory_store.is_processed(event_id) is True

    def test_different_events_are_independent(self, sqlite_store):
        """Different event IDs should be tracked independently."""
        sqlite_store.mark_processed("evt_a")

        assert sqlite_store.is_processed("evt_a") is True
        assert sqlite_store.is_processed("evt_b") is False
        assert sqlite_store.is_processed("evt_c") is False

    def test_is_processed_checks_ttl(self, in_memory_store):
        """Should return False for expired events."""
        # Create store with very short TTL
        short_ttl_store = InMemoryWebhookStore(ttl_seconds=0.1)

        event_id = "evt_will_expire"
        short_ttl_store.mark_processed(event_id)

        # Immediately after: still valid
        assert short_ttl_store.is_processed(event_id) is True

        # After TTL: expired
        time.sleep(0.15)
        assert short_ttl_store.is_processed(event_id) is False


# =============================================================================
# Test: TTL expiration (old events should be cleaned up)
# =============================================================================


class TestTTLExpiration:
    """Tests for TTL-based expiration and cleanup."""

    def test_cleanup_removes_expired_events_in_memory(self):
        """Cleanup should remove expired events from in-memory store."""
        store = InMemoryWebhookStore(ttl_seconds=0.1, cleanup_interval=1)

        store.mark_processed("evt_old_1")
        store.mark_processed("evt_old_2")

        # Wait for expiration
        time.sleep(0.15)

        removed = store.cleanup_expired()
        assert removed == 2
        assert store.size() == 0

    def test_cleanup_removes_expired_events_sqlite(self, tmp_path):
        """Cleanup should remove expired events from SQLite store."""
        store = SQLiteWebhookStore(
            db_path=tmp_path / "ttl_test.db",
            ttl_seconds=0.1,
            cleanup_interval=1,
        )

        store.mark_processed("evt_sqlite_old_1")
        store.mark_processed("evt_sqlite_old_2")

        # Wait for expiration
        time.sleep(0.15)

        removed = store.cleanup_expired()
        assert removed == 2
        assert store.size() == 0

        store.close()

    def test_cleanup_keeps_non_expired_events(self):
        """Cleanup should keep events that haven't expired."""
        store = InMemoryWebhookStore(ttl_seconds=60, cleanup_interval=1)

        store.mark_processed("evt_fresh")

        removed = store.cleanup_expired()
        assert removed == 0
        assert store.is_processed("evt_fresh") is True

    def test_automatic_cleanup_on_mark_processed(self):
        """Should run automatic cleanup periodically."""
        store = InMemoryWebhookStore(ttl_seconds=0.05, cleanup_interval=0.05)

        store.mark_processed("evt_auto_cleanup_1")
        time.sleep(0.1)

        # Mark another event - should trigger cleanup
        store.mark_processed("evt_auto_cleanup_2")

        # Old event should be cleaned up (checked on access)
        assert store.is_processed("evt_auto_cleanup_1") is False
        assert store.is_processed("evt_auto_cleanup_2") is True

    def test_sqlite_ttl_check_on_is_processed(self, tmp_path):
        """SQLite is_processed should check TTL."""
        store = SQLiteWebhookStore(
            db_path=tmp_path / "ttl_check.db",
            ttl_seconds=0.1,
        )

        store.mark_processed("evt_ttl_check")
        time.sleep(0.15)

        # Should return False for expired event
        assert store.is_processed("evt_ttl_check") is False

        store.close()


# =============================================================================
# Test: Concurrent processing of same event (race condition handling)
# =============================================================================


class TestConcurrentProcessing:
    """Tests for handling concurrent access and race conditions."""

    def test_concurrent_mark_processed_in_memory(self):
        """Concurrent mark_processed calls should be thread-safe."""
        store = InMemoryWebhookStore()
        event_id = "evt_concurrent"
        errors = []

        def mark_event():
            try:
                for _ in range(100):
                    store.mark_processed(event_id)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=mark_event) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert store.is_processed(event_id) is True

    def test_concurrent_is_processed_checks(self):
        """Concurrent is_processed calls should be thread-safe."""
        store = InMemoryWebhookStore()
        event_id = "evt_concurrent_check"
        store.mark_processed(event_id)

        results = []
        errors = []

        def check_event():
            try:
                for _ in range(100):
                    result = store.is_processed(event_id)
                    results.append(result)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=check_event) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert all(r is True for r in results)

    def test_concurrent_mixed_operations(self):
        """Mixed concurrent operations should be thread-safe."""
        store = InMemoryWebhookStore()
        errors = []

        def mixed_ops(thread_id):
            try:
                for i in range(50):
                    event_id = f"evt_mixed_{thread_id}_{i}"
                    store.mark_processed(event_id)
                    assert store.is_processed(event_id) is True
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=mixed_ops, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_concurrent_cleanup(self):
        """Concurrent cleanup operations should be thread-safe."""
        store = InMemoryWebhookStore(ttl_seconds=0.01)

        # Add some events
        for i in range(100):
            store.mark_processed(f"evt_cleanup_{i}")

        time.sleep(0.02)  # Let them expire

        errors = []

        def run_cleanup():
            try:
                store.cleanup_expired()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=run_cleanup) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_sqlite_concurrent_access(self, tmp_path):
        """SQLite store should handle concurrent access."""
        db_path = tmp_path / "concurrent_sqlite.db"
        store = SQLiteWebhookStore(db_path=db_path)
        errors = []

        def sqlite_ops(thread_id):
            try:
                for i in range(20):
                    event_id = f"evt_sqlite_{thread_id}_{i}"
                    store.mark_processed(event_id)
                    store.is_processed(event_id)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=sqlite_ops, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        store.close()

    def test_sqlite_simultaneous_first_connections(self, tmp_path):
        """Threads opening their first connection at the same instant must not lock."""
        rounds = 25
        thread_count = 8
        errors: list[Exception] = []
        seen: list[bool] = []
        sizes: list[int] = []

        # Each round uses a fresh database so every thread's first connection
        # races against the others; a single round only hits the race sometimes.
        for round_idx in range(rounds):
            store = SQLiteWebhookStore(db_path=tmp_path / f"first_conn_{round_idx}.db")
            barrier = threading.Barrier(thread_count, timeout=30)

            def first_ops(thread_id, store=store, barrier=barrier, round_idx=round_idx):
                try:
                    barrier.wait()
                    event_id = f"evt_first_{round_idx}_{thread_id}"
                    store.mark_processed(event_id)
                    seen.append(store.is_processed(event_id))
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=first_ops, args=(i,)) for i in range(thread_count)]
            try:
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
                sizes.append(store.size())
            finally:
                store.close()

        assert errors == []
        assert seen == [True] * (rounds * thread_count)
        assert sizes == [thread_count] * rounds


# =============================================================================
# Test: SQLite backend initialization
# =============================================================================


class TestSQLiteBackendInitialization:
    """Tests for SQLite backend initialization and schema."""

    def test_creates_database_file(self, tmp_path):
        """Should create SQLite database file."""
        db_path = tmp_path / "new_db.db"
        assert not db_path.exists()

        store = SQLiteWebhookStore(db_path=db_path)
        assert db_path.exists()

        store.close()

    def test_creates_parent_directories(self, tmp_path):
        """Should create parent directories if they don't exist."""
        db_path = tmp_path / "nested" / "dirs" / "webhook.db"
        assert not db_path.parent.exists()

        store = SQLiteWebhookStore(db_path=db_path)
        assert db_path.exists()
        assert db_path.parent.exists()

        store.close()

    def test_initializes_schema(self, tmp_path):
        """Should create proper database schema."""
        db_path = tmp_path / "schema_test.db"
        store = SQLiteWebhookStore(db_path=db_path)

        # Connect directly to verify schema
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='webhook_events'"
        )
        assert cursor.fetchone() is not None

        # Check index exists
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_webhook_processed_at'"
        )
        assert cursor.fetchone() is not None

        conn.close()
        store.close()

    def test_uses_wal_mode(self, tmp_path):
        """Should use WAL journal mode for better concurrency."""
        db_path = tmp_path / "wal_test.db"
        store = SQLiteWebhookStore(db_path=db_path)

        # Trigger a write to ensure WAL mode is set on the connection
        store.mark_processed("evt_wal_test")

        # Check journal mode on the store's connection which has WAL enabled
        # Note: A fresh connection may not see WAL mode if the database was
        # not checkpointed, so we verify the store's internal connection uses WAL
        conn = store._get_conn()
        cursor = conn.execute("PRAGMA journal_mode")
        journal_mode = cursor.fetchone()[0].lower()
        assert journal_mode == "wal"

        store.close()

    def test_database_file_is_wal_before_first_store_connection(self, tmp_path):
        """Construction should leave the file in WAL mode before any store connection opens."""
        db_path = tmp_path / "wal_at_init.db"
        store = SQLiteWebhookStore(db_path=db_path)
        try:
            assert store._connections == set()
            conn = sqlite3.connect(str(db_path))
            try:
                journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0].lower()
            finally:
                conn.close()
            assert journal_mode == "wal"
        finally:
            store.close()

    def test_reopens_existing_database(self, tmp_path):
        """Should work with existing database."""
        db_path = tmp_path / "existing.db"

        # Create and close first store
        store1 = SQLiteWebhookStore(db_path=db_path)
        store1.mark_processed("evt_persist")
        store1.close()

        # Open new store on same database
        store2 = SQLiteWebhookStore(db_path=db_path)
        assert store2.is_processed("evt_persist") is True

        store2.close()


# =============================================================================
# Test: Global store management
# =============================================================================


class TestGlobalStoreManagement:
    """Tests for global webhook store management functions."""

    def test_get_webhook_store_creates_store(self):
        """get_webhook_store should create a store if none exists."""
        with patch.dict(os.environ, {"ARAGORA_WEBHOOK_STORE_BACKEND": "memory"}):
            with patch("aragora.storage.production_guards.require_distributed_store"):
                store = get_webhook_store()
                assert store is not None
                assert isinstance(store, WebhookStoreBackend)

    def test_set_webhook_store_uses_custom_store(self):
        """set_webhook_store should set a custom store."""
        custom_store = InMemoryWebhookStore()
        set_webhook_store(custom_store)

        retrieved = get_webhook_store()
        assert retrieved is custom_store

    def test_reset_webhook_store_clears_global(self):
        """reset_webhook_store should clear the global store."""
        custom_store = InMemoryWebhookStore()
        set_webhook_store(custom_store)

        reset_webhook_store()

        # Next get should create a new store
        with patch.dict(os.environ, {"ARAGORA_WEBHOOK_STORE_BACKEND": "memory"}):
            with patch("aragora.storage.production_guards.require_distributed_store"):
                new_store = get_webhook_store()
                assert new_store is not custom_store


# =============================================================================
# Test: Size method
# =============================================================================


class TestSizeMethod:
    """Tests for store size reporting."""

    def test_in_memory_size_accurate(self, in_memory_store):
        """In-memory store should report accurate size."""
        assert in_memory_store.size() == 0

        in_memory_store.mark_processed("evt_1")
        assert in_memory_store.size() == 1

        in_memory_store.mark_processed("evt_2")
        in_memory_store.mark_processed("evt_3")
        assert in_memory_store.size() == 3

    def test_sqlite_size_accurate(self, sqlite_store):
        """SQLite store should report accurate size."""
        assert sqlite_store.size() == 0

        sqlite_store.mark_processed("evt_1")
        assert sqlite_store.size() == 1

        sqlite_store.mark_processed("evt_2")
        sqlite_store.mark_processed("evt_3")
        assert sqlite_store.size() == 3

    def test_size_excludes_expired(self):
        """Size should only count non-expired events."""
        store = InMemoryWebhookStore(ttl_seconds=0.1)

        store.mark_processed("evt_old")
        time.sleep(0.15)
        store.mark_processed("evt_new")

        # Old event expired but not cleaned up yet
        # Size should still count unexpired entries
        # Note: is_processed handles cleanup on access
        store.is_processed("evt_old")  # Trigger cleanup
        assert store.size() == 1  # Only evt_new


# =============================================================================
# Test: Clear method (in-memory only)
# =============================================================================


class TestClearMethod:
    """Tests for clearing the in-memory store."""

    def test_clear_removes_all_entries(self, in_memory_store):
        """Clear should remove all entries from in-memory store."""
        in_memory_store.mark_processed("evt_1")
        in_memory_store.mark_processed("evt_2")
        in_memory_store.mark_processed("evt_3")

        in_memory_store.clear()

        assert in_memory_store.size() == 0
        assert in_memory_store.is_processed("evt_1") is False
        assert in_memory_store.is_processed("evt_2") is False


# =============================================================================
# Test: Edge cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_event_id(self, in_memory_store):
        """Should handle empty event ID."""
        in_memory_store.mark_processed("")
        assert in_memory_store.is_processed("") is True

    def test_unicode_event_id(self, sqlite_store):
        """Should handle unicode event IDs."""
        event_id = "evt_unicode_\u4e2d\u6587"
        sqlite_store.mark_processed(event_id)
        assert sqlite_store.is_processed(event_id) is True

    def test_long_event_id(self, in_memory_store):
        """Should handle very long event IDs."""
        event_id = "evt_" + "x" * 1000
        in_memory_store.mark_processed(event_id)
        assert in_memory_store.is_processed(event_id) is True

    def test_special_characters_in_event_id(self, sqlite_store):
        """Should handle special characters in event IDs."""
        event_id = "evt_special_!@#$%^&*()_+-=[]{}|;':\",./<>?"
        sqlite_store.mark_processed(event_id)
        assert sqlite_store.is_processed(event_id) is True

    def test_base_backend_default_size(self):
        """WebhookStoreBackend.size() should return -1 by default."""

        # Create a minimal implementation to test base class
        class MinimalBackend(WebhookStoreBackend):
            def is_processed(self, event_id: str) -> bool:
                return False

            def mark_processed(self, event_id: str, result: str = "success") -> None:
                pass

            def cleanup_expired(self) -> int:
                return 0

        backend = MinimalBackend()
        assert backend.size() == -1

    def test_sqlite_close_all_connections(self, tmp_path):
        """close() should close all database connections."""
        db_path = tmp_path / "close_test.db"
        store = SQLiteWebhookStore(db_path=db_path)

        # Create a connection by accessing the store
        store.mark_processed("evt_close")

        # Close should not raise
        store.close()

        # Multiple closes should not raise
        store.close()
