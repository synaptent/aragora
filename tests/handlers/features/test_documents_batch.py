"""Tests for batch document upload and processing endpoint handlers.

Tests the batch document API endpoints including:
- POST /api/v1/documents/batch - Upload multiple documents
- GET /api/v1/documents/batch/{job_id} - Get batch job status
- GET /api/v1/documents/batch/{job_id}/results - Get batch job results
- DELETE /api/v1/documents/batch/{job_id} - Cancel a batch job
- GET /api/v1/documents/{doc_id}/chunks - Get document chunks
- GET /api/v1/documents/{doc_id}/context - Get LLM-ready context
- GET /api/v1/documents/processing/stats - Get processing statistics
- GET /api/v1/knowledge/jobs - Get knowledge processing jobs
- GET /api/v1/knowledge/jobs/{job_id} - Get knowledge job status

Also tests:
- can_handle() route matching
- Multipart form data parsing
- Rate limiting on batch upload
- Knowledge processing integration
- Error handling paths

These tests exercise the routed ``/api/v1/...`` surfaces directly so the
documented endpoints stay live end to end instead of only working through
internal helpers.
"""

import builtins as _builtins
import io
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_real_import = _builtins.__import__

from aragora.server.handlers.base import HandlerResult
from aragora.server.handlers.features.documents_batch import (
    DocumentBatchHandler,
    MAX_BATCH_SIZE,
    MAX_FILE_SIZE_MB,
    MAX_TOTAL_BATCH_SIZE_MB,
    _batch_upload_limiter,
)
from aragora.tenancy.record_scope import OrgScope

pytestmark = pytest.mark.usefixtures("org_scoped_request_user")

TEST_ORG = "test-org-001"
TEST_USER = "test-user-001"
SCOPE = OrgScope(org_id=TEST_ORG, user_id=TEST_USER, role="admin")
NOT_FOUND = {"error": "Job not found", "code": "not_found"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _status(result: HandlerResult) -> int:
    """Extract status code from HandlerResult."""
    return result.status_code


def _body(result: HandlerResult) -> dict[str, Any]:
    """Extract parsed JSON body from HandlerResult."""
    return json.loads(result.body.decode("utf-8"))


def _build_multipart_body(
    files: list[tuple[str, bytes]],
    form_fields: dict[str, str] | None = None,
    boundary: str = "testboundary",
) -> bytes:
    """Build a multipart/form-data body with multiple files and form fields."""
    parts = []
    for filename, content in files:
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            f'Content-Disposition: form-data; name="files[]"; filename="{filename}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n".encode()
        )
        parts.append(content)
        parts.append(b"\r\n")

    for key, value in (form_fields or {}).items():
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
        parts.append(value.encode())
        parts.append(b"\r\n")

    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts)


# ---------------------------------------------------------------------------
# Mock objects
# ---------------------------------------------------------------------------


class MockJobStatus(Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    PROCESSING = "processing"
    QUEUED = "queued"


@dataclass
class MockChunk:
    id: str = "chunk-001"
    sequence: int = 0
    token_count: int = 100
    heading_context: str = "Section 1"
    content: str = "Chunk content here"


@dataclass
class MockDocument:
    doc_id: str = "doc-001"
    filename: str = "test.txt"
    text: str = "Hello world content for testing"
    org_id: str | None = "test-org-001"

    def to_summary(self) -> dict[str, Any]:
        return {"id": self.doc_id, "filename": self.filename}


@dataclass
class MockJob:
    id: str = "job-001"
    status: MockJobStatus = MockJobStatus.COMPLETED
    filename: str = "test.txt"
    progress: float = 1.0
    document: MockDocument | None = None
    chunks: list[MockChunk] | None = None
    error_message: str | None = None
    org_id: str | None = "test-org-001"


@dataclass
class MockHTTPHandler:
    """Mock HTTP handler with headers, rfile, and client_address."""

    path: str = "/"
    command: str = "POST"
    headers: dict[str, str] = field(
        default_factory=lambda: {
            "Content-Length": "0",
            "Content-Type": "application/octet-stream",
        }
    )
    client_address: tuple = ("127.0.0.1", 12345)
    _rfile_data: bytes = b""

    def __post_init__(self):
        self.rfile = io.BytesIO(self._rfile_data)


def _make_multipart_handler(
    files: list[tuple[str, bytes]] | None = None,
    form_fields: dict[str, str] | None = None,
    boundary: str = "testboundary",
    client_ip: str = "127.0.0.1",
) -> MockHTTPHandler:
    """Create a mock handler for multipart upload requests."""
    if files is None:
        files = [("test.txt", b"hello world")]
    body = _build_multipart_body(files, form_fields, boundary)
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)),
    }
    return MockHTTPHandler(
        headers=headers,
        client_address=(client_ip, 12345),
        _rfile_data=body,
    )


class MockBatchProcessor:
    """Mock batch processor for testing."""

    def __init__(self):
        self._submitted: list[dict] = []
        self._statuses: dict[str, dict] = {}
        self._results: dict[str, MockJob] = {}
        self._cancelled: set[str] = set()
        self._removed: set[str] = set()
        self._removable: set[str] = set()
        self._stats = {"queued": 0, "processing": 0, "completed": 0, "failed": 0}
        self.stats_calls: list[dict] = []

    async def submit(
        self,
        content,
        filename,
        workspace_id,
        priority,
        chunking_strategy=None,
        chunk_size=512,
        chunk_overlap=50,
        tags=None,
        uploaded_by=None,
        org_id=None,
        document_id=None,
    ) -> str:
        job_id = f"job-{len(self._submitted):03d}"
        self._submitted.append(
            {
                "content": content,
                "filename": filename,
                "workspace_id": workspace_id,
                "priority": priority,
                "uploaded_by": uploaded_by,
                "org_id": org_id,
                "document_id": document_id,
            }
        )
        return job_id

    async def get_status(self, job_id: str) -> dict | None:
        return self._statuses.get(job_id)

    async def get_result(self, job_id: str) -> MockJob | None:
        return self._results.get(job_id)

    async def cancel(self, job_id: str) -> bool:
        if job_id in self._cancelled:
            return False
        self._cancelled.add(job_id)
        return True

    async def remove(self, job_id: str) -> bool:
        if job_id not in self._removable:
            return False
        self._removed.add(job_id)
        return True

    def get_stats(self, org_id: str | None = None) -> dict:
        self.stats_calls.append({"org_id": org_id})
        return self._stats


class MockTokenCounter:
    """Mock token counter for testing."""

    def count(self, text: str, model: str = "gpt-4") -> int:
        return len(text.split())

    def truncate_to_tokens(self, text: str, max_tokens: int, model: str = "gpt-4") -> str:
        words = text.split()
        return " ".join(words[:max_tokens])


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler():
    """Create a DocumentBatchHandler with minimal context."""
    return DocumentBatchHandler(server_context={})


@pytest.fixture
def processor():
    """Create a mock batch processor."""
    return MockBatchProcessor()


@pytest.fixture
def handler_with_processor(processor):
    """Create a handler with a batch processor in context."""
    return DocumentBatchHandler(server_context={"batch_processor": processor})


@pytest.fixture
def handler_with_document_store():
    """Create a handler with a mock document store in context."""
    store = MagicMock()
    doc = MockDocument()
    store.get.return_value = doc
    return DocumentBatchHandler(server_context={"document_store": store})


@pytest.fixture
def mock_http():
    """Create a minimal mock HTTP handler for GET requests."""
    return MockHTTPHandler(command="GET", headers={"Content-Length": "0"})


@pytest.fixture(autouse=True)
def reset_rate_limits():
    """Reset the batch upload rate limiter between tests."""
    _batch_upload_limiter._buckets.clear()
    yield
    _batch_upload_limiter._buckets.clear()


@pytest.fixture(autouse=True)
def _no_knowledge_workers(monkeypatch):
    """Queued knowledge jobs never run.

    A real knowledge job left running on the module's non-daemon executor
    keeps the interpreter from exiting after the tests finish.
    """
    import aragora.knowledge.integration as knowledge

    monkeypatch.setattr(knowledge, "_jobs", {})
    monkeypatch.setattr(knowledge, "_executor", MagicMock())


# ===========================================================================
# can_handle() tests
# ===========================================================================


class TestCanHandle:
    """Tests for route matching in can_handle()."""

    def test_batch_route(self, handler):
        assert handler.can_handle("/api/v1/batch") is True

    def test_batch_queue_status_route(self, handler):
        assert handler.can_handle("/api/v1/batch/queue/status") is True

    def test_documents_batch_route(self, handler):
        assert handler.can_handle("/api/v1/documents/batch") is True

    def test_processing_stats_route(self, handler):
        assert handler.can_handle("/api/v1/documents/processing/stats") is True

    def test_knowledge_jobs_route(self, handler):
        assert handler.can_handle("/api/v1/knowledge/jobs") is True

    def test_batch_job_id_route(self, handler):
        assert handler.can_handle("/api/v1/documents/batch/job-123") is True

    def test_batch_job_results_route(self, handler):
        assert handler.can_handle("/api/v1/documents/batch/job-123/results") is True

    def test_document_chunks_route(self, handler):
        assert handler.can_handle("/api/v1/documents/doc-001/chunks") is True

    def test_document_context_route(self, handler):
        assert handler.can_handle("/api/v1/documents/doc-001/context") is True

    def test_knowledge_job_id_route(self, handler):
        assert handler.can_handle("/api/v1/knowledge/jobs/kj-001") is True

    def test_unrelated_route(self, handler):
        assert handler.can_handle("/api/v1/users") is False

    def test_root_route(self, handler):
        assert handler.can_handle("/") is False

    def test_partial_documents_route(self, handler):
        assert handler.can_handle("/api/v1/documents") is False

    def test_documents_without_suffix(self, handler):
        """A documents path with exactly 4 slashes but no /chunks or /context suffix."""
        assert handler.can_handle("/api/v1/documents/doc-001") is False

    def test_documents_unknown_suffix(self, handler):
        assert handler.can_handle("/api/v1/documents/doc-001/metadata") is False

    def test_empty_path(self, handler):
        assert handler.can_handle("") is False

    def test_batch_deep_nested(self, handler):
        """Deeply nested batch path should not match the documented routes."""
        assert handler.can_handle("/api/v1/documents/batch/job-001/results/extra") is False


# ===========================================================================
# GET /api/v1/documents/processing/stats
# ===========================================================================


class TestGetProcessingStats:
    """Tests for GET /api/v1/documents/processing/stats."""

    @pytest.mark.asyncio
    async def test_returns_stats(self, handler_with_processor, mock_http):
        result = await handler_with_processor.handle(
            "/api/v1/documents/processing/stats", {}, mock_http
        )
        assert _status(result) == 200
        body = _body(result)
        assert "processor" in body
        assert "limits" in body
        assert body["limits"]["max_batch_size"] == MAX_BATCH_SIZE
        assert body["limits"]["max_file_size_mb"] == MAX_FILE_SIZE_MB
        assert body["limits"]["max_total_batch_size_mb"] == MAX_TOTAL_BATCH_SIZE_MB

    @pytest.mark.asyncio
    async def test_stats_contains_processor_stats(self, handler_with_processor, mock_http):
        result = await handler_with_processor.handle(
            "/api/v1/documents/processing/stats", {}, mock_http
        )
        body = _body(result)
        assert body["processor"] == {"queued": 0, "processing": 0, "completed": 0, "failed": 0}

    @pytest.mark.asyncio
    async def test_stats_creates_processor_if_missing(self, mock_http):
        handler = DocumentBatchHandler(server_context={})
        with patch(
            "aragora.documents.ingestion.batch_processor.BatchProcessor",
        ) as MockBP:
            mock_proc = MagicMock()
            mock_proc.get_stats.return_value = {"queued": 5}
            MockBP.return_value = mock_proc
            result = await handler.handle("/api/v1/documents/processing/stats", {}, mock_http)
        assert _status(result) == 200
        body = _body(result)
        assert body["processor"] == {"queued": 5}
        mock_proc.get_stats.assert_called_once_with(org_id=TEST_ORG)


# ===========================================================================
# GET /api/v1/knowledge/jobs
# ===========================================================================


class TestListKnowledgeJobs:
    """Tests for GET /api/v1/knowledge/jobs."""

    @pytest.mark.asyncio
    async def test_list_jobs_success(self, handler, mock_http):
        with patch(
            "aragora.knowledge.integration.get_all_jobs",
            return_value=[{"id": "kj-001", "status": "completed"}],
        ):
            result = await handler.handle("/api/v1/knowledge/jobs", {}, mock_http)
        assert _status(result) == 200
        body = _body(result)
        assert body["count"] == 1
        assert body["jobs"][0]["id"] == "kj-001"

    @pytest.mark.asyncio
    async def test_list_jobs_with_filters(self, handler, mock_http):
        with patch(
            "aragora.knowledge.integration.get_all_jobs",
            return_value=[],
        ) as mock_get:
            query = {
                "workspace_id": ["ws-001"],
                "status": ["processing"],
                "limit": ["50"],
            }
            result = await handler.handle("/api/v1/knowledge/jobs", query, mock_http)
        assert _status(result) == 200
        body = _body(result)
        assert body["filters"]["workspace_id"] == "ws-001"
        assert body["filters"]["status"] == "processing"
        assert body["filters"]["limit"] == 50
        mock_get.assert_called_once_with(
            workspace_id="ws-001", status="processing", limit=50, org_id=TEST_ORG
        )

    @pytest.mark.asyncio
    async def test_list_jobs_with_single_value_filters(self, handler, mock_http):
        """The live server passes each query parameter as one string."""
        with patch(
            "aragora.knowledge.integration.get_all_jobs",
            return_value=[],
        ) as mock_get:
            query = {"workspace_id": "ws-001", "status": "processing"}
            result = await handler.handle("/api/v1/knowledge/jobs", query, mock_http)
        assert _status(result) == 200
        mock_get.assert_called_once_with(
            workspace_id="ws-001", status="processing", limit=100, org_id=TEST_ORG
        )

    @pytest.mark.asyncio
    async def test_list_jobs_no_filters(self, handler, mock_http):
        with patch(
            "aragora.knowledge.integration.get_all_jobs",
            return_value=[],
        ) as mock_get:
            result = await handler.handle("/api/v1/knowledge/jobs", {}, mock_http)
        assert _status(result) == 200
        body = _body(result)
        assert body["filters"]["workspace_id"] is None
        assert body["filters"]["status"] is None
        assert body["filters"]["limit"] == 100

    @pytest.mark.asyncio
    async def test_list_jobs_import_error(self, handler, mock_http):
        with patch.dict("sys.modules", {"aragora.knowledge.integration": None}):
            with patch(
                "builtins.__import__",
                side_effect=lambda name, *a, **kw: (_ for _ in ()).throw(ImportError("no module"))
                if "aragora.knowledge.integration" in name
                else _real_import(name, *a, **kw),
            ):
                result = await handler.handle("/api/v1/knowledge/jobs", {}, mock_http)
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_list_jobs_value_error(self, handler, mock_http):
        with patch(
            "aragora.knowledge.integration.get_all_jobs",
            side_effect=ValueError("bad filter"),
        ):
            result = await handler.handle("/api/v1/knowledge/jobs", {}, mock_http)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_list_jobs_type_error(self, handler, mock_http):
        with patch(
            "aragora.knowledge.integration.get_all_jobs",
            side_effect=TypeError("wrong type"),
        ):
            result = await handler.handle("/api/v1/knowledge/jobs", {}, mock_http)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_list_jobs_attribute_error(self, handler, mock_http):
        with patch(
            "aragora.knowledge.integration.get_all_jobs",
            side_effect=AttributeError("oops"),
        ):
            result = await handler.handle("/api/v1/knowledge/jobs", {}, mock_http)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_list_jobs_key_error(self, handler, mock_http):
        with patch(
            "aragora.knowledge.integration.get_all_jobs",
            side_effect=KeyError("missing"),
        ):
            result = await handler.handle("/api/v1/knowledge/jobs", {}, mock_http)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_list_jobs_empty(self, handler, mock_http):
        with patch(
            "aragora.knowledge.integration.get_all_jobs",
            return_value=[],
        ):
            result = await handler.handle("/api/v1/knowledge/jobs", {}, mock_http)
        body = _body(result)
        assert body["count"] == 0
        assert body["jobs"] == []


# ===========================================================================
# GET /api/v1/knowledge/jobs/{job_id}
# ===========================================================================


class TestGetKnowledgeJobStatus:
    """Tests for GET /api/v1/knowledge/jobs/{job_id}."""

    @pytest.mark.asyncio
    async def test_v1_path_dispatches_to_job_status(self, handler, mock_http):
        """The documented v1 path should dispatch to job-status lookup."""
        with patch(
            "aragora.knowledge.integration.get_job_status",
            return_value={"id": "kj-001", "status": "completed", "metadata": {"org_id": TEST_ORG}},
        ):
            result = await handler.handle("/api/v1/knowledge/jobs/kj-001", {}, mock_http)
        assert _status(result) == 200
        body = _body(result)
        assert body["id"] == "kj-001"

    @pytest.mark.asyncio
    async def test_get_job_status_success_via_internal(self, handler, mock_http):
        """The internal helper still returns the same payload."""
        with patch(
            "aragora.knowledge.integration.get_job_status",
            return_value={"id": "kj-001", "status": "completed", "metadata": {"org_id": TEST_ORG}},
        ):
            result = handler._get_knowledge_job_status("kj-001", SCOPE)
        assert _status(result) == 200
        body = _body(result)
        assert body["id"] == "kj-001"

    @pytest.mark.asyncio
    async def test_get_job_status_not_found_via_internal(self, handler, mock_http):
        with patch(
            "aragora.knowledge.integration.get_job_status",
            return_value=None,
        ):
            result = handler._get_knowledge_job_status("kj-nonexistent", SCOPE)
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_get_job_status_import_error_via_internal(self, handler):
        with patch.dict("sys.modules", {"aragora.knowledge.integration": None}):
            with patch(
                "builtins.__import__",
                side_effect=lambda name, *a, **kw: (_ for _ in ()).throw(ImportError("no module"))
                if "aragora.knowledge.integration" in name
                else _real_import(name, *a, **kw),
            ):
                result = handler._get_knowledge_job_status("kj-001", SCOPE)
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_get_job_status_key_error_via_internal(self, handler):
        with patch(
            "aragora.knowledge.integration.get_job_status",
            side_effect=KeyError("invalid"),
        ):
            result = handler._get_knowledge_job_status("kj-001", SCOPE)
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_get_job_status_value_error_via_internal(self, handler):
        with patch(
            "aragora.knowledge.integration.get_job_status",
            side_effect=ValueError("bad"),
        ):
            result = handler._get_knowledge_job_status("kj-001", SCOPE)
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_get_job_status_attribute_error_via_internal(self, handler):
        with patch(
            "aragora.knowledge.integration.get_job_status",
            side_effect=AttributeError("oops"),
        ):
            result = handler._get_knowledge_job_status("kj-001", SCOPE)
        assert _status(result) == 500


# ===========================================================================
# GET /api/v1/documents/batch/{job_id}
# ===========================================================================


class TestGetJobStatus:
    """Tests for GET /api/v1/documents/batch/{job_id}."""

    @pytest.mark.asyncio
    async def test_v1_path_dispatches(self, handler_with_processor, processor, mock_http):
        """The documented v1 batch-status path should dispatch."""
        processor._statuses["job-001"] = {
            "status": "processing",
            "progress": 0.5,
            "org_id": TEST_ORG,
        }
        result = await handler_with_processor.handle(
            "/api/v1/documents/batch/job-001", {}, mock_http
        )
        assert _status(result) == 200
        body = _body(result)
        assert body["status"] == "processing"
        assert body["progress"] == 0.5

    @pytest.mark.asyncio
    async def test_get_status_found_via_internal(self, handler_with_processor, processor):
        processor._statuses["job-001"] = {
            "status": "processing",
            "progress": 0.5,
            "org_id": TEST_ORG,
        }
        result = await handler_with_processor._get_job_status("job-001", SCOPE)
        assert _status(result) == 200
        body = _body(result)
        assert body["status"] == "processing"
        assert body["progress"] == 0.5

    @pytest.mark.asyncio
    async def test_get_status_not_found_via_internal(self, handler_with_processor):
        result = await handler_with_processor._get_job_status("nonexistent", SCOPE)
        assert _status(result) == 404
        assert _body(result) == NOT_FOUND


# ===========================================================================
# GET /api/v1/documents/batch/{job_id}/results
# ===========================================================================


class TestGetJobResults:
    """Tests for GET /api/v1/documents/batch/{job_id}/results."""

    @pytest.mark.asyncio
    async def test_v1_path_dispatches(self, handler_with_processor, processor, mock_http):
        """The documented v1 batch-results path should dispatch."""
        processor._results["job-001"] = MockJob(
            id="job-001",
            status=MockJobStatus.COMPLETED,
            filename="test.txt",
            document=MockDocument(),
            chunks=[MockChunk()],
        )
        result = await handler_with_processor.handle(
            "/api/v1/documents/batch/job-001/results", {}, mock_http
        )
        assert _status(result) == 200
        body = _body(result)
        assert body["job_id"] == "job-001"
        assert body["chunks"]["total"] == 1

    @pytest.mark.asyncio
    async def test_results_completed_job(self, handler_with_processor, processor):
        job = MockJob(
            id="job-001",
            status=MockJobStatus.COMPLETED,
            filename="test.txt",
            document=MockDocument(),
            chunks=[MockChunk()],
        )
        processor._results["job-001"] = job
        result = await handler_with_processor._get_job_results("job-001", SCOPE)
        assert _status(result) == 200
        body = _body(result)
        assert body["job_id"] == "job-001"
        assert body["status"] == "completed"
        assert body["filename"] == "test.txt"
        assert "document" in body
        assert "chunks" in body
        assert body["chunks"]["total"] == 1

    @pytest.mark.asyncio
    async def test_results_failed_job(self, handler_with_processor, processor):
        job = MockJob(
            id="job-002",
            status=MockJobStatus.FAILED,
            filename="bad.txt",
            error_message="Parse error",
        )
        processor._results["job-002"] = job
        result = await handler_with_processor._get_job_results("job-002", SCOPE)
        assert _status(result) == 200
        body = _body(result)
        assert body["status"] == "failed"
        assert body["error"] == "Parse error"

    @pytest.mark.asyncio
    async def test_results_in_progress_job(self, handler_with_processor, processor):
        job = MockJob(
            id="job-003",
            status=MockJobStatus.PROCESSING,
            filename="test.txt",
            progress=0.75,
        )
        processor._results["job-003"] = job
        result = await handler_with_processor._get_job_results("job-003", SCOPE)
        assert _status(result) == 202
        body = _body(result)
        assert body["status"] == "processing"
        assert body["progress"] == 0.75
        assert body["message"] == "Job not yet complete"

    @pytest.mark.asyncio
    async def test_results_queued_job(self, handler_with_processor, processor):
        job = MockJob(
            id="job-004",
            status=MockJobStatus.QUEUED,
            filename="test.txt",
            progress=0.0,
        )
        processor._results["job-004"] = job
        result = await handler_with_processor._get_job_results("job-004", SCOPE)
        assert _status(result) == 202
        body = _body(result)
        assert body["status"] == "queued"

    @pytest.mark.asyncio
    async def test_results_not_found(self, handler_with_processor):
        result = await handler_with_processor._get_job_results("nonexistent", SCOPE)
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_results_completed_no_document(self, handler_with_processor, processor):
        job = MockJob(
            id="job-005",
            status=MockJobStatus.COMPLETED,
            filename="test.txt",
            document=None,
            chunks=None,
        )
        processor._results["job-005"] = job
        result = await handler_with_processor._get_job_results("job-005", SCOPE)
        assert _status(result) == 200
        body = _body(result)
        assert "document" not in body
        assert "chunks" not in body

    @pytest.mark.asyncio
    async def test_results_completed_with_many_chunks(self, handler_with_processor, processor):
        """Only first 10 chunks are included in summary."""
        chunks = [MockChunk(id=f"chunk-{i:03d}", sequence=i) for i in range(15)]
        job = MockJob(
            id="job-006",
            status=MockJobStatus.COMPLETED,
            filename="big.txt",
            chunks=chunks,
        )
        processor._results["job-006"] = job
        result = await handler_with_processor._get_job_results("job-006", SCOPE)
        body = _body(result)
        assert body["chunks"]["total"] == 15
        assert len(body["chunks"]["items"]) == 10  # Only first 10

    @pytest.mark.asyncio
    async def test_results_chunk_preview_truncation(self, handler_with_processor, processor):
        """Long chunk content should be truncated with '...' suffix."""
        long_content = "x" * 300
        chunks = [MockChunk(id="chunk-big", content=long_content)]
        job = MockJob(
            id="job-007",
            status=MockJobStatus.COMPLETED,
            filename="test.txt",
            chunks=chunks,
        )
        processor._results["job-007"] = job
        result = await handler_with_processor._get_job_results("job-007", SCOPE)
        body = _body(result)
        preview = body["chunks"]["items"][0]["preview"]
        assert preview.endswith("...")
        assert len(preview) == 203  # 200 + "..."

    @pytest.mark.asyncio
    async def test_results_short_chunk_no_truncation(self, handler_with_processor, processor):
        """Short chunk content should not be truncated."""
        chunks = [MockChunk(id="chunk-short", content="short")]
        job = MockJob(
            id="job-008",
            status=MockJobStatus.COMPLETED,
            filename="test.txt",
            chunks=chunks,
        )
        processor._results["job-008"] = job
        result = await handler_with_processor._get_job_results("job-008", SCOPE)
        body = _body(result)
        assert body["chunks"]["items"][0]["preview"] == "short"

    @pytest.mark.asyncio
    async def test_results_total_tokens(self, handler_with_processor, processor):
        """Total tokens should sum across all chunks."""
        chunks = [
            MockChunk(id="c1", token_count=100),
            MockChunk(id="c2", token_count=200),
            MockChunk(id="c3", token_count=50),
        ]
        job = MockJob(
            id="job-009",
            status=MockJobStatus.COMPLETED,
            filename="test.txt",
            chunks=chunks,
        )
        processor._results["job-009"] = job
        result = await handler_with_processor._get_job_results("job-009", SCOPE)
        body = _body(result)
        assert body["chunks"]["total_tokens"] == 350


# ===========================================================================
# DELETE /api/v1/documents/batch/{job_id}
# ===========================================================================


class TestCancelJob:
    """Tests for DELETE /api/v1/documents/batch/{job_id}."""

    @pytest.mark.asyncio
    async def test_v1_path_dispatches(self, handler_with_processor, processor, mock_http):
        """The documented v1 delete path should dispatch."""
        processor._results["job-001"] = MockJob(id="job-001", status=MockJobStatus.QUEUED)
        result = await handler_with_processor.handle_delete(
            "/api/v1/documents/batch/job-001", {}, mock_http
        )
        assert _status(result) == 200
        body = _body(result)
        assert body["cancelled"] is True
        assert body["job_id"] == "job-001"

    @pytest.mark.asyncio
    async def test_cancel_success_via_internal(self, handler_with_processor, processor):
        processor._results["job-001"] = MockJob(id="job-001", status=MockJobStatus.QUEUED)
        result = await handler_with_processor._cancel_job("job-001", SCOPE)
        assert _status(result) == 200
        body = _body(result)
        assert body["cancelled"] is True
        assert body["job_id"] == "job-001"

    @pytest.mark.asyncio
    async def test_cancel_already_cancelled_via_internal(self, handler_with_processor, processor):
        processor._results["job-001"] = MockJob(id="job-001")
        processor._cancelled.add("job-001")
        result = await handler_with_processor._cancel_job("job-001", SCOPE)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_delete_finished_job_via_internal(self, handler_with_processor, processor):
        """A job that can no longer be cancelled is removed instead."""
        processor._results["job-001"] = MockJob(id="job-001")
        processor._cancelled.add("job-001")
        processor._removable.add("job-001")
        result = await handler_with_processor._cancel_job("job-001", SCOPE)
        assert _status(result) == 200
        assert _body(result) == {"deleted": True, "job_id": "job-001"}
        assert processor._removed == {"job-001"}

    @pytest.mark.asyncio
    async def test_cancel_missing_job_via_internal(self, handler_with_processor, processor):
        result = await handler_with_processor._cancel_job("nonexistent", SCOPE)
        assert _status(result) == 404
        assert _body(result) == NOT_FOUND
        assert processor._cancelled == set()

    @pytest.mark.asyncio
    async def test_cancel_non_batch_path(self, handler_with_processor, mock_http):
        result = await handler_with_processor.handle_delete(
            "/api/v1/documents/other/job-001", {}, mock_http
        )
        assert result is None


# ===========================================================================
# GET /api/v1/documents/{doc_id}/chunks
# ===========================================================================


class TestGetDocumentChunks:
    """Tests for GET /api/v1/documents/{doc_id}/chunks."""

    @pytest.mark.asyncio
    async def test_v1_path_dispatches_for_chunks(self, handler_with_document_store, mock_http):
        """The documented v1 chunks path should dispatch."""
        result = await handler_with_document_store.handle(
            "/api/v1/documents/doc-001/chunks", {}, mock_http
        )
        assert _status(result) == 200
        body = _body(result)
        assert body["document_id"] == "doc-001"
        assert body["chunks"] == []

    def test_chunks_default_params_via_internal(self, handler_with_document_store):
        result = handler_with_document_store._get_document_chunks("doc-001", SCOPE)
        assert _status(result) == 200
        body = _body(result)
        assert body["document_id"] == "doc-001"
        assert body["chunks"] == []
        assert body["total"] == 0
        assert body["limit"] == 100
        assert body["offset"] == 0

    def test_chunks_custom_params_via_internal(self, handler_with_document_store):
        result = handler_with_document_store._get_document_chunks(
            "doc-001", SCOPE, limit=25, offset=10
        )
        assert _status(result) == 200
        body = _body(result)
        assert body["limit"] == 25
        assert body["offset"] == 10

    def test_chunks_different_doc_id(self, handler_with_document_store):
        result = handler_with_document_store._get_document_chunks("my-special-doc", SCOPE)
        assert _status(result) == 200
        body = _body(result)
        assert body["document_id"] == "my-special-doc"

    def test_chunks_message_mentions_phase_2(self, handler_with_document_store):
        result = handler_with_document_store._get_document_chunks("doc-001", SCOPE)
        body = _body(result)
        assert "Phase 2" in body["message"]

    def test_chunks_not_found_without_document_store(self, handler):
        """Without a document store no document is visible, so chunks are 404."""
        result = handler._get_document_chunks("doc-001", SCOPE)
        assert _status(result) == 404
        assert _body(result) == {"error": "Document not found", "code": "not_found"}

    def test_chunks_not_found_in_store(self):
        store = MagicMock()
        store.get.return_value = None
        h = DocumentBatchHandler(server_context={"document_store": store})
        result = h._get_document_chunks("doc-001", SCOPE)
        assert _status(result) == 404


# ===========================================================================
# GET /api/v1/documents/{doc_id}/context
# ===========================================================================


class TestGetDocumentContext:
    """Tests for GET /api/v1/documents/{doc_id}/context."""

    @pytest.mark.asyncio
    async def test_v1_path_dispatches_for_context(self, handler_with_document_store, mock_http):
        """The documented v1 context path should dispatch."""
        result = await handler_with_document_store.handle(
            "/api/v1/documents/doc-001/context", {}, mock_http
        )
        assert _status(result) == 200
        body = _body(result)
        assert body["document_id"] == "doc-001"
        assert body["context"] == "Hello world content for testing"

    def test_context_not_found_no_store(self, handler):
        result = handler._get_document_context("doc-001", SCOPE)
        assert _status(result) == 404

    def test_context_not_found_in_store(self):
        store = MagicMock()
        store.get.return_value = None
        h = DocumentBatchHandler(server_context={"document_store": store})
        result = h._get_document_context("doc-001", SCOPE)
        assert _status(result) == 404

    def test_context_found_no_truncation(self):
        store = MagicMock()
        doc = MockDocument(text="short text")
        store.get.return_value = doc
        h = DocumentBatchHandler(server_context={"document_store": store})
        mock_counter = MockTokenCounter()
        with patch(
            "aragora.documents.chunking.token_counter.get_token_counter",
            return_value=mock_counter,
        ):
            result = h._get_document_context("doc-001", SCOPE)
        assert _status(result) == 200
        body = _body(result)
        assert body["document_id"] == "doc-001"
        assert body["context"] == "short text"
        assert body["truncated"] is False

    def test_context_with_truncation(self):
        store = MagicMock()
        doc = MockDocument(text="word " * 5000)  # 5000 words
        store.get.return_value = doc
        h = DocumentBatchHandler(server_context={"document_store": store})
        mock_counter = MockTokenCounter()
        with patch(
            "aragora.documents.chunking.token_counter.get_token_counter",
            return_value=mock_counter,
        ):
            result = h._get_document_context("doc-001", SCOPE, max_tokens=10)
        assert _status(result) == 200
        body = _body(result)
        assert body["truncated"] is True
        assert body["max_tokens"] == 10

    def test_context_custom_model(self):
        store = MagicMock()
        doc = MockDocument(text="hello")
        store.get.return_value = doc
        h = DocumentBatchHandler(server_context={"document_store": store})
        mock_counter = MockTokenCounter()
        with patch(
            "aragora.documents.chunking.token_counter.get_token_counter",
            return_value=mock_counter,
        ):
            result = h._get_document_context("doc-001", SCOPE, model="claude-3")
        assert _status(result) == 200
        body = _body(result)
        assert body["model"] == "claude-3"

    def test_context_default_max_tokens(self):
        store = MagicMock()
        doc = MockDocument(text="hello")
        store.get.return_value = doc
        h = DocumentBatchHandler(server_context={"document_store": store})
        mock_counter = MockTokenCounter()
        with patch(
            "aragora.documents.chunking.token_counter.get_token_counter",
            return_value=mock_counter,
        ):
            result = h._get_document_context("doc-001", SCOPE)
        body = _body(result)
        assert body["max_tokens"] == 4096

    def test_context_token_count_in_response(self):
        store = MagicMock()
        doc = MockDocument(text="one two three")
        store.get.return_value = doc
        h = DocumentBatchHandler(server_context={"document_store": store})
        mock_counter = MockTokenCounter()
        with patch(
            "aragora.documents.chunking.token_counter.get_token_counter",
            return_value=mock_counter,
        ):
            result = h._get_document_context("doc-001", SCOPE)
        body = _body(result)
        assert body["token_count"] == 3  # "one two three" = 3 words


# ===========================================================================
# POST /api/v1/documents/batch (upload)
# ===========================================================================


class TestUploadBatch:
    """Tests for POST /api/v1/documents/batch."""

    @pytest.mark.asyncio
    async def test_upload_success(self, handler_with_processor):
        http = _make_multipart_handler(files=[("test.txt", b"hello world")])
        with patch(
            "aragora.documents.ingestion.batch_processor.JobPriority",
        ) as MockJP:
            MockJP.LOW = "low"
            MockJP.NORMAL = "normal"
            MockJP.HIGH = "high"
            MockJP.URGENT = "urgent"
            with patch(
                "aragora.documents.chunking.token_counter.get_token_counter",
                return_value=MockTokenCounter(),
            ):
                result = await handler_with_processor.handle_post(
                    "/api/v1/documents/batch", {}, http
                )
        assert _status(result) == 202
        body = _body(result)
        assert "job_ids" in body
        assert "batch_id" in body
        assert body["total_files"] == 1
        assert body["chunking_strategy"] == "auto"

    @pytest.mark.asyncio
    async def test_upload_wrong_content_type(self, handler_with_processor):
        http = MockHTTPHandler(
            headers={"Content-Type": "application/json", "Content-Length": "0"},
            client_address=("127.0.0.1", 12345),
        )
        result = await handler_with_processor.handle_post("/api/v1/documents/batch", {}, http)
        assert _status(result) == 400
        body = _body(result)
        assert "multipart/form-data" in body.get("error", "")

    @pytest.mark.asyncio
    async def test_upload_missing_boundary(self, handler_with_processor):
        http = MockHTTPHandler(
            headers={
                "Content-Type": "multipart/form-data",
                "Content-Length": "0",
            },
            client_address=("127.0.0.1", 12345),
        )
        result = await handler_with_processor.handle_post("/api/v1/documents/batch", {}, http)
        assert _status(result) == 400
        body = _body(result)
        assert "boundary" in body.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_upload_no_files(self, handler_with_processor):
        """Multipart body with only form fields (no files) should return 400."""
        body_data = _build_multipart_body([], {"workspace_id": "ws-001"})
        http = MockHTTPHandler(
            headers={
                "Content-Type": "multipart/form-data; boundary=testboundary",
                "Content-Length": str(len(body_data)),
            },
            client_address=("127.0.0.1", 12345),
            _rfile_data=body_data,
        )
        with patch(
            "aragora.documents.ingestion.batch_processor.JobPriority",
        ) as MockJP:
            MockJP.NORMAL = "normal"
            result = await handler_with_processor.handle_post("/api/v1/documents/batch", {}, http)
        assert _status(result) == 400
        body = _body(result)
        assert "no files" in body.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_upload_exceeds_total_size(self, handler_with_processor):
        """Body exceeding MAX_TOTAL_BATCH_SIZE_MB should return 413."""
        huge_size = MAX_TOTAL_BATCH_SIZE_MB * 1024 * 1024 + 1
        http = MockHTTPHandler(
            headers={
                "Content-Type": "multipart/form-data; boundary=testboundary",
                "Content-Length": str(huge_size),
            },
            client_address=("127.0.0.1", 12345),
            _rfile_data=b"x",  # Actual data doesn't matter since size check is first
        )
        result = await handler_with_processor.handle_post("/api/v1/documents/batch", {}, http)
        assert _status(result) == 413

    @pytest.mark.asyncio
    async def test_upload_too_many_files(self, handler_with_processor, processor):
        """More than MAX_BATCH_SIZE files should return 400."""
        files = [(f"file{i}.txt", b"content") for i in range(MAX_BATCH_SIZE + 1)]
        http = _make_multipart_handler(files=files)
        with patch(
            "aragora.documents.ingestion.batch_processor.JobPriority",
        ) as MockJP:
            MockJP.NORMAL = "normal"
            result = await handler_with_processor.handle_post("/api/v1/documents/batch", {}, http)
        assert _status(result) == 400
        body = _body(result)
        assert str(MAX_BATCH_SIZE) in body.get("error", "")

    @pytest.mark.asyncio
    async def test_upload_rate_limited(self, handler_with_processor):
        """Rate limiter should reject after too many requests."""
        # Exhaust the rate limiter (5 requests per minute)
        for _ in range(6):
            _batch_upload_limiter.is_allowed("192.168.1.100")

        http = _make_multipart_handler(client_ip="192.168.1.100")
        result = await handler_with_processor.handle_post("/api/v1/documents/batch", {}, http)
        assert _status(result) == 429

    @pytest.mark.asyncio
    async def test_upload_wrong_path_returns_none(self, handler_with_processor):
        http = _make_multipart_handler()
        result = await handler_with_processor.handle_post("/api/v1/documents/upload", {}, http)
        assert result is None

    @pytest.mark.asyncio
    async def test_upload_with_form_fields(self, handler_with_processor, processor):
        """Form fields should be parsed and used."""
        http = _make_multipart_handler(
            files=[("data.csv", b"col1,col2")],
            form_fields={
                "workspace_id": "ws-custom",
                "chunking_strategy": "semantic",
                "chunk_size": "256",
                "chunk_overlap": "25",
                "priority": "high",
                "tags": '["finance", "report"]',
            },
        )
        with patch(
            "aragora.documents.ingestion.batch_processor.JobPriority",
        ) as MockJP:
            MockJP.LOW = "low"
            MockJP.NORMAL = "normal"
            MockJP.HIGH = "high"
            MockJP.URGENT = "urgent"
            with patch(
                "aragora.documents.chunking.token_counter.get_token_counter",
                return_value=MockTokenCounter(),
            ):
                result = await handler_with_processor.handle_post(
                    "/api/v1/documents/batch", {}, http
                )
        assert _status(result) == 202
        body = _body(result)
        assert body["chunking_strategy"] == "semantic"
        assert body["chunk_size"] == 256
        assert body["chunk_overlap"] == 25

    @pytest.mark.asyncio
    async def test_upload_with_knowledge_processing(self, handler_with_processor, processor):
        """Knowledge processing should be queued when enabled."""
        http = _make_multipart_handler(
            files=[("test.txt", b"hello")],
            form_fields={"process_knowledge": "true"},
        )
        with patch(
            "aragora.documents.ingestion.batch_processor.JobPriority",
        ) as MockJP:
            MockJP.NORMAL = "normal"
            with patch(
                "aragora.documents.chunking.token_counter.get_token_counter",
                return_value=MockTokenCounter(),
            ):
                with patch(
                    "aragora.knowledge.integration.queue_document_processing",
                    return_value="kp-001",
                ) as mock_queue:
                    result = await handler_with_processor.handle_post(
                        "/api/v1/documents/batch", {}, http
                    )
        assert _status(result) == 202
        body = _body(result)
        assert "knowledge_processing" in body
        assert body["knowledge_processing"]["enabled"] is True
        assert body["knowledge_processing"]["job_ids"] == ["kp-001"]

    @pytest.mark.asyncio
    async def test_upload_knowledge_processing_unavailable(self, handler_with_processor, processor):
        """Knowledge processing unavailable should be noted in response."""
        http = _make_multipart_handler(
            files=[("test.txt", b"hello")],
            form_fields={"process_knowledge": "true"},
        )
        with patch(
            "aragora.documents.ingestion.batch_processor.JobPriority",
        ) as MockJP:
            MockJP.NORMAL = "normal"
            with patch(
                "aragora.documents.chunking.token_counter.get_token_counter",
                return_value=MockTokenCounter(),
            ):
                with patch(
                    "builtins.__import__",
                    side_effect=lambda name, *a, **kw: (_ for _ in ()).throw(ImportError())
                    if name == "aragora.knowledge.integration"
                    else _real_import(name, *a, **kw),
                ):
                    result = await handler_with_processor.handle_post(
                        "/api/v1/documents/batch", {}, http
                    )
        assert _status(result) == 202
        body = _body(result)
        assert body["knowledge_processing"]["enabled"] is True
        assert body["knowledge_processing"]["status"] == "unavailable"

    @pytest.mark.asyncio
    async def test_upload_knowledge_disabled(self, handler_with_processor, processor):
        """No knowledge_processing key when disabled."""
        http = _make_multipart_handler(
            files=[("test.txt", b"hello")],
            form_fields={"process_knowledge": "false"},
        )
        with patch(
            "aragora.documents.ingestion.batch_processor.JobPriority",
        ) as MockJP:
            MockJP.NORMAL = "normal"
            with patch(
                "aragora.documents.chunking.token_counter.get_token_counter",
                return_value=MockTokenCounter(),
            ):
                result = await handler_with_processor.handle_post(
                    "/api/v1/documents/batch", {}, http
                )
        assert _status(result) == 202
        body = _body(result)
        assert "knowledge_processing" not in body

    @pytest.mark.asyncio
    async def test_upload_multiple_files(self, handler_with_processor, processor):
        """Multiple files should each get a job ID."""
        http = _make_multipart_handler(
            files=[
                ("file1.txt", b"content one"),
                ("file2.txt", b"content two"),
                ("file3.txt", b"content three"),
            ],
        )
        with patch(
            "aragora.documents.ingestion.batch_processor.JobPriority",
        ) as MockJP:
            MockJP.NORMAL = "normal"
            with patch(
                "aragora.documents.chunking.token_counter.get_token_counter",
                return_value=MockTokenCounter(),
            ):
                result = await handler_with_processor.handle_post(
                    "/api/v1/documents/batch", {}, http
                )
        assert _status(result) == 202
        body = _body(result)
        assert body["total_files"] == 3
        assert len(body["job_ids"]) == 3

    @pytest.mark.asyncio
    async def test_upload_invalid_tags_json(self, handler_with_processor, processor):
        """Invalid tags JSON should default to empty list (not error)."""
        http = _make_multipart_handler(
            files=[("test.txt", b"hello")],
            form_fields={"tags": "not-valid-json"},
        )
        with patch(
            "aragora.documents.ingestion.batch_processor.JobPriority",
        ) as MockJP:
            MockJP.NORMAL = "normal"
            with patch(
                "aragora.documents.chunking.token_counter.get_token_counter",
                return_value=MockTokenCounter(),
            ):
                result = await handler_with_processor.handle_post(
                    "/api/v1/documents/batch", {}, http
                )
        assert _status(result) == 202

    @pytest.mark.asyncio
    async def test_upload_default_priority(self, handler_with_processor, processor):
        """Default priority should be 'normal'."""
        http = _make_multipart_handler(files=[("test.txt", b"hello")])
        with patch(
            "aragora.documents.ingestion.batch_processor.JobPriority",
        ) as MockJP:
            MockJP.LOW = "low"
            MockJP.NORMAL = "normal"
            MockJP.HIGH = "high"
            MockJP.URGENT = "urgent"
            with patch(
                "aragora.documents.chunking.token_counter.get_token_counter",
                return_value=MockTokenCounter(),
            ):
                result = await handler_with_processor.handle_post(
                    "/api/v1/documents/batch", {}, http
                )
        assert _status(result) == 202
        # Verify the processor was called with NORMAL priority
        assert len(processor._submitted) == 1
        assert processor._submitted[0]["priority"] == "normal"

    @pytest.mark.asyncio
    async def test_upload_batch_id_format(self, handler_with_processor, processor):
        """Batch ID in response should start with 'batch-'."""
        http = _make_multipart_handler(files=[("test.txt", b"hello")])
        with patch(
            "aragora.documents.ingestion.batch_processor.JobPriority",
        ) as MockJP:
            MockJP.NORMAL = "normal"
            with patch(
                "aragora.documents.chunking.token_counter.get_token_counter",
                return_value=MockTokenCounter(),
            ):
                result = await handler_with_processor.handle_post(
                    "/api/v1/documents/batch", {}, http
                )
        body = _body(result)
        assert body["batch_id"].startswith("batch-")

    @pytest.mark.asyncio
    async def test_upload_estimated_chunks(self, handler_with_processor, processor):
        """Response should contain estimated_chunks based on token count."""
        http = _make_multipart_handler(
            files=[("test.txt", b"word " * 1024)],
        )
        with patch(
            "aragora.documents.ingestion.batch_processor.JobPriority",
        ) as MockJP:
            MockJP.NORMAL = "normal"
            with patch(
                "aragora.documents.chunking.token_counter.get_token_counter",
                return_value=MockTokenCounter(),
            ):
                result = await handler_with_processor.handle_post(
                    "/api/v1/documents/batch", {}, http
                )
        body = _body(result)
        assert "estimated_chunks" in body
        assert body["estimated_chunks"] >= 1

    @pytest.mark.asyncio
    async def test_upload_total_size_bytes(self, handler_with_processor, processor):
        """Response should report total_size_bytes."""
        content = b"hello world"
        http = _make_multipart_handler(files=[("test.txt", content)])
        with patch(
            "aragora.documents.ingestion.batch_processor.JobPriority",
        ) as MockJP:
            MockJP.NORMAL = "normal"
            with patch(
                "aragora.documents.chunking.token_counter.get_token_counter",
                return_value=MockTokenCounter(),
            ):
                result = await handler_with_processor.handle_post(
                    "/api/v1/documents/batch", {}, http
                )
        body = _body(result)
        assert body["total_size_bytes"] == len(content)


# ===========================================================================
# _parse_multipart tests
# ===========================================================================


class TestParseMultipart:
    """Tests for the multipart form data parser."""

    def test_parse_single_file(self, handler):
        body = _build_multipart_body(
            [("test.txt", b"file content")],
            boundary="testboundary",
        )
        files, form_data = handler._parse_multipart(body, "testboundary")
        assert len(files) == 1
        assert files[0][0] == "test.txt"
        assert files[0][1] == b"file content"

    def test_parse_multiple_files(self, handler):
        body = _build_multipart_body(
            [("a.txt", b"aaa"), ("b.txt", b"bbb")],
            boundary="testboundary",
        )
        files, form_data = handler._parse_multipart(body, "testboundary")
        assert len(files) == 2

    def test_parse_form_fields(self, handler):
        body = _build_multipart_body(
            [],
            form_fields={"workspace_id": "ws-001", "priority": "high"},
            boundary="testboundary",
        )
        files, form_data = handler._parse_multipart(body, "testboundary")
        assert len(files) == 0
        assert form_data["workspace_id"] == "ws-001"
        assert form_data["priority"] == "high"

    def test_parse_mixed_files_and_fields(self, handler):
        body = _build_multipart_body(
            [("doc.pdf", b"pdf-content")],
            form_fields={"workspace_id": "ws-002"},
            boundary="testboundary",
        )
        files, form_data = handler._parse_multipart(body, "testboundary")
        assert len(files) == 1
        assert form_data["workspace_id"] == "ws-002"

    def test_parse_empty_body(self, handler):
        body = b"--testboundary--\r\n"
        files, form_data = handler._parse_multipart(body, "testboundary")
        assert len(files) == 0
        assert len(form_data) == 0

    def test_parse_malformed_part_skipped(self, handler):
        """Part without Content-Disposition should be skipped."""
        body = (
            b"--testboundary\r\n"
            b"Content-Type: text/plain\r\n\r\n"
            b"orphan content\r\n"
            b"--testboundary--\r\n"
        )
        files, form_data = handler._parse_multipart(body, "testboundary")
        assert len(files) == 0
        assert len(form_data) == 0

    def test_parse_no_header_separator(self, handler):
        """Part without \\r\\n\\r\\n separator should be skipped."""
        body = b"--testboundary\r\nno separator here\r\n--testboundary--\r\n"
        files, form_data = handler._parse_multipart(body, "testboundary")
        assert len(files) == 0

    def test_parse_binary_content(self, handler):
        """Binary file content should be preserved."""
        binary = bytes(range(256))
        body = _build_multipart_body([("binary.bin", binary)])
        files, form_data = handler._parse_multipart(body, "testboundary")
        assert len(files) == 1
        assert files[0][0] == "binary.bin"
        # Content may have trailing \r\n stripped by the parser
        assert binary in files[0][1] or files[0][1].startswith(binary[:200])


# ===========================================================================
# _generate_batch_id tests
# ===========================================================================


class TestGenerateBatchId:
    """Tests for batch ID generation."""

    def test_format(self, handler):
        batch_id = handler._generate_batch_id()
        assert batch_id.startswith("batch-")
        assert len(batch_id) == 18  # "batch-" (6) + 12 hex chars

    def test_uniqueness(self, handler):
        ids = {handler._generate_batch_id() for _ in range(100)}
        assert len(ids) == 100

    def test_hex_chars_only(self, handler):
        batch_id = handler._generate_batch_id()
        hex_part = batch_id[6:]
        assert all(c in "0123456789abcdef" for c in hex_part)


# ===========================================================================
# Constructor tests
# ===========================================================================


class TestConstructor:
    """Tests for handler initialization."""

    def test_server_context_kwarg(self):
        h = DocumentBatchHandler(server_context={"key": "value"})
        assert h.ctx == {"key": "value"}

    def test_ctx_kwarg(self):
        h = DocumentBatchHandler(ctx={"key": "value"})
        assert h.ctx == {"key": "value"}

    def test_no_args(self):
        h = DocumentBatchHandler()
        assert h.ctx == {}

    def test_server_context_takes_priority(self):
        h = DocumentBatchHandler(ctx={"old": 1}, server_context={"new": 2})
        assert h.ctx == {"new": 2}


# ===========================================================================
# _get_batch_processor tests
# ===========================================================================


class TestGetBatchProcessor:
    """Tests for batch processor retrieval and creation."""

    def test_returns_existing_processor(self, handler_with_processor, processor):
        result = handler_with_processor._get_batch_processor()
        assert result is processor

    def test_creates_processor_when_missing(self):
        handler = DocumentBatchHandler(server_context={})
        with patch(
            "aragora.documents.ingestion.batch_processor.BatchProcessor",
        ) as MockBP:
            mock_proc = MagicMock()
            MockBP.return_value = mock_proc
            result = handler._get_batch_processor()
        assert result is mock_proc
        assert handler.ctx["batch_processor"] is mock_proc

    def test_caches_created_processor(self):
        handler = DocumentBatchHandler(server_context={})
        with patch(
            "aragora.documents.ingestion.batch_processor.BatchProcessor",
        ) as MockBP:
            mock_proc = MagicMock()
            MockBP.return_value = mock_proc
            first = handler._get_batch_processor()
            second = handler._get_batch_processor()
        assert first is second
        # BatchProcessor() called only once
        assert MockBP.call_count == 1


# ===========================================================================
# handle() routing tests (unmatched paths)
# ===========================================================================


class TestHandleRouting:
    """Tests for the handle() method route dispatching."""

    @pytest.mark.asyncio
    async def test_unmatched_path_returns_none(self, handler, mock_http):
        result = await handler.handle("/api/v1/unrelated", {}, mock_http)
        assert result is None

    @pytest.mark.asyncio
    async def test_processing_stats_exact_match(self, handler_with_processor, mock_http):
        """Exact path match returns result, not None."""
        result = await handler_with_processor.handle(
            "/api/v1/documents/processing/stats", {}, mock_http
        )
        assert result is not None
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_knowledge_jobs_exact_match(self, handler, mock_http):
        """Exact path match for knowledge jobs."""
        with patch(
            "aragora.knowledge.integration.get_all_jobs",
            return_value=[],
        ):
            result = await handler.handle("/api/v1/knowledge/jobs", {}, mock_http)
        assert result is not None
        assert _status(result) == 200


# ===========================================================================
# ROUTES class attribute
# ===========================================================================


class TestRoutes:
    """Tests for the ROUTES class attribute."""

    def test_routes_list(self):
        expected = [
            "/api/v1/batch",
            "/api/v1/batch/queue/status",
            "/api/v1/documents/batch",
            "/api/v1/documents/processing/stats",
            "/api/v1/knowledge/jobs",
        ]
        assert DocumentBatchHandler.ROUTES == expected

    def test_routes_count(self):
        assert len(DocumentBatchHandler.ROUTES) == 5


# ===========================================================================
# Knowledge processing error paths in _upload_batch
# ===========================================================================


class TestUploadKnowledgeErrors:
    """Tests for error handling in knowledge processing during upload."""

    @pytest.mark.asyncio
    async def test_knowledge_runtime_error(self, handler_with_processor, processor):
        """RuntimeError in knowledge queue should not fail the upload."""
        http = _make_multipart_handler(
            files=[("test.txt", b"hello")],
            form_fields={"process_knowledge": "true"},
        )
        with patch(
            "aragora.documents.ingestion.batch_processor.JobPriority",
        ) as MockJP:
            MockJP.NORMAL = "normal"
            with patch(
                "aragora.documents.chunking.token_counter.get_token_counter",
                return_value=MockTokenCounter(),
            ):
                with patch(
                    "aragora.knowledge.integration.queue_document_processing",
                    side_effect=RuntimeError("queue full"),
                ):
                    result = await handler_with_processor.handle_post(
                        "/api/v1/documents/batch", {}, http
                    )
        assert _status(result) == 202
        body = _body(result)
        # Knowledge processing attempted but failed - shows unavailable
        assert body["knowledge_processing"]["enabled"] is True
        assert body["knowledge_processing"]["status"] == "unavailable"

    @pytest.mark.asyncio
    async def test_knowledge_value_error(self, handler_with_processor, processor):
        """ValueError in knowledge queue should not fail the upload."""
        http = _make_multipart_handler(
            files=[("test.txt", b"hello")],
            form_fields={"process_knowledge": "true"},
        )
        with patch(
            "aragora.documents.ingestion.batch_processor.JobPriority",
        ) as MockJP:
            MockJP.NORMAL = "normal"
            with patch(
                "aragora.documents.chunking.token_counter.get_token_counter",
                return_value=MockTokenCounter(),
            ):
                with patch(
                    "aragora.knowledge.integration.queue_document_processing",
                    side_effect=ValueError("bad value"),
                ):
                    result = await handler_with_processor.handle_post(
                        "/api/v1/documents/batch", {}, http
                    )
        assert _status(result) == 202
        body = _body(result)
        assert body["knowledge_processing"]["enabled"] is True
        assert body["knowledge_processing"]["status"] == "unavailable"


# ===========================================================================
# Edge cases
# ===========================================================================


class TestEdgeCases:
    """Miscellaneous edge case tests."""

    @pytest.mark.asyncio
    async def test_handle_post_non_batch_path(self, handler_with_processor):
        """handle_post on non-batch path should return None."""
        http = _make_multipart_handler()
        result = await handler_with_processor.handle_post("/api/v1/other", {}, http)
        assert result is None

    def test_max_batch_size_constant(self):
        assert MAX_BATCH_SIZE == 50

    def test_max_file_size_mb_constant(self):
        assert MAX_FILE_SIZE_MB == 100

    def test_max_total_batch_size_mb_constant(self):
        assert MAX_TOTAL_BATCH_SIZE_MB == 500

    @pytest.mark.asyncio
    async def test_upload_boundary_with_quotes(self, handler_with_processor, processor):
        """Boundary value wrapped in quotes should be parsed correctly."""
        files = [("test.txt", b"content")]
        body_data = _build_multipart_body(files, boundary="myboundary")
        http = MockHTTPHandler(
            headers={
                "Content-Type": 'multipart/form-data; boundary="myboundary"',
                "Content-Length": str(len(body_data)),
            },
            client_address=("127.0.0.1", 12345),
            _rfile_data=body_data,
        )
        with patch(
            "aragora.documents.ingestion.batch_processor.JobPriority",
        ) as MockJP:
            MockJP.NORMAL = "normal"
            with patch(
                "aragora.documents.chunking.token_counter.get_token_counter",
                return_value=MockTokenCounter(),
            ):
                result = await handler_with_processor.handle_post(
                    "/api/v1/documents/batch", {}, http
                )
        assert _status(result) == 202

    @pytest.mark.asyncio
    async def test_upload_default_workspace(self, handler_with_processor, processor):
        """Default workspace_id should be 'default' when not provided."""
        http = _make_multipart_handler(files=[("test.txt", b"hello")])
        with patch(
            "aragora.documents.ingestion.batch_processor.JobPriority",
        ) as MockJP:
            MockJP.NORMAL = "normal"
            with patch(
                "aragora.documents.chunking.token_counter.get_token_counter",
                return_value=MockTokenCounter(),
            ):
                result = await handler_with_processor.handle_post(
                    "/api/v1/documents/batch", {}, http
                )
        assert _status(result) == 202
        assert processor._submitted[0]["workspace_id"] == "default"

    @pytest.mark.asyncio
    async def test_upload_custom_workspace(self, handler_with_processor, processor):
        """Custom workspace_id should be passed through."""
        http = _make_multipart_handler(
            files=[("test.txt", b"hello")],
            form_fields={"workspace_id": "my-workspace"},
        )
        with patch(
            "aragora.documents.ingestion.batch_processor.JobPriority",
        ) as MockJP:
            MockJP.NORMAL = "normal"
            with patch(
                "aragora.documents.chunking.token_counter.get_token_counter",
                return_value=MockTokenCounter(),
            ):
                result = await handler_with_processor.handle_post(
                    "/api/v1/documents/batch", {}, http
                )
        assert _status(result) == 202
        assert processor._submitted[0]["workspace_id"] == "my-workspace"

    @pytest.mark.asyncio
    async def test_upload_unknown_priority_defaults_to_normal(
        self, handler_with_processor, processor
    ):
        """Unknown priority string should default to NORMAL."""
        http = _make_multipart_handler(
            files=[("test.txt", b"hello")],
            form_fields={"priority": "ultra-mega"},
        )
        with patch(
            "aragora.documents.ingestion.batch_processor.JobPriority",
        ) as MockJP:
            MockJP.LOW = "low"
            MockJP.NORMAL = "normal"
            MockJP.HIGH = "high"
            MockJP.URGENT = "urgent"
            with patch(
                "aragora.documents.chunking.token_counter.get_token_counter",
                return_value=MockTokenCounter(),
            ):
                result = await handler_with_processor.handle_post(
                    "/api/v1/documents/batch", {}, http
                )
        assert _status(result) == 202
        assert processor._submitted[0]["priority"] == "normal"

    @pytest.mark.asyncio
    async def test_handle_delete_non_matching_path(self, handler_with_processor, mock_http):
        """Delete on path that doesn't start with batch prefix returns None."""
        result = await handler_with_processor.handle_delete("/api/v1/something/else", {}, mock_http)
        assert result is None


# ===========================================================================
# Org scope
# ===========================================================================


class TestOrgScope:
    """Every route is scoped to the caller's org."""

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_anonymous_caller_gets_401(self, handler_with_processor, mock_http, monkeypatch):
        from aragora.server import auth as server_auth

        monkeypatch.setattr(server_auth.auth_config, "enabled", False)
        monkeypatch.setattr(server_auth.auth_config, "api_token", None)
        monkeypatch.setattr(
            "aragora.billing.jwt_auth.extract_user_from_request",
            lambda handler, user_store=None: None,
        )
        result = await handler_with_processor.handle(
            "/api/v1/documents/processing/stats", {}, mock_http
        )
        assert _status(result) == 401
        assert _body(result) == {"error": "Authentication required", "code": "auth_required"}

    @pytest.mark.asyncio
    async def test_unrecognized_path_skips_scope_check(self, handler, mock_http, monkeypatch):
        def _fail(*_a, **_kw):
            raise AssertionError("scope check must not run for unrecognized paths")

        monkeypatch.setattr("aragora.billing.jwt_auth.extract_user_from_request", _fail)
        assert await handler.handle("/api/v1/unrelated", {}, mock_http) is None

    @pytest.mark.asyncio
    async def test_other_org_job_status_is_404(self, handler_with_processor, processor, mock_http):
        processor._statuses["job-x"] = {"status": "completed", "org_id": "other-org"}
        result = await handler_with_processor.handle("/api/v1/documents/batch/job-x", {}, mock_http)
        assert _status(result) == 404
        assert _body(result) == NOT_FOUND

    @pytest.mark.asyncio
    async def test_unknown_owner_job_status_is_404(self, handler_with_processor, processor):
        processor._statuses["job-x"] = {"status": "completed"}
        result = await handler_with_processor._get_job_status("job-x", SCOPE)
        assert _status(result) == 404
        assert _body(result) == NOT_FOUND

    @pytest.mark.asyncio
    async def test_other_org_job_results_is_404(self, handler_with_processor, processor, mock_http):
        processor._results["job-x"] = MockJob(id="job-x", org_id="other-org")
        result = await handler_with_processor.handle(
            "/api/v1/documents/batch/job-x/results", {}, mock_http
        )
        assert _status(result) == 404
        assert _body(result) == NOT_FOUND

    @pytest.mark.asyncio
    async def test_other_org_job_delete_is_404_without_side_effects(
        self, handler_with_processor, processor, mock_http
    ):
        processor._results["job-x"] = MockJob(id="job-x", org_id="other-org")
        processor._removable.add("job-x")
        processor.cancel = AsyncMock(return_value=True)
        processor.remove = AsyncMock(return_value=True)
        result = await handler_with_processor.handle_delete(
            "/api/v1/documents/batch/job-x", {}, mock_http
        )
        assert _status(result) == 404
        assert _body(result) == NOT_FOUND
        processor.cancel.assert_not_called()
        processor.remove.assert_not_called()

    @pytest.mark.asyncio
    async def test_other_org_document_chunks_is_404(self, mock_http):
        store = MagicMock()
        store.get.return_value = MockDocument(org_id="other-org")
        h = DocumentBatchHandler(server_context={"document_store": store})
        result = await h.handle("/api/v1/documents/doc-001/chunks", {}, mock_http)
        assert _status(result) == 404
        assert _body(result) == {"error": "Document not found", "code": "not_found"}

    @pytest.mark.asyncio
    async def test_other_org_document_context_is_404(self, mock_http):
        store = MagicMock()
        store.get.return_value = MockDocument(org_id="other-org")
        h = DocumentBatchHandler(server_context={"document_store": store})
        result = await h.handle("/api/v1/documents/doc-001/context", {}, mock_http)
        assert _status(result) == 404
        assert _body(result) == {"error": "Document not found", "code": "not_found"}

    @pytest.mark.asyncio
    async def test_stats_requested_for_caller_org(
        self, handler_with_processor, processor, mock_http
    ):
        result = await handler_with_processor.handle(
            "/api/v1/documents/processing/stats", {}, mock_http
        )
        assert _status(result) == 200
        assert processor.stats_calls == [{"org_id": TEST_ORG}]

    @pytest.mark.asyncio
    async def test_knowledge_job_list_passes_org(self, handler, mock_http):
        with patch("aragora.knowledge.integration.get_all_jobs", return_value=[]) as mock_get:
            result = await handler.handle("/api/v1/knowledge/jobs", {}, mock_http)
        assert _status(result) == 200
        mock_get.assert_called_once_with(workspace_id=None, status=None, limit=100, org_id=TEST_ORG)

    @pytest.mark.asyncio
    async def test_other_org_knowledge_job_is_404(self, handler, mock_http):
        with patch(
            "aragora.knowledge.integration.get_job_status",
            return_value={"id": "kj-x", "status": "completed", "metadata": {"org_id": "other-org"}},
        ):
            result = await handler.handle("/api/v1/knowledge/jobs/kj-x", {}, mock_http)
        assert _status(result) == 404
        assert _body(result) == {"error": "Knowledge job not found", "code": "not_found"}

    @pytest.mark.asyncio
    async def test_unknown_owner_knowledge_job_is_404(self, handler):
        with patch(
            "aragora.knowledge.integration.get_job_status",
            return_value={"id": "kj-x", "status": "completed"},
        ):
            result = handler._get_knowledge_job_status("kj-x", SCOPE)
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_upload_records_org_and_uploader(self, handler_with_processor, processor):
        http = _make_multipart_handler(
            files=[("test.txt", b"hello")],
            form_fields={"process_knowledge": "true"},
        )
        with (
            patch("aragora.documents.ingestion.batch_processor.JobPriority") as MockJP,
            patch(
                "aragora.documents.chunking.token_counter.get_token_counter",
                return_value=MockTokenCounter(),
            ),
            patch(
                "aragora.knowledge.integration.queue_document_processing",
                return_value="kp-001",
            ) as mock_queue,
        ):
            MockJP.NORMAL = "normal"
            result = await handler_with_processor.handle_post("/api/v1/documents/batch", {}, http)
        assert _status(result) == 202
        submitted = processor._submitted[0]
        assert submitted["org_id"] == TEST_ORG
        assert submitted["uploaded_by"] == TEST_USER
        assert submitted["document_id"] is None
        metadata = mock_queue.call_args.kwargs["metadata"]
        assert metadata["org_id"] == TEST_ORG
        assert metadata["user_id"] == TEST_USER
        assert metadata["owner_id"] == TEST_USER

    @pytest.mark.asyncio
    async def test_upload_saves_documents_under_caller_org(self, processor):
        store = MagicMock()
        store.add.return_value = "doc-saved"
        h = DocumentBatchHandler(
            server_context={"batch_processor": processor, "document_store": store}
        )
        http = _make_multipart_handler(
            files=[("test.txt", b"hello")],
            form_fields={"process_knowledge": "false"},
        )
        parsed = MockDocument()
        with (
            patch("aragora.documents.ingestion.batch_processor.JobPriority") as MockJP,
            patch(
                "aragora.documents.chunking.token_counter.get_token_counter",
                return_value=MockTokenCounter(),
            ),
            patch("aragora.documents.parsing.parse_document", return_value=parsed) as mock_parse,
        ):
            MockJP.NORMAL = "normal"
            result = await h.handle_post("/api/v1/documents/batch", {}, http)
        assert _status(result) == 202
        mock_parse.assert_called_once_with(
            b"hello", "test.txt", org_id=TEST_ORG, created_by=TEST_USER
        )
        store.add.assert_called_once_with(parsed)
        assert processor._submitted[0]["document_id"] == "doc-saved"
