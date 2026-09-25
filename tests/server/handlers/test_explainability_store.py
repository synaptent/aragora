"""
Comprehensive tests for explainability_store.py - Batch job storage backends.

This test module provides thorough coverage of the storage layer for
explainability batch jobs, testing each backend implementation:
- MemoryBatchJobStore (in-memory with LRU eviction)
- SQLiteBatchJobStore (SQLite-backed)
- PostgresBatchJobStore (PostgreSQL-backed, mocked)
- RedisBatchJobStore (Redis-backed, mocked)
- DatabaseBatchJobStore (abstract database backend)

Also covers:
- Singleton management (get_batch_job_store, reset_batch_job_store)
- Backend selection logic based on environment variables
- TTL expiration and cleanup
- Error handling and edge cases
- BatchJob dataclass serialization
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, Mock

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


# ===========================================================================
# Test Fixtures
# ===========================================================================


@pytest.fixture(autouse=True)
def reset_store_singleton():
    """Reset batch job store singleton before and after each test."""
    reset_batch_job_store()
    yield
    reset_batch_job_store()


@pytest.fixture
def memory_store():
    """Create a MemoryBatchJobStore for testing."""
    return MemoryBatchJobStore(max_jobs=10, ttl_seconds=3600)


@pytest.fixture
def sample_job():
    """Create a sample BatchJob for testing."""
    return BatchJob(
        batch_id="batch-test-001",
        debate_ids=["debate-1", "debate-2", "debate-3"],
        status="pending",
        created_at=time.time(),
        options={"include_evidence": True, "format": "full"},
    )


@pytest.fixture
def completed_job():
    """Create a completed BatchJob for testing."""
    now = time.time()
    return BatchJob(
        batch_id="batch-completed-001",
        debate_ids=["debate-a", "debate-b"],
        status="completed",
        created_at=now - 100,
        started_at=now - 80,
        completed_at=now - 10,
        results=[
            {"debate_id": "debate-a", "status": "success", "explanation": {"confidence": 0.95}},
            {"debate_id": "debate-b", "status": "success", "explanation": {"confidence": 0.88}},
        ],
        processed_count=2,
        options={"format": "minimal"},
        error=None,
    )


@pytest.fixture
def failed_job():
    """Create a failed BatchJob for testing."""
    now = time.time()
    return BatchJob(
        batch_id="batch-failed-001",
        debate_ids=["debate-x"],
        status="failed",
        created_at=now - 200,
        started_at=now - 180,
        completed_at=now - 150,
        results=[],
        processed_count=0,
        options={},
        error="Connection timeout: unable to reach debate service",
    )


@pytest.fixture
def sqlite_store(tmp_path):
    """Create a SQLiteBatchJobStore for testing."""
    db_path = tmp_path / "test_explainability_batch.db"
    return SQLiteBatchJobStore(db_path, ttl_seconds=3600)


@pytest.fixture
def mock_redis_client():
    """Create a mock Redis client for testing RedisBatchJobStore."""
    client = MagicMock()
    client.setex = MagicMock()
    client.get = MagicMock(return_value=None)
    client.delete = MagicMock(return_value=1)
    client.scan = MagicMock(return_value=(0, []))
    return client


@pytest.fixture
def redis_store(mock_redis_client):
    """Create a RedisBatchJobStore with mock client."""
    return RedisBatchJobStore(mock_redis_client, key_prefix="test:batch:", ttl=3600)


# ===========================================================================
# BatchJob Dataclass Tests
# ===========================================================================


class TestBatchJobDataclass:
    """Test BatchJob dataclass functionality."""

    def test_create_with_minimal_fields(self):
        """Should create job with only required fields."""
        job = BatchJob(batch_id="batch-min", debate_ids=["d1"])

        assert job.batch_id == "batch-min"
        assert job.debate_ids == ["d1"]
        assert job.status == "pending"
        assert job.started_at is None
        assert job.completed_at is None
        assert job.results == []
        assert job.processed_count == 0
        assert job.options == {}
        assert job.error is None

    def test_create_with_all_fields(self, completed_job):
        """Should create job with all fields populated."""
        assert completed_job.batch_id == "batch-completed-001"
        assert completed_job.status == "completed"
        assert completed_job.started_at is not None
        assert completed_job.completed_at is not None
        assert len(completed_job.results) == 2
        assert completed_job.processed_count == 2

    def test_to_dict_roundtrip(self, sample_job):
        """Should serialize and deserialize correctly."""
        as_dict = sample_job.to_dict()
        restored = BatchJob.from_dict(as_dict)

        assert restored.batch_id == sample_job.batch_id
        assert restored.debate_ids == sample_job.debate_ids
        assert restored.status == sample_job.status
        assert restored.options == sample_job.options

    def test_to_dict_contains_all_fields(self, completed_job):
        """Should include all fields in dict representation."""
        as_dict = completed_job.to_dict()

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
        assert set(as_dict.keys()) == expected_keys

    def test_from_dict_with_error(self, failed_job):
        """Should preserve error field through serialization."""
        as_dict = failed_job.to_dict()
        restored = BatchJob.from_dict(as_dict)

        assert restored.error == failed_job.error
        assert restored.status == "failed"

    def test_created_at_default_factory(self):
        """Should set created_at to current time by default."""
        before = time.time()
        job = BatchJob(batch_id="batch-time", debate_ids=["d1"])
        after = time.time()

        assert before <= job.created_at <= after


# ===========================================================================
# MemoryBatchJobStore Tests
# ===========================================================================


class TestMemoryBatchJobStore:
    """Test in-memory batch job storage."""

    @pytest.mark.asyncio
    async def test_save_and_get_job(self, memory_store, sample_job):
        """Should save and retrieve job correctly."""
        await memory_store.save_job(sample_job)

        retrieved = await memory_store.get_job("batch-test-001")

        assert retrieved is not None
        assert retrieved.batch_id == sample_job.batch_id
        assert retrieved.debate_ids == sample_job.debate_ids
        assert retrieved.options == sample_job.options

    @pytest.mark.asyncio
    async def test_get_nonexistent_job_returns_none(self, memory_store):
        """Should return None for nonexistent job."""
        result = await memory_store.get_job("nonexistent-batch")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_existing_job(self, memory_store, sample_job):
        """Should delete existing job and return True."""
        await memory_store.save_job(sample_job)

        result = await memory_store.delete_job("batch-test-001")

        assert result is True
        assert await memory_store.get_job("batch-test-001") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_job_returns_false(self, memory_store):
        """Should return False when deleting nonexistent job."""
        result = await memory_store.delete_job("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_list_all_jobs(self, memory_store, sample_job, completed_job, failed_job):
        """Should list all jobs without filter."""
        await memory_store.save_job(sample_job)
        await memory_store.save_job(completed_job)
        await memory_store.save_job(failed_job)

        jobs = await memory_store.list_jobs()

        assert len(jobs) == 3
        batch_ids = {j.batch_id for j in jobs}
        assert "batch-test-001" in batch_ids
        assert "batch-completed-001" in batch_ids
        assert "batch-failed-001" in batch_ids

    @pytest.mark.asyncio
    async def test_list_jobs_with_status_filter(
        self, memory_store, sample_job, completed_job, failed_job
    ):
        """Should filter jobs by status."""
        await memory_store.save_job(sample_job)
        await memory_store.save_job(completed_job)
        await memory_store.save_job(failed_job)

        pending_jobs = await memory_store.list_jobs(status="pending")
        completed_jobs = await memory_store.list_jobs(status="completed")
        failed_jobs = await memory_store.list_jobs(status="failed")

        assert len(pending_jobs) == 1
        assert pending_jobs[0].batch_id == "batch-test-001"

        assert len(completed_jobs) == 1
        assert completed_jobs[0].batch_id == "batch-completed-001"

        assert len(failed_jobs) == 1
        assert failed_jobs[0].batch_id == "batch-failed-001"

    @pytest.mark.asyncio
    async def test_list_jobs_with_limit(self, memory_store):
        """Should respect limit parameter."""
        for i in range(10):
            job = BatchJob(batch_id=f"batch-{i:03d}", debate_ids=["d1"])
            await memory_store.save_job(job)

        jobs = await memory_store.list_jobs(limit=5)

        assert len(jobs) == 5

    @pytest.mark.asyncio
    async def test_lru_eviction_at_capacity(self):
        """Should evict oldest jobs when at capacity."""
        store = MemoryBatchJobStore(max_jobs=3, ttl_seconds=3600)

        for i in range(5):
            job = BatchJob(batch_id=f"batch-{i}", debate_ids=["d1"])
            await store.save_job(job)

        # Oldest jobs should be evicted
        assert await store.get_job("batch-0") is None
        assert await store.get_job("batch-1") is None

        # Most recent jobs should remain
        assert await store.get_job("batch-2") is not None
        assert await store.get_job("batch-3") is not None
        assert await store.get_job("batch-4") is not None

    @pytest.mark.asyncio
    async def test_get_moves_to_end_for_lru(self):
        """Should update LRU order when job is accessed."""
        store = MemoryBatchJobStore(max_jobs=3, ttl_seconds=3600)

        for i in range(3):
            job = BatchJob(batch_id=f"batch-{i}", debate_ids=["d1"])
            await store.save_job(job)

        # Access batch-0, making it most recently used
        await store.get_job("batch-0")

        # Add two more jobs
        await store.save_job(BatchJob(batch_id="batch-3", debate_ids=["d1"]))
        await store.save_job(BatchJob(batch_id="batch-4", debate_ids=["d1"]))

        # batch-0 should still exist (was accessed), batch-1 and batch-2 evicted
        assert await store.get_job("batch-0") is not None
        assert await store.get_job("batch-1") is None
        assert await store.get_job("batch-2") is None

    @pytest.mark.asyncio
    async def test_ttl_expiration_on_get(self):
        """Should return None and remove expired jobs on get."""
        store = MemoryBatchJobStore(max_jobs=10, ttl_seconds=1)

        # Create job with old timestamp
        job = BatchJob(
            batch_id="batch-expired",
            debate_ids=["d1"],
            created_at=time.time() - 100,
        )
        store._jobs["batch-expired"] = job

        # Should return None due to TTL
        result = await store.get_job("batch-expired")

        assert result is None
        assert "batch-expired" not in store._jobs

    @pytest.mark.asyncio
    async def test_ttl_expiration_on_list(self):
        """Should exclude expired jobs from list."""
        store = MemoryBatchJobStore(max_jobs=10, ttl_seconds=1)

        # Create fresh job
        fresh_job = BatchJob(batch_id="batch-fresh", debate_ids=["d1"])
        await store.save_job(fresh_job)

        # Create expired job directly
        expired_job = BatchJob(
            batch_id="batch-expired",
            debate_ids=["d1"],
            created_at=time.time() - 100,
        )
        store._jobs["batch-expired"] = expired_job

        jobs = await store.list_jobs()

        assert len(jobs) == 1
        assert jobs[0].batch_id == "batch-fresh"

    @pytest.mark.asyncio
    async def test_update_existing_job(self, memory_store, sample_job):
        """Should update existing job when saved again."""
        await memory_store.save_job(sample_job)

        # Modify and save again
        sample_job.status = "processing"
        sample_job.started_at = time.time()
        await memory_store.save_job(sample_job)

        retrieved = await memory_store.get_job("batch-test-001")

        assert retrieved.status == "processing"
        assert retrieved.started_at is not None


# ===========================================================================
# SQLiteBatchJobStore Tests
# ===========================================================================


class TestSQLiteBatchJobStore:
    """Test SQLite-backed batch job storage."""

    @pytest.mark.asyncio
    async def test_save_and_get_job(self, sqlite_store, sample_job):
        """Should save and retrieve job from SQLite."""
        await sqlite_store.save_job(sample_job)

        retrieved = await sqlite_store.get_job("batch-test-001")

        assert retrieved is not None
        assert retrieved.batch_id == sample_job.batch_id
        assert retrieved.debate_ids == sample_job.debate_ids
        assert retrieved.options == sample_job.options

    @pytest.mark.asyncio
    async def test_get_nonexistent_job_returns_none(self, sqlite_store):
        """Should return None for nonexistent job."""
        result = await sqlite_store.get_job("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_job(self, sqlite_store, sample_job):
        """Should delete job from SQLite."""
        await sqlite_store.save_job(sample_job)

        result = await sqlite_store.delete_job("batch-test-001")

        assert result is True
        assert await sqlite_store.get_job("batch-test-001") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_always_returns_true(self, sqlite_store):
        """SQLite delete always returns True (even if nothing deleted)."""
        result = await sqlite_store.delete_job("nonexistent")
        assert result is True

    @pytest.mark.asyncio
    async def test_list_jobs_all(self, sqlite_store, sample_job, completed_job, failed_job):
        """Should list all jobs from SQLite."""
        await sqlite_store.save_job(sample_job)
        await sqlite_store.save_job(completed_job)
        await sqlite_store.save_job(failed_job)

        jobs = await sqlite_store.list_jobs()

        assert len(jobs) == 3

    @pytest.mark.asyncio
    async def test_list_jobs_by_status(self, sqlite_store, sample_job, completed_job):
        """Should filter jobs by status in SQLite."""
        await sqlite_store.save_job(sample_job)
        await sqlite_store.save_job(completed_job)

        pending = await sqlite_store.list_jobs(status="pending")
        completed = await sqlite_store.list_jobs(status="completed")

        assert len(pending) == 1
        assert pending[0].batch_id == "batch-test-001"

        assert len(completed) == 1
        assert completed[0].batch_id == "batch-completed-001"

    @pytest.mark.asyncio
    async def test_list_jobs_with_limit(self, sqlite_store):
        """Should respect limit in SQLite queries."""
        for i in range(10):
            job = BatchJob(batch_id=f"batch-{i:03d}", debate_ids=["d1"])
            await sqlite_store.save_job(job)

        jobs = await sqlite_store.list_jobs(limit=3)

        assert len(jobs) == 3

    @pytest.mark.asyncio
    async def test_upsert_updates_existing(self, sqlite_store, sample_job):
        """Should update existing job on conflict."""
        await sqlite_store.save_job(sample_job)

        # Modify and save again
        sample_job.status = "completed"
        sample_job.completed_at = time.time()
        sample_job.processed_count = 3
        sample_job.results = [{"debate_id": "d1", "status": "success"}]
        await sqlite_store.save_job(sample_job)

        retrieved = await sqlite_store.get_job("batch-test-001")

        assert retrieved.status == "completed"
        assert retrieved.completed_at is not None
        assert retrieved.processed_count == 3
        assert len(retrieved.results) == 1

    @pytest.mark.asyncio
    async def test_complex_json_serialization(self, sqlite_store):
        """Should correctly serialize complex JSON structures."""
        job = BatchJob(
            batch_id="batch-complex",
            debate_ids=["d1", "d2", "d3"],
            results=[
                {
                    "debate_id": "d1",
                    "status": "success",
                    "explanation": {
                        "factors": [
                            {"name": "evidence", "weight": 0.4, "items": ["e1", "e2"]},
                            {"name": "consensus", "weight": 0.3},
                        ],
                        "confidence": 0.92,
                        "nested": {"level1": {"level2": {"value": 42}}},
                    },
                },
            ],
            options={
                "include_evidence": True,
                "format": "full",
                "filters": {"min_confidence": 0.5, "sources": ["internal", "external"]},
            },
        )

        await sqlite_store.save_job(job)
        retrieved = await sqlite_store.get_job("batch-complex")

        assert retrieved.results[0]["explanation"]["confidence"] == 0.92
        assert retrieved.results[0]["explanation"]["nested"]["level1"]["level2"]["value"] == 42
        assert retrieved.options["filters"]["min_confidence"] == 0.5

    @pytest.mark.asyncio
    async def test_ttl_expiration_on_get(self, tmp_path):
        """Should return None for expired jobs on get."""
        db_path = tmp_path / "test_ttl.db"
        store = SQLiteBatchJobStore(db_path, ttl_seconds=1)

        # Create job with old timestamp
        job = BatchJob(
            batch_id="batch-old",
            debate_ids=["d1"],
            created_at=time.time() - 100,
        )
        await store.save_job(job)

        # Should return None due to TTL
        result = await store.get_job("batch-old")

        assert result is None

    @pytest.mark.asyncio
    async def test_ttl_expiration_on_list(self, tmp_path):
        """Should exclude expired jobs from list and clean them up."""
        db_path = tmp_path / "test_ttl_list.db"
        store = SQLiteBatchJobStore(db_path, ttl_seconds=1)

        # Create fresh job
        fresh_job = BatchJob(batch_id="batch-fresh", debate_ids=["d1"])
        await store.save_job(fresh_job)

        # Create old job
        old_job = BatchJob(
            batch_id="batch-old",
            debate_ids=["d1"],
            created_at=time.time() - 100,
        )
        await store.save_job(old_job)

        jobs = await store.list_jobs()

        assert len(jobs) == 1
        assert jobs[0].batch_id == "batch-fresh"


# ===========================================================================
# RedisBatchJobStore Tests
# ===========================================================================


class TestRedisBatchJobStore:
    """Test Redis-backed batch job storage."""

    def test_key_generation(self, redis_store):
        """Should generate correct Redis keys."""
        key = redis_store._key("batch-123")
        assert key == "test:batch:batch-123"

    @pytest.mark.asyncio
    async def test_save_job(self, redis_store, mock_redis_client, sample_job):
        """Should save job with correct TTL."""
        await redis_store.save_job(sample_job)

        mock_redis_client.setex.assert_called_once()
        call_args = mock_redis_client.setex.call_args

        assert call_args[0][0] == "test:batch:batch-test-001"
        assert call_args[0][1] == 3600  # TTL

        # Verify JSON serialization
        saved_data = json.loads(call_args[0][2])
        assert saved_data["batch_id"] == "batch-test-001"
        assert saved_data["debate_ids"] == ["debate-1", "debate-2", "debate-3"]

    @pytest.mark.asyncio
    async def test_get_job_exists(self, redis_store, mock_redis_client, sample_job):
        """Should retrieve existing job from Redis."""
        # Configure mock to return job data
        mock_redis_client.get.return_value = json.dumps(sample_job.to_dict()).encode()

        result = await redis_store.get_job("batch-test-001")

        assert result is not None
        assert result.batch_id == "batch-test-001"
        assert result.debate_ids == sample_job.debate_ids
        mock_redis_client.get.assert_called_with("test:batch:batch-test-001")

    @pytest.mark.asyncio
    async def test_get_job_not_exists(self, redis_store, mock_redis_client):
        """Should return None when job not in Redis."""
        mock_redis_client.get.return_value = None

        result = await redis_store.get_job("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_job_handles_string_response(
        self, redis_store, mock_redis_client, sample_job
    ):
        """Should handle string (not bytes) response from Redis."""
        mock_redis_client.get.return_value = json.dumps(sample_job.to_dict())  # String, not bytes

        result = await redis_store.get_job("batch-test-001")

        assert result is not None
        assert result.batch_id == "batch-test-001"

    @pytest.mark.asyncio
    async def test_delete_job_exists(self, redis_store, mock_redis_client):
        """Should delete job and return True when exists."""
        mock_redis_client.delete.return_value = 1

        result = await redis_store.delete_job("batch-test-001")

        assert result is True
        mock_redis_client.delete.assert_called_with("test:batch:batch-test-001")

    @pytest.mark.asyncio
    async def test_delete_job_not_exists(self, redis_store, mock_redis_client):
        """Should return False when job doesn't exist."""
        mock_redis_client.delete.return_value = 0

        result = await redis_store.delete_job("nonexistent")

        assert result is False

    @pytest.mark.asyncio
    async def test_list_jobs_empty(self, redis_store, mock_redis_client):
        """Should return empty list when no jobs."""
        mock_redis_client.scan.return_value = (0, [])

        jobs = await redis_store.list_jobs()

        assert jobs == []

    @pytest.mark.asyncio
    async def test_list_jobs_with_data(
        self, redis_store, mock_redis_client, sample_job, completed_job
    ):
        """Should list all jobs from Redis."""
        # Mock scan to return two keys
        mock_redis_client.scan.return_value = (
            0,
            [b"test:batch:batch-test-001", b"test:batch:batch-completed-001"],
        )

        # Mock get to return job data for each key
        def get_side_effect(key):
            if key == b"test:batch:batch-test-001" or key == "test:batch:batch-test-001":
                return json.dumps(sample_job.to_dict()).encode()
            elif (
                key == b"test:batch:batch-completed-001" or key == "test:batch:batch-completed-001"
            ):
                return json.dumps(completed_job.to_dict()).encode()
            return None

        mock_redis_client.get.side_effect = get_side_effect

        jobs = await redis_store.list_jobs()

        assert len(jobs) == 2
        batch_ids = {j.batch_id for j in jobs}
        assert "batch-test-001" in batch_ids
        assert "batch-completed-001" in batch_ids

    @pytest.mark.asyncio
    async def test_list_jobs_with_status_filter(
        self, redis_store, mock_redis_client, sample_job, completed_job
    ):
        """Should filter jobs by status."""
        mock_redis_client.scan.return_value = (
            0,
            [b"test:batch:batch-test-001", b"test:batch:batch-completed-001"],
        )

        def get_side_effect(key):
            if "batch-test-001" in str(key):
                return json.dumps(sample_job.to_dict()).encode()
            elif "batch-completed-001" in str(key):
                return json.dumps(completed_job.to_dict()).encode()
            return None

        mock_redis_client.get.side_effect = get_side_effect

        pending_jobs = await redis_store.list_jobs(status="pending")
        completed_jobs = await redis_store.list_jobs(status="completed")

        assert len(pending_jobs) == 1
        assert pending_jobs[0].batch_id == "batch-test-001"

        assert len(completed_jobs) == 1
        assert completed_jobs[0].batch_id == "batch-completed-001"

    @pytest.mark.asyncio
    async def test_list_jobs_respects_limit(self, redis_store, mock_redis_client):
        """Should stop after reaching limit."""
        # Create mock keys for 10 jobs
        keys = [f"test:batch:batch-{i:03d}".encode() for i in range(10)]
        mock_redis_client.scan.return_value = (0, keys)

        def get_side_effect(key):
            batch_id = key.decode() if isinstance(key, bytes) else key
            batch_id = batch_id.split(":")[-1]
            return json.dumps(BatchJob(batch_id=batch_id, debate_ids=["d1"]).to_dict()).encode()

        mock_redis_client.get.side_effect = get_side_effect

        jobs = await redis_store.list_jobs(limit=5)

        assert len(jobs) == 5

    @pytest.mark.asyncio
    async def test_list_jobs_handles_scan_pagination(
        self, redis_store, mock_redis_client, sample_job
    ):
        """Should handle Redis SCAN pagination."""
        # First scan returns cursor > 0, indicating more data
        # Second scan returns cursor = 0, indicating end
        scan_calls = [0]

        def scan_side_effect(cursor, **kwargs):
            if scan_calls[0] == 0:
                scan_calls[0] += 1
                return (1, [b"test:batch:batch-test-001"])  # More data
            else:
                return (0, [])  # End of scan

        mock_redis_client.scan.side_effect = scan_side_effect
        mock_redis_client.get.return_value = json.dumps(sample_job.to_dict()).encode()

        jobs = await redis_store.list_jobs()

        assert len(jobs) == 1
        assert mock_redis_client.scan.call_count == 2


# ===========================================================================
# PostgresBatchJobStore Tests
# ===========================================================================


class TestPostgresBatchJobStore:
    """Test PostgreSQL-backed batch job storage."""

    def test_requires_psycopg2(self):
        """Should raise ImportError when psycopg2 not available."""
        with patch.dict("sys.modules", {"psycopg2": None}):
            with patch("aragora.storage.backends.POSTGRESQL_AVAILABLE", False):
                with pytest.raises(ImportError, match="psycopg2"):
                    PostgresBatchJobStore("postgresql://localhost/test")

    def test_creates_backend_with_url(self, tmp_path):
        """Should create store with PostgreSQL URL when available."""
        # Mock PostgreSQL being available and the backend class
        mock_backend = MagicMock()
        mock_backend.execute_write = MagicMock()

        with patch("aragora.server.handlers.explainability_store.POSTGRESQL_AVAILABLE", True):
            with patch(
                "aragora.server.handlers.explainability_store.PostgreSQLBackend",
                return_value=mock_backend,
            ):
                store = PostgresBatchJobStore(
                    "postgresql://user:pass@localhost/db",
                    ttl_seconds=7200,
                )

                assert store._ttl == 7200
                # Verify schema init was called
                assert mock_backend.execute_write.called


# ===========================================================================
# DatabaseBatchJobStore Internal Methods Tests
# ===========================================================================


class TestDatabaseBatchJobStoreInternals:
    """Test internal methods of DatabaseBatchJobStore."""

    def test_row_to_job_from_sqlite_row(self, sqlite_store, sample_job):
        """Should convert sqlite3.Row to BatchJob."""
        import sqlite3

        # Create a real sqlite3.Row
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE test (
                batch_id TEXT, status TEXT, created_at REAL, started_at REAL,
                completed_at REAL, processed_count INTEGER, debate_ids_json TEXT,
                results_json TEXT, options_json TEXT, error TEXT, expires_at REAL
            )
        """)
        conn.execute(
            "INSERT INTO test VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "batch-row-test",
                "pending",
                time.time(),
                None,
                None,
                0,
                '["d1", "d2"]',
                "[]",
                '{"key": "value"}',
                None,
                time.time() + 3600,
            ),
        )
        cursor = conn.execute("SELECT * FROM test")
        row = cursor.fetchone()

        job = sqlite_store._row_to_job(row)

        assert job.batch_id == "batch-row-test"
        assert job.debate_ids == ["d1", "d2"]
        assert job.options == {"key": "value"}

    def test_row_to_job_from_tuple(self, sqlite_store):
        """Should convert plain tuple to BatchJob."""
        row = (
            "batch-tuple-test",  # batch_id
            "completed",  # status
            time.time() - 100,  # created_at
            time.time() - 80,  # started_at
            time.time() - 10,  # completed_at
            5,  # processed_count
            '["d1"]',  # debate_ids_json
            '[{"id": "r1"}]',  # results_json
            "{}",  # options_json
            None,  # error
            time.time() + 3600,  # expires_at
        )

        job = sqlite_store._row_to_job(row)

        assert job.batch_id == "batch-tuple-test"
        assert job.status == "completed"
        assert job.debate_ids == ["d1"]
        assert job.results == [{"id": "r1"}]

    def test_is_expired_with_future_timestamp(self, sqlite_store):
        """Should return False for future expiry timestamp."""
        future_time = time.time() + 3600
        assert sqlite_store._is_expired(future_time) is False

    def test_is_expired_with_past_timestamp(self, sqlite_store):
        """Should return True for past expiry timestamp."""
        past_time = time.time() - 100
        assert sqlite_store._is_expired(past_time) is True

    def test_is_expired_with_none(self, sqlite_store):
        """Should return False for None expiry timestamp."""
        assert sqlite_store._is_expired(None) is False


# ===========================================================================
# Singleton Management Tests
# ===========================================================================


class TestSingletonManagement:
    """Test get_batch_job_store and reset_batch_job_store."""

    def test_returns_same_instance(self):
        """Should return same instance on subsequent calls."""
        with patch.dict(os.environ, {"ARAGORA_EXPLAINABILITY_STORE_BACKEND": "memory"}):
            with patch("aragora.storage.production_guards.require_distributed_store"):
                store1 = get_batch_job_store()
                store2 = get_batch_job_store()

                assert store1 is store2

    def test_reset_creates_new_instance(self):
        """Should create new instance after reset."""
        with patch.dict(os.environ, {"ARAGORA_EXPLAINABILITY_STORE_BACKEND": "memory"}):
            with patch("aragora.storage.production_guards.require_distributed_store"):
                store1 = get_batch_job_store()
                reset_batch_job_store()
                store2 = get_batch_job_store()

                assert store1 is not store2

    def test_explicit_memory_backend(self):
        """Should use memory backend when explicitly configured."""
        with patch.dict(os.environ, {"ARAGORA_EXPLAINABILITY_STORE_BACKEND": "memory"}):
            with patch("aragora.storage.production_guards.require_distributed_store"):
                store = get_batch_job_store()

                assert isinstance(store, MemoryBatchJobStore)

    def test_explicit_sqlite_backend(self, tmp_path):
        """Should use SQLite backend when explicitly configured."""
        db_path = str(tmp_path / "explicit_sqlite.db")

        with patch.dict(
            os.environ,
            {
                "ARAGORA_EXPLAINABILITY_STORE_BACKEND": "sqlite",
                "ARAGORA_EXPLAINABILITY_DB": db_path,
            },
        ):
            with patch("aragora.storage.production_guards.require_distributed_store"):
                store = get_batch_job_store()

                assert isinstance(store, SQLiteBatchJobStore)

    def test_explicit_redis_backend_available(self):
        """Should use Redis backend when configured and available."""
        mock_redis_client = MagicMock()

        with patch.dict(os.environ, {"ARAGORA_EXPLAINABILITY_STORE_BACKEND": "redis"}):
            with patch("aragora.utils.redis_config.is_redis_available", return_value=True):
                with patch(
                    "aragora.utils.redis_config.get_redis_client", return_value=mock_redis_client
                ):
                    store = get_batch_job_store()

                    assert isinstance(store, RedisBatchJobStore)

    def test_explicit_redis_backend_unavailable_fallback(self, tmp_path):
        """Should fallback to SQLite when Redis requested but unavailable."""
        db_path = str(tmp_path / "fallback.db")

        with patch.dict(
            os.environ,
            {
                "ARAGORA_EXPLAINABILITY_STORE_BACKEND": "redis",
                "ARAGORA_EXPLAINABILITY_DB": db_path,
            },
        ):
            with patch("aragora.utils.redis_config.is_redis_available", return_value=False):
                with patch("aragora.storage.production_guards.require_distributed_store"):
                    store = get_batch_job_store()

                    assert isinstance(store, SQLiteBatchJobStore)

    def test_explicit_postgres_backend_no_url(self, tmp_path):
        """Should fallback to SQLite when Postgres requested but no URL."""
        db_path = str(tmp_path / "no_postgres.db")

        env_vars = {
            "ARAGORA_EXPLAINABILITY_STORE_BACKEND": "postgres",
            "ARAGORA_EXPLAINABILITY_DB": db_path,
        }
        # Remove any DATABASE_URL
        for key in ["DATABASE_URL", "ARAGORA_DATABASE_URL", "ARAGORA_POSTGRES_DSN"]:
            env_vars[key] = ""

        with patch.dict(os.environ, env_vars, clear=False):
            with patch("aragora.storage.production_guards.require_distributed_store"):
                # Ensure no URL
                os.environ.pop("DATABASE_URL", None)
                os.environ.pop("ARAGORA_DATABASE_URL", None)
                os.environ.pop("ARAGORA_POSTGRES_DSN", None)

                store = get_batch_job_store()

                assert isinstance(store, SQLiteBatchJobStore)

    def test_custom_ttl_from_environment(self):
        """Should use custom TTL from environment variable."""
        with patch.dict(
            os.environ,
            {
                "ARAGORA_EXPLAINABILITY_STORE_BACKEND": "memory",
                "ARAGORA_EXPLAINABILITY_BATCH_TTL_SECONDS": "7200",
            },
        ):
            with patch("aragora.storage.production_guards.require_distributed_store"):
                store = get_batch_job_store()

                assert isinstance(store, MemoryBatchJobStore)
                assert store._ttl == 7200

    def test_default_ttl_when_not_set(self):
        """Should use default TTL (3600) when not configured."""
        with patch.dict(os.environ, {"ARAGORA_EXPLAINABILITY_STORE_BACKEND": "memory"}):
            # Remove TTL env var if present
            os.environ.pop("ARAGORA_EXPLAINABILITY_BATCH_TTL_SECONDS", None)

            with patch("aragora.storage.production_guards.require_distributed_store"):
                store = get_batch_job_store()

                assert store._ttl == 3600

    def test_default_behavior_tries_redis_first(self):
        """Should try Redis first when no backend preference."""
        mock_redis_client = MagicMock()

        # No ARAGORA_EXPLAINABILITY_STORE_BACKEND set
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ARAGORA_EXPLAINABILITY_STORE_BACKEND", None)

            with patch("aragora.utils.redis_config.is_redis_available", return_value=True):
                with patch(
                    "aragora.utils.redis_config.get_redis_client", return_value=mock_redis_client
                ):
                    store = get_batch_job_store()

                    assert isinstance(store, RedisBatchJobStore)

    def test_custom_db_path_from_environment(self, tmp_path):
        """Should use custom DB path from ARAGORA_EXPLAINABILITY_DB."""
        custom_path = tmp_path / "custom_location" / "batch.db"

        with patch.dict(
            os.environ,
            {
                "ARAGORA_EXPLAINABILITY_STORE_BACKEND": "sqlite",
                "ARAGORA_EXPLAINABILITY_DB": str(custom_path),
            },
        ):
            with patch("aragora.storage.production_guards.require_distributed_store"):
                store = get_batch_job_store()

                assert isinstance(store, SQLiteBatchJobStore)
                # Parent directory should be created
                assert custom_path.parent.exists()


# ===========================================================================
# Edge Cases and Error Handling Tests
# ===========================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_empty_debate_ids_list(self, memory_store):
        """Should handle job with empty debate_ids."""
        job = BatchJob(batch_id="batch-empty", debate_ids=[])

        await memory_store.save_job(job)
        retrieved = await memory_store.get_job("batch-empty")

        assert retrieved.debate_ids == []

    @pytest.mark.asyncio
    async def test_null_values_in_json_fields(self, sqlite_store):
        """Should handle null/None values in JSON fields."""
        job = BatchJob(
            batch_id="batch-nulls",
            debate_ids=["d1"],
            results=[{"id": "r1", "value": None}],
            options={"key": None},
        )

        await sqlite_store.save_job(job)
        retrieved = await sqlite_store.get_job("batch-nulls")

        assert retrieved.results[0]["value"] is None
        assert retrieved.options["key"] is None

    @pytest.mark.asyncio
    async def test_unicode_in_fields(self, sqlite_store):
        """Should handle Unicode characters in fields."""
        job = BatchJob(
            batch_id="batch-unicode",
            debate_ids=["debate-\u4e2d\u6587"],  # Chinese characters
            options={"description": "Test with emoji \U0001f680 and special chars \xe9\xe8\xe0"},
            error="Error: \u0414\u0430\u043d\u043d\u044b\u0435",  # Russian characters
        )

        await sqlite_store.save_job(job)
        retrieved = await sqlite_store.get_job("batch-unicode")

        assert "\u4e2d\u6587" in retrieved.debate_ids[0]
        assert "\U0001f680" in retrieved.options["description"]
        assert "\u0414\u0430\u043d\u043d\u044b\u0435" in retrieved.error

    @pytest.mark.asyncio
    async def test_very_large_results_list(self, sqlite_store):
        """Should handle large results list."""
        large_results = [
            {"debate_id": f"d-{i}", "status": "success", "data": "x" * 100} for i in range(100)
        ]

        job = BatchJob(
            batch_id="batch-large",
            debate_ids=[f"d-{i}" for i in range(100)],
            results=large_results,
        )

        await sqlite_store.save_job(job)
        retrieved = await sqlite_store.get_job("batch-large")

        assert len(retrieved.results) == 100
        assert len(retrieved.debate_ids) == 100

    @pytest.mark.asyncio
    async def test_special_characters_in_batch_id(self, memory_store):
        """Should handle special characters in batch_id."""
        special_ids = [
            "batch-with-dashes",
            "batch_with_underscores",
            "batch.with.dots",
            "batch:with:colons",
        ]

        for batch_id in special_ids:
            job = BatchJob(batch_id=batch_id, debate_ids=["d1"])
            await memory_store.save_job(job)
            retrieved = await memory_store.get_job(batch_id)

            assert retrieved is not None
            assert retrieved.batch_id == batch_id

    @pytest.mark.asyncio
    async def test_list_jobs_empty_status_filter(self, memory_store, sample_job):
        """Should return empty list when no jobs match status."""
        await memory_store.save_job(sample_job)

        jobs = await memory_store.list_jobs(status="nonexistent_status")

        assert jobs == []

    @pytest.mark.asyncio
    async def test_sqlite_handles_concurrent_access(self, tmp_path):
        """Should handle concurrent access to SQLite store."""
        import asyncio

        db_path = tmp_path / "concurrent.db"
        store = SQLiteBatchJobStore(db_path, ttl_seconds=3600)

        async def save_job(index):
            job = BatchJob(batch_id=f"batch-{index}", debate_ids=["d1"])
            await store.save_job(job)
            return await store.get_job(f"batch-{index}")

        # Run 10 concurrent saves
        results = await asyncio.gather(*[save_job(i) for i in range(10)])

        # All should succeed
        assert all(r is not None for r in results)

        # All jobs should be retrievable
        jobs = await store.list_jobs()
        assert len(jobs) == 10


# ===========================================================================
# Integration Tests
# ===========================================================================


class TestStoreIntegration:
    """Integration tests for batch job stores."""

    @pytest.mark.asyncio
    async def test_job_lifecycle_memory(self, memory_store):
        """Test complete job lifecycle in memory store."""
        # Create pending job
        job = BatchJob(
            batch_id="batch-lifecycle",
            debate_ids=["d1", "d2", "d3"],
            status="pending",
        )
        await memory_store.save_job(job)

        # Start processing
        job.status = "processing"
        job.started_at = time.time()
        await memory_store.save_job(job)

        retrieved = await memory_store.get_job("batch-lifecycle")
        assert retrieved.status == "processing"

        # Add partial results
        job.results.append({"debate_id": "d1", "status": "success"})
        job.processed_count = 1
        await memory_store.save_job(job)

        # Complete
        job.status = "completed"
        job.completed_at = time.time()
        job.results.append({"debate_id": "d2", "status": "success"})
        job.results.append({"debate_id": "d3", "status": "success"})
        job.processed_count = 3
        await memory_store.save_job(job)

        final = await memory_store.get_job("batch-lifecycle")
        assert final.status == "completed"
        assert final.processed_count == 3
        assert len(final.results) == 3

    @pytest.mark.asyncio
    async def test_job_lifecycle_sqlite(self, sqlite_store):
        """Test complete job lifecycle in SQLite store."""
        # Create and process job
        job = BatchJob(batch_id="batch-sql-lifecycle", debate_ids=["d1"])
        await sqlite_store.save_job(job)

        job.status = "processing"
        job.started_at = time.time()
        await sqlite_store.save_job(job)

        # Fail the job
        job.status = "failed"
        job.completed_at = time.time()
        job.error = "Test error message"
        await sqlite_store.save_job(job)

        final = await sqlite_store.get_job("batch-sql-lifecycle")
        assert final.status == "failed"
        assert final.error == "Test error message"

    @pytest.mark.asyncio
    async def test_batch_operations(self, sqlite_store):
        """Test batch operations across multiple jobs."""
        # Create multiple jobs
        for i in range(5):
            status = ["pending", "processing", "completed", "failed", "pending"][i]
            job = BatchJob(
                batch_id=f"batch-op-{i}",
                debate_ids=[f"d{i}"],
                status=status,
            )
            await sqlite_store.save_job(job)

        # Query by status
        pending = await sqlite_store.list_jobs(status="pending")
        assert len(pending) == 2

        # Delete some jobs
        await sqlite_store.delete_job("batch-op-0")
        await sqlite_store.delete_job("batch-op-1")

        # Verify remaining
        remaining = await sqlite_store.list_jobs()
        assert len(remaining) == 3
