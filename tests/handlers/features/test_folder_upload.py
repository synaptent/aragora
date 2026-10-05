"""Tests for folder upload handler.

Tests the folder upload API endpoints including:
- POST /api/v1/documents/folder/scan - Scan a folder and return what would be uploaded
- POST /api/v1/documents/folder/upload - Start folder upload
- GET /api/v1/documents/folder/upload/{folder_id}/status - Get upload progress
- GET /api/v1/documents/folders - List uploaded folder sets
- GET /api/v1/documents/folders/{folder_id} - Get folder details
- DELETE /api/v1/documents/folders/{folder_id} - Delete an uploaded folder set

Also tests:
- Path validation and traversal prevention
- FolderUploadJob data model
- FolderUploadStatus enum
- Background upload job lifecycle
- Error handling for missing paths, invalid bodies, etc.
"""

import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.base import HandlerResult
from aragora.server.handlers.features.folder_upload import (
    FolderUploadHandler,
    FolderUploadJob,
    FolderUploadStatus,
)
from aragora.server.handlers.features import folder_upload
from aragora.documents.folder.import_roots import org_import_roots
from aragora.tenancy.record_scope import OrgScope

SCOPE = OrgScope(org_id="test-org-001", user_id="test-user-001", role="admin")


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
    command: str = "POST"
    headers: dict[str, str] = field(
        default_factory=lambda: {
            "Content-Length": "0",
            "Content-Type": "application/json",
        }
    )
    client_address: tuple = ("127.0.0.1", 12345)
    _body: dict[str, Any] | None = None

    def __post_init__(self):
        self.rfile = MagicMock()
        if self._body is not None:
            body_bytes = json.dumps(self._body).encode()
            self.rfile.read.return_value = body_bytes
            self.headers = {
                "Content-Length": str(len(body_bytes)),
                "Content-Type": "application/json",
            }
        else:
            self.rfile.read.return_value = b"{}"
            self.headers = {
                "Content-Length": "2",
                "Content-Type": "application/json",
            }


def _make_http(body: dict[str, Any] | None = None) -> MockHTTPHandler:
    """Build a MockHTTPHandler with given JSON body."""
    return MockHTTPHandler(_body=body)


def _make_job(
    folder_id: str | None = None,
    status: FolderUploadStatus = FolderUploadStatus.COMPLETED,
    user_id: str | None = "test-user-001",
    org_id: str | None = "test-org-001",
    included_count: int = 5,
    files_uploaded: int = 5,
    total_files_found: int = 10,
    excluded_count: int = 5,
    total_size_bytes: int = 10240,
    bytes_uploaded: int = 10240,
    files_failed: int = 0,
    document_ids: list[str] | None = None,
    errors: list[dict] | None = None,
    config: dict | None = None,
    created_at: datetime | None = None,
) -> FolderUploadJob:
    """Build a FolderUploadJob with reasonable defaults."""
    now = created_at or datetime.now(timezone.utc)
    return FolderUploadJob(
        folder_id=folder_id or str(uuid.uuid4()),
        root_path="/tmp/test-folder",
        status=status,
        created_at=now,
        updated_at=now,
        user_id=user_id,
        org_id=org_id,
        total_files_found=total_files_found,
        included_count=included_count,
        excluded_count=excluded_count,
        total_size_bytes=total_size_bytes,
        files_uploaded=files_uploaded,
        files_failed=files_failed,
        bytes_uploaded=bytes_uploaded,
        document_ids=document_ids or [],
        errors=errors or [],
        config=config or {},
    )


def _mock_folder_module(scanner=None, config_cls=None):
    """Create a mock aragora.documents.folder module for sys.modules patching."""
    mock_config_instance = MagicMock()
    mock_config_instance.exclude_patterns = []
    if config_cls is None:
        config_cls = MagicMock(return_value=mock_config_instance)

    mod = MagicMock()
    mod.FolderScanner = MagicMock(return_value=scanner) if scanner else MagicMock()
    mod.FolderUploadConfig = config_cls
    return mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler():
    """Create a FolderUploadHandler with minimal context."""
    return FolderUploadHandler(ctx={})


@pytest.fixture
def mock_user_ctx():
    """Create a mock authenticated user context."""
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
    """Authenticate every request as test-user-001 of test-org-001."""
    with patch(
        "aragora.billing.jwt_auth.extract_user_from_request",
        return_value=mock_user_ctx,
    ):
        yield


@pytest.fixture(autouse=True)
def clear_jobs():
    """Clear the in-memory job storage between tests."""
    FolderUploadHandler._jobs.clear()
    yield
    FolderUploadHandler._jobs.clear()


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


def _allow(monkeypatch, *roots: Path) -> None:
    """Make ``roots`` the import roots of test-org-001."""
    roots_json = json.dumps({"test-org-001": [str(root) for root in roots]})
    monkeypatch.setenv("ARAGORA_ORG_IMPORT_ROOTS", roots_json)


def _validate_upload_path(path: str):
    return folder_upload._validate_upload_path(path, org_import_roots("test-org-001", []))


@pytest.fixture(autouse=True)
def allow_tmp_path_uploads(monkeypatch, tmp_path):
    """Folder scan and upload may read the test's tmp_path (tests can override)."""
    _allow(monkeypatch, tmp_path)


# ===========================================================================
# FolderUploadStatus enum tests
# ===========================================================================


class TestFolderUploadStatus:
    """Tests for the FolderUploadStatus enum."""

    def test_all_status_values(self):
        assert FolderUploadStatus.PENDING.value == "pending"
        assert FolderUploadStatus.SCANNING.value == "scanning"
        assert FolderUploadStatus.UPLOADING.value == "uploading"
        assert FolderUploadStatus.COMPLETED.value == "completed"
        assert FolderUploadStatus.FAILED.value == "failed"
        assert FolderUploadStatus.CANCELLED.value == "cancelled"

    def test_status_count(self):
        assert len(FolderUploadStatus) == 6


# ===========================================================================
# FolderUploadJob data model tests
# ===========================================================================


class TestFolderUploadJob:
    """Tests for FolderUploadJob dataclass and to_dict."""

    def test_to_dict_basic(self):
        job = _make_job(folder_id="test-123")
        d = job.to_dict()
        assert d["folder_id"] == "test-123"
        assert d["root_path"] == "/tmp/test-folder"
        assert d["status"] == "completed"
        assert d["user_id"] == "test-user-001"
        assert d["org_id"] == "test-org-001"

    def test_to_dict_scan_section(self):
        job = _make_job(
            total_files_found=20, included_count=15, excluded_count=5, total_size_bytes=4096
        )
        d = job.to_dict()
        assert d["scan"]["total_files_found"] == 20
        assert d["scan"]["included_count"] == 15
        assert d["scan"]["excluded_count"] == 5
        assert d["scan"]["total_size_bytes"] == 4096

    def test_to_dict_progress_section(self):
        job = _make_job(files_uploaded=3, files_failed=1, bytes_uploaded=2048, included_count=10)
        d = job.to_dict()
        assert d["progress"]["files_uploaded"] == 3
        assert d["progress"]["files_failed"] == 1
        assert d["progress"]["bytes_uploaded"] == 2048
        assert d["progress"]["percent_complete"] == 30.0

    def test_to_dict_percent_zero_when_no_files(self):
        job = _make_job(included_count=0, files_uploaded=0)
        d = job.to_dict()
        assert d["progress"]["percent_complete"] == 0

    def test_to_dict_results_section(self):
        job = _make_job(document_ids=["d1", "d2", "d3"])
        d = job.to_dict()
        assert d["results"]["document_ids"] == ["d1", "d2", "d3"]
        assert d["results"]["error_count"] == 0

    def test_to_dict_errors_truncated_to_10(self):
        errors = [{"error": f"err-{i}"} for i in range(15)]
        job = _make_job(errors=errors)
        d = job.to_dict()
        assert len(d["results"]["errors"]) == 10
        assert d["results"]["error_count"] == 15
        # Last 10 errors (slice [-10:])
        assert d["results"]["errors"][0] == {"error": "err-5"}
        assert d["results"]["errors"][-1] == {"error": "err-14"}

    def test_to_dict_datetime_iso_format(self):
        now = datetime(2026, 2, 23, 12, 0, 0, tzinfo=timezone.utc)
        job = _make_job(created_at=now)
        d = job.to_dict()
        assert "2026-02-23" in d["created_at"]
        assert "2026-02-23" in d["updated_at"]

    def test_to_dict_config(self):
        job = _make_job(config={"maxDepth": 5})
        d = job.to_dict()
        assert d["config"] == {"maxDepth": 5}

    def test_default_factory_fields(self):
        """Ensure default factory fields are independent across instances."""
        job1 = _make_job()
        job2 = _make_job()
        job1.document_ids.append("x")
        assert "x" not in job2.document_ids

    def test_to_dict_percent_complete_rounding(self):
        job = _make_job(included_count=3, files_uploaded=1)
        d = job.to_dict()
        assert d["progress"]["percent_complete"] == 33.3

    def test_to_dict_user_id_none(self):
        job = _make_job(user_id=None)
        d = job.to_dict()
        assert d["user_id"] is None

    def test_to_dict_empty_document_ids(self):
        job = _make_job(document_ids=[])
        d = job.to_dict()
        assert d["results"]["document_ids"] == []

    def test_to_dict_errors_fewer_than_10(self):
        errors = [{"error": f"e-{i}"} for i in range(3)]
        job = _make_job(errors=errors)
        d = job.to_dict()
        assert len(d["results"]["errors"]) == 3
        assert d["results"]["error_count"] == 3


# ===========================================================================
# can_handle() routing tests
# ===========================================================================


class TestCanHandle:
    """Tests for FolderUploadHandler.can_handle()."""

    def test_handles_folder_scan(self, handler):
        assert handler.can_handle("/api/v1/documents/folder/scan") is True

    def test_handles_folder_upload(self, handler):
        assert handler.can_handle("/api/v1/documents/folder/upload") is True

    def test_handles_folders_list(self, handler):
        assert handler.can_handle("/api/v1/documents/folders") is True

    def test_handles_upload_status(self, handler):
        assert handler.can_handle("/api/v1/documents/folder/upload/abc-123/status") is True

    def test_handles_folder_detail(self, handler):
        assert handler.can_handle("/api/v1/documents/folders/abc-123") is True

    def test_rejects_unrelated_path(self, handler):
        assert handler.can_handle("/api/v1/documents") is False

    def test_rejects_non_api_path(self, handler):
        assert handler.can_handle("/something/else") is False

    def test_rejects_folder_without_version(self, handler):
        assert handler.can_handle("/api/documents/folder/scan") is False

    def test_rejects_upload_status_missing_suffix(self, handler):
        assert handler.can_handle("/api/v1/documents/folder/upload/abc-123") is False

    def test_rejects_folders_with_extra_segments(self, handler):
        assert handler.can_handle("/api/v1/documents/folders/abc/extra") is False

    def test_handles_uuid_folder_id(self, handler):
        fid = str(uuid.uuid4())
        assert handler.can_handle(f"/api/v1/documents/folders/{fid}") is True

    def test_handles_uuid_upload_status(self, handler):
        fid = str(uuid.uuid4())
        assert handler.can_handle(f"/api/v1/documents/folder/upload/{fid}/status") is True


# ===========================================================================
# _validate_upload_path tests
# ===========================================================================


class TestValidateUploadPath:
    """Tests for the _validate_upload_path helper."""

    def test_valid_existing_directory(self, tmp_path):
        path = _validate_upload_path(str(tmp_path))
        assert path == tmp_path.resolve()

    def test_nonexistent_path(self, tmp_path):
        result = _validate_upload_path(str(tmp_path / "missing"))
        assert _status(result) == 404
        assert "does not exist" in _body(result)["error"]

    def test_file_not_directory(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("hello")
        result = _validate_upload_path(str(f))
        assert _status(result) == 400
        assert "not a directory" in _body(result)["error"]

    def test_allowed_dirs_restricts_path(self, tmp_path, monkeypatch):
        allowed_dir = tmp_path / "allowed"
        allowed_dir.mkdir()
        blocked_dir = tmp_path / "blocked"
        blocked_dir.mkdir()

        _allow(monkeypatch, allowed_dir)

        assert _validate_upload_path(str(allowed_dir)) == allowed_dir.resolve()

        result = _validate_upload_path(str(blocked_dir))
        assert _status(result) == 403
        assert "denied" in _body(result)["error"].lower()

    def test_allowed_dirs_subdirectory(self, tmp_path, monkeypatch):
        allowed_dir = tmp_path / "allowed"
        sub_dir = allowed_dir / "sub"
        sub_dir.mkdir(parents=True)

        _allow(monkeypatch, allowed_dir)

        assert _validate_upload_path(str(sub_dir)) == sub_dir.resolve()

    def test_no_allowed_dirs_refuses_every_path(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ARAGORA_ORG_IMPORT_ROOTS")
        result = _validate_upload_path(str(tmp_path))
        assert _status(result) == 403
        assert _body(result)["code"] == "path_not_allowed"

    def test_empty_string_path(self):
        # An empty path resolves to the working directory, outside tmp_path
        result = _validate_upload_path("")
        assert _status(result) == 403

    def test_path_with_null_bytes(self, tmp_path):
        """Path with null bytes should fail."""
        result = _validate_upload_path(f"{tmp_path}/\x00bad")
        assert _status(result) == 403

    def test_symlink_directory(self, tmp_path):
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real_dir)

        assert _validate_upload_path(str(link)) == real_dir.resolve()

    def test_multiple_allowed_dirs(self, tmp_path, monkeypatch):
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_c = tmp_path / "c"
        dir_a.mkdir()
        dir_b.mkdir()
        dir_c.mkdir()

        _allow(monkeypatch, dir_a, dir_b)

        assert _validate_upload_path(str(dir_a)) == dir_a.resolve()
        assert _validate_upload_path(str(dir_b)) == dir_b.resolve()
        assert _status(_validate_upload_path(str(dir_c))) == 403


# ===========================================================================
# GET /api/v1/documents/folders - List folders
# ===========================================================================


class TestListFolders:
    """Tests for the GET /api/v1/documents/folders endpoint."""

    def test_list_empty(self, handler):
        http = _make_http()
        result = handler.handle("/api/v1/documents/folders", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["folders"] == []
        assert body["count"] == 0

    def test_list_with_jobs(self, handler):
        job = _make_job(folder_id="folder-1")
        FolderUploadHandler._jobs["folder-1"] = job
        http = _make_http()
        result = handler.handle("/api/v1/documents/folders", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["count"] == 1
        assert body["folders"][0]["folder_id"] == "folder-1"

    def test_list_respects_limit(self, handler):
        for i in range(5):
            job = _make_job(folder_id=f"folder-{i}")
            FolderUploadHandler._jobs[f"folder-{i}"] = job

        http = _make_http()
        result = handler.handle("/api/v1/documents/folders", {"limit": "2"}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["count"] == 2

    def test_list_sorted_by_created_at_descending(self, handler):
        for i in range(3):
            job = _make_job(
                folder_id=f"folder-{i}",
                created_at=datetime(2026, 1, i + 1, tzinfo=timezone.utc),
            )
            FolderUploadHandler._jobs[f"folder-{i}"] = job

        http = _make_http()
        result = handler.handle("/api/v1/documents/folders", {}, http)
        body = _body(result)
        # Most recent first
        assert body["folders"][0]["folder_id"] == "folder-2"
        assert body["folders"][2]["folder_id"] == "folder-0"

    def test_list_default_limit_50(self, handler):
        for i in range(55):
            job = _make_job(folder_id=f"folder-{i}")
            FolderUploadHandler._jobs[f"folder-{i}"] = job

        http = _make_http()
        result = handler.handle("/api/v1/documents/folders", {}, http)
        body = _body(result)
        assert body["count"] == 50

    def test_list_limit_clamped_to_max(self, handler):
        for i in range(10):
            job = _make_job(folder_id=f"folder-{i}")
            FolderUploadHandler._jobs[f"folder-{i}"] = job

        http = _make_http()
        result = handler.handle("/api/v1/documents/folders", {"limit": "9999"}, http)
        body = _body(result)
        assert body["count"] == 10  # only 10 jobs exist

    def test_list_invalid_limit_uses_default(self, handler):
        job = _make_job(folder_id="folder-1")
        FolderUploadHandler._jobs["folder-1"] = job

        http = _make_http()
        result = handler.handle("/api/v1/documents/folders", {"limit": "abc"}, http)
        body = _body(result)
        assert body["count"] == 1

    def test_list_multiple_jobs(self, handler):
        for i in range(3):
            job = _make_job(folder_id=f"multi-{i}")
            FolderUploadHandler._jobs[f"multi-{i}"] = job

        http = _make_http()
        result = handler.handle("/api/v1/documents/folders", {}, http)
        body = _body(result)
        assert body["count"] == 3


# ===========================================================================
# GET /api/v1/documents/folder/upload/{folder_id}/status
# ===========================================================================


class TestGetUploadStatus:
    """Tests for GET /api/v1/documents/folder/upload/{folder_id}/status."""

    def test_status_found(self, handler):
        job = _make_job(folder_id="job-100", status=FolderUploadStatus.UPLOADING)
        FolderUploadHandler._jobs["job-100"] = job

        http = _make_http()
        result = handler.handle("/api/v1/documents/folder/upload/job-100/status", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["folder_id"] == "job-100"
        assert body["status"] == "uploading"

    def test_status_not_found(self, handler):
        http = _make_http()
        result = handler.handle("/api/v1/documents/folder/upload/nonexistent/status", {}, http)
        assert _status(result) == 404

    def test_status_contains_progress(self, handler):
        job = _make_job(
            folder_id="job-200",
            status=FolderUploadStatus.UPLOADING,
            files_uploaded=3,
            included_count=10,
        )
        FolderUploadHandler._jobs["job-200"] = job

        http = _make_http()
        result = handler.handle("/api/v1/documents/folder/upload/job-200/status", {}, http)
        body = _body(result)
        assert body["progress"]["files_uploaded"] == 3
        assert body["progress"]["percent_complete"] == 30.0

    def test_status_contains_scan_info(self, handler):
        job = _make_job(
            folder_id="job-300",
            total_files_found=50,
            included_count=40,
            excluded_count=10,
            total_size_bytes=102400,
        )
        FolderUploadHandler._jobs["job-300"] = job

        http = _make_http()
        result = handler.handle("/api/v1/documents/folder/upload/job-300/status", {}, http)
        body = _body(result)
        assert body["scan"]["total_files_found"] == 50
        assert body["scan"]["included_count"] == 40

    def test_status_pending(self, handler):
        job = _make_job(folder_id="job-pending", status=FolderUploadStatus.PENDING)
        FolderUploadHandler._jobs["job-pending"] = job

        http = _make_http()
        result = handler.handle("/api/v1/documents/folder/upload/job-pending/status", {}, http)
        body = _body(result)
        assert body["status"] == "pending"

    def test_status_failed(self, handler):
        job = _make_job(
            folder_id="job-fail",
            status=FolderUploadStatus.FAILED,
            errors=[{"error": "disk full", "fatal": True}],
        )
        FolderUploadHandler._jobs["job-fail"] = job

        http = _make_http()
        result = handler.handle("/api/v1/documents/folder/upload/job-fail/status", {}, http)
        body = _body(result)
        assert body["status"] == "failed"
        assert body["results"]["error_count"] == 1


# ===========================================================================
# GET /api/v1/documents/folders/{folder_id} - Get folder details
# ===========================================================================


class TestGetFolderDetail:
    """Tests for GET /api/v1/documents/folders/{folder_id}."""

    def test_get_folder_found(self, handler):
        job = _make_job(folder_id="detail-1")
        FolderUploadHandler._jobs["detail-1"] = job

        http = _make_http()
        result = handler.handle("/api/v1/documents/folders/detail-1", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["folder_id"] == "detail-1"

    def test_get_folder_not_found(self, handler):
        http = _make_http()
        result = handler.handle("/api/v1/documents/folders/missing-id", {}, http)
        assert _status(result) == 404

    def test_get_folder_returns_full_data(self, handler):
        job = _make_job(
            folder_id="detail-2",
            document_ids=["doc-a", "doc-b"],
            config={"maxDepth": 3},
        )
        FolderUploadHandler._jobs["detail-2"] = job

        http = _make_http()
        result = handler.handle("/api/v1/documents/folders/detail-2", {}, http)
        body = _body(result)
        assert body["results"]["document_ids"] == ["doc-a", "doc-b"]
        assert body["config"] == {"maxDepth": 3}

    def test_get_folder_with_uuid_id(self, handler):
        fid = str(uuid.uuid4())
        job = _make_job(folder_id=fid)
        FolderUploadHandler._jobs[fid] = job

        http = _make_http()
        result = handler.handle(f"/api/v1/documents/folders/{fid}", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["folder_id"] == fid


# ===========================================================================
# POST /api/v1/documents/folder/scan - Scan folder
# ===========================================================================


class TestScanFolder:
    """Tests for POST /api/v1/documents/folder/scan."""

    @pytest.mark.asyncio
    async def test_scan_missing_path(self, handler):
        http = _make_http(body={})
        result = await handler.handle_post("/api/v1/documents/folder/scan", {}, http)
        assert _status(result) == 400
        body = _body(result)
        assert "path" in body.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_scan_nonexistent_path(self, handler, tmp_path):
        http = _make_http(body={"path": str(tmp_path / "missing")})
        result = await handler.handle_post("/api/v1/documents/folder/scan", {}, http)
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_scan_file_not_directory(self, handler, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("content")
        http = _make_http(body={"path": str(f)})
        result = await handler.handle_post("/api/v1/documents/folder/scan", {}, http)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_scan_access_denied(self, handler, tmp_path, monkeypatch):
        test_dir = tmp_path / "test"
        test_dir.mkdir()
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        _allow(monkeypatch, allowed)
        http = _make_http(body={"path": str(test_dir)})
        result = await handler.handle_post("/api/v1/documents/folder/scan", {}, http)
        assert _status(result) == 403

    @pytest.mark.asyncio
    async def test_scan_success(self, handler, tmp_path):
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {
            "total_files_found": 5,
            "included_count": 3,
            "excluded_count": 2,
        }
        mock_scanner = MagicMock()
        mock_scanner.scan = AsyncMock(return_value=mock_result)
        mock_config_instance = MagicMock()
        mock_config_instance.exclude_patterns = []
        mock_config_cls = MagicMock(return_value=mock_config_instance)

        with patch.dict(
            "sys.modules",
            {
                "aragora.documents.folder": MagicMock(
                    FolderScanner=MagicMock(return_value=mock_scanner),
                    FolderUploadConfig=mock_config_cls,
                )
            },
        ):
            http = _make_http(body={"path": str(tmp_path)})
            result = await handler.handle_post("/api/v1/documents/folder/scan", {}, http)
            assert _status(result) == 200
            body = _body(result)
            assert body["total_files_found"] == 5

    @pytest.mark.asyncio
    async def test_scan_import_error_returns_503(self, handler, tmp_path):
        with patch.dict("sys.modules", {"aragora.documents.folder": None}):
            http = _make_http(body={"path": str(tmp_path)})
            result = await handler.handle_post("/api/v1/documents/folder/scan", {}, http)
            assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_scan_value_error_returns_400(self, handler, tmp_path):
        mock_config_instance = MagicMock()
        mock_config_instance.exclude_patterns = []
        call_count = [0]

        def config_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: FolderUploadConfig() for default patterns
                return mock_config_instance
            raise ValueError("bad config")

        with patch.dict(
            "sys.modules",
            {
                "aragora.documents.folder": MagicMock(
                    FolderScanner=MagicMock(),
                    FolderUploadConfig=MagicMock(side_effect=config_side_effect),
                )
            },
        ):
            http = _make_http(body={"path": str(tmp_path)})
            result = await handler.handle_post("/api/v1/documents/folder/scan", {}, http)
            assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_scan_runtime_error_returns_500(self, handler, tmp_path):
        mock_config_instance = MagicMock()
        mock_config_instance.exclude_patterns = []
        mock_config_cls = MagicMock(return_value=mock_config_instance)

        mock_scanner = MagicMock()
        mock_scanner.scan = AsyncMock(side_effect=RuntimeError("disk error"))

        with patch.dict(
            "sys.modules",
            {
                "aragora.documents.folder": MagicMock(
                    FolderScanner=MagicMock(return_value=mock_scanner),
                    FolderUploadConfig=mock_config_cls,
                )
            },
        ):
            http = _make_http(body={"path": str(tmp_path)})
            result = await handler.handle_post("/api/v1/documents/folder/scan", {}, http)
            assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_scan_with_custom_config(self, handler, tmp_path):
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {"total_files_found": 0}
        mock_scanner = MagicMock()
        mock_scanner.scan = AsyncMock(return_value=mock_result)
        mock_config_instance = MagicMock()
        mock_config_instance.exclude_patterns = []
        mock_config_cls = MagicMock(return_value=mock_config_instance)

        with patch.dict(
            "sys.modules",
            {
                "aragora.documents.folder": MagicMock(
                    FolderScanner=MagicMock(return_value=mock_scanner),
                    FolderUploadConfig=mock_config_cls,
                )
            },
        ):
            http = _make_http(
                body={
                    "path": str(tmp_path),
                    "config": {
                        "maxDepth": 5,
                        "excludePatterns": ["*.log"],
                        "maxFileSizeMb": 50,
                        "maxTotalSizeMb": 200,
                        "maxFileCount": 500,
                    },
                }
            )
            result = await handler.handle_post("/api/v1/documents/folder/scan", {}, http)
            assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_scan_unrelated_path_returns_none(self, handler):
        http = _make_http(body={})
        result = await handler.handle_post("/api/v1/unrelated", {}, http)
        assert result is None

    @pytest.mark.asyncio
    async def test_scan_empty_body_missing_path(self, handler):
        http = _make_http(body={})
        result = await handler.handle_post("/api/v1/documents/folder/scan", {}, http)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_scan_invalid_json_body(self, handler):
        http = MockHTTPHandler()
        http.headers = {"Content-Type": "application/json", "Content-Length": "11"}
        http.rfile = MagicMock()
        http.rfile.read.return_value = b"not json!!!"
        result = await handler.handle_post("/api/v1/documents/folder/scan", {}, http)
        assert _status(result) == 400


# ===========================================================================
# POST /api/v1/documents/folder/upload - Start upload
# ===========================================================================


class TestStartUpload:
    """Tests for POST /api/v1/documents/folder/upload."""

    @pytest.mark.asyncio
    async def test_upload_missing_path(self, handler):
        http = _make_http(body={})
        result = await handler.handle_post("/api/v1/documents/folder/upload", {}, http)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_upload_nonexistent_path(self, handler, tmp_path):
        http = _make_http(body={"path": str(tmp_path / "missing" / "yyy")})
        result = await handler.handle_post("/api/v1/documents/folder/upload", {}, http)
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_upload_file_not_directory(self, handler, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("content")
        http = _make_http(body={"path": str(f)})
        result = await handler.handle_post("/api/v1/documents/folder/upload", {}, http)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_upload_access_denied(self, handler, tmp_path, monkeypatch):
        target = tmp_path / "uploads"
        target.mkdir()
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        _allow(monkeypatch, allowed)
        http = _make_http(body={"path": str(target)})
        result = await handler.handle_post("/api/v1/documents/folder/upload", {}, http)
        assert _status(result) == 403
        assert FolderUploadHandler._jobs == {}

    @pytest.mark.asyncio
    async def test_upload_success(self, handler, tmp_path, monkeypatch):
        monkeypatch.setattr(threading.Thread, "start", lambda self: None)

        http = _make_http(body={"path": str(tmp_path)})
        result = await handler.handle_post("/api/v1/documents/folder/upload", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert "folder_id" in body
        assert body["status"] == "scanning"
        assert "message" in body

    @pytest.mark.asyncio
    async def test_upload_creates_job_in_store(self, handler, tmp_path, monkeypatch):
        monkeypatch.setattr(threading.Thread, "start", lambda self: None)

        http = _make_http(body={"path": str(tmp_path)})
        result = await handler.handle_post("/api/v1/documents/folder/upload", {}, http)
        body = _body(result)
        folder_id = body["folder_id"]
        assert folder_id in FolderUploadHandler._jobs
        job = FolderUploadHandler._jobs[folder_id]
        assert job.status == FolderUploadStatus.PENDING

    @pytest.mark.asyncio
    async def test_upload_stores_config(self, handler, tmp_path, monkeypatch):
        monkeypatch.setattr(threading.Thread, "start", lambda self: None)

        config = {"maxDepth": 3, "excludePatterns": ["*.log"]}
        http = _make_http(body={"path": str(tmp_path), "config": config})
        result = await handler.handle_post("/api/v1/documents/folder/upload", {}, http)
        body = _body(result)
        folder_id = body["folder_id"]
        assert FolderUploadHandler._jobs[folder_id].config == config

    @pytest.mark.asyncio
    async def test_upload_unrelated_path_returns_none(self, handler):
        http = _make_http(body={})
        result = await handler.handle_post("/api/v1/unrelated", {}, http)
        assert result is None

    @pytest.mark.asyncio
    async def test_upload_job_root_path_resolved(self, handler, tmp_path, monkeypatch):
        monkeypatch.setattr(threading.Thread, "start", lambda self: None)

        http = _make_http(body={"path": str(tmp_path)})
        result = await handler.handle_post("/api/v1/documents/folder/upload", {}, http)
        body = _body(result)
        job = FolderUploadHandler._jobs[body["folder_id"]]
        assert Path(job.root_path).is_absolute()

    @pytest.mark.asyncio
    async def test_upload_job_has_user_id(self, handler, tmp_path, monkeypatch):
        monkeypatch.setattr(threading.Thread, "start", lambda self: None)

        http = _make_http(body={"path": str(tmp_path)})
        result = await handler.handle_post("/api/v1/documents/folder/upload", {}, http)
        body = _body(result)
        job = FolderUploadHandler._jobs[body["folder_id"]]
        assert job.user_id == "test-user-001"

    @pytest.mark.asyncio
    async def test_upload_invalid_json(self, handler):
        http = MockHTTPHandler()
        http.headers = {"Content-Type": "application/json", "Content-Length": "11"}
        http.rfile = MagicMock()
        http.rfile.read.return_value = b"not json!!!"
        result = await handler.handle_post("/api/v1/documents/folder/upload", {}, http)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_upload_default_config_empty(self, handler, tmp_path, monkeypatch):
        monkeypatch.setattr(threading.Thread, "start", lambda self: None)

        http = _make_http(body={"path": str(tmp_path)})
        result = await handler.handle_post("/api/v1/documents/folder/upload", {}, http)
        body = _body(result)
        job = FolderUploadHandler._jobs[body["folder_id"]]
        assert job.config == {}


# ===========================================================================
# DELETE /api/v1/documents/folders/{folder_id}
# ===========================================================================


class TestDeleteFolder:
    """Tests for DELETE /api/v1/documents/folders/{folder_id}."""

    @pytest.fixture(autouse=True)
    def _bypass_auth(self):
        """Authenticate delete requests as test-user-001 of test-org-001."""
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.user_id = "test-user-001"
        mock_user.org_id = "test-org-001"
        mock_user.role = "admin"
        with patch(
            "aragora.billing.jwt_auth.extract_user_from_request",
            return_value=mock_user,
        ):
            yield

    def test_delete_success(self, handler):
        job = _make_job(folder_id="del-1", user_id="test-user-001")
        FolderUploadHandler._jobs["del-1"] = job

        http = _make_http()
        result = handler.handle_delete("/api/v1/documents/folders/del-1", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        assert "del-1" not in FolderUploadHandler._jobs

    def test_delete_not_found(self, handler):
        http = _make_http()
        result = handler.handle_delete("/api/v1/documents/folders/missing-id", {}, http)
        assert _status(result) == 404

    def test_delete_removes_job_from_store(self, handler):
        job = _make_job(folder_id="del-2", user_id="test-user-001")
        FolderUploadHandler._jobs["del-2"] = job

        http = _make_http()
        handler.handle_delete("/api/v1/documents/folders/del-2", {}, http)
        assert "del-2" not in FolderUploadHandler._jobs

    def test_delete_response_format(self, handler):
        job = _make_job(folder_id="del-3", user_id="test-user-001")
        FolderUploadHandler._jobs["del-3"] = job

        http = _make_http()
        result = handler.handle_delete("/api/v1/documents/folders/del-3", {}, http)
        body = _body(result)
        assert "success" in body
        assert "message" in body
        assert "documents_deleted" in body
        assert body["documents_deleted"] == 0

    def test_delete_unrelated_path_returns_none(self, handler):
        http = _make_http()
        result = handler.handle_delete("/api/v1/unrelated", {}, http)
        assert result is None

    def test_delete_with_uuid_id(self, handler):
        fid = str(uuid.uuid4())
        job = _make_job(folder_id=fid, user_id="test-user-001")
        FolderUploadHandler._jobs[fid] = job

        http = _make_http()
        result = handler.handle_delete(f"/api/v1/documents/folders/{fid}", {}, http)
        assert _status(result) == 200
        assert fid not in FolderUploadHandler._jobs

    def test_delete_job_with_no_user_id(self, handler):
        """Job with no user_id can still be deleted."""
        job = _make_job(folder_id="del-nouser", user_id=None)
        FolderUploadHandler._jobs["del-nouser"] = job

        http = _make_http()
        result = handler.handle_delete("/api/v1/documents/folders/del-nouser", {}, http)
        assert _status(result) == 200


# ===========================================================================
# handle() routing for GET requests
# ===========================================================================


class TestHandleRouting:
    """Tests for the handle() method routing logic."""

    def test_routes_to_list_folders(self, handler):
        http = _make_http()
        result = handler.handle("/api/v1/documents/folders", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert "folders" in body

    def test_routes_to_upload_status(self, handler):
        job = _make_job(folder_id="route-1")
        FolderUploadHandler._jobs["route-1"] = job

        http = _make_http()
        result = handler.handle("/api/v1/documents/folder/upload/route-1/status", {}, http)
        assert _status(result) == 200

    def test_routes_to_folder_detail(self, handler):
        job = _make_job(folder_id="route-2")
        FolderUploadHandler._jobs["route-2"] = job

        http = _make_http()
        result = handler.handle("/api/v1/documents/folders/route-2", {}, http)
        assert _status(result) == 200

    def test_returns_none_for_unknown_path(self, handler):
        http = _make_http()
        result = handler.handle("/api/v1/unknown/path", {}, http)
        assert result is None


# ===========================================================================
# handle_post() routing for POST requests
# ===========================================================================


class TestHandlePostRouting:
    """Tests for the handle_post() method routing logic."""

    @pytest.mark.asyncio
    async def test_routes_to_scan(self, handler, tmp_path):
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {"total_files_found": 0}
        mock_scanner = MagicMock()
        mock_scanner.scan = AsyncMock(return_value=mock_result)
        mock_config_instance = MagicMock()
        mock_config_instance.exclude_patterns = []
        mock_config_cls = MagicMock(return_value=mock_config_instance)

        with patch.dict(
            "sys.modules",
            {
                "aragora.documents.folder": MagicMock(
                    FolderScanner=MagicMock(return_value=mock_scanner),
                    FolderUploadConfig=mock_config_cls,
                )
            },
        ):
            http = _make_http(body={"path": str(tmp_path)})
            result = await handler.handle_post("/api/v1/documents/folder/scan", {}, http)
            assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_routes_to_upload(self, handler, tmp_path, monkeypatch):
        monkeypatch.setattr(threading.Thread, "start", lambda self: None)
        http = _make_http(body={"path": str(tmp_path)})
        result = await handler.handle_post("/api/v1/documents/folder/upload", {}, http)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown(self, handler):
        http = _make_http(body={})
        result = await handler.handle_post("/api/v1/unknown", {}, http)
        assert result is None


# ===========================================================================
# _update_job_status / _update_job_error internal methods
# ===========================================================================


class TestJobUpdateMethods:
    """Tests for internal job update methods."""

    def test_update_job_status(self, handler):
        job = _make_job(folder_id="upd-1", status=FolderUploadStatus.PENDING)
        FolderUploadHandler._jobs["upd-1"] = job

        handler._update_job_status("upd-1", FolderUploadStatus.SCANNING)
        assert FolderUploadHandler._jobs["upd-1"].status == FolderUploadStatus.SCANNING

    def test_update_job_status_updates_timestamp(self, handler):
        old_time = datetime(2020, 1, 1, tzinfo=timezone.utc)
        job = _make_job(folder_id="upd-2", created_at=old_time)
        job.updated_at = old_time
        FolderUploadHandler._jobs["upd-2"] = job

        handler._update_job_status("upd-2", FolderUploadStatus.COMPLETED)
        assert FolderUploadHandler._jobs["upd-2"].updated_at > old_time

    def test_update_job_status_missing_job_noop(self, handler):
        handler._update_job_status("nonexistent", FolderUploadStatus.FAILED)

    def test_update_job_error(self, handler):
        job = _make_job(folder_id="err-1")
        FolderUploadHandler._jobs["err-1"] = job

        handler._update_job_error("err-1", "Something went wrong")
        assert len(FolderUploadHandler._jobs["err-1"].errors) == 1
        assert FolderUploadHandler._jobs["err-1"].errors[0]["error"] == "Something went wrong"
        assert FolderUploadHandler._jobs["err-1"].errors[0]["fatal"] is True

    def test_update_job_error_missing_job_noop(self, handler):
        handler._update_job_error("nonexistent", "error")

    def test_update_job_error_accumulates(self, handler):
        job = _make_job(folder_id="err-2", errors=[])
        FolderUploadHandler._jobs["err-2"] = job

        handler._update_job_error("err-2", "error 1")
        handler._update_job_error("err-2", "error 2")
        assert len(FolderUploadHandler._jobs["err-2"].errors) == 2

    def test_update_job_status_all_transitions(self, handler):
        """Test transitioning through all statuses."""
        job = _make_job(folder_id="trans-1", status=FolderUploadStatus.PENDING)
        FolderUploadHandler._jobs["trans-1"] = job

        for status in [
            FolderUploadStatus.SCANNING,
            FolderUploadStatus.UPLOADING,
            FolderUploadStatus.COMPLETED,
        ]:
            handler._update_job_status("trans-1", status)
            assert FolderUploadHandler._jobs["trans-1"].status == status


# ===========================================================================
# get_document_store
# ===========================================================================


class TestGetDocumentStore:
    """Tests for get_document_store."""

    def test_returns_store_from_ctx(self):
        store = MagicMock()
        h = FolderUploadHandler(ctx={"document_store": store})
        assert h.get_document_store() is store

    def test_returns_none_when_not_configured(self):
        h = FolderUploadHandler(ctx={})
        assert h.get_document_store() is None

    def test_returns_none_for_empty_ctx(self):
        h = FolderUploadHandler()
        assert h.get_document_store() is None


# ===========================================================================
# _run_upload_job background job
# ===========================================================================


class TestRunUploadJob:
    """Tests for the background upload job runner."""

    def test_run_upload_job_no_files(self, handler, tmp_path):
        """Upload job with zero included files completes immediately."""
        job = _make_job(
            folder_id="bg-1",
            status=FolderUploadStatus.PENDING,
            included_count=0,
        )
        FolderUploadHandler._jobs["bg-1"] = job

        mock_result = MagicMock()
        mock_result.total_files_found = 0
        mock_result.included_count = 0
        mock_result.excluded_count = 0
        mock_result.included_size_bytes = 0
        mock_result.included_files = []

        mock_scanner = MagicMock()
        mock_scanner.scan = AsyncMock(return_value=mock_result)
        mock_config_instance = MagicMock()
        mock_config_instance.exclude_patterns = []
        mock_config_cls = MagicMock(return_value=mock_config_instance)

        with patch.dict(
            "sys.modules",
            {
                "aragora.documents.folder": MagicMock(
                    FolderScanner=MagicMock(return_value=mock_scanner),
                    FolderUploadConfig=mock_config_cls,
                )
            },
        ):
            handler._run_upload_job("bg-1", tmp_path, {}, SCOPE)

        assert FolderUploadHandler._jobs["bg-1"].status == FolderUploadStatus.COMPLETED

    def test_run_upload_job_no_document_store(self, handler, tmp_path):
        """Upload job fails if no document store is configured."""
        job = _make_job(
            folder_id="bg-2",
            status=FolderUploadStatus.PENDING,
        )
        FolderUploadHandler._jobs["bg-2"] = job

        mock_file = MagicMock()
        mock_file.absolute_path = str(tmp_path / "test.txt")
        mock_file.path = "test.txt"
        mock_file.size_bytes = 100

        mock_result = MagicMock()
        mock_result.total_files_found = 1
        mock_result.included_count = 1
        mock_result.excluded_count = 0
        mock_result.included_size_bytes = 100
        mock_result.included_files = [mock_file]

        mock_scanner = MagicMock()
        mock_scanner.scan = AsyncMock(return_value=mock_result)
        mock_config_instance = MagicMock()
        mock_config_instance.exclude_patterns = []
        mock_config_cls = MagicMock(return_value=mock_config_instance)

        with patch.dict(
            "sys.modules",
            {
                "aragora.documents.folder": MagicMock(
                    FolderScanner=MagicMock(return_value=mock_scanner),
                    FolderUploadConfig=mock_config_cls,
                )
            },
        ):
            handler._run_upload_job("bg-2", tmp_path, {}, SCOPE)

        assert FolderUploadHandler._jobs["bg-2"].status == FolderUploadStatus.FAILED

    def test_run_upload_job_import_error_on_scanner(self, handler, tmp_path):
        """Upload job fails when scanner module import raises ImportError.

        The _run_upload_job method doesn't catch ImportError at the outer level,
        so ModuleNotFoundError propagates. This is expected since the handler
        method _scan_folder handles it separately for the scan endpoint.
        """
        job = _make_job(folder_id="bg-3", status=FolderUploadStatus.PENDING)
        FolderUploadHandler._jobs["bg-3"] = job

        with patch.dict("sys.modules", {"aragora.documents.folder": None}):
            # ModuleNotFoundError (subclass of ImportError) is not caught by
            # _run_upload_job's outer except block
            with pytest.raises(ModuleNotFoundError):
                handler._run_upload_job("bg-3", tmp_path, {}, SCOPE)

    def test_run_upload_job_updates_scan_results(self, handler, tmp_path):
        """Upload job populates scan result fields on the job."""
        job = _make_job(
            folder_id="bg-4",
            status=FolderUploadStatus.PENDING,
            total_files_found=0,
            included_count=0,
        )
        FolderUploadHandler._jobs["bg-4"] = job

        mock_result = MagicMock()
        mock_result.total_files_found = 10
        mock_result.included_count = 0
        mock_result.excluded_count = 10
        mock_result.included_size_bytes = 0
        mock_result.included_files = []

        mock_scanner = MagicMock()
        mock_scanner.scan = AsyncMock(return_value=mock_result)
        mock_config_instance = MagicMock()
        mock_config_instance.exclude_patterns = []
        mock_config_cls = MagicMock(return_value=mock_config_instance)

        with patch.dict(
            "sys.modules",
            {
                "aragora.documents.folder": MagicMock(
                    FolderScanner=MagicMock(return_value=mock_scanner),
                    FolderUploadConfig=mock_config_cls,
                )
            },
        ):
            handler._run_upload_job("bg-4", tmp_path, {}, SCOPE)

        j = FolderUploadHandler._jobs["bg-4"]
        assert j.total_files_found == 10
        assert j.excluded_count == 10

    def test_run_upload_job_parse_import_error(self, handler, tmp_path):
        """Upload job fails if parse_document is not importable."""
        job = _make_job(folder_id="bg-5", status=FolderUploadStatus.PENDING)
        FolderUploadHandler._jobs["bg-5"] = job

        mock_file = MagicMock()
        mock_file.absolute_path = str(tmp_path / "test.txt")
        mock_file.path = "test.txt"
        mock_file.size_bytes = 100

        mock_result = MagicMock()
        mock_result.total_files_found = 1
        mock_result.included_count = 1
        mock_result.excluded_count = 0
        mock_result.included_size_bytes = 100
        mock_result.included_files = [mock_file]

        mock_scanner = MagicMock()
        mock_scanner.scan = AsyncMock(return_value=mock_result)
        mock_config_instance = MagicMock()
        mock_config_instance.exclude_patterns = []
        mock_config_cls = MagicMock(return_value=mock_config_instance)

        mock_store = MagicMock()
        handler_with_store = FolderUploadHandler(ctx={"document_store": mock_store})

        with patch.dict(
            "sys.modules",
            {
                "aragora.documents.folder": MagicMock(
                    FolderScanner=MagicMock(return_value=mock_scanner),
                    FolderUploadConfig=mock_config_cls,
                ),
                "aragora.server.documents": None,
            },
        ):
            handler_with_store._run_upload_job("bg-5", tmp_path, {}, SCOPE)

        assert FolderUploadHandler._jobs["bg-5"].status == FolderUploadStatus.FAILED

    def test_run_upload_job_scan_error_sets_failed(self, handler, tmp_path):
        """Upload job transitions to FAILED when scan raises RuntimeError."""
        job = _make_job(folder_id="bg-6", status=FolderUploadStatus.PENDING)
        FolderUploadHandler._jobs["bg-6"] = job

        mock_scanner = MagicMock()
        mock_scanner.scan = AsyncMock(side_effect=RuntimeError("boom"))
        mock_config_instance = MagicMock()
        mock_config_instance.exclude_patterns = []
        mock_config_cls = MagicMock(return_value=mock_config_instance)

        with patch.dict(
            "sys.modules",
            {
                "aragora.documents.folder": MagicMock(
                    FolderScanner=MagicMock(return_value=mock_scanner),
                    FolderUploadConfig=mock_config_cls,
                )
            },
        ):
            handler._run_upload_job("bg-6", tmp_path, {}, SCOPE)

        assert FolderUploadHandler._jobs["bg-6"].status == FolderUploadStatus.FAILED


# ===========================================================================
# Handler initialization
# ===========================================================================


class TestHandlerInit:
    """Tests for FolderUploadHandler initialization."""

    def test_init_with_ctx(self):
        h = FolderUploadHandler(ctx={"key": "value"})
        assert h.ctx == {"key": "value"}

    def test_init_with_server_context(self):
        h = FolderUploadHandler(server_context={"key": "value"})
        assert h.ctx == {"key": "value"}

    def test_init_with_both_prefers_server_context(self):
        h = FolderUploadHandler(ctx={"a": 1}, server_context={"b": 2})
        assert h.ctx == {"b": 2}

    def test_init_defaults_to_empty_dict(self):
        h = FolderUploadHandler()
        assert h.ctx == {}

    def test_routes_class_attribute(self):
        assert "/api/v1/documents/folder/scan" in FolderUploadHandler.ROUTES
        assert "/api/v1/documents/folder/upload" in FolderUploadHandler.ROUTES
        assert "/api/v1/documents/folders" in FolderUploadHandler.ROUTES


# ===========================================================================
# Edge cases
# ===========================================================================


class TestEdgeCases:
    """Additional edge cases for completeness."""

    def test_list_folders_with_mixed_statuses(self, handler):
        for i, status in enumerate(FolderUploadStatus):
            job = _make_job(folder_id=f"mix-{i}", status=status)
            FolderUploadHandler._jobs[f"mix-{i}"] = job

        http = _make_http()
        result = handler.handle("/api/v1/documents/folders", {}, http)
        body = _body(result)
        assert body["count"] == 6

    def test_job_to_dict_all_statuses(self):
        """Ensure to_dict works for all status values."""
        for status in FolderUploadStatus:
            job = _make_job(status=status)
            d = job.to_dict()
            assert d["status"] == status.value

    def test_concurrent_job_access(self, handler):
        """Basic test that the lock mechanism doesn't deadlock."""
        job = _make_job(folder_id="conc-1")
        FolderUploadHandler._jobs["conc-1"] = job

        results = []

        def read_job():
            http = _make_http()
            r = handler.handle("/api/v1/documents/folder/upload/conc-1/status", {}, http)
            results.append(_status(r))

        threads = [threading.Thread(target=read_job) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert all(s == 200 for s in results)

    def test_uuid_folder_id_in_status(self, handler):
        fid = str(uuid.uuid4())
        job = _make_job(folder_id=fid)
        FolderUploadHandler._jobs[fid] = job

        http = _make_http()
        result = handler.handle(f"/api/v1/documents/folder/upload/{fid}/status", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["folder_id"] == fid

    def test_uuid_folder_id_in_detail(self, handler):
        fid = str(uuid.uuid4())
        job = _make_job(folder_id=fid)
        FolderUploadHandler._jobs[fid] = job

        http = _make_http()
        result = handler.handle(f"/api/v1/documents/folders/{fid}", {}, http)
        assert _status(result) == 200

    def test_empty_config_in_job(self):
        job = _make_job(config={})
        d = job.to_dict()
        assert d["config"] == {}

    def test_large_number_of_errors_in_results(self):
        errors = [{"error": f"err-{i}"} for i in range(100)]
        job = _make_job(errors=errors)
        d = job.to_dict()
        assert len(d["results"]["errors"]) == 10
        assert d["results"]["error_count"] == 100

    def test_handle_delete_routing_prefix_check(self, handler):
        """Ensure handle_delete only matches /api/v1/documents/folders/."""
        http = _make_http()
        result = handler.handle_delete("/api/v1/documents/folder/scan", {}, http)
        assert result is None

    def test_multiple_jobs_independent_state(self, handler):
        """Multiple jobs maintain independent state."""
        job1 = _make_job(folder_id="ind-1", files_uploaded=1)
        job2 = _make_job(folder_id="ind-2", files_uploaded=99)
        FolderUploadHandler._jobs["ind-1"] = job1
        FolderUploadHandler._jobs["ind-2"] = job2

        http = _make_http()
        r1 = handler.handle("/api/v1/documents/folders/ind-1", {}, http)
        r2 = handler.handle("/api/v1/documents/folders/ind-2", {}, http)
        assert _body(r1)["progress"]["files_uploaded"] == 1
        assert _body(r2)["progress"]["files_uploaded"] == 99


# ===========================================================================
# Org scope
# ===========================================================================


def _user(org_id: str | None, user_id: str = "test-user-001") -> MagicMock:
    user = MagicMock()
    user.is_authenticated = bool(user_id)
    user.user_id = user_id
    user.org_id = org_id
    user.role = "admin"
    return user


class TestOrgScope:
    """Folder uploads belong to the org of the user who started them."""

    @pytest.fixture
    def as_user(self):
        def _as(user):
            return patch("aragora.billing.jwt_auth.extract_user_from_request", return_value=user)

        return _as

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method,path",
        [
            ("GET", "/api/v1/documents/folders"),
            ("GET", "/api/v1/documents/folders/f-1"),
            ("GET", "/api/v1/documents/folder/upload/f-1/status"),
            ("DELETE", "/api/v1/documents/folders/f-1"),
            ("POST", "/api/v1/documents/folder/scan"),
            ("POST", "/api/v1/documents/folder/upload"),
        ],
    )
    async def test_anonymous_gets_401(self, handler, as_user, method, path, tmp_path):
        FolderUploadHandler._jobs["f-1"] = _make_job(folder_id="f-1")
        anonymous = MagicMock(is_authenticated=False, user_id=None, org_id=None)
        http = _make_http(body={"path": str(tmp_path)})
        with as_user(anonymous):
            if method == "GET":
                result = handler.handle(path, {}, http)
            elif method == "DELETE":
                result = handler.handle_delete(path, {}, http)
            else:
                result = await handler.handle_post(path, {}, http)
        assert _status(result) == 401
        assert "f-1" in FolderUploadHandler._jobs
        assert len(FolderUploadHandler._jobs) == 1

    def test_user_without_org_gets_403(self, handler, as_user):
        with as_user(_user(None)):
            result = handler.handle("/api/v1/documents/folders", {}, _make_http())
        assert _status(result) == 403
        assert _body(result)["code"] == "org_required"

    @pytest.mark.parametrize("owner_org", ["other-org", None])
    def test_other_org_and_unknown_owner_jobs_answer_404(self, handler, owner_org):
        FolderUploadHandler._jobs["f-x"] = _make_job(folder_id="f-x", org_id=owner_org)
        http = _make_http()

        for result in (
            handler.handle("/api/v1/documents/folders/f-x", {}, http),
            handler.handle("/api/v1/documents/folder/upload/f-x/status", {}, http),
            handler.handle_delete("/api/v1/documents/folders/f-x", {}, http),
        ):
            assert _status(result) == 404
            assert _body(result) == {"error": "Folder not found", "code": "not_found"}
        assert "f-x" in FolderUploadHandler._jobs

    def test_missing_job_answers_same_404(self, handler):
        result = handler.handle("/api/v1/documents/folders/nope", {}, _make_http())
        assert _status(result) == 404
        assert _body(result) == {"error": "Folder not found", "code": "not_found"}

    def test_list_only_returns_callers_org(self, handler):
        FolderUploadHandler._jobs["mine"] = _make_job(folder_id="mine")
        FolderUploadHandler._jobs["theirs"] = _make_job(folder_id="theirs", org_id="other-org")
        FolderUploadHandler._jobs["unknown"] = _make_job(folder_id="unknown", org_id=None)

        result = handler.handle("/api/v1/documents/folders", {}, _make_http())
        body = _body(result)
        assert [f["folder_id"] for f in body["folders"]] == ["mine"]
        assert body["count"] == 1

    def test_same_org_other_user_cannot_delete(self, handler, as_user):
        FolderUploadHandler._jobs["f-1"] = _make_job(folder_id="f-1")
        with as_user(_user("test-org-001", user_id="someone-else")):
            result = handler.handle_delete("/api/v1/documents/folders/f-1", {}, _make_http())
        assert _status(result) == 403
        assert "f-1" in FolderUploadHandler._jobs

    @pytest.mark.asyncio
    async def test_upload_job_records_caller_org(self, handler, tmp_path, monkeypatch):
        monkeypatch.setattr(threading.Thread, "start", lambda self: None)
        result = await handler.handle_post(
            "/api/v1/documents/folder/upload", {}, _make_http(body={"path": str(tmp_path)})
        )
        job = FolderUploadHandler._jobs[_body(result)["folder_id"]]
        assert job.org_id == "test-org-001"
        assert job.user_id == "test-user-001"

    def test_uploaded_documents_are_stored_under_callers_org(self, tmp_path):
        from aragora.documents.parsing import DocumentStore

        folder = tmp_path / "folder"
        folder.mkdir()
        (folder / "notes.txt").write_text("quarterly plan notes")
        store = DocumentStore(tmp_path / "docs")
        handler = FolderUploadHandler(ctx={"document_store": store})
        FolderUploadHandler._jobs["f-up"] = _make_job(
            folder_id="f-up", status=FolderUploadStatus.PENDING, document_ids=[]
        )

        handler._run_upload_job("f-up", folder, {}, SCOPE)

        job = FolderUploadHandler._jobs["f-up"]
        assert job.status == FolderUploadStatus.COMPLETED
        assert len(job.document_ids) == 1
        doc = store.get(job.document_ids[0])
        assert doc.org_id == "test-org-001"
        assert doc.created_by == "test-user-001"
        assert [d["id"] for d in store.list_for_org("test-org-001")] == job.document_ids
        assert store.list_for_org("other-org") == []
