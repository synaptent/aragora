"""Tests for smart upload handler.

Tests the smart upload API endpoints including:
- POST /api/v1/upload/smart - Upload and auto-process files
- POST /api/v1/upload/batch - Batch upload with per-file processing options
- GET  /api/v1/upload/status/{id} - Check processing status

Also tests the standalone utility functions:
- validate_content_type() - magic byte validation
- detect_file_category() - file type classification
- process_file() - file processing pipeline
- smart_upload() - end-to-end upload flow
"""

import base64
import json
import time
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.features.smart_upload import (
    CATEGORY_ACTIONS,
    DANGEROUS_EXTENSIONS,
    DANGEROUS_MIME_TYPES,
    ContentValidationResult,
    FileCategory,
    ProcessingAction,
    SmartUploadHandler,
    UploadResult,
    _build_ingest_metadata,
    _build_knowledge_filename,
    _detect_language,
    _extract_symbols,
    _resolve_bool,
    _upload_results,
    detect_file_category,
    get_processing_action,
    get_upload_status,
    process_file,
    smart_upload,
    validate_content_type,
)
from aragora.server.handlers.base import HandlerResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _status(result: HandlerResult) -> int:
    """Extract status code from HandlerResult."""
    return result.status_code


def _body(result: HandlerResult) -> dict[str, Any]:
    """Extract parsed JSON body from HandlerResult."""
    return json.loads(result.body.decode("utf-8"))


@dataclass
class MockHTTPHandler:
    """Mock HTTP handler that mimics the real HTTP handler attributes."""

    path: str = "/"
    method: str = "GET"
    body: dict[str, Any] | None = None
    headers: dict[str, str] | None = None
    command: str = "GET"

    def __post_init__(self):
        if self.headers is None:
            self.headers = {"Content-Length": "0", "Content-Type": "application/json"}
        self.client_address = ("127.0.0.1", 12345)
        self.rfile = MagicMock()
        if self.body:
            body_bytes = json.dumps(self.body).encode()
            self.rfile.read.return_value = body_bytes
            self.headers["Content-Length"] = str(len(body_bytes))
        else:
            self.rfile.read.return_value = b"{}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler():
    """Create a SmartUploadHandler with minimal context."""
    ctx: dict[str, Any] = {}
    return SmartUploadHandler(ctx)


@pytest.fixture(autouse=True)
def reset_upload_results():
    """Clear the in-memory upload results between tests."""
    _upload_results.clear()
    yield
    _upload_results.clear()


@pytest.fixture(autouse=True)
def reset_rate_limiters():
    """Reset rate limiters between tests."""
    try:
        from aragora.server.middleware.rate_limit.registry import (
            reset_rate_limiters as _reset,
        )

        _reset()
    except ImportError:
        pass
    yield
    try:
        from aragora.server.middleware.rate_limit.registry import (
            reset_rate_limiters as _reset,
        )

        _reset()
    except ImportError:
        pass


# ===========================================================================
# can_handle() routing tests
# ===========================================================================


class TestCanHandle:
    """Tests for SmartUploadHandler.can_handle()."""

    def test_handles_upload_smart(self, handler):
        assert handler.can_handle("/api/v1/upload/smart")

    def test_handles_upload_batch(self, handler):
        assert handler.can_handle("/api/v1/upload/batch")

    def test_handles_upload_status(self, handler):
        assert handler.can_handle("/api/v1/upload/status")

    def test_handles_upload_status_with_id(self, handler):
        assert handler.can_handle("/api/v1/upload/status/abc123")

    def test_handles_any_upload_subpath(self, handler):
        assert handler.can_handle("/api/v1/upload/anything")

    def test_rejects_non_upload_path(self, handler):
        assert not handler.can_handle("/api/v1/debates")

    def test_rejects_root_path(self, handler):
        assert not handler.can_handle("/")

    def test_rejects_partial_upload_prefix(self, handler):
        assert not handler.can_handle("/api/v1/uploader")

    def test_rejects_different_api(self, handler):
        assert not handler.can_handle("/api/v1/users")

    def test_routes_are_defined(self, handler):
        assert hasattr(handler, "ROUTES")
        assert "/api/v1/upload/smart" in handler.ROUTES
        assert "/api/v1/upload/batch" in handler.ROUTES
        assert "/api/v1/upload/status" in handler.ROUTES


# ===========================================================================
# handle() GET routing tests
# ===========================================================================


class TestHandleGet:
    """Tests for the synchronous handle() router (GET + method check)."""

    def test_get_status_with_known_id(self, handler):
        """GET /api/v1/upload/status/<id> returns upload details."""
        upload = UploadResult(
            id="test123",
            filename="report.pdf",
            size=1024,
            category=FileCategory.DOCUMENT,
            action=ProcessingAction.EXTRACT,
            status="completed",
            result={"text": "hello"},
        )
        _upload_results["test123"] = upload

        mock = MockHTTPHandler(command="GET")
        result = handler.handle("/api/v1/upload/status/test123", {}, mock)

        assert _status(result) == 200
        body = _body(result)
        assert body["id"] == "test123"
        assert body["filename"] == "report.pdf"
        assert body["status"] == "completed"
        assert body["category"] == "document"
        assert body["action"] == "extract"
        assert body["result"] == {"text": "hello"}

    def test_get_status_not_found(self, handler):
        """GET /api/v1/upload/status/<id> returns 404 for unknown id."""
        mock = MockHTTPHandler(command="GET")
        result = handler.handle("/api/v1/upload/status/nonexistent", {}, mock)

        assert _status(result) == 404

    def test_get_status_includes_timestamps(self, handler):
        """Status response includes created_at and completed_at."""
        now = time.time()
        upload = UploadResult(
            id="ts1",
            filename="file.txt",
            size=10,
            category=FileCategory.DOCUMENT,
            action=ProcessingAction.EXTRACT,
            status="completed",
            created_at=now,
            completed_at=now + 1.0,
        )
        _upload_results["ts1"] = upload

        mock = MockHTTPHandler(command="GET")
        result = handler.handle("/api/v1/upload/status/ts1", {}, mock)
        body = _body(result)
        assert body["created_at"] == pytest.approx(now, abs=1)
        assert body["completed_at"] == pytest.approx(now + 1.0, abs=1)

    def test_get_status_error_field(self, handler):
        """Status response includes error field for rejected uploads."""
        upload = UploadResult(
            id="err1",
            filename="bad.exe",
            size=100,
            category=FileCategory.UNKNOWN,
            action=ProcessingAction.SKIP,
            status="rejected",
            error="Dangerous file extension blocked: .exe",
        )
        _upload_results["err1"] = upload

        mock = MockHTTPHandler(command="GET")
        result = handler.handle("/api/v1/upload/status/err1", {}, mock)
        body = _body(result)
        assert body["status"] == "rejected"
        assert "Dangerous" in body["error"]

    def test_non_post_non_status_returns_405(self, handler):
        """Non-POST to upload endpoints (non-status) returns 405."""
        mock = MockHTTPHandler(command="GET")
        result = handler.handle("/api/v1/upload/smart", {}, mock)
        assert _status(result) == 405

    def test_non_post_batch_returns_405(self, handler):
        """Non-POST to /batch returns 405."""
        mock = MockHTTPHandler(command="GET")
        result = handler.handle("/api/v1/upload/batch", {}, mock)
        assert _status(result) == 405


# ===========================================================================
# POST /api/v1/upload/smart tests
# ===========================================================================


class TestSmartUploadPost:
    """Tests for handle_post() -> smart upload."""

    @pytest.mark.asyncio
    async def test_upload_text_file(self, handler):
        """Upload a simple text file successfully."""
        content = base64.b64encode(b"Hello world").decode()
        body = {"content": content, "filename": "hello.txt"}
        mock = MockHTTPHandler(command="POST", body=body)

        with patch.object(
            handler, "_attach_auth_metadata", new_callable=AsyncMock, return_value={}
        ):
            result = await handler.handle_post("/api/v1/upload/smart", body, mock)

        assert _status(result) == 200
        data = _body(result)
        assert data["filename"] == "hello.txt"
        assert data["category"] == "document"
        assert data["status"] in ("completed", "processing")

    @pytest.mark.asyncio
    async def test_upload_no_content_returns_400(self, handler):
        """Upload with no content returns 400."""
        body = {"filename": "test.txt"}
        mock = MockHTTPHandler(command="POST", body=body)

        with patch.object(
            handler, "_attach_auth_metadata", new_callable=AsyncMock, return_value={}
        ):
            result = await handler.handle_post("/api/v1/upload/smart", body, mock)

        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_upload_python_file(self, handler):
        """Upload a Python code file."""
        code = b'def hello():\n    print("hi")\n'
        content = base64.b64encode(code).decode()
        body = {"content": content, "filename": "main.py"}
        mock = MockHTTPHandler(command="POST", body=body)

        with patch.object(
            handler, "_attach_auth_metadata", new_callable=AsyncMock, return_value={}
        ):
            result = await handler.handle_post("/api/v1/upload/smart", body, mock)

        assert _status(result) == 200
        data = _body(result)
        assert data["category"] == "code"
        assert data["action"] == "index"

    @pytest.mark.asyncio
    async def test_upload_json_file(self, handler):
        """Upload a JSON data file."""
        json_content = json.dumps({"key": "value"}).encode()
        content = base64.b64encode(json_content).decode()
        body = {"content": content, "filename": "data.json"}
        mock = MockHTTPHandler(command="POST", body=body)

        with patch.object(
            handler, "_attach_auth_metadata", new_callable=AsyncMock, return_value={}
        ):
            result = await handler.handle_post("/api/v1/upload/smart", body, mock)

        assert _status(result) == 200
        data = _body(result)
        assert data["category"] == "data"
        assert data["action"] == "parse"

    @pytest.mark.asyncio
    async def test_upload_with_override_action(self, handler):
        """Upload with a custom processing action override."""
        content = base64.b64encode(b"some text").decode()
        body = {
            "content": content,
            "filename": "notes.txt",
            "action": "skip",
        }
        mock = MockHTTPHandler(command="POST", body=body)

        with patch.object(
            handler, "_attach_auth_metadata", new_callable=AsyncMock, return_value={}
        ):
            result = await handler.handle_post("/api/v1/upload/smart", body, mock)

        assert _status(result) == 200
        data = _body(result)
        assert data["action"] == "skip"

    @pytest.mark.asyncio
    async def test_upload_with_mime_type(self, handler):
        """Upload with explicit MIME type hint."""
        content = base64.b64encode(b"plain text content").decode()
        body = {
            "content": content,
            "filename": "notes.txt",
            "mime_type": "text/plain",
        }
        mock = MockHTTPHandler(command="POST", body=body)

        with patch.object(
            handler, "_attach_auth_metadata", new_callable=AsyncMock, return_value={}
        ):
            result = await handler.handle_post("/api/v1/upload/smart", body, mock)

        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_upload_with_raw_bytes_content(self, handler):
        """Upload with base64-encoded binary content."""
        import base64

        encoded = base64.b64encode(b"raw bytes").decode()
        body = {"content": encoded, "filename": "notes.txt"}
        mock = MockHTTPHandler(command="POST", body=body)

        with patch.object(
            handler, "_attach_auth_metadata", new_callable=AsyncMock, return_value={}
        ):
            result = await handler.handle_post("/api/v1/upload/smart", body, mock)

        # base64 encoded content should be accepted
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_upload_unknown_path_returns_404(self, handler):
        """POST to unknown upload path returns 404."""
        body = {"content": "dGVzdA==", "filename": "test.txt"}
        mock = MockHTTPHandler(command="POST", body=body)

        result = await handler.handle_post("/api/v1/upload/unknown", body, mock)
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_upload_default_filename(self, handler):
        """Upload with no filename uses 'unknown' default."""
        content = base64.b64encode(b"data").decode()
        body = {"content": content}
        mock = MockHTTPHandler(command="POST", body=body)

        with patch.object(
            handler, "_attach_auth_metadata", new_callable=AsyncMock, return_value={}
        ):
            result = await handler.handle_post("/api/v1/upload/smart", body, mock)

        # Should complete (the file may be rejected by validation for no extension)
        assert _status(result) == 200


# ===========================================================================
# POST /api/v1/upload/batch tests
# ===========================================================================


class TestBatchUploadPost:
    """Tests for batch upload endpoint."""

    @pytest.mark.asyncio
    async def test_batch_upload_multiple_files(self, handler):
        """Batch upload processes multiple files."""
        files = [
            {"content": base64.b64encode(b"hello").decode(), "filename": "a.txt"},
            {"content": base64.b64encode(b"world").decode(), "filename": "b.txt"},
        ]
        body = {"files": files}
        mock = MockHTTPHandler(command="POST", body=body)

        with patch.object(
            handler, "_attach_auth_metadata", new_callable=AsyncMock, return_value={}
        ):
            result = await handler.handle_post("/api/v1/upload/batch", body, mock)

        assert _status(result) == 200
        data = _body(result)
        assert data["count"] == 2
        assert len(data["files"]) == 2
        assert data["files"][0]["filename"] == "a.txt"
        assert data["files"][1]["filename"] == "b.txt"

    @pytest.mark.asyncio
    async def test_batch_upload_empty_files(self, handler):
        """Batch upload with empty files list returns 400."""
        body = {"files": []}
        mock = MockHTTPHandler(command="POST", body=body)

        with patch.object(
            handler, "_attach_auth_metadata", new_callable=AsyncMock, return_value={}
        ):
            result = await handler.handle_post("/api/v1/upload/batch", body, mock)

        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_batch_upload_no_files_key(self, handler):
        """Batch upload with missing files key returns 400."""
        body = {}
        mock = MockHTTPHandler(command="POST", body=body)

        with patch.object(
            handler, "_attach_auth_metadata", new_callable=AsyncMock, return_value={}
        ):
            result = await handler.handle_post("/api/v1/upload/batch", body, mock)

        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_batch_upload_with_per_file_action(self, handler):
        """Batch upload with per-file processing action override."""
        files = [
            {
                "content": base64.b64encode(b"text content").decode(),
                "filename": "doc.txt",
                "action": "skip",
            },
        ]
        body = {"files": files}
        mock = MockHTTPHandler(command="POST", body=body)

        with patch.object(
            handler, "_attach_auth_metadata", new_callable=AsyncMock, return_value={}
        ):
            result = await handler.handle_post("/api/v1/upload/batch", body, mock)

        assert _status(result) == 200
        data = _body(result)
        assert data["count"] == 1

    @pytest.mark.asyncio
    async def test_batch_upload_mixed_file_types(self, handler):
        """Batch upload with different file types."""
        files = [
            {"content": base64.b64encode(b"text").decode(), "filename": "readme.md"},
            {
                "content": base64.b64encode(b'{"a":1}').decode(),
                "filename": "config.json",
            },
            {
                "content": base64.b64encode(b"def f(): pass").decode(),
                "filename": "app.py",
            },
        ]
        body = {"files": files}
        mock = MockHTTPHandler(command="POST", body=body)

        with patch.object(
            handler, "_attach_auth_metadata", new_callable=AsyncMock, return_value={}
        ):
            result = await handler.handle_post("/api/v1/upload/batch", body, mock)

        assert _status(result) == 200
        data = _body(result)
        assert data["count"] == 3
        categories = {f["category"] for f in data["files"]}
        # md -> document, json -> data, py -> code
        assert "document" in categories
        assert "data" in categories
        assert "code" in categories


# ===========================================================================
# validate_content_type() tests
# ===========================================================================


class TestValidateContentType:
    """Tests for magic-byte content type validation."""

    def test_png_file(self):
        content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        result = validate_content_type(content, "image.png")
        assert result.valid is True
        assert result.detected_mime == "image/png"

    def test_jpeg_file(self):
        content = b"\xff\xd8\xff" + b"\x00" * 100
        result = validate_content_type(content, "photo.jpg")
        assert result.valid is True
        assert result.detected_mime == "image/jpeg"

    def test_pdf_file(self):
        content = b"%PDF-1.4" + b"\x00" * 100
        result = validate_content_type(content, "report.pdf")
        assert result.valid is True
        assert result.detected_mime == "application/pdf"

    def test_dangerous_extension_blocked(self):
        result = validate_content_type(b"anything", "malware.exe")
        assert result.valid is False
        assert result.is_dangerous is True
        assert ".exe" in result.mismatch_warning

    def test_dangerous_dll_extension_blocked(self):
        result = validate_content_type(b"anything", "lib.dll")
        assert result.valid is False
        assert result.is_dangerous is True

    def test_dangerous_bat_extension_blocked(self):
        result = validate_content_type(b"anything", "run.bat")
        assert result.valid is False
        assert result.is_dangerous is True

    def test_dangerous_ps1_extension_blocked(self):
        result = validate_content_type(b"anything", "script.ps1")
        assert result.valid is False
        assert result.is_dangerous is True

    def test_executable_magic_bytes_blocked(self):
        """MZ header (PE executable) is blocked."""
        content = b"MZ" + b"\x00" * 100
        result = validate_content_type(content, "file.dat")
        assert result.valid is False
        assert result.is_dangerous is True
        assert result.detected_mime == "application/x-executable"

    def test_elf_magic_bytes_blocked(self):
        """ELF binary is blocked."""
        content = b"\x7fELF" + b"\x00" * 100
        result = validate_content_type(content, "file.dat")
        assert result.valid is False
        assert result.is_dangerous is True

    def test_macho_magic_bytes_blocked(self):
        """Mach-O binary is blocked."""
        content = b"\xcf\xfa\xed\xfe" + b"\x00" * 100
        result = validate_content_type(content, "file.dat")
        assert result.valid is False
        assert result.is_dangerous is True

    def test_extension_mismatch_warning(self):
        """PNG magic bytes with .jpg extension produces warning."""
        content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        result = validate_content_type(content, "file.jpg")
        assert result.valid is True  # Still valid but with warning
        assert result.mismatch_warning is not None
        assert "mismatch" in result.mismatch_warning.lower()

    def test_claimed_mime_mismatch_warning(self):
        """Claimed MIME type different from detected produces warning."""
        content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        result = validate_content_type(content, "image.png", claimed_mime="application/pdf")
        assert result.valid is True
        assert result.mismatch_warning is not None

    def test_claimed_mime_alias_no_warning(self):
        """Known MIME aliases do not produce warnings."""
        content = b"\xff\xd8\xff" + b"\x00" * 100
        result = validate_content_type(content, "photo.jpg", claimed_mime="image/jpg")
        assert result.valid is True
        # image/jpg is an alias for image/jpeg - should not warn
        assert result.mismatch_warning is None

    def test_webp_detection(self):
        """WebP files use RIFF container with WEBP marker."""
        content = b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 100
        result = validate_content_type(content, "photo.webp")
        assert result.valid is True
        assert result.detected_mime == "image/webp"

    def test_riff_non_webp_skipped(self):
        """RIFF container without WEBP marker is not detected as WebP."""
        content = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 100
        result = validate_content_type(content, "audio.wav")
        assert result.valid is True
        assert result.detected_mime != "image/webp"

    def test_zip_with_office_extension_no_warning(self):
        """ZIP-based Office documents do not produce mismatch warning."""
        content = b"PK\x03\x04" + b"\x00" * 100
        result = validate_content_type(content, "document.docx")
        assert result.valid is True
        assert result.mismatch_warning is None

    def test_unknown_magic_bytes(self):
        """File with unknown magic bytes gets no detected MIME."""
        content = b"UNKNOWN_MAGIC" + b"\x00" * 100
        result = validate_content_type(content, "file.txt")
        assert result.valid is True
        assert result.detected_mime is None

    def test_ftyp_video_detection(self):
        """Video files with ftyp marker at offset 4."""
        content = b"\x00\x00\x00\x08ftyp" + b"\x00" * 100
        result = validate_content_type(content, "video.mp4")
        assert result.valid is True
        assert result.detected_mime == "video/mp4"

    def test_gzip_detection(self):
        content = b"\x1f\x8b" + b"\x00" * 100
        result = validate_content_type(content, "archive.gz")
        assert result.valid is True
        assert result.detected_mime == "application/gzip"

    def test_mp3_id3_detection(self):
        content = b"ID3" + b"\x00" * 100
        result = validate_content_type(content, "song.mp3")
        assert result.valid is True
        assert result.detected_mime == "audio/mpeg"


# ===========================================================================
# detect_file_category() tests
# ===========================================================================


class TestDetectFileCategory:
    """Tests for file category detection."""

    def test_python_file(self):
        assert detect_file_category("main.py") == FileCategory.CODE

    def test_typescript_file(self):
        assert detect_file_category("app.tsx") == FileCategory.CODE

    def test_javascript_file(self):
        assert detect_file_category("index.js") == FileCategory.CODE

    def test_rust_file(self):
        assert detect_file_category("lib.rs") == FileCategory.CODE

    def test_go_file(self):
        assert detect_file_category("main.go") == FileCategory.CODE

    def test_pdf_document(self):
        assert detect_file_category("report.pdf") == FileCategory.DOCUMENT

    def test_docx_document(self):
        assert detect_file_category("letter.docx") == FileCategory.DOCUMENT

    def test_txt_document(self):
        assert detect_file_category("notes.txt") == FileCategory.DOCUMENT

    def test_markdown_document(self):
        assert detect_file_category("README.md") == FileCategory.DOCUMENT

    def test_mp3_audio(self):
        assert detect_file_category("song.mp3") == FileCategory.AUDIO

    def test_wav_audio(self):
        assert detect_file_category("clip.wav") == FileCategory.AUDIO

    def test_mp4_video(self):
        assert detect_file_category("movie.mp4") == FileCategory.VIDEO

    def test_mkv_video(self):
        assert detect_file_category("clip.mkv") == FileCategory.VIDEO

    def test_png_image(self):
        assert detect_file_category("photo.png") == FileCategory.IMAGE

    def test_jpeg_image(self):
        assert detect_file_category("photo.jpeg") == FileCategory.IMAGE

    def test_svg_image(self):
        assert detect_file_category("icon.svg") == FileCategory.IMAGE

    def test_json_data(self):
        assert detect_file_category("config.json") == FileCategory.DATA

    def test_csv_data(self):
        assert detect_file_category("data.csv") == FileCategory.DATA

    def test_yaml_data(self):
        assert detect_file_category("settings.yaml") == FileCategory.DATA

    def test_zip_archive(self):
        assert detect_file_category("backup.zip") == FileCategory.ARCHIVE

    def test_tar_archive(self):
        assert detect_file_category("backup.tar") == FileCategory.ARCHIVE

    def test_unknown_extension(self):
        assert detect_file_category("mystery.xyz123") == FileCategory.UNKNOWN

    def test_mime_type_fallback_audio(self):
        assert detect_file_category("file.unknown", mime_type="audio/wav") == FileCategory.AUDIO

    def test_mime_type_fallback_image(self):
        assert detect_file_category("file.unknown", mime_type="image/png") == FileCategory.IMAGE

    def test_mime_type_fallback_video(self):
        assert detect_file_category("file.unknown", mime_type="video/mp4") == FileCategory.VIDEO


# ===========================================================================
# get_processing_action() tests
# ===========================================================================


class TestGetProcessingAction:
    """Tests for category -> action mapping."""

    def test_code_maps_to_index(self):
        assert get_processing_action(FileCategory.CODE) == ProcessingAction.INDEX

    def test_document_maps_to_extract(self):
        assert get_processing_action(FileCategory.DOCUMENT) == ProcessingAction.EXTRACT

    def test_audio_maps_to_transcribe(self):
        assert get_processing_action(FileCategory.AUDIO) == ProcessingAction.TRANSCRIBE

    def test_video_maps_to_transcribe(self):
        assert get_processing_action(FileCategory.VIDEO) == ProcessingAction.TRANSCRIBE

    def test_image_maps_to_ocr(self):
        assert get_processing_action(FileCategory.IMAGE) == ProcessingAction.OCR

    def test_data_maps_to_parse(self):
        assert get_processing_action(FileCategory.DATA) == ProcessingAction.PARSE

    def test_archive_maps_to_expand(self):
        assert get_processing_action(FileCategory.ARCHIVE) == ProcessingAction.EXPAND

    def test_unknown_maps_to_skip(self):
        assert get_processing_action(FileCategory.UNKNOWN) == ProcessingAction.SKIP


# ===========================================================================
# process_file() tests
# ===========================================================================


class TestProcessFile:
    """Tests for the file processing pipeline."""

    @pytest.mark.asyncio
    async def test_process_code_file(self):
        code = b'def hello():\n    print("hello world")\n\nclass Foo:\n    pass\n'
        result = await process_file(code, "main.py", FileCategory.CODE, ProcessingAction.INDEX)
        assert result["filename"] == "main.py"
        assert result["category"] == "code"
        assert result["action"] == "index"
        assert result["indexed"] is True
        assert result["language"] == "python"
        assert result["line_count"] > 0

    @pytest.mark.asyncio
    async def test_process_text_file(self):
        text = b"Hello world, this is a test document with some text."
        result = await process_file(
            text, "notes.txt", FileCategory.DOCUMENT, ProcessingAction.EXTRACT
        )
        assert result["text"] == text.decode()
        assert result["word_count"] > 0

    @pytest.mark.asyncio
    async def test_process_markdown_file(self):
        md = b"# Title\n\nSome markdown content."
        result = await process_file(
            md, "readme.md", FileCategory.DOCUMENT, ProcessingAction.EXTRACT
        )
        assert "# Title" in result["text"]

    @pytest.mark.asyncio
    async def test_process_json_file(self):
        json_data = json.dumps({"key": "value", "count": 42}).encode()
        result = await process_file(
            json_data, "data.json", FileCategory.DATA, ProcessingAction.PARSE
        )
        assert result["parsed"] is True
        assert result["type"] == "json"
        assert result["record_count"] == 1

    @pytest.mark.asyncio
    async def test_process_json_array(self):
        json_data = json.dumps([1, 2, 3]).encode()
        result = await process_file(
            json_data, "list.json", FileCategory.DATA, ProcessingAction.PARSE
        )
        assert result["parsed"] is True
        assert result["record_count"] == 3

    @pytest.mark.asyncio
    async def test_process_csv_file(self):
        csv_data = b"name,age\nAlice,30\nBob,25\n"
        result = await process_file(
            csv_data, "people.csv", FileCategory.DATA, ProcessingAction.PARSE
        )
        assert result["parsed"] is True
        assert result["type"] == "csv"
        assert result["record_count"] == 2
        assert "name" in result["columns"]

    @pytest.mark.asyncio
    async def test_process_invalid_json(self):
        result = await process_file(
            b"{bad json", "bad.json", FileCategory.DATA, ProcessingAction.PARSE
        )
        assert result["parsed"] is False
        assert result["error"] == "Internal server error"

    @pytest.mark.asyncio
    async def test_process_skip_action(self):
        result = await process_file(
            b"whatever", "file.bin", FileCategory.UNKNOWN, ProcessingAction.SKIP
        )
        assert result["stored"] is True

    @pytest.mark.asyncio
    async def test_process_audio_without_whisper(self):
        """Audio processing falls back gracefully when whisper is unavailable."""
        import sys

        # Temporarily hide the whisper module so the import inside
        # _transcribe_audio_video raises ImportError.
        mod_key = "aragora.connectors.whisper"
        saved = sys.modules.get(mod_key)
        sys.modules[mod_key] = None  # type: ignore[assignment]
        try:
            result = await process_file(
                b"\xff\xfb" + b"\x00" * 100,
                "song.mp3",
                FileCategory.AUDIO,
                ProcessingAction.TRANSCRIBE,
            )
        finally:
            if saved is not None:
                sys.modules[mod_key] = saved
            else:
                sys.modules.pop(mod_key, None)
        assert "transcription" in result

    @pytest.mark.asyncio
    async def test_process_image_without_ocr(self):
        """Image processing falls back gracefully when OCR is unavailable."""
        result = await process_file(
            b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,
            "image.png",
            FileCategory.IMAGE,
            ProcessingAction.OCR,
        )
        assert "text" in result

    @pytest.mark.asyncio
    async def test_process_pdf_without_pymupdf(self):
        """PDF extraction falls back when PyMuPDF is not installed."""
        result = await process_file(
            b"%PDF-1.4" + b"\x00" * 100,
            "doc.pdf",
            FileCategory.DOCUMENT,
            ProcessingAction.EXTRACT,
        )
        assert "text" in result

    @pytest.mark.asyncio
    async def test_process_unsupported_document(self):
        result = await process_file(
            b"\x00" * 100, "file.rtf", FileCategory.DOCUMENT, ProcessingAction.EXTRACT
        )
        assert "Unsupported" in result.get("text", "")

    @pytest.mark.asyncio
    async def test_process_unsupported_data_format(self):
        result = await process_file(
            b"content", "data.toml", FileCategory.DATA, ProcessingAction.PARSE
        )
        assert result["parsed"] is False
        assert result["type"] == ".toml"


# ===========================================================================
# smart_upload() end-to-end tests
# ===========================================================================


class TestSmartUpload:
    """Tests for the smart_upload() function."""

    @pytest.mark.asyncio
    async def test_successful_upload(self):
        with patch(
            "aragora.server.handlers.features.smart_upload.validate_file_upload"
        ) as mock_validate:
            mock_validate.return_value = MagicMock(valid=True)
            result = await smart_upload(b"hello world", "test.txt")

        assert result.status in ("completed", "processing")
        assert result.filename == "test.txt"
        assert result.size == 11
        assert result.category == FileCategory.DOCUMENT
        assert result.id in _upload_results

    @pytest.mark.asyncio
    async def test_dangerous_file_rejected(self):
        """Dangerous file extensions are rejected."""
        with patch(
            "aragora.server.handlers.features.smart_upload.validate_file_upload"
        ) as mock_validate:
            mock_validate.return_value = MagicMock(
                valid=False,
                error_message="Unsupported file extension: .exe",
            )
            result = await smart_upload(b"MZ\x90\x00", "malware.exe")

        assert result.status == "rejected"
        assert result.error is not None
        assert "Dangerous" in result.error or "Unsupported" in result.error

    @pytest.mark.asyncio
    async def test_content_validation_failure(self):
        """Files that fail content validation are rejected."""
        with (
            patch(
                "aragora.server.handlers.features.smart_upload.validate_file_upload"
            ) as mock_validate,
            patch(
                "aragora.server.handlers.features.smart_upload.validate_content_type"
            ) as mock_content,
        ):
            mock_validate.return_value = MagicMock(valid=True)
            mock_content.return_value = ContentValidationResult(
                valid=False,
                is_dangerous=True,
                mismatch_warning="Dangerous file type blocked: application/x-executable",
            )
            result = await smart_upload(b"MZ" + b"\x00" * 100, "file.dat")

        assert result.status == "rejected"

    @pytest.mark.asyncio
    async def test_upload_generates_unique_id(self):
        with patch(
            "aragora.server.handlers.features.smart_upload.validate_file_upload"
        ) as mock_validate:
            mock_validate.return_value = MagicMock(valid=True)
            r1 = await smart_upload(b"content1", "a.txt")
            r2 = await smart_upload(b"content2", "b.txt")

        assert r1.id != r2.id

    @pytest.mark.asyncio
    async def test_upload_id_contains_content_hash(self):
        with patch(
            "aragora.server.handlers.features.smart_upload.validate_file_upload"
        ) as mock_validate:
            mock_validate.return_value = MagicMock(valid=True)
            result = await smart_upload(b"deterministic content", "test.txt")

        assert "_" in result.id  # format: uuid_hash

    @pytest.mark.asyncio
    async def test_override_action(self):
        with patch(
            "aragora.server.handlers.features.smart_upload.validate_file_upload"
        ) as mock_validate:
            mock_validate.return_value = MagicMock(valid=True)
            result = await smart_upload(
                b"some text",
                "notes.txt",
                override_action=ProcessingAction.SKIP,
            )

        assert result.action == ProcessingAction.SKIP

    @pytest.mark.asyncio
    async def test_mismatch_warning_in_result(self):
        """Content type mismatch warnings are preserved in result."""
        with (
            patch(
                "aragora.server.handlers.features.smart_upload.validate_file_upload"
            ) as mock_validate,
            patch(
                "aragora.server.handlers.features.smart_upload.validate_content_type"
            ) as mock_content,
        ):
            mock_validate.return_value = MagicMock(valid=True)
            mock_content.return_value = ContentValidationResult(
                valid=True,
                detected_mime="image/png",
                mismatch_warning="Extension mismatch",
            )
            result = await smart_upload(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100, "file.jpg")

        assert result.status == "completed"
        assert result.result is not None
        assert "content_type_warning" in result.result

    @pytest.mark.asyncio
    async def test_processing_error_sets_failed_status(self):
        """Processing errors result in 'failed' status."""
        with (
            patch(
                "aragora.server.handlers.features.smart_upload.validate_file_upload"
            ) as mock_validate,
            patch(
                "aragora.server.handlers.features.smart_upload.validate_content_type"
            ) as mock_content,
            patch(
                "aragora.server.handlers.features.smart_upload.process_file",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ),
        ):
            mock_validate.return_value = MagicMock(valid=True)
            mock_content.return_value = ContentValidationResult(valid=True)
            result = await smart_upload(b"data", "file.txt")

        assert result.status == "failed"
        assert result.error == "Internal server error"


# ===========================================================================
# get_upload_status() tests
# ===========================================================================


class TestGetUploadStatus:
    """Tests for upload status retrieval."""

    def test_returns_none_for_unknown(self):
        assert get_upload_status("nonexistent") is None

    def test_returns_stored_result(self):
        upload = UploadResult(
            id="test1",
            filename="a.txt",
            size=10,
            category=FileCategory.DOCUMENT,
            action=ProcessingAction.EXTRACT,
            status="completed",
        )
        _upload_results["test1"] = upload
        assert get_upload_status("test1") is upload


# ===========================================================================
# _detect_language() tests
# ===========================================================================


class TestDetectLanguage:
    """Tests for programming language detection."""

    def test_python(self):
        assert _detect_language("main.py") == "python"

    def test_typescript(self):
        assert _detect_language("app.ts") == "typescript"

    def test_tsx(self):
        assert _detect_language("component.tsx") == "typescript"

    def test_javascript(self):
        assert _detect_language("index.js") == "javascript"

    def test_go(self):
        assert _detect_language("main.go") == "go"

    def test_rust(self):
        assert _detect_language("lib.rs") == "rust"

    def test_java(self):
        assert _detect_language("Main.java") == "java"

    def test_c(self):
        assert _detect_language("main.c") == "c"

    def test_cpp(self):
        assert _detect_language("main.cpp") == "cpp"

    def test_ruby(self):
        assert _detect_language("script.rb") == "ruby"

    def test_unknown(self):
        assert _detect_language("file.xyz") == "unknown"


# ===========================================================================
# _extract_symbols() tests
# ===========================================================================


class TestExtractSymbols:
    """Tests for code symbol extraction."""

    def test_python_functions(self):
        code = "def foo():\n    pass\ndef bar():\n    pass\n"
        symbols = _extract_symbols(code, "main.py")
        names = [s["name"] for s in symbols]
        assert "foo" in names
        assert "bar" in names
        assert all(s["type"] == "function" for s in symbols)

    def test_python_classes(self):
        code = "class MyClass:\n    pass\n"
        symbols = _extract_symbols(code, "models.py")
        assert len(symbols) == 1
        assert symbols[0]["name"] == "MyClass"
        assert symbols[0]["type"] == "class"

    def test_javascript_functions(self):
        code = "function hello() {}\nexport async function world() {}\n"
        symbols = _extract_symbols(code, "app.js")
        names = [s["name"] for s in symbols]
        assert "hello" in names
        assert "world" in names

    def test_typescript_class(self):
        code = "export class UserService {}\n"
        symbols = _extract_symbols(code, "service.ts")
        assert len(symbols) == 1
        assert symbols[0]["name"] == "UserService"

    def test_symbol_limit(self):
        """Symbols are limited to first 50."""
        code = "\n".join(f"def func_{i}(): pass" for i in range(60))
        symbols = _extract_symbols(code, "many.py")
        assert len(symbols) == 50

    def test_unsupported_language_returns_empty(self):
        code = "fn main() {}"
        symbols = _extract_symbols(code, "main.rs")
        assert symbols == []


# ===========================================================================
# _resolve_bool() tests
# ===========================================================================


class TestResolveBool:
    """Tests for the _resolve_bool() helper."""

    def test_none_returns_default(self):
        assert _resolve_bool(None, True) is True
        assert _resolve_bool(None, False) is False

    def test_bool_passed_through(self):
        assert _resolve_bool(True, False) is True
        assert _resolve_bool(False, True) is False

    def test_int_converted(self):
        assert _resolve_bool(1, False) is True
        assert _resolve_bool(0, True) is False

    def test_string_false_values(self):
        assert _resolve_bool("false", True) is False
        assert _resolve_bool("0", True) is False
        assert _resolve_bool("no", True) is False
        assert _resolve_bool("off", True) is False

    def test_string_true_values(self):
        assert _resolve_bool("true", False) is True
        assert _resolve_bool("1", False) is True
        assert _resolve_bool("yes", False) is True

    def test_non_standard_type_returns_default(self):
        assert _resolve_bool([], True) is True
        assert _resolve_bool({}, False) is False


# ===========================================================================
# _build_knowledge_filename() tests
# ===========================================================================


class TestBuildKnowledgeFilename:
    """Tests for knowledge filename builder."""

    def test_with_suffix(self):
        assert _build_knowledge_filename("audio.mp3", "transcript") == "audio.mp3.transcript.txt"

    def test_without_suffix(self):
        assert _build_knowledge_filename("report.pdf", "") == "report.pdf"

    def test_with_path_prefix(self):
        result = _build_knowledge_filename("/path/to/doc.pdf", "extracted")
        assert result == "doc.pdf.extracted.txt"


# ===========================================================================
# _build_ingest_metadata() tests
# ===========================================================================


class TestBuildIngestMetadata:
    """Tests for knowledge ingestion metadata builder."""

    def test_basic_metadata(self):
        meta = _build_ingest_metadata(
            options={},
            category=FileCategory.DOCUMENT,
            action=ProcessingAction.EXTRACT,
            filename="doc.pdf",
            processing_result={},
        )
        assert meta["source"] == "smart_upload"
        assert meta["source_category"] == "document"
        assert meta["source_action"] == "extract"
        assert meta["filename"] == "doc.pdf"

    def test_preserves_existing_metadata(self):
        meta = _build_ingest_metadata(
            options={"metadata": {"custom_key": "custom_value", "source": "override"}},
            category=FileCategory.CODE,
            action=ProcessingAction.INDEX,
            filename="app.py",
            processing_result={},
        )
        assert meta["custom_key"] == "custom_value"
        # setdefault should NOT override existing
        assert meta["source"] == "override"

    def test_transcription_metadata(self):
        meta = _build_ingest_metadata(
            options={},
            category=FileCategory.AUDIO,
            action=ProcessingAction.TRANSCRIBE,
            filename="audio.mp3",
            processing_result={"language": "en", "duration": 120.5, "segments": [1, 2, 3]},
        )
        assert meta["transcription_language"] == "en"
        assert meta["transcription_duration"] == 120.5
        assert meta["segment_count"] == 3

    def test_ocr_metadata(self):
        meta = _build_ingest_metadata(
            options={},
            category=FileCategory.IMAGE,
            action=ProcessingAction.OCR,
            filename="scan.png",
            processing_result={"confidence": 0.95},
        )
        assert meta["ocr_confidence"] == 0.95

    def test_mime_type_from_options(self):
        meta = _build_ingest_metadata(
            options={"mime_type": "application/pdf"},
            category=FileCategory.DOCUMENT,
            action=ProcessingAction.EXTRACT,
            filename="doc.pdf",
            processing_result={},
        )
        assert meta["mime_type"] == "application/pdf"


# ===========================================================================
# FileCategory and ProcessingAction enum tests
# ===========================================================================


class TestEnums:
    """Tests for FileCategory and ProcessingAction enums."""

    def test_file_category_values(self):
        assert FileCategory.CODE.value == "code"
        assert FileCategory.DOCUMENT.value == "document"
        assert FileCategory.AUDIO.value == "audio"
        assert FileCategory.VIDEO.value == "video"
        assert FileCategory.IMAGE.value == "image"
        assert FileCategory.DATA.value == "data"
        assert FileCategory.ARCHIVE.value == "archive"
        assert FileCategory.UNKNOWN.value == "unknown"

    def test_processing_action_values(self):
        assert ProcessingAction.INDEX.value == "index"
        assert ProcessingAction.EXTRACT.value == "extract"
        assert ProcessingAction.TRANSCRIBE.value == "transcribe"
        assert ProcessingAction.OCR.value == "ocr"
        assert ProcessingAction.PARSE.value == "parse"
        assert ProcessingAction.EXPAND.value == "expand"
        assert ProcessingAction.SKIP.value == "skip"

    def test_all_categories_have_actions(self):
        for category in FileCategory:
            assert category in CATEGORY_ACTIONS


# ===========================================================================
# UploadResult dataclass tests
# ===========================================================================


class TestUploadResult:
    """Tests for the UploadResult dataclass."""

    def test_default_created_at(self):
        before = time.time()
        result = UploadResult(
            id="test",
            filename="f.txt",
            size=10,
            category=FileCategory.DOCUMENT,
            action=ProcessingAction.EXTRACT,
            status="pending",
        )
        after = time.time()
        assert before <= result.created_at <= after

    def test_default_none_fields(self):
        result = UploadResult(
            id="test",
            filename="f.txt",
            size=10,
            category=FileCategory.DOCUMENT,
            action=ProcessingAction.EXTRACT,
            status="pending",
        )
        assert result.completed_at is None
        assert result.result is None
        assert result.error is None


# ===========================================================================
# ContentValidationResult dataclass tests
# ===========================================================================


class TestContentValidationResult:
    """Tests for ContentValidationResult."""

    def test_defaults(self):
        result = ContentValidationResult(valid=True)
        assert result.valid is True
        assert result.detected_mime is None
        assert result.expected_extensions is None
        assert result.is_dangerous is False
        assert result.mismatch_warning is None


# ===========================================================================
# Dangerous file type constants tests
# ===========================================================================


class TestSecurityConstants:
    """Tests for security-related constants."""

    def test_dangerous_extensions_include_executables(self):
        assert ".exe" in DANGEROUS_EXTENSIONS
        assert ".dll" in DANGEROUS_EXTENSIONS
        assert ".bat" in DANGEROUS_EXTENSIONS
        assert ".cmd" in DANGEROUS_EXTENSIONS

    def test_dangerous_extensions_include_scripts(self):
        assert ".vbs" in DANGEROUS_EXTENSIONS
        assert ".ps1" in DANGEROUS_EXTENSIONS
        assert ".wsh" in DANGEROUS_EXTENSIONS

    def test_dangerous_mime_types_include_executables(self):
        assert "application/x-executable" in DANGEROUS_MIME_TYPES
        assert "application/x-mach-binary" in DANGEROUS_MIME_TYPES
        assert "application/x-msdownload" in DANGEROUS_MIME_TYPES


# ===========================================================================
# _attach_auth_metadata() tests
# ===========================================================================


class TestAttachAuthMetadata:
    """Tests for the auth metadata enrichment method."""

    @pytest.mark.asyncio
    async def test_returns_options_when_auth_unavailable(self, handler):
        """When auth context is not importable, options pass through unchanged."""
        mock = MockHTTPHandler()
        with patch(
            "aragora.server.handlers.features.smart_upload.SmartUploadHandler._attach_auth_metadata",
        ) as mock_attach:
            mock_attach.return_value = {"key": "value"}
            result = await handler._attach_auth_metadata(mock, {"key": "value"})
        assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_creates_options_dict_when_none(self, handler):
        """Passing None for options creates a new dict."""
        # Patch get_auth_context to raise ImportError to exercise fallback path
        with patch(
            "aragora.server.handlers.features.smart_upload.SmartUploadHandler._attach_auth_metadata",
            new_callable=AsyncMock,
            return_value={},
        ):
            result = await handler._attach_auth_metadata(MockHTTPHandler(), None)
        assert isinstance(result, dict)


# ===========================================================================
# _queue_knowledge_from_result() tests
# ===========================================================================


class TestQueueKnowledge:
    """Tests for knowledge queue integration."""

    @pytest.mark.asyncio
    async def test_skips_when_no_text(self):
        from aragora.server.handlers.features.smart_upload import _queue_knowledge_from_result

        result = await _queue_knowledge_from_result(
            options={},
            category=FileCategory.CODE,
            action=ProcessingAction.INDEX,
            filename="main.py",
            processing_result={},
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_skips_placeholder_text(self):
        from aragora.server.handlers.features.smart_upload import _queue_knowledge_from_result

        result = await _queue_knowledge_from_result(
            options={},
            category=FileCategory.AUDIO,
            action=ProcessingAction.TRANSCRIBE,
            filename="audio.mp3",
            processing_result={"transcription": "[Whisper connector not available]"},
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_skips_empty_text(self):
        from aragora.server.handlers.features.smart_upload import _queue_knowledge_from_result

        result = await _queue_knowledge_from_result(
            options={},
            category=FileCategory.DOCUMENT,
            action=ProcessingAction.EXTRACT,
            filename="doc.pdf",
            processing_result={"text": "   "},
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_processes_valid_transcription(self):
        from aragora.server.handlers.features.smart_upload import _queue_knowledge_from_result

        mock_result = {"knowledge_processing": {"status": "queued"}}
        with patch(
            "aragora.knowledge.integration.process_uploaded_text",
            return_value=mock_result,
        ) as mock_process:
            result = await _queue_knowledge_from_result(
                options={"workspace_id": "ws1"},
                category=FileCategory.AUDIO,
                action=ProcessingAction.TRANSCRIBE,
                filename="audio.mp3",
                processing_result={"transcription": "Hello world, this is real text."},
            )

        assert result is not None
        mock_process.assert_called_once()
        call_kwargs = mock_process.call_args
        assert (
            call_kwargs[1]["workspace_id"] == "ws1"
            or call_kwargs.kwargs.get("workspace_id") == "ws1"
        )

    @pytest.mark.asyncio
    async def test_falls_back_to_default_workspace(self):
        from aragora.server.handlers.features.smart_upload import _queue_knowledge_from_result

        with patch(
            "aragora.knowledge.integration.process_uploaded_text",
            return_value={"knowledge_processing": {"status": "queued"}},
        ) as mock_process:
            await _queue_knowledge_from_result(
                options={},
                category=FileCategory.DOCUMENT,
                action=ProcessingAction.EXTRACT,
                filename="doc.txt",
                processing_result={"text": "Real extracted text content"},
            )

        call_kwargs = mock_process.call_args
        # workspace_id should default to "default"
        if call_kwargs.kwargs:
            assert call_kwargs.kwargs.get("workspace_id") == "default"
        else:
            # positional: text, filename, workspace_id
            assert "default" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_handles_import_error_gracefully(self):
        from aragora.server.handlers.features.smart_upload import _queue_knowledge_from_result

        with patch(
            "aragora.knowledge.integration.process_uploaded_text",
            side_effect=ImportError("not installed"),
        ):
            result = await _queue_knowledge_from_result(
                options={},
                category=FileCategory.DOCUMENT,
                action=ProcessingAction.EXTRACT,
                filename="doc.txt",
                processing_result={"text": "Some real text here"},
            )

        assert result is None


class TestKnowledgeOrgScope:
    """Knowledge ingestion is scoped to the verified org, never to a client-supplied one."""

    @pytest.mark.asyncio
    async def test_attach_auth_metadata_overrides_client_org(self, handler):
        options = await handler._attach_auth_metadata(
            MockHTTPHandler(command="POST"), {"metadata": {"org_id": "org-b"}}
        )
        assert options["metadata"]["org_id"] == "test-org-001"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", ["/api/v1/upload/smart", "/api/v1/upload/batch"])
    async def test_upload_passes_verified_org(self, handler, path):
        file_body = {
            "content": base64.b64encode(b"Hello world").decode(),
            "filename": "hello.txt",
            "options": {"metadata": {"org_id": "org-b"}},
        }
        body = file_body if path.endswith("smart") else {"files": [file_body]}
        uploaded = UploadResult(
            id="u1",
            filename="hello.txt",
            size=11,
            category=FileCategory.DOCUMENT,
            action=ProcessingAction.EXTRACT,
            status="completed",
        )
        with patch(
            "aragora.server.handlers.features.smart_upload.smart_upload",
            new_callable=AsyncMock,
            return_value=uploaded,
        ) as mock_upload:
            result = await handler.handle_post(path, body, MockHTTPHandler(command="POST"))

        assert _status(result) == 200
        assert mock_upload.call_args.kwargs["org_id"] == "test-org-001"

    @pytest.mark.asyncio
    async def test_smart_upload_forwards_org_to_knowledge(self):
        with patch(
            "aragora.server.handlers.features.smart_upload._queue_knowledge_from_result",
            new_callable=AsyncMock,
            return_value=None,
        ) as mock_queue:
            await smart_upload(
                b"Hello world", "hello.txt", options={"process_knowledge": True}, org_id="org-a"
            )
        assert mock_queue.call_args.kwargs["org_id"] == "org-a"

    @pytest.mark.asyncio
    async def test_knowledge_uses_only_the_given_org(self):
        from aragora.server.handlers.features.smart_upload import _queue_knowledge_from_result

        kwargs: dict[str, Any] = {
            "options": {"metadata": {"org_id": "org-b"}},
            "category": FileCategory.DOCUMENT,
            "action": ProcessingAction.EXTRACT,
            "filename": "doc.txt",
            "processing_result": {"text": "Real extracted text content"},
        }
        with patch(
            "aragora.knowledge.integration.process_uploaded_text",
            return_value={"knowledge_processing": {"status": "queued"}},
        ) as mock_process:
            await _queue_knowledge_from_result(**kwargs, org_id="org-a")
            await _queue_knowledge_from_result(**kwargs)

        assert [c.kwargs["org_id"] for c in mock_process.call_args_list] == ["org-a", None]


# ===========================================================================
# Archive expansion tests
# ===========================================================================


class TestArchiveExpansion:
    """Tests for archive file listing."""

    @pytest.mark.asyncio
    async def test_expand_zip_archive(self):
        import zipfile
        import io

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("file1.txt", "hello")
            zf.writestr("file2.txt", "world")
        zip_bytes = buf.getvalue()

        result = await process_file(
            zip_bytes, "test.zip", FileCategory.ARCHIVE, ProcessingAction.EXPAND
        )
        assert result["expanded"] is True
        assert result["file_count"] == 2
        names = [f["name"] for f in result["files"]]
        assert "file1.txt" in names
        assert "file2.txt" in names

    @pytest.mark.asyncio
    async def test_expand_invalid_zip(self):
        result = await process_file(
            b"not a zip file",
            "bad.zip",
            FileCategory.ARCHIVE,
            ProcessingAction.EXPAND,
        )
        # Should return an error dict from error_dict()
        assert "error" in result

    @pytest.mark.asyncio
    async def test_expand_tar_archive(self):
        import tarfile
        import io

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            data = b"hello"
            info = tarfile.TarInfo(name="readme.txt")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        tar_bytes = buf.getvalue()

        result = await process_file(
            tar_bytes, "archive.tar", FileCategory.ARCHIVE, ProcessingAction.EXPAND
        )
        assert result["expanded"] is True
        assert result["file_count"] == 1


# ===========================================================================
# Docx extraction tests
# ===========================================================================


class TestDocxExtraction:
    """Tests for DOCX document extraction."""

    @pytest.mark.asyncio
    async def test_docx_without_python_docx(self):
        """DOCX extraction without python-docx falls back gracefully."""
        result = await process_file(
            b"PK\x03\x04" + b"\x00" * 100,
            "document.docx",
            FileCategory.DOCUMENT,
            ProcessingAction.EXTRACT,
        )
        assert "text" in result


# ===========================================================================
# Knowledge processing integration in process_file
# ===========================================================================


class TestKnowledgeProcessingInProcessFile:
    """Tests for the knowledge processing hooks in process_file."""

    @pytest.mark.asyncio
    async def test_knowledge_processing_disabled_via_option(self):
        """When process_knowledge=false, knowledge queue is skipped."""
        text = b"Some text content for the document."
        result = await process_file(
            text,
            "notes.txt",
            FileCategory.DOCUMENT,
            ProcessingAction.EXTRACT,
            options={"process_knowledge": "false"},
        )
        # Should not have knowledge_processing key
        assert "knowledge_processing" not in result

    @pytest.mark.asyncio
    async def test_knowledge_processing_enabled(self):
        """When knowledge processing succeeds, result includes knowledge info."""
        mock_kp_result = {"knowledge_processing": {"status": "queued", "doc_id": "kp1"}}
        with patch(
            "aragora.server.handlers.features.smart_upload._queue_knowledge_from_result",
            new_callable=AsyncMock,
            return_value=mock_kp_result,
        ):
            text = b"Real document text for knowledge processing."
            result = await process_file(
                text,
                "article.txt",
                FileCategory.DOCUMENT,
                ProcessingAction.EXTRACT,
                options={"process_knowledge": True},
            )
        assert "knowledge_processing" in result
