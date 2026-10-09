"""
Tests for Decision Result Store.

Tests cover:
- Basic CRUD operations
- TTL expiration
- LRU eviction
- In-memory caching
- Persistence across restarts
"""

import logging
import pytest
import sqlite3
import threading
import time
from contextlib import closing, contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import aragora.storage.decision_result_store as store_module
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

    @pytest.mark.parametrize("write_path", ["save", "claim"])
    def test_lru_eviction(self, tmp_path, write_path):
        """Should evict oldest entries when max reached."""
        store = DecisionResultStore(
            db_path=tmp_path / "lru_test.db",
            max_entries=5,
            cache_size=5,
        )

        # Add more than max entries
        for i in range(10):
            if write_path == "save":
                store.save(f"req-{i}", {"status": "completed"})
            else:
                store.claim(f"req-{i}", {"status": "pending"}, org_id="org-a")
                store.save_if_status(
                    f"req-{i}", {"status": "completed"}, org_id="org-a", expected_status="pending"
                )
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


class TestDecisionResultClaimAndConditionalSave:
    """A claim never overwrites a stored result; a conditional save only lands on an unchanged one."""

    @pytest.fixture
    def temp_db(self, tmp_path):
        return tmp_path / "claims.db"

    @pytest.fixture
    def store(self, temp_db):
        return DecisionResultStore(db_path=temp_db, ttl_seconds=3600)

    def test_claim_of_a_new_id_stores_it(self, store, temp_db):
        claimed = store.claim(
            "req-1",
            {"status": "pending", "result": {"request": {"content": "Q"}}},
            org_id="org-a",
            created_by="u1",
        )

        assert claimed == "pending"
        for reader in (store, DecisionResultStore(db_path=temp_db)):
            saved = reader.get("req-1")
            assert (saved["status"], saved["result"]) == ("pending", {"request": {"content": "Q"}})
            assert (saved["org_id"], saved["created_by"]) == ("org-a", "u1")

    def test_claim_keeps_the_owners_existing_result(self, store, temp_db):
        store.save(
            "req-1",
            {"status": "completed", "result": {"answer": "a"}},
            org_id="org-a",
            created_by="u1",
        )

        claimed = store.claim("req-1", {"status": "pending"}, org_id="org-a", created_by="u2")

        assert claimed == "completed"
        for reader in (store, DecisionResultStore(db_path=temp_db)):
            kept = reader.get("req-1")
            assert (kept["status"], kept["result"]) == ("completed", {"answer": "a"})
            assert kept["created_by"] == "u1"

    @pytest.mark.parametrize("owner", ["org-b", None])
    def test_claim_of_an_id_owned_elsewhere_is_rejected(self, store, temp_db, owner):
        store.save("req-1", {"status": "completed", "result": {"answer": "theirs"}}, org_id=owner)

        with pytest.raises(DecisionOwnershipConflict):
            store.claim("req-1", {"status": "pending"}, org_id="org-a", created_by="u1")

        kept = DecisionResultStore(db_path=temp_db).get("req-1")
        assert (kept["status"], kept["result"], kept["org_id"]) == (
            "completed",
            {"answer": "theirs"},
            owner,
        )

    def test_save_if_status_applies_while_the_status_is_unchanged(self, store, temp_db):
        store.claim("req-1", {"status": "pending"}, org_id="org-a", created_by="u1")

        saved = store.save_if_status(
            "req-1",
            {"status": "completed", "result": {"answer": "a"}, "completed_at": "done-at"},
            org_id="org-a",
            expected_status="pending",
        )

        assert saved is True
        for reader in (store, DecisionResultStore(db_path=temp_db)):
            stored = reader.get("req-1")
            assert (stored["status"], stored["result"]) == ("completed", {"answer": "a"})
            assert (stored["completed_at"], stored["created_by"]) == ("done-at", "u1")

    def test_save_if_status_leaves_a_changed_result_alone(self, store, temp_db):
        store.claim("req-1", {"status": "pending"}, org_id="org-a", created_by="u1")
        DecisionResultStore(db_path=temp_db).save(
            "req-1", {"status": "cancelled"}, org_id="org-a", created_by="u1"
        )

        saved = store.save_if_status(
            "req-1",
            {"status": "completed", "result": {"answer": "late"}},
            org_id="org-a",
            expected_status="pending",
        )

        assert saved is False
        for reader in (store, DecisionResultStore(db_path=temp_db)):
            kept = reader.get("req-1")
            assert (kept["status"], kept["result"]) == ("cancelled", {})

    @pytest.mark.parametrize("writer_org", ["org-b", None])
    def test_save_if_status_never_writes_another_orgs_result(self, store, temp_db, writer_org):
        store.claim("req-1", {"status": "pending"}, org_id="org-a", created_by="u1")

        saved = store.save_if_status(
            "req-1",
            {"status": "completed", "result": {"answer": "b"}},
            org_id=writer_org,
            expected_status="pending",
        )

        assert saved is False
        kept = DecisionResultStore(db_path=temp_db).get("req-1")
        assert (kept["status"], kept["org_id"]) == ("pending", "org-a")

    def test_save_if_status_of_a_missing_id_writes_nothing(self, store):
        saved = store.save_if_status(
            "missing", {"status": "completed"}, org_id="org-a", expected_status="pending"
        )

        assert saved is False
        assert store.get("missing") is None


class _Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def time(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch):
    """A clock for the store module only; tests move it by hand."""
    fixed = _Clock()
    monkeypatch.setattr(store_module, "time", SimpleNamespace(time=fixed.time))
    return fixed


def _durable_rows(db_path: Path) -> list[tuple]:
    """The rows on disk, read on a separate read-only connection (no store cache)."""
    with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as conn:
        return conn.execute(
            "SELECT request_id, status, org_id, expires_at, result_json, created_by "
            "FROM decision_results ORDER BY created_at, request_id"
        ).fetchall()


def _statuses(db_path: Path) -> list[tuple[str, str]]:
    return [(row[0], row[1]) for row in _durable_rows(db_path)]


def _create(store, request_id: str, *, org_id: str = "org-a") -> None:
    """One decision create as the handler runs it: claim it pending, then save the outcome."""
    claimed = store.claim(
        request_id,
        {"status": "pending", "result": {"request": {"content": request_id}}},
        org_id=org_id,
        created_by="u1",
    )
    assert claimed == "pending"
    assert store.save_if_status(
        request_id,
        {"status": "completed", "result": {"answer": request_id}},
        org_id=org_id,
        expected_status="pending",
    )


class TestClaimLifecycleMaintenance:
    """Creates and cancels (claim + save_if_status) keep the store's expiry and capacity limits."""

    @pytest.fixture
    def db_path(self, tmp_path):
        return tmp_path / "maintenance.db"

    def test_creates_stay_within_max_entries(self, db_path, clock):
        store = DecisionResultStore(
            db_path=db_path, ttl_seconds=10_000, max_entries=5, cache_size=5, cleanup_interval=5
        )

        for i in range(12):
            clock.now = 1000.0 + i
            _create(store, f"fresh-{i:02}")
            assert len(_durable_rows(db_path)) <= 5

        assert [row[0] for row in _durable_rows(db_path)] == [f"fresh-{i:02}" for i in range(7, 12)]
        assert store.count() == 5

    def test_expired_rows_are_purged_every_cleanup_interval(self, db_path, clock):
        store = DecisionResultStore(
            db_path=db_path, ttl_seconds=10, max_entries=100, cleanup_interval=5
        )
        _create(store, "seed-0")
        _create(store, "seed-1")

        for epoch in range(1, 5):
            clock.now = 1000.0 + epoch * 20
            _create(store, f"epoch-{epoch}-0")
            _create(store, f"epoch-{epoch}-1")
            expired = [row[0] for row in _durable_rows(db_path) if row[3] <= clock.now]
            assert expired == []

        assert [row[0] for row in _durable_rows(db_path)] == ["epoch-4-0", "epoch-4-1"]

    def test_a_cancel_alone_runs_the_expiry_purge(self, db_path, clock):
        store = DecisionResultStore(
            db_path=db_path, ttl_seconds=10, max_entries=100, cleanup_interval=5
        )
        _create(store, "old-0")
        _create(store, "old-1")
        clock.now = 1008.0
        assert store.claim("live", {"status": "pending"}, org_id="org-a") == "pending"
        assert len(_durable_rows(db_path)) == 3
        clock.now = 1014.0  # old-0 and old-1 expired at 1010; "live" is still pending

        assert store.save_if_status(
            "live", {"status": "cancelled"}, org_id="org-a", expected_status="pending"
        )

        assert _statuses(db_path) == [("live", "cancelled")]

    def test_in_flight_claim_survives_eviction_and_its_late_save_lands(self, db_path, clock):
        store = DecisionResultStore(
            db_path=db_path, ttl_seconds=10_000, max_entries=3, cleanup_interval=5
        )
        assert store.claim("in-flight", {"status": "pending"}, org_id="org-a") == "pending"

        for i in range(5):
            clock.now = 1001.0 + i
            _create(store, f"other-{i}")
            statuses = _statuses(db_path)
            assert ("in-flight", "pending") in statuses
            assert len([s for s in statuses if s[1] == "completed"]) <= 2

        clock.now = 1010.0
        assert store.save_if_status(
            "in-flight",
            {"status": "completed", "result": {"answer": "late"}},
            org_id="org-a",
            expected_status="pending",
        )
        assert _statuses(db_path) == [
            ("in-flight", "completed"),
            ("other-3", "completed"),
            ("other-4", "completed"),
        ]

    @pytest.mark.parametrize("in_flight_status", ["pending", "running", "processing"])
    def test_save_never_evicts_an_in_flight_row(self, db_path, clock, in_flight_status):
        store = DecisionResultStore(
            db_path=db_path, ttl_seconds=10_000, max_entries=3, cleanup_interval=5
        )
        store.save("in-flight", {"status": in_flight_status}, org_id="org-a")

        for i in range(4):
            clock.now = 1001.0 + i
            store.save(f"done-{i}", {"status": "completed"}, org_id="org-a")

        assert _statuses(db_path) == [
            ("in-flight", in_flight_status),
            ("done-2", "completed"),
            ("done-3", "completed"),
        ]

    def test_in_flight_rows_exceed_the_limit_only_until_they_finish(self, db_path, clock):
        store = DecisionResultStore(
            db_path=db_path, ttl_seconds=10_000, max_entries=2, cleanup_interval=5
        )
        for i in range(4):
            clock.now = 1000.0 + i
            assert store.claim(f"run-{i}", {"status": "pending"}, org_id="org-a") == "pending"
        assert len(_durable_rows(db_path)) == 4

        for i in range(4):
            clock.now = 1010.0 + i
            assert store.save_if_status(
                f"run-{i}", {"status": "completed"}, org_id="org-a", expected_status="pending"
            )

        assert _statuses(db_path) == [("run-2", "completed"), ("run-3", "completed")]

    def test_expiry_still_purges_an_orphaned_in_flight_row(self, db_path, clock):
        store = DecisionResultStore(
            db_path=db_path, ttl_seconds=10, max_entries=100, cleanup_interval=5
        )
        assert store.claim("orphan", {"status": "pending"}, org_id="org-a") == "pending"
        clock.now = 1020.0

        _create(store, "next")

        assert _statuses(db_path) == [("next", "completed")]

    def test_an_evicted_result_is_not_served_from_the_read_cache(self, db_path, clock):
        store = DecisionResultStore(
            db_path=db_path, ttl_seconds=10_000, max_entries=2, cleanup_interval=5
        )
        store.save("saved", {"status": "completed"}, org_id="org-a")
        _create(store, "created")
        assert store.get("saved")["status"] == "completed"
        assert store.get("created")["status"] == "completed"

        for i in range(2):
            clock.now = 1001.0 + i
            _create(store, f"newer-{i}")

        assert [row[0] for row in _durable_rows(db_path)] == ["newer-0", "newer-1"]
        assert store.get("saved") is None
        assert store.get_for_org("created", "org-a") is None
        assert store.get("newer-1")["status"] == "completed"

    def test_cancel_during_routing_stays_cancelled_under_maintenance(self, db_path, clock):
        store = DecisionResultStore(
            db_path=db_path, ttl_seconds=10_000, max_entries=3, cleanup_interval=5
        )
        for i in range(3):
            clock.now = 1000.0 + i
            _create(store, f"old-{i}")
        clock.now = 1003.0
        assert store.claim("routing", {"status": "pending"}, org_id="org-a") == "pending"
        clock.now = 1004.0
        assert store.save_if_status(
            "routing", {"status": "cancelled"}, org_id="org-a", expected_status="pending"
        )
        for i in range(2):
            clock.now = 1010.0 + i
            _create(store, f"new-{i}")

        late = store.save_if_status(
            "routing",
            {"status": "completed", "result": {"answer": "late"}},
            org_id="org-a",
            expected_status="pending",
        )

        assert late is False
        for reader in (store, DecisionResultStore(db_path=db_path)):
            kept = reader.get_for_org("routing", "org-a")
            assert (kept["status"], kept["result"]) == ("cancelled", {})
        assert [row[0] for row in _durable_rows(db_path)] == ["routing", "new-0", "new-1"]

    def test_cross_org_conflict_runs_no_maintenance(self, db_path, clock):
        seeder = DecisionResultStore(
            db_path=db_path, ttl_seconds=10_000, max_entries=100, cleanup_interval=10_000
        )
        seeder.save("theirs", {"status": "completed", "result": {"answer": "b"}}, org_id="org-b")
        seeder.save("older", {"status": "completed"}, org_id="org-b")
        DecisionResultStore(
            db_path=db_path, ttl_seconds=10, max_entries=100, cleanup_interval=10_000
        ).save("expiring", {"status": "completed"}, org_id="org-b")
        writer = DecisionResultStore(
            db_path=db_path, ttl_seconds=10_000, max_entries=1, cleanup_interval=5
        )
        clock.now = 1100.0  # cleanup is due, "expiring" has expired, 2 live rows > max_entries
        before = _durable_rows(db_path)

        with (
            patch.object(writer, "_maybe_cleanup", wraps=writer._maybe_cleanup) as cleanup,
            patch.object(
                writer, "_enforce_max_entries", wraps=writer._enforce_max_entries
            ) as enforce,
        ):
            with pytest.raises(DecisionOwnershipConflict):
                writer.claim("theirs", {"status": "pending"}, org_id="org-a", created_by="u1")
            assert (
                writer.save_if_status(
                    "theirs", {"status": "cancelled"}, org_id="org-a", expected_status="completed"
                )
                is False
            )

        cleanup.assert_not_called()
        enforce.assert_not_called()
        assert _durable_rows(db_path) == before

    def test_a_maintenance_failure_never_fails_a_committed_write(
        self, db_path, clock, monkeypatch, caplog
    ):
        store = DecisionResultStore(
            db_path=db_path, ttl_seconds=10_000, max_entries=100, cleanup_interval=5
        )

        class DriverError(Exception):
            """A driver error the maintenance methods do not catch (like psycopg2.Error)."""

        def broken() -> None:
            raise DriverError("connection lost")

        monkeypatch.setattr(store, "_maybe_cleanup", broken)
        monkeypatch.setattr(store, "_enforce_max_entries", broken)

        with caplog.at_level(logging.WARNING, logger=store_module.__name__):
            assert store.claim("req-1", {"status": "pending"}, org_id="org-a") == "pending"
            assert store.save_if_status(
                "req-1", {"status": "completed"}, org_id="org-a", expected_status="pending"
            )
            store.save("req-2", {"status": "completed"}, org_id="org-a")

        assert _statuses(db_path) == [("req-1", "completed"), ("req-2", "completed")]
        failures = [r for r in caplog.records if "connection lost" in r.getMessage()]
        assert len(failures) == 6
        assert {r.levelno for r in failures} == {logging.WARNING}


class TestClaimOfAnExpiredResult:
    """An expired row that cleanup has not purged yet decides neither the owner nor the status."""

    @pytest.fixture
    def db_path(self, tmp_path):
        return tmp_path / "expired_claim.db"

    @staticmethod
    def _store(db_path: Path, ttl_seconds: int) -> DecisionResultStore:
        return DecisionResultStore(
            db_path=db_path, ttl_seconds=ttl_seconds, cleanup_interval=1_000_000
        )

    def test_claim_of_expired_unpurged_id_is_fresh(self, db_path, clock):
        # Built before the clock moves: a store purges expired rows when it is constructed.
        short_lived = self._store(db_path, ttl_seconds=10)
        store = self._store(db_path, ttl_seconds=10_000)
        short_lived.save(
            "dup",
            {"status": "completed", "result": {"answer": "org-b secret"}},
            org_id="org-b",
            created_by="ub",
        )
        short_lived.save("mine", {"status": "cancelled"}, org_id="org-a", created_by="u1")
        clock.now = 1011.0
        assert len(_durable_rows(db_path)) == 2  # expired, but not purged yet

        assert (
            store.claim(
                "dup",
                {"status": "pending", "result": {"q": "org-a"}},
                org_id="org-a",
                created_by="u1",
            )
            == "pending"
        )
        assert store.claim("mine", {"status": "pending"}, org_id="org-a", created_by="u1") == (
            "pending"
        )

        rows = {row[0]: row for row in _durable_rows(db_path)}
        assert rows["dup"][1:3] == ("pending", "org-a")
        assert rows["dup"][4:] == ('{"q": "org-a"}', "u1")
        assert rows["mine"][1:3] == ("pending", "org-a")
        assert store.get_for_org("dup", "org-b") is None
        assert store.save_if_status(
            "dup", {"status": "completed"}, org_id="org-a", expected_status="pending"
        )

    def test_a_live_foreign_result_still_conflicts(self, db_path, clock):
        store = self._store(db_path, ttl_seconds=10_000)
        self._store(db_path, ttl_seconds=10).save(
            "dup", {"status": "completed", "result": {"answer": "b"}}, org_id="org-b"
        )
        clock.now = 1009.0

        with pytest.raises(DecisionOwnershipConflict):
            store.claim("dup", {"status": "pending"}, org_id="org-a")

        assert _statuses(db_path) == [("dup", "completed")]
        assert _durable_rows(db_path)[0][2] == "org-b"


class TestRoutingPin:
    """A claimed result survives capacity eviction until its route saves or ends, whatever its status."""

    @pytest.fixture
    def db_path(self, tmp_path):
        return tmp_path / "routing_pin.db"

    @staticmethod
    def _store(db_path: Path, path: str = "backend") -> DecisionResultStore:
        store = DecisionResultStore(
            db_path=db_path, ttl_seconds=10_000, max_entries=2, cleanup_interval=5
        )
        if path == "legacy":
            store._backend = None  # the store's own-connection code path
        return store

    @pytest.mark.parametrize("path", ["backend", "legacy"])
    def test_reclaimed_finished_result_survives_eviction_and_its_late_save_lands(
        self, db_path, clock, path
    ):
        store = self._store(db_path, path)
        store.save("reuse", {"status": "completed", "result": {"answer": "v1"}}, org_id="org-a")
        clock.now = 1001.0
        assert store.claim("reuse", {"status": "pending"}, org_id="org-a") == "completed"
        assert store.get("reuse")["result"] == {"answer": "v1"}

        with patch.object(store, "_forget_cached", wraps=store._forget_cached) as forget:
            for i in range(2):
                clock.now = 1002.0 + i
                _create(store, f"other-{i}")
                assert ("reuse", "completed") in _statuses(db_path)
        assert all("reuse" not in c.args for c in forget.call_args_list)

        clock.now = 1010.0
        assert store.save_if_status(
            "reuse",
            {"status": "completed", "result": {"answer": "v2"}},
            org_id="org-a",
            expected_status="completed",
        )
        assert _statuses(db_path) == [("reuse", "completed"), ("other-1", "completed")]
        assert store.get_for_org("reuse", "org-a")["result"] == {"answer": "v2"}
        assert store._routing_ids == set()

    @pytest.mark.parametrize("expected", ["completed", "cancelled"], ids=["saved", "mismatched"])
    def test_a_conditional_save_releases_the_pin_whatever_its_result(
        self, db_path, clock, expected
    ):
        store = self._store(db_path)
        store.save("reuse", {"status": "completed"}, org_id="org-a")
        assert store.claim("reuse", {"status": "pending"}, org_id="org-a") == "completed"
        assert store.claim("new", {"status": "pending"}, org_id="org-a") == "pending"
        assert store._routing_ids == {"reuse", "new"}

        saved = store.save_if_status(
            "reuse", {"status": "failed"}, org_id="org-a", expected_status=expected
        )

        assert saved is (expected == "completed")
        assert store._routing_ids == {"new"}

    def test_released_or_conflicting_claims_leave_no_pin(self, db_path, clock):
        store = self._store(db_path)
        store.save("reuse", {"status": "completed"}, org_id="org-a")
        clock.now = 1000.5
        store.save("theirs", {"status": "completed"}, org_id="org-b")
        assert store.claim("reuse", {"status": "pending"}, org_id="org-a") == "completed"
        with pytest.raises(DecisionOwnershipConflict):
            store.claim("theirs", {"status": "pending"}, org_id="org-a")

        for _ in range(2):
            store.release_routing("reuse")
        store.release_routing("never-claimed")

        assert store._routing_ids == set()
        clock.now = 1001.0
        _create(store, "newer")
        assert [row[0] for row in _durable_rows(db_path)] == ["theirs", "newer"]


class _SignalOnContention:
    """Wraps a lock and sets ``waiting`` when the ``waiter`` thread finds it held."""

    def __init__(self, inner: Any, waiting: threading.Event) -> None:
        self._inner = inner
        self._waiting = waiting
        self.waiter: threading.Thread | None = None

    def __enter__(self) -> "_SignalOnContention":
        if not self._inner.acquire(blocking=False):
            if threading.current_thread() is self.waiter:
                self._waiting.set()
            self._inner.acquire()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._inner.release()


def _reclaim_during_eviction(store: DecisionResultStore, evict, reclaim) -> dict[str, Any]:
    """Run ``evict`` and ``reclaim`` on two threads, the re-claim inside the eviction.

    The first eviction on the ``evict`` thread pauses once it has built its
    statements (its pin snapshot). Then ``reclaim`` starts, and the eviction
    resumes when the re-claim has returned or is waiting for the store's
    claim/eviction lock. Returns each callable's result; re-raises a thread's error.
    """
    prepared, resume, reclaim_progress = threading.Event(), threading.Event(), threading.Event()
    results: dict[str, Any] = {}
    errors: list[BaseException] = []
    build = store._eviction_statements

    def build_then_pause(excess: int) -> tuple[str, str, tuple]:
        statements = build(excess)
        if threading.current_thread() is evictor and not prepared.is_set():
            prepared.set()
            resume.wait(10)
        return statements

    def run(name: str, fn, done: threading.Event | None = None) -> None:
        try:
            results[name] = fn()
        except BaseException as e:  # noqa: BLE001 - re-raised on the test thread
            errors.append(e)
        finally:
            if done is not None:
                done.set()

    evictor = threading.Thread(target=run, args=("evict", evict), daemon=True)
    reclaimer = threading.Thread(
        target=run, args=("reclaim", reclaim, reclaim_progress), daemon=True
    )
    # getattr: a store without the lock (the pre-fix code) gets an unused stand-in.
    lock = _SignalOnContention(
        getattr(store, "_claim_evict_lock", threading.Lock()), reclaim_progress
    )
    lock.waiter = reclaimer
    store._claim_evict_lock = lock  # type: ignore[assignment]
    store._eviction_statements = build_then_pause  # type: ignore[method-assign]
    try:
        evictor.start()
        assert prepared.wait(10), "the eviction never built its statements"
        reclaimer.start()
        assert reclaim_progress.wait(10), "the re-claim neither returned nor waited"
    finally:
        resume.set()
        for thread in (evictor, reclaimer):
            if thread.ident is not None:
                thread.join(10)
    assert not evictor.is_alive() and not reclaimer.is_alive()
    if errors:
        raise errors[0]
    return results


class TestClaimDuringEviction:
    """A claim that pins a result while another thread's eviction runs never loses that result."""

    @pytest.fixture
    def db_path(self, tmp_path):
        return tmp_path / "claim_during_eviction.db"

    @pytest.mark.timeout(60)
    @pytest.mark.parametrize("path", ["backend", "legacy"])
    def test_a_result_reclaimed_after_the_pin_snapshot_survives_and_its_late_save_lands(
        self, db_path, clock, path
    ):
        store = TestRoutingPin._store(db_path, path)
        store.save("X", {"status": "completed", "result": {"answer": "v1"}}, org_id="org-a")
        clock.now = 1001.0
        store.save("Y", {"status": "completed"}, org_id="org-a")
        clock.now = 1002.0

        results = _reclaim_during_eviction(
            store,
            evict=lambda: store.claim("Z", {"status": "pending"}, org_id="org-a"),
            reclaim=lambda: store.claim("X", {"status": "pending"}, org_id="org-a"),
        )

        assert results["evict"] == "pending"
        reclaimed = results["reclaim"]
        assert reclaimed in ("completed", "pending")
        assert ("X", reclaimed) in _statuses(db_path)
        assert store._routing_ids == {"X", "Z"}
        assert store.save_if_status(
            "X",
            {"status": "completed", "result": {"answer": "v2"}},
            org_id="org-a",
            expected_status=reclaimed,
        )
        assert store.get_for_org("X", "org-a")["result"] == {"answer": "v2"}
        assert _statuses(db_path) == [("X", "completed"), ("Z", "pending")]
        assert store._routing_ids == {"Z"}

    @pytest.mark.timeout(120)
    @pytest.mark.parametrize("path", ["backend", "legacy"])
    def test_concurrent_reclaims_and_evictions_neither_deadlock_nor_lose_a_pinned_result(
        self, db_path, path
    ):
        store = TestRoutingPin._store(db_path, path)
        store.save("hot", {"status": "completed"}, org_id="org-a")
        lost: list[tuple[int, str]] = []
        errors: list[BaseException] = []

        def reclaim_hot() -> None:
            for i in range(200):
                status = store.claim("hot", {"status": "pending"}, org_id="org-a")
                if not store.save_if_status(
                    "hot",
                    {"status": "completed", "result": {"answer": i}},
                    org_id="org-a",
                    expected_status=status,
                ):
                    lost.append((i, status))

        def churn() -> None:
            for i in range(200):
                _create(store, f"churn-{i}")

        def run(fn) -> None:
            try:
                fn()
            except BaseException as e:  # noqa: BLE001 - asserted on the test thread
                errors.append(e)

        threads = [
            threading.Thread(target=run, args=(fn,), daemon=True) for fn in (reclaim_hot, churn)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(90)

        assert not any(thread.is_alive() for thread in threads), "claim and eviction deadlocked"
        assert errors == []
        assert lost == []
        assert store._routing_ids == set()
        assert len(_durable_rows(db_path)) <= 2


class _RecordingPostgreSQLBackend:
    """Stands in for PostgreSQLBackend: records each statement and answers the store's reads."""

    def __init__(self, database_url: str, **kwargs: Any) -> None:
        self.statements: list[tuple[str, tuple]] = []
        self.owner: tuple | None = ("org-a", "pending")
        self.rowcount = 1
        self.live_rows = 0
        self.expired_rows = 0
        self.oldest_finished: list[tuple] = []

    @staticmethod
    def convert_placeholder(sql: str) -> str:
        return sql.replace("?", "%s")

    def _record(self, sql: str, params: tuple) -> str:
        normalized = " ".join(sql.replace("%s", "?").split())
        self.statements.append((normalized, tuple(params)))
        return normalized

    @contextmanager
    def connection(self):
        backend = self

        class _Cursor:
            rowcount = backend.rowcount

            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                return False

            def execute(self, sql, params=()):
                backend._record(sql, params)

        yield SimpleNamespace(cursor=_Cursor)

    def execute_write(self, sql: str, params: tuple = ()) -> None:
        self._record(sql, params)

    def fetch_one(self, sql: str, params: tuple = ()) -> tuple | None:
        sql = self._record(sql, params)
        if sql.startswith("SELECT org_id, status"):
            return self.owner
        if sql.startswith("SELECT COUNT(*)"):
            return (self.expired_rows,) if "expires_at <=" in sql else (self.live_rows,)
        return None

    def fetch_all(self, sql: str, params: tuple = ()) -> list[Any]:
        sql = self._record(sql, params)
        return list(self.oldest_finished) if sql.startswith("SELECT request_id") else []

    def close(self) -> None:
        pass


_PURGE_SQL = "DELETE FROM decision_results WHERE expires_at <= ?"
_EVICT_PREFIX = "DELETE FROM decision_results WHERE request_id IN ( "


class TestPostgreSQLMaintenance:
    """The PostgreSQL code path issues the same maintenance after claims and conditional saves."""

    @pytest.fixture
    def pg_store(self, monkeypatch, tmp_path, clock):
        monkeypatch.setattr(store_module, "PostgreSQLBackend", _RecordingPostgreSQLBackend)
        monkeypatch.setattr(store_module, "POSTGRESQL_AVAILABLE", True)
        store = DecisionResultStore(
            db_path=tmp_path / "unused.db",
            backend="postgresql",
            database_url="postgresql://u@127.0.0.1:1/db",
            max_entries=2,
            cleanup_interval=5,
        )
        store._backend.live_rows = 3
        store._backend.expired_rows = 1
        store._backend.statements.clear()
        return store

    @staticmethod
    def _maintenance(backend) -> tuple[list[tuple], list[tuple]]:
        purges = [(s, p) for s, p in backend.statements if s == _PURGE_SQL]
        evictions = [
            (s, p)
            for s, p in backend.statements
            if "ORDER BY created_at ASC" in s and s.startswith("DELETE")
        ]
        return purges, evictions

    def _assert_maintained(self, backend, pinned: tuple[str, ...] = ()) -> None:
        purges, evictions = self._maintenance(backend)
        assert len(purges) == 1
        assert len(evictions) == 1
        sql, params = evictions[0]
        assert sql.startswith("DELETE FROM decision_results WHERE request_id IN (")
        unpinned = f" AND request_id NOT IN ({', '.join('?' for _ in pinned)})" if pinned else ""
        assert f"status NOT IN (?, ?, ?){unpinned} ORDER BY" in sql
        assert params[1:] == ("pending", "running", "processing", *pinned, 1)
        # The SELECT that picks the ids to drop from the read cache has the same predicate.
        selected = [(s, p) for s, p in backend.statements if s.startswith("SELECT request_id")]
        assert selected == [(sql.removeprefix(_EVICT_PREFIX).removesuffix(" )"), params)]

    def test_claim_and_conditional_save_issue_the_maintenance_sql(self, pg_store, clock):
        backend = pg_store._backend

        clock.now += 10
        assert pg_store.claim("req-1", {"status": "pending"}, org_id="org-a") == "pending"
        self._assert_maintained(backend, pinned=("req-1",))

        backend.statements.clear()
        clock.now += 10
        assert pg_store.save_if_status(
            "req-1", {"status": "completed"}, org_id="org-a", expected_status="pending"
        )
        self._assert_maintained(backend)

    def test_reclaimed_results_are_never_selected_for_eviction(self, pg_store, clock):
        backend = pg_store._backend
        backend.owner = ("org-a", "completed")
        clock.now += 10
        assert pg_store.claim("reuse", {"status": "pending"}, org_id="org-a") == "completed"
        self._assert_maintained(backend, pinned=("reuse",))

        backend.statements.clear()
        backend.owner = ("org-a", "pending")
        clock.now += 10
        assert pg_store.claim("other", {"status": "pending"}, org_id="org-a") == "pending"
        self._assert_maintained(backend, pinned=("other", "reuse"))

        backend.statements.clear()
        pg_store.release_routing("other")
        clock.now += 10
        assert pg_store.save_if_status(
            "reuse", {"status": "completed"}, org_id="org-a", expected_status="completed"
        )
        self._assert_maintained(backend)

    def test_evicted_results_leave_the_read_cache(self, pg_store, clock):
        pg_store._cache["old-1"] = DecisionResultEntry(
            request_id="old-1", status="completed", result={}, org_id="org-a"
        )
        pg_store._cache["kept"] = DecisionResultEntry(
            request_id="kept", status="completed", result={}, org_id="org-a"
        )
        assert pg_store.get("old-1")["status"] == "completed"
        pg_store._backend.oldest_finished = [("old-1",)]

        assert pg_store.claim("req-1", {"status": "pending"}, org_id="org-a") == "pending"

        assert pg_store.get("old-1") is None
        assert pg_store.get("kept")["status"] == "completed"

    def test_claim_first_deletes_only_an_expired_row_for_its_id(self, pg_store, clock):
        backend = pg_store._backend

        assert pg_store.claim("req-1", {"status": "pending"}, org_id="org-a") == "pending"

        first, second = backend.statements[:2]
        assert first == (
            "DELETE FROM decision_results WHERE request_id = ? AND expires_at <= ?",
            ("req-1", clock.now),
        )
        assert second[0].startswith("INSERT INTO decision_results")
        assert second[0].endswith("ON CONFLICT (request_id) DO NOTHING")

    def test_writes_that_change_nothing_issue_no_maintenance_sql(self, pg_store, clock):
        backend = pg_store._backend
        clock.now += 10

        backend.rowcount = 0
        assert (
            pg_store.save_if_status(
                "req-1", {"status": "completed"}, org_id="org-a", expected_status="pending"
            )
            is False
        )
        backend.owner = ("org-b", "completed")
        with pytest.raises(DecisionOwnershipConflict):
            pg_store.claim("req-2", {"status": "pending"}, org_id="org-a")

        assert self._maintenance(backend) == ([], [])

    @pytest.mark.timeout(60)
    def test_an_eviction_never_deletes_a_result_pinned_after_its_snapshot(self, pg_store, clock):
        backend = pg_store._backend
        pinned_at_delete: list[tuple[tuple, set[str]]] = []
        execute_write = backend.execute_write

        def record_pins_at_delete(sql: str, params: tuple = ()) -> None:
            if sql.startswith("DELETE FROM decision_results WHERE request_id IN"):
                with pg_store._routing_lock:
                    pinned_at_delete.append((tuple(params), set(pg_store._routing_ids)))
            execute_write(sql, params)

        backend.execute_write = record_pins_at_delete

        def reclaim_finished() -> str:
            backend.owner = ("org-a", "completed")
            return pg_store.claim("X", {"status": "pending"}, org_id="org-a")

        _reclaim_during_eviction(
            pg_store,
            evict=lambda: pg_store.claim("Z", {"status": "pending"}, org_id="org-a"),
            reclaim=reclaim_finished,
        )

        assert len(pinned_at_delete) == 2
        for params, pinned in pinned_at_delete:
            assert pinned <= set(params[4:-1])
        evict_z_only = next(
            i
            for i, (sql, params) in enumerate(backend.statements)
            if sql.startswith(_EVICT_PREFIX) and params[4:-1] == ("Z",)
        )
        claim_x = next(
            i
            for i, (sql, params) in enumerate(backend.statements)
            if sql.startswith("INSERT INTO decision_results") and params[0] == "X"
        )
        assert evict_z_only < claim_x


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
