"""Tests for the DocumentHandler class."""

import json
import pytest
from collections import OrderedDict
from unittest.mock import Mock, MagicMock, patch


@pytest.fixture(autouse=True)
def mock_auth():
    """Mock auth to return a valid user context for all tests."""
    mock_user = Mock()
    mock_user.user_id = "test-user-123"
    mock_user.org_id = "test-org-456"
    mock_user.email = "test@example.com"
    mock_user.is_authenticated = True
    mock_user.error_reason = None
    # Patch the jwt_auth module that gets imported at runtime
    with patch("aragora.billing.jwt_auth.extract_user_from_request", return_value=mock_user):
        yield


class TestDocumentHandlerRouting:
    """Test route matching for DocumentHandler."""

    @pytest.fixture
    def doc_handler(self):
        from aragora.server.handlers.features import DocumentHandler

        ctx = {"document_store": None}
        return DocumentHandler(ctx)

    def test_can_handle_documents_list(self, doc_handler):
        assert doc_handler.can_handle("/api/v1/documents") is True

    def test_can_handle_documents_formats(self, doc_handler):
        assert doc_handler.can_handle("/api/v1/documents/formats") is True

    def test_can_handle_document_by_id(self, doc_handler):
        assert doc_handler.can_handle("/api/v1/documents/abc123") is True

    def test_cannot_handle_nested_path(self, doc_handler):
        assert doc_handler.can_handle("/api/v1/documents/abc/nested") is False

    def test_cannot_handle_unknown_route(self, doc_handler):
        assert doc_handler.can_handle("/api/v1/other") is False


class TestListDocumentsEndpoint:
    """Test /api/documents endpoint."""

    @pytest.fixture
    def mock_store(self):
        store = Mock()
        store.list_for_org.return_value = [
            {"id": "doc1", "filename": "test.pdf", "word_count": 100},
            {"id": "doc2", "filename": "other.txt", "word_count": 50},
        ]
        return store

    @pytest.fixture
    def doc_handler(self, mock_store):
        from aragora.server.handlers.features import DocumentHandler

        ctx = {"document_store": mock_store}
        return DocumentHandler(ctx)

    def test_list_documents_returns_documents(self, doc_handler, mock_store):
        result = doc_handler.handle("/api/v1/documents", {}, None)
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["count"] == 2
        assert len(data["documents"]) == 2
        mock_store.list_for_org.assert_called_once_with("test-org-456")
        mock_store.list_all.assert_not_called()

    def test_list_documents_no_store_returns_empty(self):
        from aragora.server.handlers.features import DocumentHandler

        ctx = {"document_store": None}
        handler = DocumentHandler(ctx)
        result = handler.handle("/api/v1/documents", {}, None)
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["count"] == 0
        assert data["documents"] == []
        assert "error" in data


class TestFormatsEndpoint:
    """Test /api/documents/formats endpoint."""

    @pytest.fixture
    def doc_handler(self):
        from aragora.server.handlers.features import DocumentHandler

        ctx = {"document_store": None}
        return DocumentHandler(ctx)

    def test_formats_returns_supported_types(self, doc_handler):
        result = doc_handler.handle("/api/v1/documents/formats", {}, None)
        assert result.status_code == 200
        data = json.loads(result.body)
        # Should return some format information
        assert isinstance(data, dict)


class TestGetDocumentEndpoint:
    """Test /api/documents/{id} endpoint."""

    @pytest.fixture
    def mock_store(self):
        store = Mock()
        doc = Mock()
        doc.org_id = "test-org-456"
        doc.to_dict.return_value = {
            "id": "doc123",
            "filename": "test.pdf",
            "content": "Hello world",
        }
        store.get.return_value = doc
        return store

    @pytest.fixture
    def doc_handler(self, mock_store):
        from aragora.server.handlers.features import DocumentHandler

        ctx = {"document_store": mock_store}
        return DocumentHandler(ctx)

    def test_get_document_returns_doc(self, doc_handler, mock_store):
        result = doc_handler.handle("/api/v1/documents/doc123", {}, None)
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["id"] == "doc123"
        assert data["filename"] == "test.pdf"
        mock_store.get.assert_called_once_with("doc123")

    def test_get_document_not_found(self, doc_handler, mock_store):
        mock_store.get.return_value = None
        result = doc_handler.handle("/api/v1/documents/missing", {}, None)
        assert result.status_code == 404
        data = json.loads(result.body)
        assert data == {"error": "Document not found", "code": "not_found"}

    @pytest.mark.parametrize("owner", ["other-org", None])
    def test_get_document_of_another_or_unknown_owner_is_not_found(
        self, doc_handler, mock_store, owner
    ):
        mock_store.get.return_value.org_id = owner
        result = doc_handler.handle("/api/v1/documents/doc123", {}, None)
        assert result.status_code == 404
        assert json.loads(result.body) == {"error": "Document not found", "code": "not_found"}

    def test_get_document_no_store_returns_500(self):
        from aragora.server.handlers.features import DocumentHandler

        ctx = {"document_store": None}
        handler = DocumentHandler(ctx)
        result = handler.handle("/api/v1/documents/doc123", {}, None)
        assert result.status_code == 500


class TestDocumentIdValidation:
    """Test document ID validation."""

    @pytest.fixture
    def doc_handler(self):
        from aragora.server.handlers.features import DocumentHandler

        store = Mock()
        store.get.return_value = None  # Document not found
        ctx = {"document_store": store}
        return DocumentHandler(ctx)

    def test_path_traversal_in_id_blocked(self, doc_handler):
        # ID with path traversal pattern embedded
        result = doc_handler.handle("/api/v1/documents/doc..id", {}, None)
        # Should return 400 for invalid ID (contains ..)
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "error" in data

    def test_special_chars_blocked(self, doc_handler):
        result = doc_handler.handle("/api/v1/documents/doc;rm", {}, None)
        assert result.status_code == 400

    def test_valid_id_accepted(self, doc_handler):
        result = doc_handler.handle("/api/v1/documents/valid-doc-123", {}, None)
        # Should proceed to check store (returns 404 since mock returns None)
        assert result.status_code == 404


class TestDocumentUploadEndpoint:
    """Test POST /api/documents/upload endpoint."""

    @pytest.fixture
    def mock_store(self):
        store = Mock()
        store.add.return_value = "doc-new-123"
        return store

    @pytest.fixture
    def doc_handler(self, mock_store):
        from aragora.server.handlers.features import DocumentHandler

        ctx = {"document_store": mock_store}
        handler = DocumentHandler(ctx)
        # Reset rate limits for test isolation
        DocumentHandler._upload_counts = OrderedDict()
        return handler

    @pytest.fixture
    def mock_http_handler(self):
        handler = Mock()
        handler.client_address = ("127.0.0.1", 12345)
        handler.headers = {"Content-Length": "100", "Content-Type": "text/plain"}
        handler.rfile = Mock()
        return handler

    def test_upload_no_store_returns_500(self, mock_http_handler):
        from aragora.server.handlers.features import DocumentHandler

        ctx = {"document_store": None}
        handler = DocumentHandler(ctx)
        DocumentHandler._upload_counts = OrderedDict()

        result = handler.handle_post("/api/v1/documents/upload", {}, mock_http_handler)
        assert result.status_code == 500
        data = json.loads(result.body)
        assert "storage not configured" in data["error"].lower()

    def test_upload_no_content_returns_400(self, doc_handler, mock_http_handler):
        mock_http_handler.headers = {"Content-Length": "0"}

        result = doc_handler.handle_post("/api/v1/documents/upload", {}, mock_http_handler)
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "no content" in data["error"].lower()

    def test_upload_file_too_large_returns_413(self, doc_handler, mock_http_handler):
        # Set content length to > 100MB (MAX_FILE_SIZE default)
        mock_http_handler.headers = {"Content-Length": str(101 * 1024 * 1024)}

        result = doc_handler.handle_post("/api/v1/documents/upload", {}, mock_http_handler)
        assert result.status_code == 413
        data = json.loads(result.body)
        assert "too large" in data["error"].lower()

    def test_upload_invalid_content_length_returns_400(self, doc_handler, mock_http_handler):
        mock_http_handler.headers = {"Content-Length": "not-a-number"}

        result = doc_handler.handle_post("/api/v1/documents/upload", {}, mock_http_handler)
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "content-length" in data["error"].lower()

    def test_upload_returns_none_for_other_routes(self, doc_handler, mock_http_handler):
        result = doc_handler.handle_post("/api/v1/documents/other", {}, mock_http_handler)
        assert result is None


class TestDocumentUploadRateLimiting:
    """Test rate limiting for document uploads."""

    @pytest.fixture
    def mock_store(self):
        store = Mock()
        store.add.return_value = "doc-new"
        return store

    @pytest.fixture
    def doc_handler(self, mock_store):
        from aragora.server.handlers.features import DocumentHandler

        ctx = {"document_store": mock_store}
        handler = DocumentHandler(ctx)
        # Reset rate limits for test isolation
        DocumentHandler._upload_counts = OrderedDict()
        return handler

    @pytest.fixture
    def mock_http_handler(self):
        handler = Mock()
        handler.client_address = ("192.168.1.100", 12345)
        handler.headers = {"Content-Length": "0"}
        return handler

    def test_rate_limit_tracks_per_ip(self, doc_handler, mock_http_handler):
        from aragora.server.handlers.features import DocumentHandler

        # First few requests should pass rate limit check
        for _ in range(4):
            result = doc_handler._check_upload_rate_limit(mock_http_handler)
            assert result is None  # None means allowed

    def test_rate_limit_blocks_after_per_minute_limit(self, doc_handler, mock_http_handler):
        from aragora.server.handlers.features import DocumentHandler

        # Exhaust the per-minute limit
        for _ in range(DocumentHandler.MAX_UPLOADS_PER_MINUTE):
            result = doc_handler._check_upload_rate_limit(mock_http_handler)
            assert result is None

        # Next request should be blocked
        result = doc_handler._check_upload_rate_limit(mock_http_handler)
        assert result is not None
        assert result.status_code == 429
        data = json.loads(result.body)
        assert "per minute" in data["error"].lower()

    def test_rate_limit_different_ips_independent(self, doc_handler):
        from aragora.server.handlers.features import DocumentHandler

        handler1 = Mock()
        handler1.client_address = ("1.1.1.1", 12345)

        handler2 = Mock()
        handler2.client_address = ("2.2.2.2", 12345)

        # Exhaust limit for IP1
        for _ in range(DocumentHandler.MAX_UPLOADS_PER_MINUTE):
            doc_handler._check_upload_rate_limit(handler1)

        # IP2 should still be allowed
        result = doc_handler._check_upload_rate_limit(handler2)
        assert result is None


class TestDocumentUploadParsing:
    """Test upload content parsing."""

    @pytest.fixture
    def mock_store(self):
        store = Mock()
        store.add.return_value = "doc-uploaded"
        return store

    @pytest.fixture
    def doc_handler(self, mock_store):
        from aragora.server.handlers.features import DocumentHandler

        ctx = {"document_store": mock_store}
        handler = DocumentHandler(ctx)
        DocumentHandler._upload_counts = OrderedDict()
        return handler

    def test_parse_raw_upload_extracts_filename(self, doc_handler):
        handler = Mock()
        handler.headers = {"X-Filename": "myfile.txt"}
        handler.rfile.read.return_value = b"file content"

        content, filename = doc_handler._parse_raw_upload(handler, 12)
        assert content == b"file content"
        assert filename == "myfile.txt"

    def test_parse_raw_upload_sanitizes_path_traversal(self, doc_handler):
        """Path traversal attempts are sanitized using os.path.basename."""
        handler = Mock()
        handler.headers = {"X-Filename": "../../../etc/passwd"}
        handler.rfile.read.return_value = b"file content"

        content, filename = doc_handler._parse_raw_upload(handler, 12)
        # os.path.basename sanitizes path traversal to just "passwd"
        assert content == b"file content"
        assert filename == "passwd"
        # The important thing is the path is stripped, not that it's rejected

    def test_parse_raw_upload_rejects_null_byte(self, doc_handler):
        handler = Mock()
        handler.headers = {"X-Filename": "file\x00name.txt"}
        handler.rfile.read.return_value = b"file content"

        content, filename = doc_handler._parse_raw_upload(handler, 12)
        assert content is None
        assert filename is None

    def test_parse_raw_upload_sanitizes_path(self, doc_handler):
        handler = Mock()
        handler.headers = {"X-Filename": "/path/to/myfile.txt"}
        handler.rfile.read.return_value = b"file content"

        content, filename = doc_handler._parse_raw_upload(handler, 12)
        assert content == b"file content"
        # os.path.basename should strip path
        assert filename == "myfile.txt"

    def test_parse_multipart_extracts_file(self, doc_handler):
        handler = Mock()

        # Create a minimal multipart body
        boundary = "----WebKitFormBoundary"
        body = (
            b"------WebKitFormBoundary\r\n"
            b'Content-Disposition: form-data; name="file"; filename="test.txt"\r\n'
            b"Content-Type: text/plain\r\n"
            b"\r\n"
            b"Hello World\r\n"
            b"------WebKitFormBoundary--\r\n"
        )
        handler.rfile.read.return_value = body

        content_type = f"multipart/form-data; boundary={boundary}"
        content, filename = doc_handler._parse_multipart(handler, content_type, len(body))

        assert filename == "test.txt"
        assert b"Hello World" in content

    def test_parse_multipart_sanitizes_path_traversal_filename(self, doc_handler):
        """Path traversal in multipart is sanitized using os.path.basename."""
        handler = Mock()

        boundary = "----WebKitFormBoundary"
        body = (
            b"------WebKitFormBoundary\r\n"
            b'Content-Disposition: form-data; name="file"; filename="../../../etc/passwd"\r\n'
            b"Content-Type: text/plain\r\n"
            b"\r\n"
            b"malicious content\r\n"
            b"------WebKitFormBoundary--\r\n"
        )
        handler.rfile.read.return_value = body

        content_type = f"multipart/form-data; boundary={boundary}"
        content, filename = doc_handler._parse_multipart(handler, content_type, len(body))

        # os.path.basename sanitizes "../../../etc/passwd" to "passwd"
        assert filename == "passwd"
        assert b"malicious content" in content

    def test_parse_multipart_rejects_dotdot_in_basename(self, doc_handler):
        """Filenames containing '..' after basename extraction are rejected."""
        handler = Mock()

        boundary = "----WebKitFormBoundary"
        body = (
            b"------WebKitFormBoundary\r\n"
            b'Content-Disposition: form-data; name="file"; filename="file..name.txt"\r\n'
            b"Content-Type: text/plain\r\n"
            b"\r\n"
            b"content\r\n"
            b"------WebKitFormBoundary--\r\n"
        )
        handler.rfile.read.return_value = body

        content_type = f"multipart/form-data; boundary={boundary}"
        content, filename = doc_handler._parse_multipart(handler, content_type, len(body))

        # Filename contains ".." so it's rejected
        assert content is None
        assert filename is None

    def test_parse_multipart_rejects_null_byte_filename(self, doc_handler):
        handler = Mock()

        boundary = "----WebKitFormBoundary"
        body = (
            b"------WebKitFormBoundary\r\n"
            b'Content-Disposition: form-data; name="file"; filename="test\x00.txt"\r\n'
            b"Content-Type: text/plain\r\n"
            b"\r\n"
            b"content\r\n"
            b"------WebKitFormBoundary--\r\n"
        )
        handler.rfile.read.return_value = body

        content_type = f"multipart/form-data; boundary={boundary}"
        content, filename = doc_handler._parse_multipart(handler, content_type, len(body))

        assert content is None
        assert filename is None

    def test_parse_multipart_no_boundary_returns_none(self, doc_handler):
        handler = Mock()
        handler.rfile.read.return_value = b"some content"

        content_type = "multipart/form-data"  # Missing boundary
        content, filename = doc_handler._parse_multipart(handler, content_type, 12)

        assert content is None
        assert filename is None

    def test_parse_multipart_rejects_too_many_parts(self, doc_handler):
        handler = Mock()

        # Create multipart with many parts (DoS protection)
        boundary = "----WebKitFormBoundary"
        parts = []
        for i in range(15):  # MAX_MULTIPART_PARTS is 10
            parts.append(
                f"------WebKitFormBoundary\r\n"
                f'Content-Disposition: form-data; name="field{i}"\r\n'
                f"\r\n"
                f"value{i}\r\n"
            )
        parts.append("------WebKitFormBoundary--\r\n")
        body = "".join(parts).encode()
        handler.rfile.read.return_value = body

        content_type = f"multipart/form-data; boundary={boundary}"
        content, filename = doc_handler._parse_multipart(handler, content_type, len(body))

        assert content is None
        assert filename is None


class TestDocumentHandlerGetClientIP:
    """Test client IP extraction."""

    @pytest.fixture
    def doc_handler(self):
        from aragora.server.handlers.features import DocumentHandler

        ctx = {"document_store": None}
        return DocumentHandler(ctx)

    def test_extracts_ip_from_client_address(self, doc_handler):
        handler = Mock()
        handler.client_address = ("192.168.1.50", 54321)

        ip = doc_handler._get_client_ip(handler)
        assert ip == "192.168.1.50"

    def test_returns_unknown_when_no_client_address(self, doc_handler):
        handler = Mock(spec=[])  # No client_address attribute

        ip = doc_handler._get_client_ip(handler)
        assert ip == "unknown"


class TestDocumentListException:
    """Test exception handling in document listing."""

    @pytest.fixture
    def mock_store(self):
        store = Mock()
        store.list_all.side_effect = OSError("Database error")
        return store

    @pytest.fixture
    def doc_handler(self, mock_store):
        from aragora.server.handlers.features import DocumentHandler

        ctx = {"document_store": mock_store}
        return DocumentHandler(ctx)

    def test_list_documents_exception_returns_500(self, doc_handler):
        result = doc_handler.handle("/api/v1/documents", {}, None)
        assert result.status_code == 500
        data = json.loads(result.body)
        assert "error" in data


class TestDocumentGetException:
    """Test exception handling in document retrieval."""

    @pytest.fixture
    def mock_store(self):
        store = Mock()
        store.get.side_effect = OSError("Storage error")
        return store

    @pytest.fixture
    def doc_handler(self, mock_store):
        from aragora.server.handlers.features import DocumentHandler

        ctx = {"document_store": mock_store}
        return DocumentHandler(ctx)

    def test_get_document_exception_returns_500(self, doc_handler):
        result = doc_handler.handle("/api/v1/documents/doc123", {}, None)
        assert result.status_code == 500
        data = json.loads(result.body)
        assert "error" in data
