"""
Tests for Decision Result Store.

Tests cover:
- Basic CRUD operations
- TTL expiration
- LRU eviction
- In-memory caching
- Persistence across restarts
"""

import pytest
import time
from pathlib import Path

from aragora.storage.decision_result_store import (
    DecisionOwnershipConflict,
    DecisionResultStore,
    DecisionResultEntry,
    get_decision_result_store,
    reset_decision_result_store,
)


class TestDecisionResultEntry:
    """Tests for DecisionResultEntry dataclass."""

    def test_create_entry(self):
        """Should create entry with defaults."""
        entry = DecisionResultEntry(
            request_id="req-123",
            status="completed",
            result={"answer": "test"},
        )

        assert entry.request_id == "req-123"
        assert entry.status == "completed"
        assert entry.result == {"answer": "test"}
        assert entry.created_at > 0

    def test_entry_to_dict(self):
        """Should convert to dictionary."""
        entry = DecisionResultEntry(
            request_id="req-123",
            status="completed",
            result={"answer": "test"},
            completed_at="2024-01-01T00:00:00",
        )

        data = entry.to_dict()
        assert data["request_id"] == "req-123"
        assert data["status"] == "completed"
        assert data["completed_at"] == "2024-01-01T00:00:00"

    def test_entry_from_dict(self):
        """Should create from dictionary."""
        data = {
            "request_id": "req-456",
            "status": "failed",
            "result": {"error": "test"},
            "error": "Something went wrong",
        }

        entry = DecisionResultEntry.from_dict(data)
        assert entry.request_id == "req-456"
        assert entry.status == "failed"
        assert entry.error == "Something went wrong"

    def test_entry_expiration(self):
        """Should detect expired entries."""
        # Create entry with 0 TTL (already expired)
        entry = DecisionResultEntry(
            request_id="req-123",
            status="completed",
            result={},
            ttl_seconds=0,
            created_at=time.time() - 1,
        )

        assert entry.is_expired is True

        # Create entry with long TTL
        entry2 = DecisionResultEntry(
            request_id="req-456",
            status="completed",
            result={},
            ttl_seconds=3600,
        )

        assert entry2.is_expired is False


class TestDecisionResultStore:
    """Tests for DecisionResultStore."""

    @pytest.fixture
    def temp_db(self, tmp_path):
        """Create a temporary database path."""
        return tmp_path / "test_decisions.db"

    @pytest.fixture
    def store(self, temp_db):
        """Create a fresh store instance."""
        return DecisionResultStore(
            db_path=temp_db,
            ttl_seconds=3600,
            max_entries=100,
            cache_size=10,
        )

    def test_save_and_get(self, store):
        """Should save and retrieve decision results."""
        store.save(
            "req-123",
            {
                "status": "completed",
                "result": {"answer": "42"},
                "completed_at": "2024-01-01T00:00:00",
            },
        )

        result = store.get("req-123")
        assert result is not None
        assert result["request_id"] == "req-123"
        assert result["status"] == "completed"
        assert result["result"]["answer"] == "42"
        assert result["org_id"] is None
        assert result["created_by"] is None

    def test_get_nonexistent(self, store):
        """Should return None for nonexistent entries."""
        result = store.get("nonexistent")
        assert result is None

    def test_get_status(self, store):
        """Should return status for polling."""
        store.save(
            "req-123",
            {
                "status": "completed",
                "completed_at": "2024-01-01T00:00:00",
            },
        )

        status = store.get_status("req-123")
        assert status["request_id"] == "req-123"
        assert status["status"] == "completed"
        assert status["completed_at"] == "2024-01-01T00:00:00"

    def test_get_status_not_found(self, store):
        """Should return not_found status for missing entries."""
        status = store.get_status("nonexistent")
        assert status["status"] == "not_found"

    def test_list_recent(self, store):
        """Should list recent decisions."""
        for i in range(5):
            store.save(f"req-{i}", {"status": "completed"})

        recent = store.list_recent(limit=3)
        assert len(recent) == 3
        # Most recent first
        assert recent[0]["request_id"] == "req-4"

    def test_count(self, store):
        """Should count entries."""
        assert store.count() == 0

        for i in range(3):
            store.save(f"req-{i}", {"status": "completed"})

        assert store.count() == 3

    def test_delete(self, store):
        """Should delete entries."""
        store.save("req-123", {"status": "completed"})
        assert store.get("req-123") is not None

        deleted = store.delete("req-123")
        assert deleted is True
        assert store.get("req-123") is None

    def test_delete_nonexistent(self, store):
        """Should return False when deleting nonexistent entry."""
        deleted = store.delete("nonexistent")
        assert deleted is False

    def test_ttl_expiration(self, tmp_path):
        """Should expire entries after TTL."""
        store = DecisionResultStore(
            db_path=tmp_path / "ttl_test.db",
            ttl_seconds=1,  # 1 second TTL
        )

        store.save("req-123", {"status": "completed"})
        assert store.get("req-123") is not None

        # Wait for expiration
        time.sleep(1.5)

        # Should be expired now
        assert store.get("req-123") is None

    def test_lru_eviction(self, tmp_path):
        """Should evict oldest entries when max reached."""
        store = DecisionResultStore(
            db_path=tmp_path / "lru_test.db",
            max_entries=5,
            cache_size=5,
        )

        # Add more than max entries
        for i in range(10):
            store.save(f"req-{i}", {"status": "completed"})
            time.sleep(0.01)  # Small delay to ensure ordering

        # Should have at most max_entries
        assert store.count() <= 5

        # Oldest entries should be evicted, newest should remain
        assert store.get("req-9") is not None

    def test_cache_hit(self, store):
        """Should serve from cache on subsequent reads."""
        store.save("req-123", {"status": "completed"})

        # First read populates cache
        result1 = store.get("req-123")
        # Second read should hit cache
        result2 = store.get("req-123")

        assert result1 == result2

    def test_update_existing(self, store):
        """Should update existing entries."""
        store.save("req-123", {"status": "pending"})
        store.save("req-123", {"status": "completed", "result": {"answer": "done"}})

        result = store.get("req-123")
        assert result["status"] == "completed"
        assert result["result"]["answer"] == "done"

    def test_persistence_across_instances(self, temp_db):
        """Should persist data across store instances."""
        # First instance
        store1 = DecisionResultStore(db_path=temp_db)
        store1.save("req-123", {"status": "completed", "result": {"data": "test"}})

        # Second instance (simulates restart)
        store2 = DecisionResultStore(db_path=temp_db)
        result = store2.get("req-123")

        assert result is not None
        assert result["status"] == "completed"
        assert result["result"]["data"] == "test"

    def test_get_metrics(self, store):
        """Should return store metrics."""
        for i in range(5):
            store.save(f"req-{i}", {"status": "completed"})

        metrics = store.get_metrics()

        assert metrics["total_entries"] == 5
        assert "cache_size" in metrics
        assert "max_entries" in metrics
        assert "ttl_seconds" in metrics


class TestDecisionResultOwnership:
    """Tests for org ownership of decision results."""

    @pytest.fixture
    def temp_db(self, tmp_path):
        return tmp_path / "ownership.db"

    @pytest.fixture
    def store(self, temp_db):
        return DecisionResultStore(db_path=temp_db, ttl_seconds=3600)

    def test_entry_round_trips_owner(self):
        entry = DecisionResultEntry(
            request_id="req-1", status="completed", result={}, org_id="org-a", created_by="u1"
        )
        data = entry.to_dict()
        assert data["org_id"] == "org-a"
        assert data["created_by"] == "u1"
        restored = DecisionResultEntry.from_dict(data)
        assert (restored.org_id, restored.created_by) == ("org-a", "u1")

    def test_save_persists_owner(self, store, temp_db):
        store.save("req-1", {"status": "completed"}, org_id="org-a", created_by="u1")

        assert store.get("req-1")["org_id"] == "org-a"
        fresh = DecisionResultStore(db_path=temp_db).get("req-1")
        assert fresh["org_id"] == "org-a"
        assert fresh["created_by"] == "u1"

    def test_save_falls_back_to_owner_in_data(self, store):
        store.save("req-1", {"status": "completed", "org_id": "org-a", "created_by": "u1"})

        result = store.get_for_org("req-1", "org-a")
        assert result is not None
        assert result["created_by"] == "u1"

    def test_get_for_org(self, store, temp_db):
        store.save("req-a", {"status": "completed"}, org_id="org-a", created_by="u1")
        store.save("req-null", {"status": "completed"})

        assert store.get_for_org("req-a", "org-a")["request_id"] == "req-a"
        assert store.get_for_org("req-a", "org-b") is None
        assert store.get_for_org("req-null", "org-a") is None
        assert store.get_for_org("missing", "org-a") is None
        fresh = DecisionResultStore(db_path=temp_db)
        assert fresh.get_for_org("req-a", "org-b") is None
        assert fresh.get_for_org("req-a", "org-a") is not None

    def test_list_and_count_filter_by_org(self, store):
        store.save("req-a1", {"status": "completed"}, org_id="org-a")
        store.save("req-a2", {"status": "pending"}, org_id="org-a")
        store.save("req-b1", {"status": "completed"}, org_id="org-b")
        store.save("req-null", {"status": "completed"})

        listed = store.list_recent_for_org("org-a")
        assert {d["request_id"] for d in listed} == {"req-a1", "req-a2"}
        assert store.count_for_org("org-a") == 2
        assert [d["request_id"] for d in store.list_recent_for_org("org-b")] == ["req-b1"]
        assert store.count_for_org("org-b") == 1
        assert len(store.list_recent_for_org("org-a", limit=1)) == 1
        assert store.list_recent_for_org("org-none") == []
        assert store.count_for_org("org-none") == 0
        assert store.count() == 4

    def test_owner_save_updates_result_and_keeps_creator(self, store, temp_db):
        store.save("req-1", {"status": "pending"}, org_id="org-a", created_by="u1")
        store.save(
            "req-1",
            {"status": "completed", "result": {"answer": "a2"}},
            org_id="org-a",
            created_by="u3",
        )

        fresh = DecisionResultStore(db_path=temp_db).get("req-1")
        assert (fresh["status"], fresh["result"]) == ("completed", {"answer": "a2"})
        assert (fresh["org_id"], fresh["created_by"]) == ("org-a", "u1")

    @pytest.mark.parametrize("fresh_writer", [False, True])
    @pytest.mark.parametrize("writer_org", ["org-b", None])
    def test_save_over_another_orgs_result_is_rejected(
        self, store, temp_db, writer_org, fresh_writer
    ):
        store.save(
            "req-1",
            {"status": "pending", "result": {"answer": "a"}},
            org_id="org-a",
            created_by="u1",
        )
        writer = DecisionResultStore(db_path=temp_db, ttl_seconds=3600) if fresh_writer else store

        with pytest.raises(DecisionOwnershipConflict):
            writer.save(
                "req-1",
                {"status": "completed", "result": {"answer": "b"}},
                org_id=writer_org,
                created_by="u2",
            )

        for reader in (store, writer, DecisionResultStore(db_path=temp_db)):
            kept = reader.get("req-1")
            assert (kept["status"], kept["result"]) == ("pending", {"answer": "a"})
            assert (kept["org_id"], kept["created_by"]) == ("org-a", "u1")
        assert store.count_for_org("org-b") == 0

    def test_ownerless_result_is_not_claimed(self, store, temp_db):
        store.save("req-1", {"status": "pending", "result": {"answer": "legacy"}})

        with pytest.raises(DecisionOwnershipConflict):
            store.save("req-1", {"status": "completed"}, org_id="org-a", created_by="u1")

        for reader in (store, DecisionResultStore(db_path=temp_db)):
            kept = reader.get("req-1")
            assert (kept["status"], kept["result"]) == ("pending", {"answer": "legacy"})
            assert (kept["org_id"], kept["created_by"]) == (None, None)
            assert reader.get_for_org("req-1", "org-a") is None

    def test_ownership_conflict_is_a_value_error(self):
        assert issubclass(DecisionOwnershipConflict, ValueError)

    def test_migrates_table_without_owner_columns(self, temp_db):
        import sqlite3

        conn = sqlite3.connect(temp_db)
        conn.execute(
            """
            CREATE TABLE decision_results (
                request_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                result_json TEXT,
                created_at REAL NOT NULL,
                completed_at TEXT,
                error TEXT,
                expires_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO decision_results VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("req-legacy", "completed", "{}", time.time(), None, None, time.time() + 3600),
        )
        conn.commit()
        conn.close()

        store = DecisionResultStore(db_path=temp_db, ttl_seconds=3600)
        store.save("req-new", {"status": "completed"}, org_id="org-a", created_by="u1")

        columns = {
            row[1]
            for row in sqlite3.connect(temp_db).execute("PRAGMA table_info(decision_results)")
        }
        assert {"org_id", "created_by"} <= columns
        fresh = DecisionResultStore(db_path=temp_db)
        assert fresh.get_for_org("req-new", "org-a")["created_by"] == "u1"
        legacy = fresh.get("req-legacy")
        assert legacy["org_id"] is None
        assert fresh.get_for_org("req-legacy", "org-a") is None
        assert fresh.count_for_org("org-a") == 1


class TestGlobalStore:
    """Tests for global store functions."""

    def setup_method(self):
        """Reset global store before each test."""
        reset_decision_result_store()

    def test_get_decision_result_store_singleton(self, tmp_path):
        """Should return same instance."""
        import os

        os.environ["ARAGORA_DECISION_RESULTS_DB"] = str(tmp_path / "singleton.db")

        try:
            store1 = get_decision_result_store()
            store2 = get_decision_result_store()
            assert store1 is store2
        finally:
            del os.environ["ARAGORA_DECISION_RESULTS_DB"]
            reset_decision_result_store()

    def test_reset_decision_result_store(self, tmp_path):
        """Should reset global instance."""
        import os

        os.environ["ARAGORA_DECISION_RESULTS_DB"] = str(tmp_path / "reset.db")

        try:
            store1 = get_decision_result_store()
            reset_decision_result_store()
            store2 = get_decision_result_store()

            # Should be different instances after reset
            assert store1 is not store2
        finally:
            del os.environ["ARAGORA_DECISION_RESULTS_DB"]
            reset_decision_result_store()


class TestConcurrency:
    """Tests for concurrent access."""

    def test_concurrent_writes(self, tmp_path):
        """Should handle concurrent writes safely."""
        import concurrent.futures

        store = DecisionResultStore(db_path=tmp_path / "concurrent.db")

        def write_entry(i):
            store.save(f"req-{i}", {"status": "completed", "index": i})
            return i

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(write_entry, i) for i in range(100)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        assert len(results) == 100
        assert store.count() == 100

    def test_concurrent_reads(self, tmp_path):
        """Should handle concurrent reads safely."""
        import concurrent.futures

        store = DecisionResultStore(db_path=tmp_path / "concurrent_read.db")

        # Populate store
        for i in range(100):
            store.save(f"req-{i}", {"status": "completed", "index": i})

        def read_entry(i):
            return store.get(f"req-{i}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(read_entry, i) for i in range(100)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        assert len(results) == 100
        assert all(r is not None for r in results)
