"""Tests for DocumentBatchHandler.

Tests cover routing, can_handle, batch upload, job status, job results,
job cancellation, document chunks, document context, processing stats,
and knowledge job endpoints.
"""

import sys
import types as _types_mod

# Pre-stub Slack modules to prevent import chain failures
_SLACK_ATTRS = [
    "SlackHandler",
    "get_slack_handler",
    "get_slack_integration",
    "get_workspace_store",
    "resolve_workspace",
    "create_tracked_task",
    "_validate_slack_url",
    "SLACK_SIGNING_SECRET",
    "SLACK_BOT_TOKEN",
    "SLACK_WEBHOOK_URL",
    "SLACK_ALLOWED_DOMAINS",
    "SignatureVerifierMixin",
    "CommandsMixin",
    "EventsMixin",
    "init_slack_handler",
]
for _mod_name in (
    "aragora.server.handlers.social.slack.handler",
    "aragora.server.handlers.social.slack",
    "aragora.server.handlers.social._slack_impl",
):
    if _mod_name not in sys.modules:
        _m = _types_mod.ModuleType(_mod_name)
        for _a in _SLACK_ATTRS:
            setattr(_m, _a, None)
        sys.modules[_mod_name] = _m

import json
from dataclasses import dataclass, field
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.features.documents_batch import (
    DocumentBatchHandler,
    MAX_BATCH_SIZE,
    MAX_FILE_SIZE_MB,
    MAX_TOTAL_BATCH_SIZE_MB,
)
from aragora.tenancy.record_scope import OrgScope

ORG = "test-org-001"
SCOPE = OrgScope(org_id=ORG, user_id="test-user-001", role="member")
OTHER_SCOPE = OrgScope(org_id="other-org", user_id="other-user", role="member")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class MockJob:
    """Mock DocumentJob for testing."""

    id: str = "job-123"
    status: MagicMock = field(default_factory=lambda: MagicMock(value="completed"))
    progress: float = 1.0
    filename: str = "test.pdf"
    document: MagicMock = None
    chunks: list = field(default_factory=list)
    error_message: str = ""
    org_id: str | None = ORG

    def __post_init__(self):
        if self.document is None:
            self.document = MagicMock()
            self.document.to_summary.return_value = {"id": "doc-1", "filename": "test.pdf"}


class MockBatchProcessor:
    """Mock BatchProcessor for testing."""

    def __init__(self):
        self.jobs = {}
        self.cancelled = set()

    async def submit(
        self,
        content: bytes,
        filename: str,
        workspace_id: str,
        priority=None,
        chunking_strategy=None,
        chunk_size=512,
        chunk_overlap=50,
        tags=None,
        uploaded_by=None,
        org_id=None,
        document_id=None,
    ) -> str:
        job_id = f"job-{len(self.jobs)}"
        self.jobs[job_id] = {
            "content": content,
            "filename": filename,
            "workspace_id": workspace_id,
            "status": "queued",
            "org_id": org_id,
            "uploaded_by": uploaded_by,
        }
        return job_id

    def _org(self, job_id: str) -> str | None:
        return self.jobs[job_id].get("org_id", ORG)

    async def get_status(self, job_id: str) -> dict | None:
        if job_id not in self.jobs:
            return None
        return {
            "job_id": job_id,
            "status": self.jobs[job_id]["status"],
            "progress": 0.5,
            "org_id": self._org(job_id),
        }

    async def get_result(self, job_id: str):
        if job_id not in self.jobs:
            return None
        return MockJob(id=job_id, org_id=self._org(job_id))

    async def cancel(self, job_id: str) -> bool:
        if job_id not in self.jobs:
            return False
        if self.jobs[job_id]["status"] == "processing":
            return False
        self.cancelled.add(job_id)
        return True

    async def remove(self, job_id: str) -> bool:
        return False

    def get_stats(self, org_id: str | None = None) -> dict:
        jobs = [j for j in self.jobs.values() if org_id is None or j.get("org_id", ORG) == org_id]
        return {
            "total_jobs": len(jobs),
            "queued": len([j for j in jobs if j["status"] == "queued"]),
            "completed": 0,
            "failed": 0,
        }


class MockTokenCounter:
    """Mock token counter for testing."""

    def count(self, text: str, model: str = "gpt-4") -> int:
        return len(text.split())

    def truncate_to_tokens(self, text: str, max_tokens: int, model: str = "gpt-4") -> str:
        words = text.split()
        return " ".join(words[:max_tokens])


def create_multipart_body(
    files: list[tuple[str, bytes]], form_data: dict = None
) -> tuple[bytes, str]:
    """Create multipart/form-data body for testing."""
    boundary = "----TestBoundary1234567890"
    parts = []

    # Add files
    for filename, content in files:
        parts.append(f"------{boundary}\r\n")
        parts.append(f'Content-Disposition: form-data; name="files[]"; filename="{filename}"\r\n')
        parts.append("Content-Type: application/octet-stream\r\n\r\n")
        parts.append(
            content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
        )
        parts.append("\r\n")

    # Add form fields
    if form_data:
        for key, value in form_data.items():
            parts.append(f"------{boundary}\r\n")
            parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n')
            parts.append(str(value))
            parts.append("\r\n")

    parts.append(f"------{boundary}--\r\n")

    body = "".join(parts).encode("utf-8")
    content_type = f"multipart/form-data; boundary=----{boundary}"
    return body, content_type


def make_mock_handler(
    content_type: str = "application/json",
    body: bytes = b"{}",
    content_length: int = None,
):
    """Create a mock HTTP handler."""
    mock = MagicMock()
    mock.headers = {
        "Content-Type": content_type,
        "Content-Length": str(content_length if content_length is not None else len(body)),
    }
    mock.rfile = BytesIO(body)
    mock.client_address = ("127.0.0.1", 12345)
    return mock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler():
    """Create a DocumentBatchHandler instance."""
    return DocumentBatchHandler({})


@pytest.fixture
def mock_processor():
    """Create a mock batch processor."""
    return MockBatchProcessor()


# Bypass RBAC decorator for testing
@pytest.fixture(autouse=True)
def bypass_rbac():
    """Bypass RBAC decorator for testing."""

    def passthrough_decorator(*args, **kwargs):
        """Return identity decorator that preserves __wrapped__."""
        import functools

        def identity(func):
            @functools.wraps(func)
            def wrapper(*a, **kw):
                return func(*a, **kw)

            return wrapper

        # If used as @require_permission("permission"), return identity
        if args and callable(args[0]):

            @functools.wraps(args[0])
            def passthrough(*a, **kw):
                return args[0](*a, **kw)

            return passthrough
        return identity

    with patch("aragora.rbac.decorators.require_permission", passthrough_decorator):
        yield


# ---------------------------------------------------------------------------
# Constants Tests
# ---------------------------------------------------------------------------


class TestDocumentBatchConstants:
    """Tests for module constants."""

    def test_max_batch_size(self):
        """Test max batch size constant."""
        assert MAX_BATCH_SIZE == 50

    def test_max_file_size(self):
        """Test max file size constant."""
        assert MAX_FILE_SIZE_MB == 100

    def test_max_total_batch_size(self):
        """Test max total batch size constant."""
        assert MAX_TOTAL_BATCH_SIZE_MB == 500


# ---------------------------------------------------------------------------
# Handler Routes Tests
# ---------------------------------------------------------------------------


class TestDocumentBatchHandlerRoutes:
    """Tests for handler route definitions."""

    def test_routes_defined(self):
        """Test that ROUTES are defined."""
        assert hasattr(DocumentBatchHandler, "ROUTES")
        assert isinstance(DocumentBatchHandler.ROUTES, list)

    def test_batch_route_in_routes(self):
        """Test batch endpoint is in routes."""
        assert "/api/v1/documents/batch" in DocumentBatchHandler.ROUTES

    def test_processing_stats_route_in_routes(self):
        """Test processing stats endpoint is in routes."""
        assert "/api/v1/documents/processing/stats" in DocumentBatchHandler.ROUTES

    def test_knowledge_jobs_route_in_routes(self):
        """Test knowledge jobs endpoint is in routes."""
        assert "/api/v1/knowledge/jobs" in DocumentBatchHandler.ROUTES


# ---------------------------------------------------------------------------
# can_handle Tests
# ---------------------------------------------------------------------------


class TestCanHandle:
    """Tests for can_handle method."""

    def test_can_handle_batch_route(self, handler):
        """Test can_handle for batch upload route."""
        assert handler.can_handle("/api/v1/documents/batch") is True

    def test_can_handle_processing_stats(self, handler):
        """Test can_handle for processing stats route."""
        assert handler.can_handle("/api/v1/documents/processing/stats") is True

    def test_can_handle_knowledge_jobs(self, handler):
        """Test can_handle for knowledge jobs route."""
        assert handler.can_handle("/api/v1/knowledge/jobs") is True

    def test_can_handle_batch_job_id(self, handler):
        """Test can_handle for batch job status route."""
        assert handler.can_handle("/api/v1/documents/batch/job123") is True

    def test_can_handle_batch_job_results(self, handler):
        """Test can_handle for batch job results route."""
        assert handler.can_handle("/api/v1/documents/batch/job123/results") is True

    def test_can_handle_knowledge_job_id(self, handler):
        """Test can_handle for knowledge job status route."""
        assert handler.can_handle("/api/v1/knowledge/jobs/kp_123") is True

    def test_cannot_handle_invalid_route(self, handler):
        """Test can_handle rejects invalid routes."""
        assert handler.can_handle("/api/v1/invalid/route") is False

    def test_cannot_handle_partial_batch_route(self, handler):
        """Test can_handle rejects partial routes."""
        assert handler.can_handle("/api/v1/documents") is False

    def test_cannot_handle_wrong_prefix(self, handler):
        """Test can_handle rejects wrong prefix."""
        assert handler.can_handle("/api/v2/documents/batch") is False


# ---------------------------------------------------------------------------
# GET Processing Stats Tests
# ---------------------------------------------------------------------------


class TestProcessingStats:
    """Tests for processing stats endpoint."""

    def test_get_processing_stats(self, handler, mock_processor):
        """Test getting processing stats."""
        with patch.object(handler, "_get_batch_processor", return_value=mock_processor):
            result = handler._get_processing_stats(SCOPE)

        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        assert "processor" in body
        assert "limits" in body
        assert body["limits"]["max_batch_size"] == MAX_BATCH_SIZE

    def test_processing_stats_includes_limits(self, handler, mock_processor):
        """Test that processing stats include limits."""
        with patch.object(handler, "_get_batch_processor", return_value=mock_processor):
            result = handler._get_processing_stats(SCOPE)

        body = json.loads(result.body)
        assert body["limits"]["max_file_size_mb"] == MAX_FILE_SIZE_MB
        assert body["limits"]["max_total_batch_size_mb"] == MAX_TOTAL_BATCH_SIZE_MB


# ---------------------------------------------------------------------------
# GET Job Status Tests
# ---------------------------------------------------------------------------


class TestGetJobStatus:
    """Tests for job status endpoint."""

    @pytest.mark.asyncio
    async def test_get_job_status_success(self, handler, mock_processor):
        """Test getting job status for existing job."""
        mock_processor.jobs["job-123"] = {"status": "processing"}

        with patch.object(handler, "_get_batch_processor", return_value=mock_processor):
            result = await handler._get_job_status("job-123", SCOPE)

        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["job_id"] == "job-123"

    @pytest.mark.asyncio
    async def test_get_job_status_not_found(self, handler, mock_processor):
        """Test getting status for non-existent job."""
        with patch.object(handler, "_get_batch_processor", return_value=mock_processor):
            result = await handler._get_job_status("nonexistent", SCOPE)

        assert result is not None
        assert result.status_code == 404
        body = json.loads(result.body)
        assert "error" in body


# ---------------------------------------------------------------------------
# GET Job Results Tests
# ---------------------------------------------------------------------------


class TestGetJobResults:
    """Tests for job results endpoint."""

    @pytest.mark.asyncio
    async def test_get_job_results_completed(self, handler, mock_processor):
        """Test getting results for completed job."""
        mock_processor.jobs["job-123"] = {"status": "completed"}

        with patch.object(handler, "_get_batch_processor", return_value=mock_processor):
            result = await handler._get_job_results("job-123", SCOPE)

        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["job_id"] == "job-123"
        assert body["status"] == "completed"

    @pytest.mark.asyncio
    async def test_get_job_results_not_found(self, handler, mock_processor):
        """Test getting results for non-existent job."""
        with patch.object(handler, "_get_batch_processor", return_value=mock_processor):
            result = await handler._get_job_results("nonexistent", SCOPE)

        assert result is not None
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_get_job_results_in_progress(self, handler):
        """Test getting results for job still in progress."""
        mock_job = MockJob()
        mock_job.status = MagicMock(value="processing")

        mock_processor = MagicMock()
        mock_processor.get_result = AsyncMock(return_value=mock_job)

        with patch.object(handler, "_get_batch_processor", return_value=mock_processor):
            result = await handler._get_job_results("job-123", SCOPE)

        assert result is not None
        assert result.status_code == 202
        body = json.loads(result.body)
        assert body["status"] == "processing"
        assert "message" in body


# ---------------------------------------------------------------------------
# DELETE Cancel Job Tests
# ---------------------------------------------------------------------------


class TestCancelJob:
    """Tests for job cancellation endpoint."""

    @pytest.mark.asyncio
    async def test_cancel_job_success(self, handler, mock_processor):
        """Test successful job cancellation."""
        mock_processor.jobs["job-123"] = {"status": "queued"}

        with patch.object(handler, "_get_batch_processor", return_value=mock_processor):
            result = await handler._cancel_job("job-123", SCOPE)

        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["cancelled"] is True
        assert body["job_id"] == "job-123"

    @pytest.mark.asyncio
    async def test_cancel_job_not_found(self, handler, mock_processor):
        """Test cancelling a non-existent job."""
        with patch.object(handler, "_get_batch_processor", return_value=mock_processor):
            result = await handler._cancel_job("nonexistent", SCOPE)

        assert result is not None
        assert result.status_code == 404
        assert json.loads(result.body) == {"error": "Job not found", "code": "not_found"}

    @pytest.mark.asyncio
    async def test_cancel_job_processing(self, handler, mock_processor):
        """Test cancelling a job that is already processing."""
        mock_processor.jobs["job-123"] = {"status": "processing"}

        with patch.object(handler, "_get_batch_processor", return_value=mock_processor):
            result = await handler._cancel_job("job-123", SCOPE)

        assert result is not None
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_cancel_other_org_job_is_not_found(self, handler, mock_processor):
        """Another org's job answers like a missing one and stays queued."""
        mock_processor.jobs["job-123"] = {"status": "queued", "org_id": "other-org"}

        with patch.object(handler, "_get_batch_processor", return_value=mock_processor):
            result = await handler._cancel_job("job-123", SCOPE)

        assert result.status_code == 404
        assert mock_processor.cancelled == set()


# ---------------------------------------------------------------------------
# GET Document Chunks Tests
# ---------------------------------------------------------------------------


class TestDocumentChunks:
    """Tests for document chunks endpoint."""

    @pytest.fixture
    def doc_store(self, handler):
        store = MagicMock()
        store.get.return_value = MagicMock(org_id=ORG)
        handler.ctx = {"document_store": store}
        return store

    def test_get_document_chunks(self, handler, doc_store):
        """Test getting document chunks."""
        result = handler._get_document_chunks("doc123", SCOPE, limit=50, offset=0)

        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["document_id"] == "doc123"
        assert "chunks" in body
        assert body["limit"] == 50
        assert body["offset"] == 0

    def test_get_document_chunks_default_pagination(self, handler, doc_store):
        """Test document chunks with default pagination."""
        result = handler._get_document_chunks("doc123", SCOPE)

        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["limit"] == 100
        assert body["offset"] == 0

    def test_get_document_chunks_other_org_is_not_found(self, handler, doc_store):
        """Another org's document answers like a missing one."""
        result = handler._get_document_chunks("doc123", OTHER_SCOPE)

        assert result.status_code == 404
        assert json.loads(result.body) == {"error": "Document not found", "code": "not_found"}


# ---------------------------------------------------------------------------
# GET Document Context Tests
# ---------------------------------------------------------------------------


class TestDocumentContext:
    """Tests for document context endpoint."""

    def test_get_document_context_not_found(self, handler):
        """Test getting context for non-existent document."""
        handler.ctx = {}  # No document store

        result = handler._get_document_context("doc123", SCOPE)

        assert result is not None
        assert result.status_code == 404

    def test_get_document_context_with_store(self, handler):
        """Test getting context with document store."""
        mock_doc = MagicMock()
        mock_doc.text = "This is a test document with some content."
        mock_doc.org_id = ORG

        mock_store = MagicMock()
        mock_store.get.return_value = mock_doc

        handler.ctx = {"document_store": mock_store}

        mock_counter = MockTokenCounter()

        with patch(
            "aragora.documents.chunking.token_counter.get_token_counter",
            return_value=mock_counter,
        ):
            result = handler._get_document_context("doc123", SCOPE, max_tokens=1000, model="gpt-4")

        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["document_id"] == "doc123"
        assert "context" in body
        assert body["max_tokens"] == 1000
        assert body["model"] == "gpt-4"


# ---------------------------------------------------------------------------
# Knowledge Jobs Tests
# ---------------------------------------------------------------------------


class TestKnowledgeJobs:
    """Tests for knowledge job endpoints."""

    def test_list_knowledge_jobs_unavailable(self, handler):
        """Test listing knowledge jobs when pipeline unavailable."""
        with patch.dict(
            "sys.modules",
            {"aragora.knowledge.integration": None},
        ):
            # Force re-import to trigger ImportError
            result = handler._list_knowledge_jobs(SCOPE)

        assert result is not None
        assert result.status_code == 503

    def test_list_knowledge_jobs_success(self, handler):
        """Test listing knowledge jobs."""
        mock_jobs = [
            {"id": "kp_1", "status": "completed"},
            {"id": "kp_2", "status": "processing"},
        ]

        # Create a mock module
        mock_integration = MagicMock()
        mock_integration.get_all_jobs = MagicMock(return_value=mock_jobs)

        with patch.dict(
            "sys.modules",
            {"aragora.knowledge.integration": mock_integration},
        ):
            result = handler._list_knowledge_jobs(
                SCOPE, workspace_id="ws1", status="completed", limit=50
            )

        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["count"] == 2
        assert len(body["jobs"]) == 2
        mock_integration.get_all_jobs.assert_called_once_with(
            workspace_id="ws1", status="completed", limit=50, org_id=ORG
        )

    def test_get_knowledge_job_status_success(self, handler):
        """Test getting specific knowledge job status."""
        mock_status = {
            "id": "kp_123",
            "status": "completed",
            "progress": 1.0,
            "metadata": {"org_id": ORG},
        }

        # Create a mock module
        mock_integration = MagicMock()
        mock_integration.get_job_status = MagicMock(return_value=mock_status)
        mock_integration.job_org_id = MagicMock(return_value=ORG)

        with patch.dict(
            "sys.modules",
            {"aragora.knowledge.integration": mock_integration},
        ):
            result = handler._get_knowledge_job_status("kp_123", SCOPE)

        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["id"] == "kp_123"

    def test_get_knowledge_job_status_not_found(self, handler):
        """Test getting status for non-existent knowledge job."""
        # Create a mock module
        mock_integration = MagicMock()
        mock_integration.get_job_status = MagicMock(return_value=None)

        with patch.dict(
            "sys.modules",
            {"aragora.knowledge.integration": mock_integration},
        ):
            result = handler._get_knowledge_job_status("nonexistent", SCOPE)

        assert result is not None
        assert result.status_code == 404


# ---------------------------------------------------------------------------
# POST Batch Upload Tests
# ---------------------------------------------------------------------------


class TestBatchUpload:
    """Tests for batch upload endpoint."""

    @pytest.mark.asyncio
    async def test_batch_upload_wrong_content_type(self, handler):
        """Test batch upload rejects non-multipart content type."""
        mock_handler = make_mock_handler(content_type="application/json")

        result = await handler._upload_batch(mock_handler, SCOPE)

        assert result is not None
        assert result.status_code == 400
        body = json.loads(result.body)
        assert "multipart" in body["error"].lower()

    @pytest.mark.asyncio
    async def test_batch_upload_missing_boundary(self, handler):
        """Test batch upload requires multipart boundary."""
        mock_handler = make_mock_handler(content_type="multipart/form-data")

        result = await handler._upload_batch(mock_handler, SCOPE)

        assert result is not None
        assert result.status_code == 400
        body = json.loads(result.body)
        assert "boundary" in body["error"].lower()

    @pytest.mark.asyncio
    async def test_batch_upload_no_files(self, handler, mock_processor):
        """Test batch upload requires files."""
        body, content_type = create_multipart_body([], {"workspace_id": "ws1"})
        mock_handler = make_mock_handler(content_type=content_type, body=body)

        with patch.object(handler, "_get_batch_processor", return_value=mock_processor):
            result = await handler._upload_batch(mock_handler, SCOPE)

        assert result is not None
        assert result.status_code == 400
        body_json = json.loads(result.body)
        assert "files" in body_json["error"].lower() or "no files" in body_json["error"].lower()

    @pytest.mark.asyncio
    async def test_batch_upload_success(self, handler, mock_processor):
        """Test successful batch upload."""
        files = [
            ("test1.txt", b"Test content 1"),
            ("test2.txt", b"Test content 2"),
        ]
        body, content_type = create_multipart_body(files, {"workspace_id": "ws1"})
        mock_handler = make_mock_handler(content_type=content_type, body=body)

        mock_counter = MockTokenCounter()

        with (
            patch.object(handler, "_get_batch_processor", return_value=mock_processor),
            patch(
                "aragora.documents.chunking.token_counter.get_token_counter",
                return_value=mock_counter,
            ),
            patch.dict(
                "sys.modules",
                {"aragora.knowledge.integration": None},
            ),
        ):
            result = await handler._upload_batch(mock_handler, SCOPE)

        assert result is not None
        assert result.status_code == 202
        body_json = json.loads(result.body)
        assert "job_ids" in body_json
        assert len(body_json["job_ids"]) == 2
        assert "batch_id" in body_json
        assert body_json["total_files"] == 2
        for job_id in body_json["job_ids"]:
            assert mock_processor.jobs[job_id]["org_id"] == ORG
            assert mock_processor.jobs[job_id]["uploaded_by"] == "test-user-001"

    @pytest.mark.asyncio
    async def test_batch_upload_with_chunking_options(self, handler, mock_processor):
        """Test batch upload with custom chunking options."""
        files = [("test.txt", b"Test content")]
        form_data = {
            "workspace_id": "ws1",
            "chunking_strategy": "semantic",
            "chunk_size": "256",
            "chunk_overlap": "25",
            "priority": "high",
        }
        body, content_type = create_multipart_body(files, form_data)
        mock_handler = make_mock_handler(content_type=content_type, body=body)

        mock_counter = MockTokenCounter()

        with (
            patch.object(handler, "_get_batch_processor", return_value=mock_processor),
            patch(
                "aragora.documents.chunking.token_counter.get_token_counter",
                return_value=mock_counter,
            ),
            patch.dict(
                "sys.modules",
                {"aragora.knowledge.integration": None},
            ),
        ):
            result = await handler._upload_batch(mock_handler, SCOPE)

        assert result is not None
        assert result.status_code == 202
        body_json = json.loads(result.body)
        assert body_json["chunking_strategy"] == "semantic"
        assert body_json["chunk_size"] == 256
        assert body_json["chunk_overlap"] == 25

    @pytest.mark.asyncio
    async def test_batch_upload_exceeds_total_size_limit(self, handler):
        """Test batch upload rejects oversized batches."""
        # Create a body that exceeds the limit
        content_length = (MAX_TOTAL_BATCH_SIZE_MB + 1) * 1024 * 1024
        mock_handler = make_mock_handler(
            content_type="multipart/form-data; boundary=----TestBoundary",
            body=b"",
            content_length=content_length,
        )

        result = await handler._upload_batch(mock_handler, SCOPE)

        assert result is not None
        assert result.status_code == 413

    @pytest.mark.asyncio
    async def test_batch_upload_too_many_files(self, handler, mock_processor):
        """Test batch upload rejects too many files."""
        files = [(f"test{i}.txt", b"content") for i in range(MAX_BATCH_SIZE + 1)]
        body, content_type = create_multipart_body(files, {})
        mock_handler = make_mock_handler(content_type=content_type, body=body)

        with patch.object(handler, "_get_batch_processor", return_value=mock_processor):
            result = await handler._upload_batch(mock_handler, SCOPE)

        assert result is not None
        assert result.status_code == 400
        body_json = json.loads(result.body)
        assert str(MAX_BATCH_SIZE) in body_json["error"]


# ---------------------------------------------------------------------------
# Multipart Parsing Tests
# ---------------------------------------------------------------------------


class TestMultipartParsing:
    """Tests for multipart form parsing."""

    def test_parse_multipart_single_file(self, handler):
        """Test parsing multipart with single file."""
        body = (
            b"--boundary\r\n"
            b'Content-Disposition: form-data; name="file"; filename="test.txt"\r\n'
            b"Content-Type: text/plain\r\n\r\n"
            b"Hello World\r\n"
            b"--boundary--\r\n"
        )

        files, form_data = handler._parse_multipart(body, "boundary")
        assert len(files) == 1
        assert files[0][0] == "test.txt"
        assert files[0][1] == b"Hello World"

    def test_parse_multipart_with_form_fields(self, handler):
        """Test parsing multipart with form fields."""
        body = (
            b"--boundary\r\n"
            b'Content-Disposition: form-data; name="workspace_id"\r\n\r\n'
            b"ws-123\r\n"
            b"--boundary\r\n"
            b'Content-Disposition: form-data; name="file"; filename="doc.pdf"\r\n'
            b"Content-Type: application/pdf\r\n\r\n"
            b"PDF content\r\n"
            b"--boundary--\r\n"
        )

        files, form_data = handler._parse_multipart(body, "boundary")
        assert len(files) == 1
        assert form_data["workspace_id"] == "ws-123"

    def test_parse_multipart_multiple_files(self, handler):
        """Test parsing multipart with multiple files."""
        body = (
            b"--boundary\r\n"
            b'Content-Disposition: form-data; name="files[]"; filename="file1.txt"\r\n\r\n'
            b"Content 1\r\n"
            b"--boundary\r\n"
            b'Content-Disposition: form-data; name="files[]"; filename="file2.txt"\r\n\r\n'
            b"Content 2\r\n"
            b"--boundary--\r\n"
        )

        files, form_data = handler._parse_multipart(body, "boundary")
        assert len(files) == 2
        assert files[0][0] == "file1.txt"
        assert files[1][0] == "file2.txt"


# ---------------------------------------------------------------------------
# Helper Method Tests
# ---------------------------------------------------------------------------


class TestHelperMethods:
    """Tests for helper methods."""

    def test_generate_batch_id(self, handler):
        """Test batch ID generation."""
        batch_id = handler._generate_batch_id()
        assert batch_id.startswith("batch-")
        assert len(batch_id) > len("batch-")

    def test_generate_batch_id_unique(self, handler):
        """Test that batch IDs are unique."""
        ids = [handler._generate_batch_id() for _ in range(100)]
        assert len(set(ids)) == 100

    def test_get_batch_processor_creates_new(self, handler):
        """Test that _get_batch_processor creates a processor if not in context."""
        handler.ctx = {}

        with patch("aragora.documents.ingestion.batch_processor.BatchProcessor") as MockProcessor:
            MockProcessor.return_value = MagicMock()
            processor = handler._get_batch_processor()

            assert processor is not None
            assert "batch_processor" in handler.ctx

    def test_get_batch_processor_returns_existing(self, handler):
        """Test that _get_batch_processor returns existing processor."""
        existing_processor = MagicMock()
        handler.ctx = {"batch_processor": existing_processor}

        processor = handler._get_batch_processor()
        assert processor is existing_processor


# ---------------------------------------------------------------------------
# Handler Instance Tests
# ---------------------------------------------------------------------------


class TestHandlerInstance:
    """Tests for handler instance creation."""

    def test_handler_creation(self):
        """Test creating handler instance."""
        handler = DocumentBatchHandler({})
        assert handler is not None

    def test_handler_with_context(self):
        """Test handler uses provided context."""
        ctx = {"test_key": "test_value"}
        handler = DocumentBatchHandler(ctx)
        assert handler.ctx == ctx

    def test_handler_inherits_base(self):
        """Test handler inherits from BaseHandler."""
        from aragora.server.handlers.base import BaseHandler

        assert issubclass(DocumentBatchHandler, BaseHandler)
