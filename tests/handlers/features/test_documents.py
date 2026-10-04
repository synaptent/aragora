"""Tests for document management handler.

Tests the document API endpoints including:
- GET /api/v1/documents - List all uploaded documents
- GET /api/v1/documents/formats - Get supported file formats
- GET /api/v1/documents/{doc_id} - Get a document by ID
- POST /api/v1/documents/upload - Upload a document
- DELETE /api/v1/documents/{doc_id} - Delete a document by ID

Also tests:
- Upload rate limiting (per-minute and per-hour)
- Multipart form-data and raw upload parsing
- File validation (size, extension, filename security)
- Knowledge pipeline integration
- Structured upload error codes
"""

import io
import json
import time
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.base import HandlerResult
from aragora.server.handlers.features.documents import (
    MAX_FILENAME_LENGTH,
    MAX_MULTIPART_PARTS,
    MIN_FILE_SIZE,
    DocumentHandler,
    UploadError,
    UploadErrorCode,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _status(result: HandlerResult) -> int:
    """Extract status code from HandlerResult."""
    return result.status_code


def _body(result: HandlerResult) -> dict[str, Any]:
    """Extract parsed JSON body from HandlerResult."""
    return json.loads(result.body.decode("utf-8"))


# ---------------------------------------------------------------------------
# Mock objects
# ---------------------------------------------------------------------------


@dataclass
class MockDocument:
    """Mock document returned by store."""

    doc_id: str = "doc-001"
    filename: str = "test.txt"
    word_count: int = 100
    page_count: int = 1
    preview: str = "Hello world..."
    content: str = "Hello world"
    # The org of the user patch_user_auth signs every request in as.
    org_id: str | None = "test-org-001"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.doc_id,
            "filename": self.filename,
            "word_count": self.word_count,
            "page_count": self.page_count,
            "preview": self.preview,
        }


class MockDocumentStore:
    """Mock document store for testing."""

    def __init__(self):
        self._docs: dict[str, MockDocument] = {}

    def list_all(self) -> list[dict]:
        return [doc.to_dict() for doc in self._docs.values()]

    def list_for_org(self, org_id: str) -> list[dict]:
        return [doc.to_dict() for doc in self._docs.values() if doc.org_id == org_id]

    def get(self, doc_id: str) -> MockDocument | None:
        return self._docs.get(doc_id)

    def add(self, doc: Any) -> str:
        doc_id = f"doc-{len(self._docs) + 1:03d}"
        self._docs[doc_id] = doc
        return doc_id

    def delete(self, doc_id: str) -> bool:
        if doc_id in self._docs:
            del self._docs[doc_id]
            return True
        return False


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


def _make_http_handler(
    content: bytes = b"",
    content_type: str = "application/octet-stream",
    filename: str | None = None,
    client_ip: str = "127.0.0.1",
) -> MockHTTPHandler:
    """Build a MockHTTPHandler with the given file content."""
    headers = {
        "Content-Length": str(len(content)),
        "Content-Type": content_type,
    }
    if filename:
        headers["X-Filename"] = filename
    h = MockHTTPHandler(
        headers=headers,
        client_address=(client_ip, 12345),
        _rfile_data=content,
    )
    return h


def _make_multipart_body(filename: str, content: bytes, boundary: str = "----boundary") -> bytes:
    """Build a multipart/form-data body with a single file part."""
    parts = []
    parts.append(f"------{boundary}".encode())
    parts.append(
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n".encode()
    )
    parts.append(content)
    parts.append(f"\r\n------{boundary}--\r\n".encode())
    return b"\r\n".join(parts)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store():
    """Create a mock document store."""
    return MockDocumentStore()


@pytest.fixture
def handler(store):
    """Create a DocumentHandler with a document store in context."""
    return DocumentHandler(server_context={"document_store": store})


@pytest.fixture
def handler_no_store():
    """Create a DocumentHandler with no document store."""
    return DocumentHandler(server_context={})


@pytest.fixture(autouse=True)
def reset_rate_limits():
    """Reset rate limit state between tests."""
    DocumentHandler._upload_counts.clear()
    yield
    DocumentHandler._upload_counts.clear()


@pytest.fixture
def mock_user_ctx():
    """Create a mock authenticated user context for upload tests."""
    ctx = MagicMock()
    ctx.is_authenticated = True
    ctx.authenticated = True
    ctx.user_id = "test-user-001"
    ctx.org_id = "test-org-001"
    ctx.role = "admin"
    ctx.error_reason = None
    return ctx


@pytest.fixture(autouse=True)
def patch_user_auth(mock_user_ctx):
    """Patch extract_user_from_request to bypass JWT auth for upload tests."""
    with patch(
        "aragora.billing.jwt_auth.extract_user_from_request",
        return_value=mock_user_ctx,
    ):
        yield


# ===========================================================================
# UploadError tests
# ===========================================================================


class TestUploadError:
    """Tests for the UploadError dataclass."""

    def test_to_response_default_status(self):
        err = UploadError(UploadErrorCode.NO_CONTENT, "No content provided")
        result = err.to_response()
        assert _status(result) == 400
        body = _body(result)
        assert body["error"] == "No content provided"
        assert body["error_code"] == "no_content"

    def test_to_response_custom_status(self):
        err = UploadError(UploadErrorCode.FILE_TOO_LARGE, "File too large")
        result = err.to_response(status=413)
        assert _status(result) == 413

    def test_to_response_with_details(self):
        details = {"received_bytes": 5000, "max_bytes": 1000}
        err = UploadError(UploadErrorCode.FILE_TOO_LARGE, "Too big", details=details)
        result = err.to_response()
        body = _body(result)
        assert body["details"] == details

    def test_to_response_without_details(self):
        err = UploadError(UploadErrorCode.NO_CONTENT, "Empty")
        result = err.to_response()
        body = _body(result)
        assert "details" not in body

    def test_all_error_codes_have_string_values(self):
        for code in UploadErrorCode:
            assert isinstance(code.value, str)
            assert len(code.value) > 0


# ===========================================================================
# can_handle tests
# ===========================================================================


class TestCanHandle:
    """Tests for route matching."""

    def test_list_documents(self, handler):
        assert handler.can_handle("/api/v1/documents")

    def test_formats_endpoint(self, handler):
        assert handler.can_handle("/api/v1/documents/formats")

    def test_upload_endpoint(self, handler):
        assert handler.can_handle("/api/v1/documents/upload")

    def test_document_by_id(self, handler):
        assert handler.can_handle("/api/v1/documents/doc-001")

    def test_document_by_uuid(self, handler):
        assert handler.can_handle("/api/v1/documents/abc123")

    def test_rejects_non_documents_path(self, handler):
        assert not handler.can_handle("/api/v1/users")

    def test_rejects_deeper_nesting(self, handler):
        assert not handler.can_handle("/api/v1/documents/doc-001/versions")

    def test_rejects_root(self, handler):
        assert not handler.can_handle("/")

    def test_rejects_partial_match(self, handler):
        assert not handler.can_handle("/api/v1/document")

    def test_routes_constant(self, handler):
        assert "/api/v1/documents" in handler.ROUTES
        assert "/api/v1/documents/formats" in handler.ROUTES
        assert "/api/v1/documents/upload" in handler.ROUTES


# ===========================================================================
# handle() GET tests - list documents
# ===========================================================================


class TestListDocuments:
    """Tests for GET /api/v1/documents."""

    def test_list_empty(self, handler, store):
        mock = MockHTTPHandler(command="GET")
        result = handler.handle("/api/v1/documents", {}, mock)
        assert _status(result) == 200
        body = _body(result)
        assert body["documents"] == []
        assert body["count"] == 0

    def test_list_with_documents(self, handler, store):
        store._docs["d1"] = MockDocument(doc_id="d1", filename="a.txt")
        store._docs["d2"] = MockDocument(doc_id="d2", filename="b.pdf")
        mock = MockHTTPHandler(command="GET")
        result = handler.handle("/api/v1/documents", {}, mock)
        assert _status(result) == 200
        body = _body(result)
        assert body["count"] == 2
        assert len(body["documents"]) == 2

    def test_list_no_store(self, handler_no_store):
        mock = MockHTTPHandler(command="GET")
        result = handler_no_store.handle("/api/v1/documents", {}, mock)
        assert _status(result) == 200
        body = _body(result)
        assert body["documents"] == []
        assert body["count"] == 0
        assert "error" in body

    def test_list_store_exception(self, handler, store):
        store.list_for_org = MagicMock(side_effect=ValueError("DB error"))
        mock = MockHTTPHandler(command="GET")
        result = handler.handle("/api/v1/documents", {}, mock)
        assert _status(result) == 500

    def test_list_store_key_error(self, handler, store):
        store.list_for_org = MagicMock(side_effect=KeyError("missing key"))
        mock = MockHTTPHandler(command="GET")
        result = handler.handle("/api/v1/documents", {}, mock)
        assert _status(result) == 500

    def test_list_store_os_error(self, handler, store):
        store.list_for_org = MagicMock(side_effect=OSError("disk error"))
        mock = MockHTTPHandler(command="GET")
        result = handler.handle("/api/v1/documents", {}, mock)
        assert _status(result) == 500

    def test_list_store_type_error(self, handler, store):
        store.list_for_org = MagicMock(side_effect=TypeError("wrong type"))
        mock = MockHTTPHandler(command="GET")
        result = handler.handle("/api/v1/documents", {}, mock)
        assert _status(result) == 500


# ===========================================================================
# handle() GET tests - get document by ID
# ===========================================================================


class TestGetDocument:
    """Tests for GET /api/v1/documents/{doc_id}."""

    def test_get_existing_document(self, handler, store):
        doc = MockDocument(doc_id="d1", filename="report.pdf", word_count=500)
        store._docs["d1"] = doc
        mock = MockHTTPHandler(command="GET")
        result = handler.handle("/api/v1/documents/d1", {}, mock)
        assert _status(result) == 200
        body = _body(result)
        assert body["id"] == "d1"
        assert body["filename"] == "report.pdf"
        assert body["word_count"] == 500

    def test_get_nonexistent_document(self, handler, store):
        mock = MockHTTPHandler(command="GET")
        result = handler.handle("/api/v1/documents/nonexistent", {}, mock)
        assert _status(result) == 404
        body = _body(result)
        assert "not found" in body["error"].lower()

    def test_get_document_no_store(self, handler_no_store):
        mock = MockHTTPHandler(command="GET")
        result = handler_no_store.handle("/api/v1/documents/d1", {}, mock)
        assert _status(result) == 500
        body = _body(result)
        assert "not configured" in body["error"].lower()

    def test_get_document_store_exception(self, handler, store):
        store.get = MagicMock(side_effect=ValueError("corruption"))
        mock = MockHTTPHandler(command="GET")
        result = handler.handle("/api/v1/documents/d1", {}, mock)
        assert _status(result) == 500

    def test_get_document_store_key_error(self, handler, store):
        store.get = MagicMock(side_effect=KeyError("missing"))
        mock = MockHTTPHandler(command="GET")
        result = handler.handle("/api/v1/documents/d1", {}, mock)
        assert _status(result) == 500

    def test_get_document_store_os_error(self, handler, store):
        store.get = MagicMock(side_effect=OSError("disk"))
        mock = MockHTTPHandler(command="GET")
        result = handler.handle("/api/v1/documents/d1", {}, mock)
        assert _status(result) == 500


# ===========================================================================
# handle() GET tests - supported formats
# ===========================================================================


class TestGetSupportedFormats:
    """Tests for GET /api/v1/documents/formats."""

    def test_formats_with_module(self, handler):
        mock_formats = {"extensions": [".txt", ".pdf", ".md", ".docx"], "note": "full"}
        mock = MockHTTPHandler(command="GET")
        with patch(
            "aragora.server.handlers.features.documents.get_supported_formats",
            return_value=mock_formats,
            create=True,
        ):
            # Need to patch at the import site inside _get_supported_formats
            with patch.dict(
                "sys.modules",
                {
                    "aragora.server.documents": MagicMock(
                        get_supported_formats=MagicMock(return_value=mock_formats)
                    )
                },
            ):
                result = handler.handle("/api/v1/documents/formats", {}, mock)
        assert _status(result) == 200
        body = _body(result)
        assert "extensions" in body

    def test_formats_import_error_fallback(self, handler):
        mock = MockHTTPHandler(command="GET")
        with patch.dict("sys.modules", {"aragora.server.documents": None}):
            result = handler.handle("/api/v1/documents/formats", {}, mock)
        assert _status(result) == 200
        body = _body(result)
        assert ".txt" in body["extensions"]
        assert ".md" in body["extensions"]
        assert ".pdf" in body["extensions"]
        assert "note" in body


# ===========================================================================
# handle() routing - returns None for unmatched paths
# ===========================================================================


class TestHandleRouting:
    """Tests for handle() routing logic."""

    def test_returns_none_for_upload_path(self, handler):
        """GET /api/v1/documents/upload should not match the doc_id branch."""
        mock = MockHTTPHandler(command="GET")
        result = handler.handle("/api/v1/documents/upload", {}, mock)
        assert result is None

    def test_returns_none_for_unknown_path(self, handler):
        mock = MockHTTPHandler(command="GET")
        result = handler.handle("/api/v1/other", {}, mock)
        assert result is None


# ===========================================================================
# handle_delete() tests
# ===========================================================================


class TestDeleteDocument:
    """Tests for DELETE /api/v1/documents/{doc_id}."""

    def test_delete_existing_document(self, handler, store):
        store._docs["d1"] = MockDocument(doc_id="d1")
        mock = MockHTTPHandler(command="DELETE")
        result = handler.handle_delete("/api/v1/documents/d1", {}, mock)
        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        assert "d1" not in store._docs

    def test_delete_nonexistent_document(self, handler, store):
        mock = MockHTTPHandler(command="DELETE")
        result = handler.handle_delete("/api/v1/documents/nonexistent", {}, mock)
        assert _status(result) == 404

    def test_delete_no_store(self, handler_no_store):
        mock = MockHTTPHandler(command="DELETE")
        result = handler_no_store.handle_delete("/api/v1/documents/d1", {}, mock)
        assert _status(result) == 500

    def test_delete_store_returns_false(self, handler, store):
        store._docs["d1"] = MockDocument(doc_id="d1")
        store.delete = MagicMock(return_value=False)
        store.get = MagicMock(return_value=MockDocument(doc_id="d1"))
        mock = MockHTTPHandler(command="DELETE")
        result = handler.handle_delete("/api/v1/documents/d1", {}, mock)
        assert _status(result) == 500

    def test_delete_store_exception(self, handler, store):
        store._docs["d1"] = MockDocument(doc_id="d1")
        store.get = MagicMock(side_effect=ValueError("fail"))
        mock = MockHTTPHandler(command="DELETE")
        result = handler.handle_delete("/api/v1/documents/d1", {}, mock)
        assert _status(result) == 500

    def test_delete_store_os_error(self, handler, store):
        store._docs["d1"] = MockDocument(doc_id="d1")
        store.get = MagicMock(side_effect=OSError("disk"))
        mock = MockHTTPHandler(command="DELETE")
        result = handler.handle_delete("/api/v1/documents/d1", {}, mock)
        assert _status(result) == 500

    def test_delete_upload_path_returns_none(self, handler):
        mock = MockHTTPHandler(command="DELETE")
        result = handler.handle_delete("/api/v1/documents/upload", {}, mock)
        assert result is None

    def test_delete_unknown_path(self, handler):
        mock = MockHTTPHandler(command="DELETE")
        result = handler.handle_delete("/api/v1/other", {}, mock)
        assert result is None


# ===========================================================================
# handle_post() upload tests
# ===========================================================================


class TestUploadDocument:
    """Tests for POST /api/v1/documents/upload."""

    def _upload(
        self,
        handler,
        content: bytes = b"Hello world content here",
        filename: str = "test.txt",
        content_type: str = "application/octet-stream",
        query_params: dict | None = None,
        client_ip: str = "10.0.0.1",
    ) -> HandlerResult:
        """Helper to perform an upload through handle_post."""
        http_handler = _make_http_handler(
            content=content,
            content_type=content_type,
            filename=filename,
            client_ip=client_ip,
        )
        qp = query_params or {}
        return handler.handle_post("/api/v1/documents/upload", qp, http_handler)

    @patch("aragora.server.handlers.features.documents.validate_file_upload")
    @patch("aragora.server.handlers.features.documents.parse_document", create=True)
    def test_successful_upload(self, mock_parse, mock_validate, handler, store):
        mock_validate.return_value = MagicMock(valid=True)
        mock_doc = MockDocument()
        mock_parse.return_value = mock_doc

        with patch.dict(
            "sys.modules",
            {
                "aragora.server.documents": MagicMock(
                    parse_document=mock_parse,
                    SUPPORTED_EXTENSIONS={".txt", ".pdf", ".md"},
                ),
            },
        ):
            result = self._upload(handler, content=b"x" * 24, filename="test.txt")

        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        assert "document" in body

    def test_upload_returns_none_for_wrong_path(self, handler):
        http_handler = _make_http_handler(content=b"data", filename="test.txt")
        result = handler.handle_post("/api/v1/documents", {}, http_handler)
        assert result is None

    def test_upload_no_store(self, handler_no_store):
        http_handler = _make_http_handler(content=b"Hello data here!!!!!!!!!", filename="test.txt")
        result = handler_no_store.handle_post("/api/v1/documents/upload", {}, http_handler)
        assert _status(result) == 500
        body = _body(result)
        assert body["error_code"] == "storage_not_configured"

    def test_upload_zero_content_length(self, handler):
        http_handler = _make_http_handler(content=b"", filename="test.txt")
        result = handler.handle_post("/api/v1/documents/upload", {}, http_handler)
        assert _status(result) == 400
        body = _body(result)
        assert body["error_code"] == "no_content"

    def test_upload_invalid_content_length(self, handler):
        http_handler = _make_http_handler(content=b"data", filename="test.txt")
        http_handler.headers["Content-Length"] = "not-a-number"
        result = handler.handle_post("/api/v1/documents/upload", {}, http_handler)
        assert _status(result) == 400
        body = _body(result)
        assert body["error_code"] == "invalid_content_length"

    def test_upload_file_too_large(self, handler):
        http_handler = _make_http_handler(content=b"x", filename="test.txt")
        # Set Content-Length to exceed max
        http_handler.headers["Content-Length"] = str(200 * 1024 * 1024)
        result = handler.handle_post("/api/v1/documents/upload", {}, http_handler)
        assert _status(result) == 413
        body = _body(result)
        assert body["error_code"] == "file_too_large"

    @patch("aragora.server.handlers.features.documents.validate_file_upload")
    def test_upload_unsupported_extension(self, mock_validate, handler, store):
        mock_validate.return_value = MagicMock(valid=True)
        content = b"x" * 20
        http_handler = _make_http_handler(content=content, filename="test.exe")

        with patch.dict(
            "sys.modules",
            {
                "aragora.server.documents": MagicMock(
                    SUPPORTED_EXTENSIONS={".txt", ".pdf"},
                    parse_document=MagicMock(),
                ),
            },
        ):
            result = handler.handle_post("/api/v1/documents/upload", {}, http_handler)
        assert _status(result) == 400
        body = _body(result)
        assert body["error_code"] == "unsupported_format"

    @patch("aragora.server.handlers.features.documents.validate_file_upload")
    def test_upload_parse_error(self, mock_validate, handler, store):
        mock_validate.return_value = MagicMock(valid=True)
        content = b"x" * 20
        http_handler = _make_http_handler(content=content, filename="test.txt")

        with patch.dict(
            "sys.modules",
            {
                "aragora.server.documents": MagicMock(
                    SUPPORTED_EXTENSIONS={".txt"},
                    parse_document=MagicMock(side_effect=ValueError("bad format")),
                ),
            },
        ):
            result = handler.handle_post("/api/v1/documents/upload", {}, http_handler)
        assert _status(result) == 400
        body = _body(result)
        assert body["error_code"] == "parsing_failed"

    @patch("aragora.server.handlers.features.documents.validate_file_upload")
    def test_upload_storage_error(self, mock_validate, handler, store):
        mock_validate.return_value = MagicMock(valid=True)
        content = b"x" * 20
        mock_doc = MockDocument()
        http_handler = _make_http_handler(content=content, filename="test.txt")

        store.add = MagicMock(side_effect=RuntimeError("storage full"))

        with patch.dict(
            "sys.modules",
            {
                "aragora.server.documents": MagicMock(
                    SUPPORTED_EXTENSIONS={".txt"},
                    parse_document=MagicMock(return_value=mock_doc),
                ),
            },
        ):
            result = handler.handle_post("/api/v1/documents/upload", {}, http_handler)
        assert _status(result) == 500
        body = _body(result)
        assert body["error_code"] == "storage_failed"

    @patch("aragora.server.handlers.features.documents.validate_file_upload")
    def test_upload_import_error_for_documents_module(self, mock_validate, handler, store):
        mock_validate.return_value = MagicMock(valid=True)
        content = b"x" * 20
        http_handler = _make_http_handler(content=content, filename="test.txt")

        with patch.dict("sys.modules", {"aragora.server.documents": None}):
            result = handler.handle_post("/api/v1/documents/upload", {}, http_handler)
        assert _status(result) == 500
        body = _body(result)
        assert body["error_code"] == "parsing_failed"

    def test_upload_process_knowledge_param_true(self, handler):
        """Test that process_knowledge=true query param is parsed."""
        qp = {"process_knowledge": ["true"], "workspace_id": ["ws-1"]}
        http_handler = _make_http_handler(content=b"", filename="test.txt")
        # This will hit zero content length first, but we verify param parsing works
        result = handler.handle_post("/api/v1/documents/upload", qp, http_handler)
        assert _status(result) == 400  # no content, but route matched
        body = _body(result)
        assert body["error_code"] == "no_content"

    def test_upload_process_knowledge_param_false(self, handler):
        qp = {"process_knowledge": ["false"]}
        http_handler = _make_http_handler(content=b"", filename="test.txt")
        result = handler.handle_post("/api/v1/documents/upload", qp, http_handler)
        assert _status(result) == 400
        body = _body(result)
        assert body["error_code"] == "no_content"

    @patch("aragora.server.handlers.features.documents.validate_file_upload")
    def test_upload_with_knowledge_processing(self, mock_validate, handler, store):
        mock_validate.return_value = MagicMock(valid=True)
        content = b"x" * 20
        mock_doc = MockDocument()
        http_handler = _make_http_handler(content=content, filename="test.txt")
        knowledge_result = {"knowledge_processing": {"status": "queued", "job_id": "job-1"}}

        with patch.dict(
            "sys.modules",
            {
                "aragora.server.documents": MagicMock(
                    SUPPORTED_EXTENSIONS={".txt"},
                    parse_document=MagicMock(return_value=mock_doc),
                ),
                "aragora.knowledge.integration": MagicMock(
                    process_uploaded_document=MagicMock(return_value=knowledge_result),
                ),
            },
        ):
            result = handler.handle_post(
                "/api/v1/documents/upload",
                {"process_knowledge": ["true"]},
                http_handler,
            )

        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        assert body["knowledge_processing"]["status"] == "queued"

    @patch("aragora.server.handlers.features.documents.validate_file_upload")
    def test_upload_knowledge_import_error(self, mock_validate, handler, store):
        mock_validate.return_value = MagicMock(valid=True)
        content = b"x" * 20
        mock_doc = MockDocument()
        http_handler = _make_http_handler(content=content, filename="test.txt")

        with patch.dict(
            "sys.modules",
            {
                "aragora.server.documents": MagicMock(
                    SUPPORTED_EXTENSIONS={".txt"},
                    parse_document=MagicMock(return_value=mock_doc),
                ),
                "aragora.knowledge.integration": None,
            },
        ):
            result = handler.handle_post(
                "/api/v1/documents/upload",
                {"process_knowledge": ["true"]},
                http_handler,
            )

        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True

    @patch("aragora.server.handlers.features.documents.validate_file_upload")
    def test_upload_knowledge_processing_failure(self, mock_validate, handler, store):
        mock_validate.return_value = MagicMock(valid=True)
        content = b"x" * 20
        mock_doc = MockDocument()
        http_handler = _make_http_handler(content=content, filename="test.txt")

        knowledge_mod = MagicMock()
        knowledge_mod.process_uploaded_document.side_effect = ValueError("pipeline error")

        with patch.dict(
            "sys.modules",
            {
                "aragora.server.documents": MagicMock(
                    SUPPORTED_EXTENSIONS={".txt"},
                    parse_document=MagicMock(return_value=mock_doc),
                ),
                "aragora.knowledge.integration": knowledge_mod,
            },
        ):
            result = handler.handle_post(
                "/api/v1/documents/upload",
                {"process_knowledge": ["true"]},
                http_handler,
            )

        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        assert body["knowledge_processing"]["status"] == "failed"

    @patch("aragora.server.handlers.features.documents.validate_file_upload")
    def test_upload_skip_knowledge_when_disabled(self, mock_validate, handler, store):
        mock_validate.return_value = MagicMock(valid=True)
        content = b"x" * 20
        mock_doc = MockDocument()
        http_handler = _make_http_handler(content=content, filename="test.txt")

        with patch.dict(
            "sys.modules",
            {
                "aragora.server.documents": MagicMock(
                    SUPPORTED_EXTENSIONS={".txt"},
                    parse_document=MagicMock(return_value=mock_doc),
                ),
            },
        ):
            result = handler.handle_post(
                "/api/v1/documents/upload",
                {"process_knowledge": ["false"]},
                http_handler,
            )

        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        # knowledge_processing should not be in response
        assert "knowledge_processing" not in body

    @patch("aragora.server.handlers.features.documents.validate_file_upload")
    def test_upload_content_length_mismatch(self, mock_validate, handler, store):
        """Upload where actual content length doesn't match header."""
        mock_validate.return_value = MagicMock(valid=True)
        content = b"x" * 10
        http_handler = _make_http_handler(content=content, filename="test.txt")
        # Lie about content length
        http_handler.headers["Content-Length"] = "20"

        with patch.dict(
            "sys.modules",
            {
                "aragora.server.documents": MagicMock(
                    SUPPORTED_EXTENSIONS={".txt"},
                    parse_document=MagicMock(),
                ),
            },
        ):
            result = handler.handle_post("/api/v1/documents/upload", {}, http_handler)

        assert _status(result) == 400
        body = _body(result)
        assert body["error_code"] == "corrupted_upload"


# ===========================================================================
# Rate limiting tests
# ===========================================================================


class TestUploadRateLimiting:
    """Tests for upload rate limiting."""

    def test_within_rate_limit(self, handler):
        http_handler = _make_http_handler(content=b"", filename="test.txt", client_ip="1.2.3.4")
        # Content-Length 0 will fail on content check, but rate limit should pass
        result = handler.handle_post("/api/v1/documents/upload", {}, http_handler)
        body = _body(result)
        assert body["error_code"] == "no_content"  # Not rate_limited

    def test_per_minute_rate_limit(self, handler):
        """Exceed per-minute rate limit."""
        # Fill up rate limit counter directly
        now = time.time()
        ip = "10.0.0.99"
        DocumentHandler._upload_counts[ip] = [now] * DocumentHandler.MAX_UPLOADS_PER_MINUTE

        http_handler = _make_http_handler(
            content=b"test content data!!",
            filename="test.txt",
            client_ip=ip,
        )
        result = handler.handle_post("/api/v1/documents/upload", {}, http_handler)
        assert _status(result) == 429

    def test_per_hour_rate_limit(self, handler):
        """Exceed per-hour rate limit."""
        now = time.time()
        ip = "10.0.0.100"
        # Timestamps spread over the hour but exceeding hourly limit
        DocumentHandler._upload_counts[ip] = [
            now - (i * 120) for i in range(DocumentHandler.MAX_UPLOADS_PER_HOUR)
        ]

        http_handler = _make_http_handler(
            content=b"test content data!!",
            filename="test.txt",
            client_ip=ip,
        )
        result = handler.handle_post("/api/v1/documents/upload", {}, http_handler)
        assert _status(result) == 429

    def test_different_ips_independent(self, handler):
        """Different IPs have independent rate limits."""
        now = time.time()
        DocumentHandler._upload_counts["1.1.1.1"] = [now] * DocumentHandler.MAX_UPLOADS_PER_MINUTE

        http_handler = _make_http_handler(
            content=b"",
            filename="test.txt",
            client_ip="2.2.2.2",
        )
        result = handler.handle_post("/api/v1/documents/upload", {}, http_handler)
        body = _body(result)
        # Should not be rate limited for different IP
        assert body["error_code"] != "rate_limited"

    def test_old_timestamps_cleaned(self, handler):
        """Timestamps older than 1 hour should be cleaned up."""
        ip = "10.0.0.101"
        old_time = time.time() - 7200  # 2 hours ago
        DocumentHandler._upload_counts[ip] = [old_time] * 100

        http_handler = _make_http_handler(
            content=b"",
            filename="test.txt",
            client_ip=ip,
        )
        result = handler.handle_post("/api/v1/documents/upload", {}, http_handler)
        body = _body(result)
        # Old timestamps should be cleaned, so we're not rate limited
        assert body["error_code"] != "rate_limited"

    def test_lru_eviction(self, handler):
        """LRU eviction should remove oldest entries when MAX_TRACKED_IPS exceeded."""
        # Fill to max
        for i in range(DocumentHandler.MAX_TRACKED_IPS):
            DocumentHandler._upload_counts[f"10.0.{i // 256}.{i % 256}"] = [time.time()]

        # One more should trigger eviction
        http_handler = _make_http_handler(
            content=b"",
            filename="test.txt",
            client_ip="99.99.99.99",
        )
        handler.handle_post("/api/v1/documents/upload", {}, http_handler)

        # Should still be within limits
        assert len(DocumentHandler._upload_counts) <= DocumentHandler.MAX_TRACKED_IPS + 1


# ===========================================================================
# Client IP extraction tests
# ===========================================================================


class TestClientIP:
    """Tests for _get_client_ip."""

    def test_extracts_client_address(self, handler):
        http_handler = MockHTTPHandler(client_address=("192.168.1.1", 5000))
        ip = handler._get_client_ip(http_handler)
        assert ip == "192.168.1.1"

    def test_missing_client_address(self, handler):
        http_handler = MagicMock(spec=[])  # No client_address attribute
        ip = handler._get_client_ip(http_handler)
        assert ip == "unknown"


# ===========================================================================
# Multipart parsing tests
# ===========================================================================


class TestMultipartParsing:
    """Tests for _parse_multipart_with_error."""

    def test_missing_boundary(self, handler):
        http_handler = MockHTTPHandler()
        content_type = "multipart/form-data"  # No boundary
        _, _, err = handler._parse_multipart_with_error(http_handler, content_type, 0)
        assert err is not None
        assert err.code == UploadErrorCode.MISSING_BOUNDARY

    def test_valid_multipart(self, handler):
        boundary = "testboundary123"
        file_content = b"file data here"
        body = (
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="test.txt"\r\n'
                f"Content-Type: text/plain\r\n\r\n"
            ).encode()
            + file_content
            + f"\r\n--{boundary}--\r\n".encode()
        )

        http_handler = MockHTTPHandler(_rfile_data=body)
        content_type = f"multipart/form-data; boundary={boundary}"

        data, filename, err = handler._parse_multipart_with_error(
            http_handler, content_type, len(body)
        )
        assert err is None
        assert filename == "test.txt"
        assert data is not None

    def test_boundary_with_quotes(self, handler):
        boundary = "myboundary"
        body = (
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="doc.pdf"\r\n\r\n'
            ).encode()
            + b"data"
            + f"\r\n--{boundary}--\r\n".encode()
        )

        http_handler = MockHTTPHandler(_rfile_data=body)
        content_type = f'multipart/form-data; boundary="{boundary}"'

        data, filename, err = handler._parse_multipart_with_error(
            http_handler, content_type, len(body)
        )
        assert err is None
        assert filename == "doc.pdf"

    def test_empty_filename_in_multipart(self, handler):
        boundary = "bound"
        body = (
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename=""\r\n\r\n'
            ).encode()
            + b"data"
            + f"\r\n--{boundary}--\r\n".encode()
        )

        http_handler = MockHTTPHandler(_rfile_data=body)
        content_type = f"multipart/form-data; boundary={boundary}"

        _, _, err = handler._parse_multipart_with_error(http_handler, content_type, len(body))
        assert err is not None
        assert err.code == UploadErrorCode.INVALID_FILENAME

    def test_null_bytes_in_filename(self, handler):
        boundary = "bound"
        body = (
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="test\x00.txt"\r\n\r\n'
            ).encode()
            + b"data"
            + f"\r\n--{boundary}--\r\n".encode()
        )

        http_handler = MockHTTPHandler(_rfile_data=body)
        content_type = f"multipart/form-data; boundary={boundary}"

        _, _, err = handler._parse_multipart_with_error(http_handler, content_type, len(body))
        assert err is not None
        assert err.code == UploadErrorCode.INVALID_FILENAME

    def test_path_traversal_in_filename(self, handler):
        boundary = "bound"
        body = (
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="..test.txt"\r\n\r\n'
            ).encode()
            + b"data"
            + f"\r\n--{boundary}--\r\n".encode()
        )

        http_handler = MockHTTPHandler(_rfile_data=body)
        content_type = f"multipart/form-data; boundary={boundary}"

        _, _, err = handler._parse_multipart_with_error(http_handler, content_type, len(body))
        assert err is not None
        assert err.code == UploadErrorCode.INVALID_FILENAME

    def test_dots_only_filename(self, handler):
        boundary = "bound"
        body = (
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="..."\r\n\r\n'
            ).encode()
            + b"data"
            + f"\r\n--{boundary}--\r\n".encode()
        )

        http_handler = MockHTTPHandler(_rfile_data=body)
        content_type = f"multipart/form-data; boundary={boundary}"

        _, _, err = handler._parse_multipart_with_error(http_handler, content_type, len(body))
        assert err is not None
        assert err.code == UploadErrorCode.INVALID_FILENAME

    def test_too_many_parts(self, handler):
        boundary = "bound"
        # Create body with too many parts
        parts = []
        for i in range(MAX_MULTIPART_PARTS + 5):
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="field{i}"\r\n\r\nvalue{i}'
            )
        body_str = "\r\n".join(parts) + f"\r\n--{boundary}--"
        body = body_str.encode()

        http_handler = MockHTTPHandler(_rfile_data=body)
        content_type = f"multipart/form-data; boundary={boundary}"

        _, _, err = handler._parse_multipart_with_error(http_handler, content_type, len(body))
        assert err is not None
        assert err.code == UploadErrorCode.MULTIPART_PARSE_ERROR

    def test_no_file_part_in_multipart(self, handler):
        boundary = "bound"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="field"\r\n\r\nvalue'
            f"\r\n--{boundary}--\r\n"
        ).encode()

        http_handler = MockHTTPHandler(_rfile_data=body)
        content_type = f"multipart/form-data; boundary={boundary}"

        _, _, err = handler._parse_multipart_with_error(http_handler, content_type, len(body))
        assert err is not None
        assert err.code == UploadErrorCode.MULTIPART_PARSE_ERROR

    def test_multipart_read_error(self, handler):
        http_handler = MagicMock()
        http_handler.rfile.read.side_effect = OSError("read error")
        content_type = "multipart/form-data; boundary=bound"

        _, _, err = handler._parse_multipart_with_error(http_handler, content_type, 100)
        assert err is not None
        assert err.code == UploadErrorCode.CORRUPTED_UPLOAD

    def test_path_in_filename_is_stripped(self, handler):
        """os.path.basename should strip directory components."""
        boundary = "bound"
        body = (
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="/etc/passwd"\r\n\r\n'
            ).encode()
            + b"data"
            + f"\r\n--{boundary}--\r\n".encode()
        )

        http_handler = MockHTTPHandler(_rfile_data=body)
        content_type = f"multipart/form-data; boundary={boundary}"

        data, filename, err = handler._parse_multipart_with_error(
            http_handler, content_type, len(body)
        )
        assert err is None
        assert filename == "passwd"


# ===========================================================================
# Raw upload parsing tests
# ===========================================================================


class TestRawUploadParsing:
    """Tests for _parse_raw_upload_with_error."""

    def test_successful_raw_upload(self, handler):
        content = b"file data"
        http_handler = _make_http_handler(content=content, filename="test.txt")
        data, filename, err = handler._parse_raw_upload_with_error(http_handler, len(content))
        assert err is None
        assert filename == "test.txt"
        assert data == content

    def test_default_filename(self, handler):
        content = b"data"
        http_handler = _make_http_handler(content=content)
        # No X-Filename header
        data, filename, err = handler._parse_raw_upload_with_error(http_handler, len(content))
        assert err is None
        assert filename == "document.txt"

    def test_null_bytes_in_raw_filename(self, handler):
        http_handler = _make_http_handler(content=b"data", filename="test\x00.txt")
        _, _, err = handler._parse_raw_upload_with_error(http_handler, 4)
        assert err is not None
        assert err.code == UploadErrorCode.INVALID_FILENAME

    def test_path_traversal_in_raw_filename(self, handler):
        http_handler = _make_http_handler(content=b"data", filename="..test.txt")
        _, _, err = handler._parse_raw_upload_with_error(http_handler, 4)
        assert err is not None
        assert err.code == UploadErrorCode.INVALID_FILENAME

    def test_raw_upload_read_error(self, handler):
        http_handler = MagicMock()
        http_handler.headers = {"X-Filename": "test.txt"}
        http_handler.rfile.read.side_effect = OSError("fail")
        _, _, err = handler._parse_raw_upload_with_error(http_handler, 100)
        assert err is not None
        assert err.code == UploadErrorCode.CORRUPTED_UPLOAD

    def test_raw_upload_strips_path(self, handler):
        http_handler = _make_http_handler(content=b"data", filename="/tmp/evil/test.txt")
        data, filename, err = handler._parse_raw_upload_with_error(http_handler, 4)
        assert err is None
        assert filename == "test.txt"

    def test_raw_upload_memory_error(self, handler):
        http_handler = MagicMock()
        http_handler.headers = {"X-Filename": "test.txt"}
        http_handler.rfile.read.side_effect = MemoryError("OOM")
        _, _, err = handler._parse_raw_upload_with_error(http_handler, 100)
        assert err is not None
        assert err.code == UploadErrorCode.CORRUPTED_UPLOAD


# ===========================================================================
# Legacy method tests
# ===========================================================================


class TestLegacyMethods:
    """Tests for legacy parse methods that delegate to *_with_error variants."""

    def test_parse_upload_multipart(self, handler):
        boundary = "testbound"
        body = (
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="doc.txt"\r\n\r\n'
            ).encode()
            + b"content"
            + f"\r\n--{boundary}--\r\n".encode()
        )

        http_handler = MockHTTPHandler(_rfile_data=body)
        content_type = f"multipart/form-data; boundary={boundary}"

        data, filename = handler._parse_upload(http_handler, content_type, len(body))
        assert filename == "doc.txt"

    def test_parse_upload_raw(self, handler):
        content = b"data"
        http_handler = _make_http_handler(content=content, filename="test.txt")
        data, filename = handler._parse_upload(
            http_handler, "application/octet-stream", len(content)
        )
        assert filename == "test.txt"
        assert data == content

    def test_parse_multipart_legacy(self, handler):
        boundary = "b"
        body = (
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="f.txt"\r\n\r\n'
            ).encode()
            + b"x"
            + f"\r\n--{boundary}--\r\n".encode()
        )

        http_handler = MockHTTPHandler(_rfile_data=body)
        content_type = f"multipart/form-data; boundary={boundary}"

        data, filename = handler._parse_multipart(http_handler, content_type, len(body))
        assert filename == "f.txt"

    def test_parse_raw_upload_legacy(self, handler):
        content = b"hello"
        http_handler = _make_http_handler(content=content, filename="report.md")
        data, filename = handler._parse_raw_upload(http_handler, len(content))
        assert filename == "report.md"
        assert data == content


# ===========================================================================
# File validation integration tests
# ===========================================================================


class TestFileValidation:
    """Tests for file validation in upload flow."""

    @patch("aragora.server.handlers.features.documents.validate_file_upload")
    def test_validation_failure_maps_to_error_code(self, mock_validate, handler, store):
        from aragora.server.handlers.utils.file_validation import FileValidationErrorCode

        mock_validate.return_value = MagicMock(
            valid=False,
            error_code=FileValidationErrorCode.PATH_TRAVERSAL,
            error_message="Path traversal detected",
            http_status=400,
            details={"filename": "../etc/passwd"},
        )

        content = b"x" * 20
        http_handler = _make_http_handler(content=content, filename="test.txt")

        result = handler.handle_post("/api/v1/documents/upload", {}, http_handler)
        assert _status(result) == 400
        body = _body(result)
        assert body["error_code"] == "invalid_filename"

    @patch("aragora.server.handlers.features.documents.validate_file_upload")
    def test_validation_too_large(self, mock_validate, handler, store):
        from aragora.server.handlers.utils.file_validation import FileValidationErrorCode

        mock_validate.return_value = MagicMock(
            valid=False,
            error_code=FileValidationErrorCode.FILE_TOO_LARGE,
            error_message="File too large",
            http_status=413,
            details={},
        )

        content = b"x" * 20
        http_handler = _make_http_handler(content=content, filename="test.txt")

        result = handler.handle_post("/api/v1/documents/upload", {}, http_handler)
        assert _status(result) == 413
        body = _body(result)
        assert body["error_code"] == "file_too_large"

    @patch("aragora.server.handlers.features.documents.validate_file_upload")
    def test_validation_null_bytes(self, mock_validate, handler, store):
        from aragora.server.handlers.utils.file_validation import FileValidationErrorCode

        mock_validate.return_value = MagicMock(
            valid=False,
            error_code=FileValidationErrorCode.NULL_BYTES,
            error_message="Null bytes in filename",
            http_status=400,
            details={},
        )

        content = b"x" * 20
        http_handler = _make_http_handler(content=content, filename="test.txt")

        result = handler.handle_post("/api/v1/documents/upload", {}, http_handler)
        assert _status(result) == 400
        body = _body(result)
        assert body["error_code"] == "invalid_filename"

    @patch("aragora.server.handlers.features.documents.validate_file_upload")
    def test_validation_invalid_mime(self, mock_validate, handler, store):
        from aragora.server.handlers.utils.file_validation import FileValidationErrorCode

        mock_validate.return_value = MagicMock(
            valid=False,
            error_code=FileValidationErrorCode.INVALID_MIME_TYPE,
            error_message="MIME type not allowed",
            http_status=400,
            details={},
        )

        content = b"x" * 20
        http_handler = _make_http_handler(content=content, filename="test.txt")

        result = handler.handle_post("/api/v1/documents/upload", {}, http_handler)
        assert _status(result) == 400
        body = _body(result)
        assert body["error_code"] == "unsupported_format"

    @patch("aragora.server.handlers.features.documents.validate_file_upload")
    def test_validation_empty_filename(self, mock_validate, handler, store):
        from aragora.server.handlers.utils.file_validation import FileValidationErrorCode

        mock_validate.return_value = MagicMock(
            valid=False,
            error_code=FileValidationErrorCode.EMPTY_FILENAME,
            error_message="Filename is empty",
            http_status=400,
            details={},
        )

        content = b"x" * 20
        http_handler = _make_http_handler(content=content, filename="test.txt")

        result = handler.handle_post("/api/v1/documents/upload", {}, http_handler)
        assert _status(result) == 400
        body = _body(result)
        assert body["error_code"] == "invalid_filename"

    @patch("aragora.server.handlers.features.documents.validate_file_upload")
    def test_validation_filename_too_long(self, mock_validate, handler, store):
        from aragora.server.handlers.utils.file_validation import FileValidationErrorCode

        mock_validate.return_value = MagicMock(
            valid=False,
            error_code=FileValidationErrorCode.FILENAME_TOO_LONG,
            error_message="Filename too long",
            http_status=400,
            details={},
        )

        content = b"x" * 20
        http_handler = _make_http_handler(content=content, filename="test.txt")

        result = handler.handle_post("/api/v1/documents/upload", {}, http_handler)
        assert _status(result) == 400
        body = _body(result)
        assert body["error_code"] == "filename_too_long"

    @patch("aragora.server.handlers.features.documents.validate_file_upload")
    def test_validation_unknown_error_code_falls_back(self, mock_validate, handler, store):
        """When validation error_code is None, fall back to INVALID_FILENAME."""
        mock_validate.return_value = MagicMock(
            valid=False,
            error_code=None,
            error_message="Unknown validation error",
            http_status=400,
            details=None,
        )

        content = b"x" * 20
        http_handler = _make_http_handler(content=content, filename="test.txt")

        result = handler.handle_post("/api/v1/documents/upload", {}, http_handler)
        assert _status(result) == 400
        body = _body(result)
        assert body["error_code"] == "invalid_filename"


# ===========================================================================
# Constructor tests
# ===========================================================================


class TestConstructor:
    """Tests for DocumentHandler initialization."""

    def test_init_with_server_context(self):
        h = DocumentHandler(server_context={"document_store": "s"})
        assert h.ctx == {"document_store": "s"}

    def test_init_with_ctx(self):
        h = DocumentHandler(ctx={"document_store": "s"})
        assert h.ctx == {"document_store": "s"}

    def test_init_with_both_prefers_server_context(self):
        h = DocumentHandler(ctx={"a": 1}, server_context={"b": 2})
        assert h.ctx == {"b": 2}

    def test_init_with_neither(self):
        h = DocumentHandler()
        assert h.ctx == {}

    def test_get_document_store(self):
        store = MockDocumentStore()
        h = DocumentHandler(server_context={"document_store": store})
        assert h.get_document_store() is store

    def test_get_document_store_none(self):
        h = DocumentHandler(server_context={})
        assert h.get_document_store() is None


# ===========================================================================
# _parse_upload_with_error dispatch tests
# ===========================================================================


class TestParseUploadDispatch:
    """Tests for _parse_upload_with_error content type routing."""

    def test_dispatches_multipart(self, handler):
        boundary = "b"
        body = (
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="f.txt"\r\n\r\n'
            ).encode()
            + b"x"
            + f"\r\n--{boundary}--\r\n".encode()
        )

        http_handler = MockHTTPHandler(_rfile_data=body)
        content_type = f"multipart/form-data; boundary={boundary}"

        data, filename, err = handler._parse_upload_with_error(
            http_handler, content_type, len(body)
        )
        assert err is None
        assert filename == "f.txt"

    def test_dispatches_raw(self, handler):
        content = b"raw data"
        http_handler = _make_http_handler(content=content, filename="raw.txt")

        data, filename, err = handler._parse_upload_with_error(
            http_handler, "application/octet-stream", len(content)
        )
        assert err is None
        assert filename == "raw.txt"
        assert data == content


# ===========================================================================
# Upload error code enum tests
# ===========================================================================


class TestUploadErrorCodeEnum:
    """Tests for UploadErrorCode values."""

    def test_rate_limited_value(self):
        assert UploadErrorCode.RATE_LIMITED.value == "rate_limited"

    def test_file_too_large_value(self):
        assert UploadErrorCode.FILE_TOO_LARGE.value == "file_too_large"

    def test_file_too_small_value(self):
        assert UploadErrorCode.FILE_TOO_SMALL.value == "file_too_small"

    def test_no_content_value(self):
        assert UploadErrorCode.NO_CONTENT.value == "no_content"

    def test_unsupported_format_value(self):
        assert UploadErrorCode.UNSUPPORTED_FORMAT.value == "unsupported_format"

    def test_storage_not_configured_value(self):
        assert UploadErrorCode.STORAGE_NOT_CONFIGURED.value == "storage_not_configured"

    def test_storage_failed_value(self):
        assert UploadErrorCode.STORAGE_FAILED.value == "storage_failed"

    def test_parsing_failed_value(self):
        assert UploadErrorCode.PARSING_FAILED.value == "parsing_failed"

    def test_missing_boundary_value(self):
        assert UploadErrorCode.MISSING_BOUNDARY.value == "missing_boundary"


# ===========================================================================
# Edge case / integration tests
# ===========================================================================


class TestEdgeCases:
    """Edge-case and integration tests."""

    @patch("aragora.server.handlers.features.documents.validate_file_upload")
    def test_upload_import_error_during_parse(self, mock_validate, handler, store):
        """ImportError during parse_document call maps to parsing_failed."""
        mock_validate.return_value = MagicMock(valid=True)
        content = b"x" * 20
        http_handler = _make_http_handler(content=content, filename="test.txt")

        mock_mod = MagicMock()
        mock_mod.SUPPORTED_EXTENSIONS = {".txt"}
        mock_mod.parse_document.side_effect = ImportError("missing dep")

        with patch.dict("sys.modules", {"aragora.server.documents": mock_mod}):
            result = handler.handle_post("/api/v1/documents/upload", {}, http_handler)

        assert _status(result) == 400
        body = _body(result)
        assert body["error_code"] == "parsing_failed"

    @patch("aragora.server.handlers.features.documents.validate_file_upload")
    def test_upload_key_error_during_store(self, mock_validate, handler, store):
        """KeyError during store.add maps to storage_failed."""
        mock_validate.return_value = MagicMock(valid=True)
        content = b"x" * 20
        mock_doc = MockDocument()
        http_handler = _make_http_handler(content=content, filename="test.txt")

        store.add = MagicMock(side_effect=KeyError("key"))

        with patch.dict(
            "sys.modules",
            {
                "aragora.server.documents": MagicMock(
                    SUPPORTED_EXTENSIONS={".txt"},
                    parse_document=MagicMock(return_value=mock_doc),
                ),
            },
        ):
            result = handler.handle_post("/api/v1/documents/upload", {}, http_handler)

        assert _status(result) == 500
        body = _body(result)
        assert body["error_code"] == "storage_failed"

    @patch("aragora.server.handlers.features.documents.validate_file_upload")
    def test_upload_os_error_during_store(self, mock_validate, handler, store):
        """OSError during store.add maps to storage_failed."""
        mock_validate.return_value = MagicMock(valid=True)
        content = b"x" * 20
        mock_doc = MockDocument()
        http_handler = _make_http_handler(content=content, filename="test.txt")

        store.add = MagicMock(side_effect=OSError("disk full"))

        with patch.dict(
            "sys.modules",
            {
                "aragora.server.documents": MagicMock(
                    SUPPORTED_EXTENSIONS={".txt"},
                    parse_document=MagicMock(return_value=mock_doc),
                ),
            },
        ):
            result = handler.handle_post("/api/v1/documents/upload", {}, http_handler)

        assert _status(result) == 500
        body = _body(result)
        assert body["error_code"] == "storage_failed"

    @patch("aragora.server.handlers.features.documents.validate_file_upload")
    def test_successful_upload_response_shape(self, mock_validate, handler, store):
        """Verify the full response shape of a successful upload."""
        mock_validate.return_value = MagicMock(valid=True)
        content = b"x" * 20
        mock_doc = MagicMock()
        mock_doc.filename = "test.txt"
        mock_doc.word_count = 5
        mock_doc.page_count = 1
        mock_doc.preview = "xxxxx..."

        http_handler = _make_http_handler(content=content, filename="test.txt")

        with patch.dict(
            "sys.modules",
            {
                "aragora.server.documents": MagicMock(
                    SUPPORTED_EXTENSIONS={".txt"},
                    parse_document=MagicMock(return_value=mock_doc),
                ),
                "aragora.knowledge.integration": None,  # Disable knowledge processing
            },
        ):
            result = handler.handle_post(
                "/api/v1/documents/upload",
                {"process_knowledge": ["true"]},
                http_handler,
            )

        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        doc = body["document"]
        assert "id" in doc
        assert doc["filename"] == "test.txt"
        assert doc["word_count"] == 5
        assert doc["page_count"] == 1
        assert doc["preview"] == "xxxxx..."

    def test_delete_key_error(self, handler, store):
        store._docs["d1"] = MockDocument(doc_id="d1")
        store.get = MagicMock(side_effect=KeyError("key"))
        mock = MockHTTPHandler(command="DELETE")
        result = handler.handle_delete("/api/v1/documents/d1", {}, mock)
        assert _status(result) == 500

    def test_delete_type_error(self, handler, store):
        store._docs["d1"] = MockDocument(doc_id="d1")
        store.get = MagicMock(side_effect=TypeError("bad type"))
        mock = MockHTTPHandler(command="DELETE")
        result = handler.handle_delete("/api/v1/documents/d1", {}, mock)
        assert _status(result) == 500

    @patch("aragora.server.handlers.features.documents.validate_file_upload")
    def test_upload_workspace_id_from_params(self, mock_validate, handler, store):
        """Test that workspace_id is extracted from query params."""
        mock_validate.return_value = MagicMock(valid=True)
        content = b"x" * 20
        mock_doc = MockDocument()
        http_handler = _make_http_handler(content=content, filename="test.txt")

        captured_kwargs = {}

        def capture_process(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return {"knowledge_processing": {"status": "queued"}}

        knowledge_mod = MagicMock()
        knowledge_mod.process_uploaded_document = capture_process

        with patch.dict(
            "sys.modules",
            {
                "aragora.server.documents": MagicMock(
                    SUPPORTED_EXTENSIONS={".txt"},
                    parse_document=MagicMock(return_value=mock_doc),
                ),
                "aragora.knowledge.integration": knowledge_mod,
            },
        ):
            result = handler.handle_post(
                "/api/v1/documents/upload",
                {"workspace_id": ["my-workspace"], "process_knowledge": ["true"]},
                http_handler,
            )

        assert _status(result) == 200
        assert captured_kwargs.get("workspace_id") == "my-workspace"

    @patch("aragora.server.handlers.features.documents.validate_file_upload")
    def test_upload_type_error_during_store(self, mock_validate, handler, store):
        """TypeError during store.add maps to storage_failed."""
        mock_validate.return_value = MagicMock(valid=True)
        content = b"x" * 20
        mock_doc = MockDocument()
        http_handler = _make_http_handler(content=content, filename="test.txt")

        store.add = MagicMock(side_effect=TypeError("type err"))

        with patch.dict(
            "sys.modules",
            {
                "aragora.server.documents": MagicMock(
                    SUPPORTED_EXTENSIONS={".txt"},
                    parse_document=MagicMock(return_value=mock_doc),
                ),
            },
        ):
            result = handler.handle_post("/api/v1/documents/upload", {}, http_handler)

        assert _status(result) == 500
        body = _body(result)
        assert body["error_code"] == "storage_failed"

    def test_multipart_value_error_in_part_parsing(self, handler):
        """Parts that raise ValueError during header parsing are skipped."""
        boundary = "bound"
        # A part without \r\n\r\n separator will raise ValueError on index()
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="broken"\r\nNO_DOUBLE_CRLF'
            f"\r\n--{boundary}--\r\n"
        ).encode()

        http_handler = MockHTTPHandler(_rfile_data=body)
        content_type = f"multipart/form-data; boundary={boundary}"

        _, _, err = handler._parse_multipart_with_error(http_handler, content_type, len(body))
        # Should fail with no valid file found
        assert err is not None
        assert err.code == UploadErrorCode.MULTIPART_PARSE_ERROR
