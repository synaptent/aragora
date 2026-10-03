"""
Tests for batch explainability endpoints in ExplainabilityHandler.

Tests cover:
- POST /api/v1/explainability/batch - Create batch explanation job
- GET  /api/v1/explainability/batch/:id/status - Get batch job status
- GET  /api/v1/explainability/batch/:id/results - Get batch job results
- POST /api/v1/explainability/compare - Compare explanations across debates
"""

import asyncio
import json
import pytest
import threading
import time
import uuid
from unittest.mock import Mock, patch, AsyncMock

from aragora.server.handlers.explainability import (
    ExplainabilityHandler,
    BatchStatus,
    BatchJob,
    BatchDebateResult,
    _get_batch_job,
    _save_batch_job,
)
from aragora.server.handlers.explainability_store import (
    MemoryBatchJobStore,
    get_batch_job_store,
)
from aragora.server.handlers.base import HandlerResult


def run_async(coro):
    """Run an async coroutine synchronously."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


def parse_handler_result(result: HandlerResult) -> tuple[dict, int]:
    """Helper to parse HandlerResult into (body_dict, status_code)."""
    body_str = result.body.decode("utf-8") if isinstance(result.body, bytes) else result.body
    try:
        body_dict = json.loads(body_str)
    except (json.JSONDecodeError, TypeError):
        body_dict = {"raw": body_str}
    return body_dict, result.status_code


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def _reset_batch_store():
    """Reset batch store singleton between tests to prevent cross-test pollution."""
    from aragora.server.handlers.explainability_store import reset_batch_job_store

    reset_batch_job_store()
    yield
    reset_batch_job_store()


@pytest.fixture
def handler():
    """Create a fresh handler instance for each test."""
    return ExplainabilityHandler(server_context={})


@pytest.fixture
def mock_post_request():
    """Create a mock POST request handler."""
    request = Mock()
    request.headers = {"Content-Type": "application/json", "Content-Length": "100"}
    request.command = "POST"
    request.client_address = ("127.0.0.1", 12345)
    return request


@pytest.fixture
def mock_get_request():
    """Create a mock GET request handler."""
    request = Mock()
    request.headers = {"Content-Type": "application/json"}
    request.command = "GET"
    request.client_address = ("127.0.0.1", 12345)
    return request


@pytest.fixture(autouse=True)
def clear_batch_jobs():
    """Clear batch jobs before each test by resetting the store singleton."""
    import aragora.server.handlers.explainability_store as store_module

    # Reset the singleton to use a fresh memory store for each test
    store_module._batch_store = MemoryBatchJobStore()
    yield
    store_module._batch_store = None


@pytest.fixture(autouse=True)
def batch_workers(monkeypatch, _reset_batch_store, clear_batch_jobs):
    """Track batch worker threads and join them before the store is reset.

    Depending on the store fixtures makes this teardown run first, so a worker
    can never save into the next test's store or lazily recreate the default
    SQLite store in the shared data directory.
    """
    workers: list[threading.Thread] = []
    start = ExplainabilityHandler._start_batch_processing

    # Record threads at construction: a fast worker may already have exited by
    # the time start() returns, so diffing threading.enumerate() can miss it.
    # Only threads built by the calling thread count, so helper threads that
    # the worker itself creates while the patch is active are not recorded.
    def tracked_start(self, job):
        caller = threading.current_thread()

        class RecordingThread(threading.Thread):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                if threading.current_thread() is caller:
                    workers.append(self)

        with monkeypatch.context() as patch_threads:
            patch_threads.setattr(threading, "Thread", RecordingThread)
            start(self, job)

    monkeypatch.setattr(ExplainabilityHandler, "_start_batch_processing", tracked_start)
    # Keep workers off the process-global debates database in the shared data dir.
    monkeypatch.setattr("aragora.server.storage.get_debates_db", lambda: None)
    yield workers
    for worker in workers:
        worker.join(timeout=10)
    leaked = [worker.name for worker in workers if worker.is_alive()]
    assert not leaked, f"batch workers outlived their test: {leaked}"


# ============================================================================
# Test BatchStatus Enum
# ============================================================================


class TestBatchStatus:
    """Test BatchStatus enum."""

    def test_status_values(self):
        assert BatchStatus.PENDING.value == "pending"
        assert BatchStatus.PROCESSING.value == "processing"
        assert BatchStatus.COMPLETED.value == "completed"
        assert BatchStatus.PARTIAL.value == "partial"
        assert BatchStatus.FAILED.value == "failed"


# ============================================================================
# Test BatchDebateResult
# ============================================================================


class TestBatchDebateResult:
    """Test BatchDebateResult dataclass."""

    def test_to_dict_success(self):
        result = BatchDebateResult(
            debate_id="debate-123",
            status="success",
            explanation={"confidence": 0.85},
            processing_time_ms=125.5,
        )
        data = result.to_dict()

        assert data["debate_id"] == "debate-123"
        assert data["status"] == "success"
        assert data["explanation"] == {"confidence": 0.85}
        assert data["processing_time_ms"] == 125.5
        assert "error" not in data

    def test_to_dict_error(self):
        result = BatchDebateResult(
            debate_id="debate-456",
            status="error",
            error="Debate not found",
            processing_time_ms=10.2,
        )
        data = result.to_dict()

        assert data["debate_id"] == "debate-456"
        assert data["status"] == "error"
        assert data["error"] == "Debate not found"
        assert "explanation" not in data


# ============================================================================
# Test BatchJob
# ============================================================================


class TestBatchJob:
    """Test BatchJob dataclass."""

    def test_to_dict(self):
        job = BatchJob(
            batch_id="batch-123",
            debate_ids=["d1", "d2", "d3"],
            status=BatchStatus.PROCESSING,
            processed_count=1,
            results=[BatchDebateResult(debate_id="d1", status="success", processing_time_ms=100)],
        )
        data = job.to_dict()

        assert data["batch_id"] == "batch-123"
        assert data["status"] == "processing"
        assert data["total_debates"] == 3
        assert data["processed_count"] == 1
        assert data["success_count"] == 1
        assert data["error_count"] == 0
        assert data["progress_pct"] == 33.3

    def test_progress_calculation(self):
        job = BatchJob(
            batch_id="batch-456",
            debate_ids=["d1", "d2", "d3", "d4"],
            processed_count=2,
        )
        data = job.to_dict()
        assert data["progress_pct"] == 50.0

    def test_empty_debates_progress(self):
        job = BatchJob(
            batch_id="batch-789",
            debate_ids=[],
            processed_count=0,
        )
        data = job.to_dict()
        assert data["progress_pct"] == 0


# ============================================================================
# Test can_handle
# ============================================================================


class TestCanHandle:
    """Test can_handle for batch endpoints."""

    def test_batch_create_post(self, handler):
        assert handler.can_handle("/api/v1/explainability/batch", "POST") is True

    def test_batch_create_get_rejected(self, handler):
        assert handler.can_handle("/api/v1/explainability/batch", "GET") is False

    def test_batch_status_get(self, handler):
        assert handler.can_handle("/api/v1/explainability/batch/batch-123/status", "GET") is True

    def test_batch_results_get(self, handler):
        assert handler.can_handle("/api/v1/explainability/batch/batch-123/results", "GET") is True

    def test_compare_post(self, handler):
        assert handler.can_handle("/api/v1/explainability/compare", "POST") is True

    def test_compare_get_rejected(self, handler):
        assert handler.can_handle("/api/v1/explainability/compare", "GET") is False


# ============================================================================
# Test Create Batch Job
# ============================================================================


class TestCreateBatchJob:
    """Test POST /api/v1/explainability/batch endpoint."""

    def test_create_batch_valid(self, handler, mock_post_request):
        body = {
            "debate_ids": ["debate-1", "debate-2", "debate-3"],
            "options": {
                "include_evidence": True,
                "format": "summary",
            },
        }
        mock_post_request.rfile = Mock()
        mock_post_request.rfile.read = Mock(return_value=json.dumps(body).encode())
        mock_post_request.headers["Content-Length"] = len(json.dumps(body))

        result = handler._handle_batch_create(mock_post_request)
        response_body, status = parse_handler_result(result)

        assert status == 202
        assert "batch_id" in response_body
        assert response_body["status"] == "pending"
        assert response_body["total_debates"] == 3
        assert "status_url" in response_body
        assert "results_url" in response_body

    def test_create_batch_snapshots_pending_before_worker_starts(
        self, handler, mock_post_request, monkeypatch
    ):
        body = {"debate_ids": ["debate-1"]}
        mock_post_request.rfile = Mock()
        mock_post_request.rfile.read = Mock(return_value=json.dumps(body).encode())
        mock_post_request.headers["Content-Length"] = len(json.dumps(body))
        worker_observation = {}

        def fail_immediately(job):
            worker_observation["initial_status"] = job.status
            job.status = BatchStatus.FAILED

        monkeypatch.setattr(handler, "_start_batch_processing", fail_immediately)

        result = handler._handle_batch_create(mock_post_request)
        response_body, status = parse_handler_result(result)

        assert worker_observation["initial_status"] is BatchStatus.PENDING
        assert status == 202
        assert response_body["status"] == "pending"

    def test_create_batch_worker_finishes_within_the_test(
        self, handler, mock_post_request, batch_workers
    ):
        debate_id = f"missing-{uuid.uuid4().hex}"
        body = {"debate_ids": [debate_id]}
        mock_post_request.rfile = Mock()
        mock_post_request.rfile.read = Mock(return_value=json.dumps(body).encode())
        mock_post_request.headers["Content-Length"] = len(json.dumps(body))

        result = handler._handle_batch_create(mock_post_request)
        response_body, status = parse_handler_result(result)

        assert status == 202
        assert len(batch_workers) == 1
        batch_workers[0].join(timeout=10)
        assert not batch_workers[0].is_alive()
        job = _get_batch_job(response_body["batch_id"])
        assert job is not None
        assert job.status is BatchStatus.FAILED
        assert [(r.debate_id, r.status) for r in job.results] == [(debate_id, "not_found")]

    def test_create_batch_empty_debate_ids(self, handler, mock_post_request):
        body = {"debate_ids": []}
        mock_post_request.rfile = Mock()
        mock_post_request.rfile.read = Mock(return_value=json.dumps(body).encode())
        mock_post_request.headers["Content-Length"] = len(json.dumps(body))

        result = handler._handle_batch_create(mock_post_request)
        response_body, status = parse_handler_result(result)

        assert status == 400
        assert "error" in response_body

    def test_create_batch_missing_debate_ids(self, handler, mock_post_request):
        body = {"options": {"format": "full"}}
        mock_post_request.rfile = Mock()
        mock_post_request.rfile.read = Mock(return_value=json.dumps(body).encode())
        mock_post_request.headers["Content-Length"] = len(json.dumps(body))

        result = handler._handle_batch_create(mock_post_request)
        response_body, status = parse_handler_result(result)

        assert status == 400
        assert "error" in response_body

    def test_create_batch_invalid_json(self, handler, mock_post_request):
        mock_post_request.rfile = Mock()
        mock_post_request.rfile.read = Mock(return_value=b"not valid json")
        mock_post_request.headers["Content-Length"] = 14

        result = handler._handle_batch_create(mock_post_request)
        response_body, status = parse_handler_result(result)

        assert status == 400
        assert "error" in response_body


# ============================================================================
# Test Get Batch Status
# ============================================================================


class TestGetBatchStatus:
    """Test GET /api/v1/explainability/batch/:id/status endpoint."""

    def test_get_status_pending(self, handler, mock_get_request):
        # Create a job directly
        job = BatchJob(
            batch_id="batch-test-123",
            debate_ids=["d1", "d2"],
            status=BatchStatus.PENDING,
        )
        _save_batch_job(job)

        result = handler._handle_batch_status("batch-test-123")
        response_body, status = parse_handler_result(result)

        assert status == 200
        assert response_body["batch_id"] == "batch-test-123"
        assert response_body["status"] == "pending"
        assert response_body["total_debates"] == 2

    def test_get_status_processing(self, handler, mock_get_request):
        job = BatchJob(
            batch_id="batch-test-456",
            debate_ids=["d1", "d2", "d3"],
            status=BatchStatus.PROCESSING,
            processed_count=1,
            started_at=time.time(),
        )
        _save_batch_job(job)

        result = handler._handle_batch_status("batch-test-456")
        response_body, status = parse_handler_result(result)

        assert status == 200
        assert response_body["status"] == "processing"
        assert response_body["processed_count"] == 1
        assert response_body["progress_pct"] == 33.3

    def test_get_status_not_found(self, handler, mock_get_request):
        result = handler._handle_batch_status("nonexistent")
        response_body, status = parse_handler_result(result)

        assert status == 404
        assert "error" in response_body


# ============================================================================
# Test Get Batch Results
# ============================================================================


class TestGetBatchResults:
    """Test GET /api/v1/explainability/batch/:id/results endpoint."""

    def test_get_results_completed(self, handler, mock_get_request):
        job = BatchJob(
            batch_id="batch-results-123",
            debate_ids=["d1", "d2"],
            status=BatchStatus.COMPLETED,
            processed_count=2,
            completed_at=time.time(),
            results=[
                BatchDebateResult(
                    debate_id="d1",
                    status="success",
                    explanation={"confidence": 0.9},
                    processing_time_ms=100,
                ),
                BatchDebateResult(
                    debate_id="d2",
                    status="success",
                    explanation={"confidence": 0.8},
                    processing_time_ms=150,
                ),
            ],
        )
        _save_batch_job(job)

        result = handler._handle_batch_results("batch-results-123", {})
        response_body, status = parse_handler_result(result)

        assert status == 200
        assert response_body["status"] == "completed"
        assert len(response_body["results"]) == 2
        assert response_body["results"][0]["debate_id"] == "d1"
        assert "pagination" in response_body

    def test_get_results_pending(self, handler, mock_get_request):
        job = BatchJob(
            batch_id="batch-pending-123",
            debate_ids=["d1", "d2"],
            status=BatchStatus.PENDING,
        )
        _save_batch_job(job)

        result = handler._handle_batch_results("batch-pending-123", {})
        response_body, status = parse_handler_result(result)

        assert status == 202
        assert "error" in response_body or "message" in response_body

    def test_get_results_partial_allowed(self, handler, mock_get_request):
        job = BatchJob(
            batch_id="batch-partial-123",
            debate_ids=["d1", "d2", "d3"],
            status=BatchStatus.PROCESSING,
            processed_count=1,
            results=[
                BatchDebateResult(
                    debate_id="d1",
                    status="success",
                    explanation={"confidence": 0.9},
                    processing_time_ms=100,
                ),
            ],
        )
        _save_batch_job(job)

        result = handler._handle_batch_results("batch-partial-123", {"include_partial": "true"})
        response_body, status = parse_handler_result(result)

        assert status == 200
        assert len(response_body["results"]) == 1

    def test_get_results_pagination(self, handler, mock_get_request):
        results = [
            BatchDebateResult(
                debate_id=f"d{i}", status="success", explanation={}, processing_time_ms=100
            )
            for i in range(10)
        ]
        job = BatchJob(
            batch_id="batch-paginated",
            debate_ids=[f"d{i}" for i in range(10)],
            status=BatchStatus.COMPLETED,
            processed_count=10,
            results=results,
        )
        _save_batch_job(job)

        result = handler._handle_batch_results("batch-paginated", {"limit": "3", "offset": "2"})
        response_body, status = parse_handler_result(result)

        assert status == 200
        assert len(response_body["results"]) == 3
        assert response_body["pagination"]["offset"] == 2
        assert response_body["pagination"]["limit"] == 3
        assert response_body["pagination"]["has_more"] is True

    def test_get_results_not_found(self, handler, mock_get_request):
        result = handler._handle_batch_results("nonexistent", {})
        response_body, status = parse_handler_result(result)

        assert status == 404
        assert "error" in response_body


# ============================================================================
# Test Compare Explanations
# ============================================================================


class TestCompareExplanations:
    """Test POST /api/v1/explainability/compare endpoint."""

    def test_compare_insufficient_debates(self, handler, mock_post_request):
        body = {"debate_ids": ["debate-1"]}  # Need at least 2
        mock_post_request.rfile = Mock()
        mock_post_request.rfile.read = Mock(return_value=json.dumps(body).encode())
        mock_post_request.headers["Content-Length"] = len(json.dumps(body))

        result = asyncio.run(handler._handle_compare(mock_post_request))
        response_body, status = parse_handler_result(result)

        assert status == 400
        assert "error" in response_body

    def test_compare_too_many_debates(self, handler, mock_post_request):
        body = {"debate_ids": [f"debate-{i}" for i in range(15)]}  # Max is 10
        mock_post_request.rfile = Mock()
        mock_post_request.rfile.read = Mock(return_value=json.dumps(body).encode())
        mock_post_request.headers["Content-Length"] = len(json.dumps(body))

        result = asyncio.run(handler._handle_compare(mock_post_request))
        response_body, status = parse_handler_result(result)

        assert status == 400
        assert "error" in response_body

    def test_compare_invalid_json(self, handler, mock_post_request):
        mock_post_request.rfile = Mock()
        mock_post_request.rfile.read = Mock(return_value=b"invalid json")
        mock_post_request.headers["Content-Length"] = 12

        result = asyncio.run(handler._handle_compare(mock_post_request))
        response_body, status = parse_handler_result(result)

        assert status == 400
        assert "error" in response_body
