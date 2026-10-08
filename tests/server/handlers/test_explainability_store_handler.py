"""
Tests for ExplainabilityStore - Batch job storage for explainability.

Tests cover:
- Route matching (can_handle) for ExplainabilityHandler
- RBAC permission tests
- BatchJob dataclass operations
- MemoryBatchJobStore operations
- DatabaseBatchJobStore operations
- Singleton management (get_batch_job_store, reset_batch_job_store)
- Input validation tests
- Happy path tests for batch endpoints
- Error handling tests
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.explainability_store import (
    BatchJob,
    BatchJobStore,
    DatabaseBatchJobStore,
    MemoryBatchJobStore,
    SQLiteBatchJobStore,
    get_batch_job_store,
    reset_batch_job_store,
)

# Explainability reads are org-scoped; requests act for the org that owns every debate.
pytestmark = pytest.mark.usefixtures("explainability_org_member")

TEST_ORG = "test-org-001"
# Batch jobs answer status and results only for the org that created them.
OWNED_BY_TEST_ORG = {"_owner_org_id": TEST_ORG}


# ===========================================================================
# Test Fixtures and Mocks
# ===========================================================================


@pytest.fixture(autouse=True)
def reset_store_singleton():
    """Reset batch job store singleton before and after each test."""
    reset_batch_job_store()
    yield
    reset_batch_job_store()


@pytest.fixture
def memory_store():
    """Create a fresh MemoryBatchJobStore for testing."""
    return MemoryBatchJobStore(max_jobs=10, ttl_seconds=3600)


@pytest.fixture
def sample_batch_job():
    """Create a sample BatchJob for testing."""
    return BatchJob(
        batch_id="batch-001",
        debate_ids=["debate-1", "debate-2", "debate-3"],
        status="pending",
        created_at=time.time(),
        started_at=None,
        completed_at=None,
        results=[],
        processed_count=0,
        options={"include_evidence": True},
        error=None,
    )


@pytest.fixture
def processing_batch_job():
    """Create a processing BatchJob for testing."""
    return BatchJob(
        batch_id="batch-002",
        debate_ids=["debate-a", "debate-b"],
        status="processing",
        created_at=time.time() - 60,
        started_at=time.time() - 30,
        completed_at=None,
        results=[{"debate_id": "debate-a", "status": "success"}],
        processed_count=1,
        options={},
        error=None,
    )


@pytest.fixture
def completed_batch_job():
    """Create a completed BatchJob for testing."""
    return BatchJob(
        batch_id="batch-003",
        debate_ids=["debate-x"],
        status="completed",
        created_at=time.time() - 120,
        started_at=time.time() - 100,
        completed_at=time.time() - 10,
        results=[{"debate_id": "debate-x", "status": "success", "explanation": {}}],
        processed_count=1,
        options={"format": "minimal"},
        error=None,
    )


@pytest.fixture
def sqlite_store(tmp_path):
    """Create a SQLiteBatchJobStore for testing."""
    db_path = tmp_path / "test_explainability.db"
    return SQLiteBatchJobStore(db_path, ttl_seconds=3600)


# ===========================================================================
# BatchJob Dataclass Tests
# ===========================================================================


class TestBatchJob:
    """Test BatchJob dataclass."""

    def test_create_batch_job_with_defaults(self):
        """Should create batch job with default values."""
        job = BatchJob(
            batch_id="batch-test",
            debate_ids=["d1", "d2"],
        )

        assert job.batch_id == "batch-test"
        assert job.debate_ids == ["d1", "d2"]
        assert job.status == "pending"
        assert job.started_at is None
        assert job.completed_at is None
        assert job.results == []
        assert job.processed_count == 0
        assert job.options == {}
        assert job.error is None

    def test_batch_job_to_dict(self, sample_batch_job):
        """Should convert batch job to dictionary correctly."""
        as_dict = sample_batch_job.to_dict()

        assert as_dict["batch_id"] == "batch-001"
        assert as_dict["debate_ids"] == ["debate-1", "debate-2", "debate-3"]
        assert as_dict["status"] == "pending"
        assert "created_at" in as_dict
        assert as_dict["started_at"] is None
        assert as_dict["completed_at"] is None
        assert as_dict["results"] == []
        assert as_dict["processed_count"] == 0
        assert as_dict["options"] == {"include_evidence": True}
        assert as_dict["error"] is None

    def test_batch_job_from_dict(self):
        """Should create batch job from dictionary."""
        data = {
            "batch_id": "batch-from-dict",
            "debate_ids": ["d1"],
            "status": "completed",
            "created_at": 1000.0,
            "started_at": 1001.0,
            "completed_at": 1005.0,
            "results": [{"debate_id": "d1", "status": "success"}],
            "processed_count": 1,
            "options": {"format": "full"},
            "error": None,
        }

        job = BatchJob.from_dict(data)

        assert job.batch_id == "batch-from-dict"
        assert job.status == "completed"
        assert job.created_at == 1000.0
        assert job.started_at == 1001.0
        assert job.completed_at == 1005.0
        assert len(job.results) == 1
        assert job.processed_count == 1

    def test_batch_job_with_error(self):
        """Should handle error field correctly."""
        job = BatchJob(
            batch_id="batch-error",
            debate_ids=["d1"],
            status="failed",
            error="Connection timeout",
        )

        assert job.status == "failed"
        assert job.error == "Connection timeout"

        as_dict = job.to_dict()
        assert as_dict["error"] == "Connection timeout"


# ===========================================================================
# MemoryBatchJobStore Tests
# ===========================================================================


class TestMemoryBatchJobStore:
    """Test MemoryBatchJobStore operations."""

    @pytest.mark.asyncio
    async def test_save_and_get_job(self, memory_store, sample_batch_job):
        """Should save and retrieve a job."""
        await memory_store.save_job(sample_batch_job)

        retrieved = await memory_store.get_job("batch-001")

        assert retrieved is not None
        assert retrieved.batch_id == "batch-001"
        assert retrieved.debate_ids == ["debate-1", "debate-2", "debate-3"]

    @pytest.mark.asyncio
    async def test_get_nonexistent_job(self, memory_store):
        """Should return None for nonexistent job."""
        result = await memory_store.get_job("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_job(self, memory_store, sample_batch_job):
        """Should delete a job."""
        await memory_store.save_job(sample_batch_job)

        result = await memory_store.delete_job("batch-001")

        assert result is True
        assert await memory_store.get_job("batch-001") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_job(self, memory_store):
        """Should return False when deleting nonexistent job."""
        result = await memory_store.delete_job("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_list_jobs_all(self, memory_store, sample_batch_job, processing_batch_job):
        """Should list all jobs."""
        await memory_store.save_job(sample_batch_job)
        await memory_store.save_job(processing_batch_job)

        jobs = await memory_store.list_jobs()

        assert len(jobs) == 2
        batch_ids = [j.batch_id for j in jobs]
        assert "batch-001" in batch_ids
        assert "batch-002" in batch_ids

    @pytest.mark.asyncio
    async def test_list_jobs_by_status(self, memory_store, sample_batch_job, processing_batch_job):
        """Should filter jobs by status."""
        await memory_store.save_job(sample_batch_job)
        await memory_store.save_job(processing_batch_job)

        pending_jobs = await memory_store.list_jobs(status="pending")
        processing_jobs = await memory_store.list_jobs(status="processing")

        assert len(pending_jobs) == 1
        assert pending_jobs[0].batch_id == "batch-001"

        assert len(processing_jobs) == 1
        assert processing_jobs[0].batch_id == "batch-002"

    @pytest.mark.asyncio
    async def test_list_jobs_with_limit(self, memory_store):
        """Should respect limit parameter."""
        for i in range(5):
            job = BatchJob(batch_id=f"batch-{i}", debate_ids=["d1"])
            await memory_store.save_job(job)

        jobs = await memory_store.list_jobs(limit=3)

        assert len(jobs) == 3

    @pytest.mark.asyncio
    async def test_lru_eviction(self):
        """Should evict oldest jobs when at capacity."""
        store = MemoryBatchJobStore(max_jobs=3, ttl_seconds=3600)

        for i in range(5):
            job = BatchJob(batch_id=f"batch-{i}", debate_ids=["d1"])
            await store.save_job(job)

        # Should have evicted oldest jobs
        assert await store.get_job("batch-0") is None
        assert await store.get_job("batch-1") is None
        assert await store.get_job("batch-4") is not None

    @pytest.mark.asyncio
    async def test_ttl_expiration(self):
        """Should expire jobs after TTL."""
        store = MemoryBatchJobStore(max_jobs=10, ttl_seconds=1)

        job = BatchJob(
            batch_id="batch-expire",
            debate_ids=["d1"],
            created_at=time.time() - 10,  # Created 10 seconds ago
        )
        store._jobs["batch-expire"] = job

        # Should return None due to TTL
        result = await store.get_job("batch-expire")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_existing_job(self, memory_store, sample_batch_job):
        """Should update an existing job."""
        await memory_store.save_job(sample_batch_job)

        # Update the job
        sample_batch_job.status = "processing"
        sample_batch_job.started_at = time.time()
        await memory_store.save_job(sample_batch_job)

        retrieved = await memory_store.get_job("batch-001")
        assert retrieved.status == "processing"
        assert retrieved.started_at is not None


# ===========================================================================
# DatabaseBatchJobStore Tests (SQLite)
# ===========================================================================


class TestSQLiteBatchJobStore:
    """Test SQLiteBatchJobStore operations."""

    @pytest.mark.asyncio
    async def test_save_and_get_job(self, sqlite_store, sample_batch_job):
        """Should save and retrieve a job from SQLite."""
        await sqlite_store.save_job(sample_batch_job)

        retrieved = await sqlite_store.get_job("batch-001")

        assert retrieved is not None
        assert retrieved.batch_id == "batch-001"
        assert retrieved.debate_ids == ["debate-1", "debate-2", "debate-3"]
        assert retrieved.options == {"include_evidence": True}

    @pytest.mark.asyncio
    async def test_get_nonexistent_job(self, sqlite_store):
        """Should return None for nonexistent job."""
        result = await sqlite_store.get_job("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_job(self, sqlite_store, sample_batch_job):
        """Should delete a job from SQLite."""
        await sqlite_store.save_job(sample_batch_job)

        result = await sqlite_store.delete_job("batch-001")

        assert result is True
        assert await sqlite_store.get_job("batch-001") is None

    @pytest.mark.asyncio
    async def test_list_jobs_all(self, sqlite_store, sample_batch_job, processing_batch_job):
        """Should list all jobs from SQLite."""
        await sqlite_store.save_job(sample_batch_job)
        await sqlite_store.save_job(processing_batch_job)

        jobs = await sqlite_store.list_jobs()

        assert len(jobs) == 2

    @pytest.mark.asyncio
    async def test_list_jobs_by_status(self, sqlite_store, sample_batch_job, processing_batch_job):
        """Should filter jobs by status in SQLite."""
        await sqlite_store.save_job(sample_batch_job)
        await sqlite_store.save_job(processing_batch_job)

        pending_jobs = await sqlite_store.list_jobs(status="pending")

        assert len(pending_jobs) == 1
        assert pending_jobs[0].batch_id == "batch-001"

    @pytest.mark.asyncio
    async def test_list_jobs_with_limit(self, sqlite_store):
        """Should respect limit parameter in SQLite."""
        for i in range(5):
            job = BatchJob(batch_id=f"batch-{i}", debate_ids=["d1"])
            await sqlite_store.save_job(job)

        jobs = await sqlite_store.list_jobs(limit=3)

        assert len(jobs) == 3

    @pytest.mark.asyncio
    async def test_upsert_job(self, sqlite_store, sample_batch_job):
        """Should update existing job on conflict."""
        await sqlite_store.save_job(sample_batch_job)

        # Update the job
        sample_batch_job.status = "completed"
        sample_batch_job.completed_at = time.time()
        sample_batch_job.processed_count = 3
        await sqlite_store.save_job(sample_batch_job)

        retrieved = await sqlite_store.get_job("batch-001")
        assert retrieved.status == "completed"
        assert retrieved.processed_count == 3

    @pytest.mark.asyncio
    async def test_ttl_expiration_on_get(self, tmp_path):
        """Should expire jobs after TTL on retrieval."""
        db_path = tmp_path / "test_ttl.db"
        store = SQLiteBatchJobStore(db_path, ttl_seconds=1)

        # Create a job that was created long ago
        job = BatchJob(
            batch_id="batch-old",
            debate_ids=["d1"],
            created_at=time.time() - 100,  # Created 100 seconds ago
        )
        await store.save_job(job)

        # Should return None due to TTL
        result = await store.get_job("batch-old")
        assert result is None

    @pytest.mark.asyncio
    async def test_complex_results_serialization(self, sqlite_store):
        """Should correctly serialize and deserialize complex results."""
        job = BatchJob(
            batch_id="batch-complex",
            debate_ids=["d1", "d2"],
            results=[
                {
                    "debate_id": "d1",
                    "status": "success",
                    "explanation": {
                        "factors": ["factor1", "factor2"],
                        "confidence": 0.95,
                        "nested": {"key": "value"},
                    },
                },
                {
                    "debate_id": "d2",
                    "status": "error",
                    "error": "Not found",
                },
            ],
            options={"include_evidence": True, "format": "full"},
        )

        await sqlite_store.save_job(job)
        retrieved = await sqlite_store.get_job("batch-complex")

        assert len(retrieved.results) == 2
        assert retrieved.results[0]["explanation"]["confidence"] == 0.95
        assert retrieved.options["include_evidence"] is True


# ===========================================================================
# Singleton Management Tests
# ===========================================================================


class TestSingletonManagement:
    """Test get_batch_job_store and reset_batch_job_store."""

    def test_reset_batch_job_store(self):
        """Should reset the singleton store."""
        # Get initial store
        with patch.dict(os.environ, {"ARAGORA_EXPLAINABILITY_STORE_BACKEND": "memory"}):
            with patch("aragora.storage.production_guards.require_distributed_store"):
                store1 = get_batch_job_store()

        reset_batch_job_store()

        # Get new store after reset
        with patch.dict(os.environ, {"ARAGORA_EXPLAINABILITY_STORE_BACKEND": "memory"}):
            with patch("aragora.storage.production_guards.require_distributed_store"):
                store2 = get_batch_job_store()

        # Should be different instances after reset
        assert store1 is not store2

    def test_get_store_returns_same_instance(self):
        """Should return same instance on subsequent calls."""
        with patch.dict(os.environ, {"ARAGORA_EXPLAINABILITY_STORE_BACKEND": "memory"}):
            with patch("aragora.storage.production_guards.require_distributed_store"):
                store1 = get_batch_job_store()
                store2 = get_batch_job_store()

        assert store1 is store2

    def test_explicit_memory_backend(self):
        """Should use memory backend when explicitly configured."""
        with patch.dict(os.environ, {"ARAGORA_EXPLAINABILITY_STORE_BACKEND": "memory"}):
            with patch("aragora.storage.production_guards.require_distributed_store"):
                store = get_batch_job_store()

        assert isinstance(store, MemoryBatchJobStore)

    def test_explicit_sqlite_backend(self, tmp_path):
        """Should use SQLite backend when explicitly configured."""
        db_path = str(tmp_path / "test.db")
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


# ===========================================================================
# ExplainabilityHandler Route Tests
# ===========================================================================


class TestExplainabilityHandlerRouting:
    """Test ExplainabilityHandler can_handle routing."""

    @pytest.fixture
    def handler(self, mock_server_context):
        """Create handler with mocked dependencies."""
        from aragora.server.handlers.explainability import ExplainabilityHandler

        return ExplainabilityHandler(mock_server_context)

    def test_can_handle_batch_create(self, handler):
        """Should handle POST to batch endpoint."""
        assert handler.can_handle("/api/v1/explainability/batch", "POST")
        assert not handler.can_handle("/api/v1/explainability/batch", "GET")

    def test_can_handle_batch_status(self, handler):
        """Should handle GET to batch status endpoint."""
        assert handler.can_handle("/api/v1/explainability/batch/batch-123/status", "GET")
        assert not handler.can_handle("/api/v1/explainability/batch/batch-123/status", "POST")

    def test_can_handle_batch_results(self, handler):
        """Should handle GET to batch results endpoint."""
        assert handler.can_handle("/api/v1/explainability/batch/batch-123/results", "GET")

    def test_can_handle_compare(self, handler):
        """Should handle POST to compare endpoint."""
        assert handler.can_handle("/api/v1/explainability/compare", "POST")
        assert not handler.can_handle("/api/v1/explainability/compare", "GET")

    def test_can_handle_debate_explanation(self, handler):
        """Should handle GET for debate explanation."""
        assert handler.can_handle("/api/v1/debates/debate-123/explanation", "GET")
        assert not handler.can_handle("/api/v1/debates/debate-123/explanation", "POST")

    def test_can_handle_debate_evidence(self, handler):
        """Should handle GET for debate evidence."""
        assert handler.can_handle("/api/v1/debates/debate-123/evidence", "GET")

    def test_can_handle_debate_vote_pivots(self, handler):
        """Should handle GET for vote pivots."""
        assert handler.can_handle("/api/v1/debates/debate-123/votes/pivots", "GET")

    def test_can_handle_debate_counterfactuals(self, handler):
        """Should handle GET for counterfactuals."""
        assert handler.can_handle("/api/v1/debates/debate-123/counterfactuals", "GET")

    def test_can_handle_debate_summary(self, handler):
        """Summary is owned by DebatesHandler, not ExplainabilityHandler."""
        assert not handler.can_handle("/api/v1/debates/debate-123/summary", "GET")

    def test_can_handle_explain_shortcut(self, handler):
        """Should handle explain shortcut."""
        assert handler.can_handle("/api/v1/explain/debate-123", "GET")

    def test_cannot_handle_other_paths(self, handler):
        """Should reject non-explainability paths."""
        assert not handler.can_handle("/api/v1/debates", "GET")
        assert not handler.can_handle("/api/v1/backups", "GET")
        assert not handler.can_handle("/api/v2/explainability/batch", "POST")


# ===========================================================================
# RBAC Permission Tests
# ===========================================================================


class TestExplainabilityHandlerRBAC:
    """Test RBAC permission enforcement."""

    @pytest.fixture
    def handler(self, mock_server_context):
        """Create handler with mocked dependencies."""
        from aragora.server.handlers.explainability import ExplainabilityHandler

        return ExplainabilityHandler(mock_server_context)

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_batch_create_requires_permission(self, mock_server_context, mock_http_handler):
        """Test that batch create requires explainability:read permission."""
        from aragora.server.handlers.explainability import ExplainabilityHandler
        from aragora.rbac.decorators import PermissionDeniedError
        from aragora.server.auth import auth_config

        orig_enabled = auth_config.enabled
        os.environ["ARAGORA_TEST_REAL_AUTH"] = "1"
        auth_config.enabled = True
        try:
            h = ExplainabilityHandler(mock_server_context)
            http = mock_http_handler(
                method="POST",
                body={"debate_ids": ["d1", "d2"]},
            )

            # Without proper auth context, should raise PermissionDeniedError
            with pytest.raises(PermissionDeniedError):
                await h.handle("/api/v1/explainability/batch", {}, http)
        finally:
            auth_config.enabled = orig_enabled
            del os.environ["ARAGORA_TEST_REAL_AUTH"]

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_explanation_requires_permission(self, mock_server_context, mock_http_handler):
        """Test that explanation endpoint requires explainability:read permission."""
        from aragora.server.handlers.explainability import ExplainabilityHandler
        from aragora.rbac.decorators import PermissionDeniedError
        from aragora.server.auth import auth_config

        orig_enabled = auth_config.enabled
        os.environ["ARAGORA_TEST_REAL_AUTH"] = "1"
        auth_config.enabled = True
        try:
            h = ExplainabilityHandler(mock_server_context)
            http = mock_http_handler(method="GET")

            # Without proper auth context, should raise PermissionDeniedError
            with pytest.raises(PermissionDeniedError):
                await h.handle("/api/v1/debates/debate-123/explanation", {}, http)
        finally:
            auth_config.enabled = orig_enabled
            del os.environ["ARAGORA_TEST_REAL_AUTH"]


# ===========================================================================
# Input Validation Tests
# ===========================================================================


class TestExplainabilityHandlerValidation:
    """Test input validation for explainability endpoints."""

    @pytest.fixture
    def handler(self, mock_server_context):
        """Create handler with mocked dependencies."""
        from aragora.server.handlers.explainability import ExplainabilityHandler

        return ExplainabilityHandler(mock_server_context)

    @pytest.mark.asyncio
    async def test_batch_create_missing_debate_ids(self, handler, mock_http_handler):
        """Test batch create without debate_ids returns 400."""
        http = mock_http_handler(method="POST", body={})

        result = handler._handle_batch_create(http)

        assert result.status_code == 400
        body = json.loads(result.body)
        assert "debate_ids" in body.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_batch_create_empty_debate_ids(self, handler, mock_http_handler):
        """Test batch create with empty debate_ids returns 400."""
        http = mock_http_handler(method="POST", body={"debate_ids": []})

        result = handler._handle_batch_create(http)

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_batch_create_exceeds_max_size(self, handler, mock_http_handler):
        """Test batch create exceeding max size returns 400."""
        # MAX_BATCH_SIZE is 100
        debate_ids = [f"debate-{i}" for i in range(150)]
        http = mock_http_handler(method="POST", body={"debate_ids": debate_ids})

        result = handler._handle_batch_create(http)

        assert result.status_code == 400
        body = json.loads(result.body)
        assert "maximum" in body.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_batch_create_invalid_json(self, handler, mock_http_handler):
        """Test batch create with invalid JSON returns 400."""
        http = mock_http_handler(method="POST")
        http.rfile.read.return_value = b"not valid json"

        result = handler._handle_batch_create(http)

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_batch_create_no_body(self, handler, mock_http_handler):
        """Test batch create with no body returns 400."""
        http = mock_http_handler(method="POST")
        http.headers = {"Content-Length": "0"}

        result = handler._handle_batch_create(http)

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_compare_requires_two_debates(self, handler, mock_http_handler):
        """Test compare endpoint requires at least 2 debates."""
        http = mock_http_handler(method="POST", body={"debate_ids": ["d1"]})

        result = await handler._handle_compare(http)

        assert result.status_code == 400
        body = json.loads(result.body)
        assert "at least 2" in body.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_compare_max_ten_debates(self, handler, mock_http_handler):
        """Test compare endpoint limits to 10 debates."""
        debate_ids = [f"debate-{i}" for i in range(15)]
        http = mock_http_handler(method="POST", body={"debate_ids": debate_ids})

        result = await handler._handle_compare(http)

        assert result.status_code == 400
        body = json.loads(result.body)
        assert "10" in body.get("error", "")


# ===========================================================================
# Happy Path Tests
# ===========================================================================


class TestExplainabilityHandlerHappyPath:
    """Test happy path scenarios for explainability endpoints."""

    @pytest.fixture
    def handler(self, mock_server_context):
        """Create handler with mocked dependencies."""
        from aragora.server.handlers.explainability import ExplainabilityHandler

        h = ExplainabilityHandler(mock_server_context)
        return h

    @pytest.mark.asyncio
    async def test_batch_create_success(self, handler, mock_http_handler):
        """Test successful batch job creation."""
        with patch.object(handler, "_start_batch_processing"):
            with patch("aragora.server.handlers.explainability._save_batch_job"):
                http = mock_http_handler(
                    method="POST",
                    body={
                        "debate_ids": ["debate-1", "debate-2"],
                        "options": {"include_evidence": True},
                    },
                )

                result = handler._handle_batch_create(http)

                assert result.status_code == 202
                body = json.loads(result.body)
                assert "batch_id" in body
                assert body["status"] == "pending"
                assert body["total_debates"] == 2
                assert "status_url" in body
                assert "results_url" in body

    @pytest.mark.asyncio
    async def test_batch_status_success(self, handler):
        """Test getting batch job status."""
        job = BatchJob(
            batch_id="batch-test-status",
            options=OWNED_BY_TEST_ORG,
            debate_ids=["d1", "d2"],
            status="processing",
            processed_count=1,
        )

        with patch("aragora.server.handlers.explainability._get_batch_job", return_value=job):
            result = handler._handle_batch_status("batch-test-status", TEST_ORG)

        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["batch_id"] == "batch-test-status"
        assert body["status"] == "processing"

    @pytest.mark.asyncio
    async def test_batch_results_success(self, handler):
        """Test getting batch job results."""
        from aragora.server.handlers.explainability import BatchStatus, BatchDebateResult

        job = BatchJob(
            batch_id="batch-test-results",
            options=OWNED_BY_TEST_ORG,
            debate_ids=["d1"],
            status="completed",
        )
        # Set status as BatchStatus enum for the handler
        job.status = BatchStatus.COMPLETED
        job.results = [
            BatchDebateResult(
                debate_id="d1",
                status="success",
                explanation={"confidence": 0.95},
            ),
        ]

        with patch("aragora.server.handlers.explainability._get_batch_job", return_value=job):
            result = handler._handle_batch_results("batch-test-results", {}, TEST_ORG)

        assert result.status_code == 200
        body = json.loads(result.body)
        assert "results" in body
        assert "pagination" in body


# ===========================================================================
# Error Handling Tests
# ===========================================================================


class TestExplainabilityHandlerErrors:
    """Test error handling in explainability endpoints."""

    @pytest.fixture
    def handler(self, mock_server_context):
        """Create handler with mocked dependencies."""
        from aragora.server.handlers.explainability import ExplainabilityHandler

        return ExplainabilityHandler(mock_server_context)

    @pytest.mark.asyncio
    async def test_batch_status_not_found(self, handler):
        """Test batch status returns 404 for nonexistent job."""
        with patch("aragora.server.handlers.explainability._get_batch_job", return_value=None):
            result = handler._handle_batch_status("nonexistent", TEST_ORG)

        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_batch_results_not_found(self, handler):
        """Test batch results returns 404 for nonexistent job."""
        with patch("aragora.server.handlers.explainability._get_batch_job", return_value=None):
            result = handler._handle_batch_results("nonexistent", {}, TEST_ORG)

        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_batch_results_pending_returns_202(self, handler):
        """Test batch results returns 202 when job is pending."""
        from aragora.server.handlers.explainability import BatchStatus

        job = BatchJob(
            batch_id="batch-pending",
            options=OWNED_BY_TEST_ORG,
            debate_ids=["d1"],
        )
        job.status = BatchStatus.PENDING

        with patch("aragora.server.handlers.explainability._get_batch_job", return_value=job):
            result = handler._handle_batch_results("batch-pending", {}, TEST_ORG)

        assert result.status_code == 202

    @pytest.mark.asyncio
    async def test_explanation_not_found(self, handler):
        """Test explanation returns 404 for nonexistent debate."""
        with patch.object(handler, "_get_or_build_decision", return_value=None):
            result = await handler._handle_full_explanation("nonexistent", {}, False)

        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_evidence_not_found(self, handler):
        """Test evidence returns 404 for nonexistent debate."""
        with patch.object(handler, "_get_or_build_decision", return_value=None):
            result = await handler._handle_evidence("nonexistent", {}, False)

        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_vote_pivots_not_found(self, handler):
        """Test vote pivots returns 404 for nonexistent debate."""
        with patch.object(handler, "_get_or_build_decision", return_value=None):
            result = await handler._handle_vote_pivots("nonexistent", {}, False)

        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_counterfactuals_not_found(self, handler):
        """Test counterfactuals returns 404 for nonexistent debate."""
        with patch.object(handler, "_get_or_build_decision", return_value=None):
            result = await handler._handle_counterfactuals("nonexistent", {}, False)

        assert result.status_code == 404

    def test_summary_helper_not_defined(self, handler):
        """Summary route helpers live on DebatesHandler."""
        assert not hasattr(handler, "_handle_summary")


# ===========================================================================
# Batch Processing Tests
# ===========================================================================


class TestBatchProcessing:
    """Test batch processing logic."""

    @pytest.fixture
    def handler(self, mock_server_context):
        """Create handler with mocked dependencies."""
        from aragora.server.handlers.explainability import ExplainabilityHandler

        return ExplainabilityHandler(mock_server_context)

    def test_build_explanation_dict_minimal(self, handler):
        """Test building minimal explanation dict."""
        mock_decision = MagicMock()
        mock_decision.debate_id = "test-debate"
        mock_decision.confidence = 0.85
        mock_decision.consensus_reached = True
        mock_decision.contributing_factors = [
            MagicMock(name="factor1", contribution=0.4),
            MagicMock(name="factor2", contribution=0.3),
        ]

        result = handler._build_explanation_dict(
            mock_decision,
            format_type="minimal",
        )

        assert result["confidence"] == 0.85
        assert result["consensus_reached"] is True
        assert "primary_factors" in result

    def test_build_explanation_dict_full(self, handler):
        """Test building full explanation dict."""
        mock_decision = MagicMock()
        mock_decision.to_dict.return_value = {
            "debate_id": "test-debate",
            "confidence": 0.85,
            "evidence_chain": [{"id": "e1"}],
            "counterfactuals": [{"id": "c1"}],
            "vote_pivots": [{"id": "v1"}],
        }

        result = handler._build_explanation_dict(
            mock_decision,
            include_evidence=True,
            include_counterfactuals=True,
            include_vote_pivots=True,
            format_type="full",
        )

        assert "evidence_chain" in result
        assert "counterfactuals" in result
        assert "vote_pivots" in result

    def test_build_explanation_dict_exclude_evidence(self, handler):
        """Test excluding evidence from explanation dict."""
        mock_decision = MagicMock()
        mock_decision.to_dict.return_value = {
            "debate_id": "test-debate",
            "confidence": 0.85,
            "evidence_chain": [{"id": "e1"}],
        }

        result = handler._build_explanation_dict(
            mock_decision,
            include_evidence=False,
            format_type="full",
        )

        assert "evidence_chain" not in result


# ===========================================================================
# Handler Version and Legacy Tests
# ===========================================================================


class TestExplainabilityHandlerVersioning:
    """Test API versioning and legacy route handling."""

    @pytest.fixture
    def handler(self, mock_server_context):
        """Create handler with mocked dependencies."""
        from aragora.server.handlers.explainability import ExplainabilityHandler

        return ExplainabilityHandler(mock_server_context)

    def test_is_legacy_route_detection(self, handler):
        """Should correctly identify legacy vs versioned routes."""
        assert handler._is_legacy_route("/api/debates/123/explanation") is True
        assert handler._is_legacy_route("/api/v1/debates/123/explanation") is False

    def test_add_headers_versioned(self, handler):
        """Should add version header to responses."""
        from aragora.server.handlers.base import HandlerResult

        result = HandlerResult(
            status_code=200,
            body=b"{}",
            content_type="application/json",
        )

        result = handler._add_headers(result, is_legacy=False)

        assert result.headers["X-API-Version"] == "v1"
        assert "Deprecation" not in result.headers

    def test_add_headers_legacy(self, handler):
        """Should add deprecation headers to legacy responses."""
        from aragora.server.handlers.base import HandlerResult

        result = HandlerResult(
            status_code=200,
            body=b"{}",
            content_type="application/json",
        )

        result = handler._add_headers(result, is_legacy=True)

        assert result.headers["Deprecation"] == "true"
        assert "Sunset" in result.headers
