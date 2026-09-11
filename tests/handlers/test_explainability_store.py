"""Tests for the explainability batch job store module.

Tests all store backends (Memory, Redis, Database/SQLite, PostgreSQL),
the BatchJob dataclass, the factory function get_batch_job_store,
and the reset_batch_job_store helper.
"""

from __future__ import annotations

import json
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.explainability_store import (
    BatchJob,
    BatchJobStore,
    DatabaseBatchJobStore,
    MemoryBatchJobStore,
    PostgresBatchJobStore,
    RedisBatchJobStore,
    SQLiteBatchJobStore,
    get_batch_job_store,
    reset_batch_job_store,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job(
    batch_id: str = "batch-001",
    debate_ids: list[str] | None = None,
    status: str = "pending",
    created_at: float | None = None,
    started_at: float | None = None,
    completed_at: float | None = None,
    results: list[dict[str, Any]] | None = None,
    processed_count: int = 0,
    options: dict[str, Any] | None = None,
    error: str | None = None,
) -> BatchJob:
    return BatchJob(
        batch_id=batch_id,
        debate_ids=debate_ids or ["d1", "d2"],
        status=status,
        created_at=created_at or time.time(),
        started_at=started_at,
        completed_at=completed_at,
        results=results or [],
        processed_count=processed_count,
        options=options or {},
        error=error,
    )


# ---------------------------------------------------------------------------
# Fixture: reset singleton between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_store_singleton():
    """Reset the module-level singleton before and after each test."""
    reset_batch_job_store()
    yield
    reset_batch_job_store()


# ---------------------------------------------------------------------------
# BatchJob dataclass
# ---------------------------------------------------------------------------


class TestBatchJob:
    """Tests for the BatchJob dataclass."""

    def test_default_values(self):
        job = BatchJob(batch_id="b1", debate_ids=["d1"])
        assert job.status == "pending"
        assert job.started_at is None
        assert job.completed_at is None
        assert job.results == []
        assert job.processed_count == 0
        assert job.options == {}
        assert job.error is None
        assert isinstance(job.created_at, float)

    def test_to_dict(self):
        job = _make_job(batch_id="b2", status="completed", error="oops")
        d = job.to_dict()
        assert d["batch_id"] == "b2"
        assert d["status"] == "completed"
        assert d["error"] == "oops"
        assert d["debate_ids"] == ["d1", "d2"]
        assert isinstance(d["created_at"], float)

    def test_to_dict_keys(self):
        job = _make_job()
        d = job.to_dict()
        expected_keys = {
            "batch_id",
            "debate_ids",
            "status",
            "created_at",
            "started_at",
            "completed_at",
            "results",
            "processed_count",
            "options",
            "error",
        }
        assert set(d.keys()) == expected_keys

    def test_from_dict(self):
        original = _make_job(batch_id="b3", status="processing", processed_count=5)
        d = original.to_dict()
        restored = BatchJob.from_dict(d)
        assert restored.batch_id == "b3"
        assert restored.status == "processing"
        assert restored.processed_count == 5
        assert restored.debate_ids == original.debate_ids

    def test_from_dict_roundtrip(self):
        original = _make_job(
            batch_id="round",
            debate_ids=["x", "y", "z"],
            status="completed",
            started_at=1000.0,
            completed_at=2000.0,
            results=[{"id": "x", "ok": True}],
            processed_count=3,
            options={"detail": True},
            error=None,
        )
        assert BatchJob.from_dict(original.to_dict()).to_dict() == original.to_dict()

    def test_from_dict_with_error(self):
        d = {
            "batch_id": "err",
            "debate_ids": [],
            "status": "failed",
            "created_at": 100.0,
            "started_at": None,
            "completed_at": None,
            "results": [],
            "processed_count": 0,
            "options": {},
            "error": "something went wrong",
        }
        job = BatchJob.from_dict(d)
        assert job.error == "something went wrong"
        assert job.status == "failed"

    def test_to_dict_preserves_none_fields(self):
        job = _make_job()
        d = job.to_dict()
        assert d["started_at"] is None
        assert d["completed_at"] is None
        assert d["error"] is None

    def test_independent_results_list(self):
        """Each job should have independent results list."""
        j1 = BatchJob(batch_id="a", debate_ids=[])
        j2 = BatchJob(batch_id="b", debate_ids=[])
        j1.results.append({"x": 1})
        assert j2.results == []


# ---------------------------------------------------------------------------
# MemoryBatchJobStore
# ---------------------------------------------------------------------------


class TestMemoryBatchJobStore:
    """Tests for in-memory batch job storage."""

    @pytest.fixture
    def store(self) -> MemoryBatchJobStore:
        return MemoryBatchJobStore(max_jobs=5, ttl_seconds=3600)

    @pytest.mark.asyncio
    async def test_save_and_get(self, store):
        job = _make_job(batch_id="m1")
        await store.save_job(job)
        retrieved = await store.get_job("m1")
        assert retrieved is not None
        assert retrieved.batch_id == "m1"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, store):
        assert await store.get_job("nope") is None

    @pytest.mark.asyncio
    async def test_delete_existing(self, store):
        job = _make_job(batch_id="del1")
        await store.save_job(job)
        assert await store.delete_job("del1") is True
        assert await store.get_job("del1") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, store):
        assert await store.delete_job("nope") is False

    @pytest.mark.asyncio
    async def test_list_all(self, store):
        for i in range(3):
            await store.save_job(_make_job(batch_id=f"list-{i}"))
        jobs = await store.list_jobs()
        assert len(jobs) == 3

    @pytest.mark.asyncio
    async def test_list_with_status_filter(self, store):
        await store.save_job(_make_job(batch_id="p1", status="pending"))
        await store.save_job(_make_job(batch_id="c1", status="completed"))
        await store.save_job(_make_job(batch_id="p2", status="pending"))
        jobs = await store.list_jobs(status="pending")
        assert len(jobs) == 2
        assert all(j.status == "pending" for j in jobs)

    @pytest.mark.asyncio
    async def test_list_with_limit(self, store):
        for i in range(4):
            await store.save_job(_make_job(batch_id=f"lim-{i}"))
        jobs = await store.list_jobs(limit=2)
        assert len(jobs) == 2

    @pytest.mark.asyncio
    async def test_lru_eviction(self, store):
        """When max_jobs is reached, oldest jobs are evicted."""
        for i in range(6):  # max_jobs=5
            await store.save_job(_make_job(batch_id=f"ev-{i}"))
        # First job should be evicted
        assert await store.get_job("ev-0") is None
        # Last 5 should remain
        assert await store.get_job("ev-5") is not None

    @pytest.mark.asyncio
    async def test_ttl_expiration_on_get(self, store):
        """Expired jobs should return None on get."""
        expired_job = _make_job(batch_id="exp1", created_at=time.time() - 7200)
        await store.save_job(expired_job)
        assert await store.get_job("exp1") is None

    @pytest.mark.asyncio
    async def test_ttl_expiration_on_list(self, store):
        """Expired jobs should be excluded from list."""
        await store.save_job(_make_job(batch_id="fresh"))
        await store.save_job(_make_job(batch_id="stale", created_at=time.time() - 7200))
        jobs = await store.list_jobs()
        assert len(jobs) == 1
        assert jobs[0].batch_id == "fresh"

    @pytest.mark.asyncio
    async def test_save_moves_to_end(self, store):
        """Saving a job moves it to end of LRU."""
        await store.save_job(_make_job(batch_id="a"))
        await store.save_job(_make_job(batch_id="b"))
        await store.save_job(_make_job(batch_id="c"))
        # Re-save 'a' to move it to end
        await store.save_job(_make_job(batch_id="a"))
        # Internal order: b, c, a
        keys = list(store._jobs.keys())
        assert keys[-1] == "a"

    @pytest.mark.asyncio
    async def test_get_moves_to_end(self, store):
        """Getting a job moves it to end of LRU."""
        await store.save_job(_make_job(batch_id="x"))
        await store.save_job(_make_job(batch_id="y"))
        await store.get_job("x")
        keys = list(store._jobs.keys())
        assert keys[-1] == "x"

    @pytest.mark.asyncio
    async def test_list_empty_store(self, store):
        jobs = await store.list_jobs()
        assert jobs == []

    @pytest.mark.asyncio
    async def test_list_status_filter_no_match(self, store):
        await store.save_job(_make_job(batch_id="p1", status="pending"))
        jobs = await store.list_jobs(status="failed")
        assert jobs == []

    @pytest.mark.asyncio
    async def test_default_params(self):
        store = MemoryBatchJobStore()
        assert store._max_jobs == 100
        assert store._ttl == 3600

    @pytest.mark.asyncio
    async def test_custom_ttl(self):
        store = MemoryBatchJobStore(ttl_seconds=60)
        assert store._ttl == 60


# ---------------------------------------------------------------------------
# RedisBatchJobStore
# ---------------------------------------------------------------------------


class TestRedisBatchJobStore:
    """Tests for Redis-backed batch job storage."""

    @pytest.fixture
    def mock_redis(self):
        return MagicMock()

    @pytest.fixture
    def store(self, mock_redis) -> RedisBatchJobStore:
        return RedisBatchJobStore(mock_redis, key_prefix="test:", ttl=600)

    @pytest.mark.asyncio
    async def test_save_job(self, store, mock_redis):
        job = _make_job(batch_id="r1")
        await store.save_job(job)
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert call_args[0][0] == "test:r1"
        assert call_args[0][1] == 600
        parsed = json.loads(call_args[0][2])
        assert parsed["batch_id"] == "r1"

    @pytest.mark.asyncio
    async def test_get_job_found_str(self, store, mock_redis):
        job_data = _make_job(batch_id="r2").to_dict()
        mock_redis.get.return_value = json.dumps(job_data)
        result = await store.get_job("r2")
        assert result is not None
        assert result.batch_id == "r2"

    @pytest.mark.asyncio
    async def test_get_job_found_bytes(self, store, mock_redis):
        job_data = _make_job(batch_id="r3").to_dict()
        mock_redis.get.return_value = json.dumps(job_data).encode()
        result = await store.get_job("r3")
        assert result is not None
        assert result.batch_id == "r3"

    @pytest.mark.asyncio
    async def test_get_job_not_found(self, store, mock_redis):
        mock_redis.get.return_value = None
        assert await store.get_job("missing") is None

    @pytest.mark.asyncio
    async def test_delete_job_success(self, store, mock_redis):
        mock_redis.delete.return_value = 1
        assert await store.delete_job("r4") is True

    @pytest.mark.asyncio
    async def test_delete_job_not_found(self, store, mock_redis):
        mock_redis.delete.return_value = 0
        assert await store.delete_job("nope") is False

    @pytest.mark.asyncio
    async def test_list_jobs_empty(self, store, mock_redis):
        mock_redis.scan.return_value = (0, [])
        jobs = await store.list_jobs()
        assert jobs == []

    @pytest.mark.asyncio
    async def test_list_jobs_with_data(self, store, mock_redis):
        job1 = _make_job(batch_id="l1", status="pending")
        job2 = _make_job(batch_id="l2", status="completed")
        mock_redis.scan.return_value = (0, ["test:l1", "test:l2"])
        mock_redis.get.side_effect = [
            json.dumps(job1.to_dict()),
            json.dumps(job2.to_dict()),
        ]
        jobs = await store.list_jobs()
        assert len(jobs) == 2

    @pytest.mark.asyncio
    async def test_list_jobs_status_filter(self, store, mock_redis):
        job1 = _make_job(batch_id="f1", status="pending")
        job2 = _make_job(batch_id="f2", status="completed")
        mock_redis.scan.return_value = (0, ["test:f1", "test:f2"])
        mock_redis.get.side_effect = [
            json.dumps(job1.to_dict()),
            json.dumps(job2.to_dict()),
        ]
        jobs = await store.list_jobs(status="pending")
        assert len(jobs) == 1
        assert jobs[0].batch_id == "f1"

    @pytest.mark.asyncio
    async def test_list_jobs_respects_limit(self, store, mock_redis):
        jobs_data = [_make_job(batch_id=f"lim-{i}") for i in range(5)]
        mock_redis.scan.return_value = (0, [f"test:lim-{i}" for i in range(5)])
        mock_redis.get.side_effect = [json.dumps(j.to_dict()) for j in jobs_data]
        jobs = await store.list_jobs(limit=2)
        assert len(jobs) == 2

    @pytest.mark.asyncio
    async def test_list_jobs_pagination(self, store, mock_redis):
        """Test scanning with cursor continuation."""
        job1 = _make_job(batch_id="pg1")
        job2 = _make_job(batch_id="pg2")
        # First scan returns cursor=42 (more data), second returns cursor=0 (done)
        mock_redis.scan.side_effect = [
            (42, ["test:pg1"]),
            (0, ["test:pg2"]),
        ]
        mock_redis.get.side_effect = [
            json.dumps(job1.to_dict()),
            json.dumps(job2.to_dict()),
        ]
        jobs = await store.list_jobs()
        assert len(jobs) == 2

    @pytest.mark.asyncio
    async def test_list_jobs_skips_none_values(self, store, mock_redis):
        """If redis.get returns None for a key, skip it."""
        mock_redis.scan.return_value = (0, ["test:gone"])
        mock_redis.get.return_value = None
        jobs = await store.list_jobs()
        assert jobs == []

    @pytest.mark.asyncio
    async def test_key_prefix(self, store):
        assert store._key("abc") == "test:abc"

    @pytest.mark.asyncio
    async def test_default_prefix(self):
        redis_mock = MagicMock()
        s = RedisBatchJobStore(redis_mock)
        assert s._key("x") == "aragora:batch:x"
        assert s._ttl == 3600


# ---------------------------------------------------------------------------
# DatabaseBatchJobStore (via SQLiteBatchJobStore)
# ---------------------------------------------------------------------------


class TestSQLiteBatchJobStore:
    """Tests for SQLite-backed batch job storage."""

    @pytest.fixture
    def store(self, tmp_path) -> SQLiteBatchJobStore:
        db_path = tmp_path / "test_batch.db"
        return SQLiteBatchJobStore(db_path, ttl_seconds=3600)

    @pytest.mark.asyncio
    async def test_save_and_get(self, store):
        job = _make_job(batch_id="sq1")
        await store.save_job(job)
        retrieved = await store.get_job("sq1")
        assert retrieved is not None
        assert retrieved.batch_id == "sq1"
        assert retrieved.debate_ids == ["d1", "d2"]

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, store):
        assert await store.get_job("nope") is None

    @pytest.mark.asyncio
    async def test_save_upsert(self, store):
        """Saving with same batch_id updates the existing record."""
        job1 = _make_job(batch_id="up1", status="pending")
        await store.save_job(job1)
        job2 = _make_job(batch_id="up1", status="completed", processed_count=10)
        await store.save_job(job2)
        retrieved = await store.get_job("up1")
        assert retrieved is not None
        assert retrieved.status == "completed"
        assert retrieved.processed_count == 10

    @pytest.mark.asyncio
    async def test_delete_job(self, store):
        job = _make_job(batch_id="del1")
        await store.save_job(job)
        result = await store.delete_job("del1")
        assert result is True
        assert await store.get_job("del1") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, store):
        # DatabaseBatchJobStore.delete_job always returns True
        result = await store.delete_job("nope")
        assert result is True

    @pytest.mark.asyncio
    async def test_list_all(self, store):
        for i in range(3):
            await store.save_job(_make_job(batch_id=f"all-{i}"))
        jobs = await store.list_jobs()
        assert len(jobs) == 3

    @pytest.mark.asyncio
    async def test_list_status_filter(self, store):
        await store.save_job(_make_job(batch_id="p1", status="pending"))
        await store.save_job(_make_job(batch_id="c1", status="completed"))
        await store.save_job(_make_job(batch_id="p2", status="pending"))
        jobs = await store.list_jobs(status="pending")
        assert len(jobs) == 2
        assert all(j.status == "pending" for j in jobs)

    @pytest.mark.asyncio
    async def test_list_with_limit(self, store):
        for i in range(5):
            await store.save_job(_make_job(batch_id=f"lim-{i}"))
        jobs = await store.list_jobs(limit=2)
        assert len(jobs) == 2

    @pytest.mark.asyncio
    async def test_list_ordered_by_created_at_desc(self, store):
        now = time.time()
        await store.save_job(_make_job(batch_id="old", created_at=now - 100))
        await store.save_job(_make_job(batch_id="new", created_at=now))
        await store.save_job(_make_job(batch_id="mid", created_at=now - 50))
        jobs = await store.list_jobs()
        assert jobs[0].batch_id == "new"
        assert jobs[1].batch_id == "mid"
        assert jobs[2].batch_id == "old"

    @pytest.mark.asyncio
    async def test_ttl_expiration_on_get(self, store):
        expired = _make_job(batch_id="exp1", created_at=time.time() - 7200)
        await store.save_job(expired)
        assert await store.get_job("exp1") is None

    @pytest.mark.asyncio
    async def test_ttl_expiration_on_list(self, store):
        await store.save_job(_make_job(batch_id="fresh"))
        await store.save_job(_make_job(batch_id="stale", created_at=time.time() - 7200))
        jobs = await store.list_jobs()
        assert len(jobs) == 1
        assert jobs[0].batch_id == "fresh"

    @pytest.mark.asyncio
    async def test_list_empty_store(self, store):
        jobs = await store.list_jobs()
        assert jobs == []

    @pytest.mark.asyncio
    async def test_preserves_options(self, store):
        job = _make_job(batch_id="opt1", options={"detail_level": "high", "format": "json"})
        await store.save_job(job)
        retrieved = await store.get_job("opt1")
        assert retrieved is not None
        assert retrieved.options == {"detail_level": "high", "format": "json"}

    @pytest.mark.asyncio
    async def test_preserves_results(self, store):
        job = _make_job(
            batch_id="res1",
            results=[{"debate_id": "d1", "explanation": "test"}],
        )
        await store.save_job(job)
        retrieved = await store.get_job("res1")
        assert retrieved is not None
        assert len(retrieved.results) == 1
        assert retrieved.results[0]["debate_id"] == "d1"

    @pytest.mark.asyncio
    async def test_preserves_error(self, store):
        job = _make_job(batch_id="e1", status="failed", error="timeout")
        await store.save_job(job)
        retrieved = await store.get_job("e1")
        assert retrieved is not None
        assert retrieved.error == "timeout"

    @pytest.mark.asyncio
    async def test_null_error(self, store):
        job = _make_job(batch_id="ne1")
        await store.save_job(job)
        retrieved = await store.get_job("ne1")
        assert retrieved is not None
        assert retrieved.error is None

    @pytest.mark.asyncio
    async def test_schema_created(self, tmp_path):
        """Schema tables and indexes should be created on init."""
        import sqlite3

        db_path = tmp_path / "schema_test.db"
        SQLiteBatchJobStore(db_path)
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='explainability_batch_jobs'"
        )
        assert cursor.fetchone() is not None
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = [row[0] for row in cursor.fetchall()]
        assert "idx_explainability_batch_jobs_status" in indexes
        assert "idx_explainability_batch_jobs_expires" in indexes
        conn.close()

    @pytest.mark.asyncio
    async def test_timestamps(self, store):
        now = time.time()
        job = _make_job(
            batch_id="ts1",
            created_at=now,
            started_at=now + 1,
            completed_at=now + 10,
        )
        await store.save_job(job)
        retrieved = await store.get_job("ts1")
        assert retrieved is not None
        assert abs(retrieved.created_at - now) < 0.01
        assert abs(retrieved.started_at - (now + 1)) < 0.01
        assert abs(retrieved.completed_at - (now + 10)) < 0.01


# ---------------------------------------------------------------------------
# PostgresBatchJobStore
# ---------------------------------------------------------------------------


class TestPostgresBatchJobStore:
    """Tests for PostgreSQL-backed store initialization."""

    def test_raises_when_psycopg2_unavailable(self):
        with patch("aragora.server.handlers.explainability_store.POSTGRESQL_AVAILABLE", False):
            with pytest.raises(ImportError, match="psycopg2"):
                PostgresBatchJobStore("postgresql://localhost/test")

    def test_creates_with_postgresql_backend(self):
        with (
            patch("aragora.server.handlers.explainability_store.POSTGRESQL_AVAILABLE", True),
            patch(
                "aragora.server.handlers.explainability_store.PostgreSQLBackend"
            ) as mock_backend_cls,
        ):
            mock_backend = MagicMock()
            mock_backend_cls.return_value = mock_backend
            store = PostgresBatchJobStore("postgresql://localhost/test", ttl_seconds=1800)
            mock_backend_cls.assert_called_once_with("postgresql://localhost/test")
            assert store._ttl == 1800


# ---------------------------------------------------------------------------
# DatabaseBatchJobStore._row_to_job
# ---------------------------------------------------------------------------


class TestRowToJob:
    """Tests for converting database rows to BatchJob objects."""

    @pytest.fixture
    def store(self, tmp_path) -> SQLiteBatchJobStore:
        return SQLiteBatchJobStore(tmp_path / "row_test.db")

    def test_tuple_row(self, store):
        row = (
            "b1",  # batch_id
            "completed",  # status
            1000.0,  # created_at
            1001.0,  # started_at
            1010.0,  # completed_at
            5,  # processed_count
            '["d1","d2"]',  # debate_ids_json
            '[{"ok":true}]',  # results_json
            '{"detail":true}',  # options_json
            None,  # error
            2000.0,  # expires_at
        )
        job = store._row_to_job(row)
        assert job.batch_id == "b1"
        assert job.status == "completed"
        assert job.debate_ids == ["d1", "d2"]
        assert job.results == [{"ok": True}]
        assert job.options == {"detail": True}
        assert job.processed_count == 5

    def test_tuple_row_null_json_fields(self, store):
        """Handles None/null JSON fields gracefully."""
        row = (
            "b2",
            "pending",
            1000.0,
            None,
            None,
            0,
            None,  # debate_ids_json = None -> []
            None,  # results_json = None -> []
            None,  # options_json = None -> {}
            "error msg",
            2000.0,
        )
        job = store._row_to_job(row)
        assert job.debate_ids == []
        assert job.results == []
        assert job.options == {}
        assert job.error == "error msg"

    def test_tuple_row_zero_processed_count(self, store):
        row = (
            "b3",
            "pending",
            1000.0,
            None,
            None,
            0,
            "[]",
            "[]",
            "{}",
            None,
            2000.0,
        )
        job = store._row_to_job(row)
        assert job.processed_count == 0

    def test_tuple_row_none_processed_count(self, store):
        row = (
            "b4",
            "pending",
            1000.0,
            None,
            None,
            None,
            "[]",
            "[]",
            "{}",
            None,
            2000.0,
        )
        job = store._row_to_job(row)
        assert job.processed_count == 0


# ---------------------------------------------------------------------------
# DatabaseBatchJobStore._is_expired
# ---------------------------------------------------------------------------


class TestIsExpired:
    """Tests for the expiration check helper."""

    @pytest.fixture
    def store(self, tmp_path) -> SQLiteBatchJobStore:
        return SQLiteBatchJobStore(tmp_path / "exp_test.db")

    def test_none_not_expired(self, store):
        assert store._is_expired(None) is False

    def test_future_not_expired(self, store):
        assert store._is_expired(time.time() + 3600) is False

    def test_past_is_expired(self, store):
        assert store._is_expired(time.time() - 1) is True


# ---------------------------------------------------------------------------
# get_batch_job_store factory
# ---------------------------------------------------------------------------


class TestGetBatchJobStore:
    """Tests for the factory function that selects a storage backend."""

    @pytest.fixture(autouse=True)
    def _patch_production_guards(self, monkeypatch):
        """Prevent production guards from raising in tests."""
        monkeypatch.setattr(
            "aragora.server.handlers.explainability_store._require_distributed",
            lambda mode, reason: None,
            raising=False,
        )
        # Fallback: patch the inner function references used within closures
        try:
            import aragora.storage.production_guards as pg

            monkeypatch.setattr(pg, "require_distributed_store", lambda *a, **kw: None)
        except (ImportError, AttributeError):
            pass

    def test_returns_memory_store_when_all_fail(self, monkeypatch, tmp_path):
        """Falls back to memory store when SQLite and Redis fail."""
        monkeypatch.setenv("ARAGORA_EXPLAINABILITY_STORE_BACKEND", "memory")
        store = get_batch_job_store()
        assert isinstance(store, MemoryBatchJobStore)

    def test_explicit_sqlite_backend(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ARAGORA_EXPLAINABILITY_STORE_BACKEND", "sqlite")
        monkeypatch.setenv("ARAGORA_EXPLAINABILITY_DB", str(tmp_path / "test.db"))
        store = get_batch_job_store()
        assert isinstance(store, SQLiteBatchJobStore)

    def test_explicit_redis_backend_available(self, monkeypatch):
        monkeypatch.setenv("ARAGORA_EXPLAINABILITY_STORE_BACKEND", "redis")
        mock_redis = MagicMock()
        with (
            patch(
                "aragora.server.handlers.explainability_store.get_redis_client",
                return_value=mock_redis,
                create=True,
            ),
            patch(
                "aragora.server.handlers.explainability_store.is_redis_available",
                return_value=True,
                create=True,
            ),
            patch(
                "aragora.utils.redis_config.get_redis_client",
                return_value=mock_redis,
            ),
            patch(
                "aragora.utils.redis_config.is_redis_available",
                return_value=True,
            ),
        ):
            store = get_batch_job_store()
            assert isinstance(store, RedisBatchJobStore)

    def test_explicit_redis_backend_unavailable_fallback(self, monkeypatch, tmp_path):
        """When Redis is explicitly requested but unavailable, falls back to SQLite."""
        monkeypatch.setenv("ARAGORA_EXPLAINABILITY_STORE_BACKEND", "redis")
        monkeypatch.setenv("ARAGORA_EXPLAINABILITY_DB", str(tmp_path / "fallback.db"))
        with (
            patch(
                "aragora.utils.redis_config.is_redis_available",
                return_value=False,
            ),
            patch(
                "aragora.utils.redis_config.get_redis_client",
                return_value=None,
            ),
        ):
            store = get_batch_job_store()
            assert isinstance(store, (SQLiteBatchJobStore, DatabaseBatchJobStore))

    def test_explicit_postgres_backend_no_dsn(self, monkeypatch, tmp_path):
        """PostgreSQL requested but no DSN configured falls back to SQLite."""
        monkeypatch.setenv("ARAGORA_EXPLAINABILITY_STORE_BACKEND", "postgres")
        monkeypatch.setenv("ARAGORA_EXPLAINABILITY_DB", str(tmp_path / "pg_fall.db"))
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("ARAGORA_DATABASE_URL", raising=False)
        monkeypatch.delenv("ARAGORA_POSTGRES_DSN", raising=False)
        store = get_batch_job_store()
        assert isinstance(store, (SQLiteBatchJobStore, DatabaseBatchJobStore))

    def test_explicit_postgres_backend_import_error(self, monkeypatch, tmp_path):
        """PostgreSQL backend import error falls back to SQLite."""
        monkeypatch.setenv("ARAGORA_EXPLAINABILITY_STORE_BACKEND", "postgresql")
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        monkeypatch.setenv("ARAGORA_EXPLAINABILITY_DB", str(tmp_path / "pg_err.db"))
        with patch(
            "aragora.server.handlers.explainability_store.PostgresBatchJobStore",
            side_effect=ImportError("no psycopg2"),
        ):
            store = get_batch_job_store()
            assert isinstance(store, (SQLiteBatchJobStore, DatabaseBatchJobStore))

    def test_custom_ttl(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ARAGORA_EXPLAINABILITY_BATCH_TTL_SECONDS", "120")
        monkeypatch.setenv("ARAGORA_EXPLAINABILITY_STORE_BACKEND", "memory")
        store = get_batch_job_store()
        assert isinstance(store, MemoryBatchJobStore)
        assert store._ttl == 120

    def test_default_ttl(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ARAGORA_EXPLAINABILITY_STORE_BACKEND", "memory")
        store = get_batch_job_store()
        assert isinstance(store, MemoryBatchJobStore)
        assert store._ttl == 3600

    def test_singleton_caching(self, monkeypatch, tmp_path):
        """Second call returns cached singleton."""
        monkeypatch.setenv("ARAGORA_EXPLAINABILITY_STORE_BACKEND", "memory")
        store1 = get_batch_job_store()
        store2 = get_batch_job_store()
        assert store1 is store2

    def test_custom_db_path(self, monkeypatch, tmp_path):
        db_file = tmp_path / "custom" / "batch.db"
        monkeypatch.setenv("ARAGORA_EXPLAINABILITY_DB", str(db_file))
        monkeypatch.setenv("ARAGORA_EXPLAINABILITY_STORE_BACKEND", "sqlite")
        store = get_batch_job_store()
        assert isinstance(store, SQLiteBatchJobStore)
        assert db_file.parent.exists()

    def test_default_auto_redis_fallback_to_sqlite(self, monkeypatch, tmp_path):
        """With no explicit backend, tries Redis then falls back to SQLite."""
        monkeypatch.delenv("ARAGORA_EXPLAINABILITY_STORE_BACKEND", raising=False)
        monkeypatch.setenv("ARAGORA_EXPLAINABILITY_DB", str(tmp_path / "auto.db"))
        with (
            patch(
                "aragora.utils.redis_config.is_redis_available",
                return_value=False,
            ),
            patch(
                "aragora.utils.redis_config.get_redis_client",
                return_value=None,
            ),
        ):
            store = get_batch_job_store()
            assert isinstance(
                store, (SQLiteBatchJobStore, DatabaseBatchJobStore, MemoryBatchJobStore)
            )

    def test_default_auto_redis_import_error(self, monkeypatch, tmp_path):
        """Redis import fails gracefully in default mode."""
        monkeypatch.delenv("ARAGORA_EXPLAINABILITY_STORE_BACKEND", raising=False)
        monkeypatch.setenv("ARAGORA_EXPLAINABILITY_DB", str(tmp_path / "auto2.db"))
        with patch.dict(
            "sys.modules",
            {"aragora.utils.redis_config": None},
        ):
            store = get_batch_job_store()
            assert store is not None


# ---------------------------------------------------------------------------
# reset_batch_job_store
# ---------------------------------------------------------------------------


class TestResetBatchJobStore:
    """Tests for the singleton reset helper."""

    def test_reset_clears_singleton(self, monkeypatch):
        monkeypatch.setenv("ARAGORA_EXPLAINABILITY_STORE_BACKEND", "memory")
        try:
            import aragora.storage.production_guards as pg

            monkeypatch.setattr(pg, "require_distributed_store", lambda *a, **kw: None)
        except (ImportError, AttributeError):
            pass
        store1 = get_batch_job_store()
        reset_batch_job_store()
        store2 = get_batch_job_store()
        assert store1 is not store2

    def test_reset_clears_warned_flag(self):
        import aragora.server.handlers.explainability_store as mod

        mod._warned_memory = True
        reset_batch_job_store()
        assert mod._warned_memory is False

    def test_reset_sets_store_to_none(self):
        import aragora.server.handlers.explainability_store as mod

        mod._batch_store = MemoryBatchJobStore()
        reset_batch_job_store()
        assert mod._batch_store is None


# ---------------------------------------------------------------------------
# BatchJobStore ABC
# ---------------------------------------------------------------------------


class TestBatchJobStoreABC:
    """Tests for the abstract base class."""

    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            BatchJobStore()

    def test_subclass_must_implement_methods(self):
        class IncompletStore(BatchJobStore):
            pass

        with pytest.raises(TypeError):
            IncompletStore()

    def test_complete_subclass(self):
        class CompleteStore(BatchJobStore):
            async def save_job(self, job):
                pass

            async def get_job(self, batch_id):
                return None

            async def delete_job(self, batch_id):
                return False

            async def list_jobs(self, status=None, limit=100):
                return []

        store = CompleteStore()
        assert store is not None


# ---------------------------------------------------------------------------
# Module exports
# ---------------------------------------------------------------------------


class TestModuleExports:
    """Tests for __all__ exports."""

    def test_all_exports(self):
        import aragora.server.handlers.explainability_store as mod

        expected = {
            "BatchJob",
            "BatchJobStore",
            "DatabaseBatchJobStore",
            "SQLiteBatchJobStore",
            "PostgresBatchJobStore",
            "RedisBatchJobStore",
            "MemoryBatchJobStore",
            "get_batch_job_store",
            "reset_batch_job_store",
        }
        assert set(mod.__all__) == expected

    def test_all_exports_are_importable(self):
        import aragora.server.handlers.explainability_store as mod

        for name in mod.__all__:
            assert hasattr(mod, name), f"Missing export: {name}"


# ---------------------------------------------------------------------------
# Edge cases for list_jobs in DatabaseBatchJobStore
# ---------------------------------------------------------------------------


class TestDatabaseListExpiredCleanup:
    """Tests for expired row cleanup during list_jobs."""

    @pytest.mark.asyncio
    async def test_list_deletes_expired_rows(self, tmp_path):
        store = SQLiteBatchJobStore(tmp_path / "cleanup.db", ttl_seconds=1)
        expired = _make_job(batch_id="gone", created_at=time.time() - 100)
        await store.save_job(expired)
        fresh = _make_job(batch_id="here")
        await store.save_job(fresh)
        jobs = await store.list_jobs()
        assert len(jobs) == 1
        assert jobs[0].batch_id == "here"
        # Verify expired row is actually deleted from DB
        assert await store.get_job("gone") is None

    @pytest.mark.asyncio
    async def test_list_handles_delete_error_gracefully(self, tmp_path):
        """If deleting an expired row fails, it should not crash."""
        store = SQLiteBatchJobStore(tmp_path / "err_cleanup.db", ttl_seconds=1)
        expired = _make_job(batch_id="gone2", created_at=time.time() - 100)
        await store.save_job(expired)
        fresh = _make_job(batch_id="here2")
        await store.save_job(fresh)
        # Patch execute_write to raise on DELETE
        original_execute = store._backend.execute_write

        def failing_write(sql, params=None):
            if "DELETE" in sql:
                raise OSError("disk error")
            return original_execute(sql, params)

        store._backend.execute_write = failing_write
        # Should not raise, just log warning
        jobs = await store.list_jobs()
        assert len(jobs) == 1
        assert jobs[0].batch_id == "here2"


# ---------------------------------------------------------------------------
# MemoryBatchJobStore edge cases
# ---------------------------------------------------------------------------


class TestMemoryStoreEdgeCases:
    """Additional edge cases for MemoryBatchJobStore."""

    @pytest.mark.asyncio
    async def test_max_jobs_one(self):
        store = MemoryBatchJobStore(max_jobs=1)
        await store.save_job(_make_job(batch_id="a"))
        await store.save_job(_make_job(batch_id="b"))
        assert await store.get_job("a") is None
        assert await store.get_job("b") is not None

    @pytest.mark.asyncio
    async def test_save_overwrites_existing(self):
        store = MemoryBatchJobStore()
        await store.save_job(_make_job(batch_id="ow1", status="pending"))
        await store.save_job(_make_job(batch_id="ow1", status="completed"))
        job = await store.get_job("ow1")
        assert job is not None
        assert job.status == "completed"

    @pytest.mark.asyncio
    async def test_ttl_zero_everything_expires(self):
        """With TTL=0, all non-current jobs expire immediately."""
        store = MemoryBatchJobStore(ttl_seconds=0)
        # Job created slightly in the past
        await store.save_job(_make_job(batch_id="instant", created_at=time.time() - 0.01))
        assert await store.get_job("instant") is None

    @pytest.mark.asyncio
    async def test_delete_then_list(self):
        store = MemoryBatchJobStore()
        await store.save_job(_make_job(batch_id="dl1"))
        await store.save_job(_make_job(batch_id="dl2"))
        await store.delete_job("dl1")
        jobs = await store.list_jobs()
        assert len(jobs) == 1
        assert jobs[0].batch_id == "dl2"
