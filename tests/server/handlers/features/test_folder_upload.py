"""Tests for Folder Upload Handler."""

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

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from aragora.server.handlers.features.folder_upload import (
    FolderUploadHandler,
    FolderUploadJob,
    FolderUploadStatus,
)
from aragora.tenancy.record_scope import OrgScope

SCOPE = OrgScope(org_id="test_org", user_id="test_user", role="admin")


@pytest.fixture(autouse=True)
def clear_jobs():
    """Clear jobs between tests."""
    FolderUploadHandler._jobs.clear()
    yield


@pytest.fixture(autouse=True)
def mock_auth():
    """Mock authentication for all tests."""
    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.user_id = "test_user"
    mock_user.org_id = "test_org"
    mock_user.role = "admin"
    mock_user.error_reason = None

    with patch(
        "aragora.billing.jwt_auth.extract_user_from_request",
        return_value=mock_user,
    ):
        yield


@pytest.fixture
def handler():
    """Create handler instance."""
    h = FolderUploadHandler({})
    h.headers = MagicMock()  # Add headers for auth decorator
    return h


@pytest.fixture
def upload_root(monkeypatch, tmp_path):
    """Configure tmp_path as the only directory folder scan/upload may read."""
    monkeypatch.setenv("ARAGORA_ALLOWED_UPLOAD_DIRS", str(tmp_path))
    return tmp_path


class TestFolderUploadStatus:
    """Tests for FolderUploadStatus enum."""

    def test_status_values(self):
        """Test status enum values."""
        assert FolderUploadStatus.PENDING.value == "pending"
        assert FolderUploadStatus.SCANNING.value == "scanning"
        assert FolderUploadStatus.UPLOADING.value == "uploading"
        assert FolderUploadStatus.COMPLETED.value == "completed"
        assert FolderUploadStatus.FAILED.value == "failed"
        assert FolderUploadStatus.CANCELLED.value == "cancelled"


class TestFolderUploadJob:
    """Tests for FolderUploadJob dataclass."""

    def test_job_creation(self):
        """Test creating job instance."""
        now = datetime.now(timezone.utc)
        job = FolderUploadJob(
            folder_id="folder123",
            root_path="/test/path",
            status=FolderUploadStatus.PENDING,
            created_at=now,
            updated_at=now,
        )
        assert job.folder_id == "folder123"
        assert job.root_path == "/test/path"
        assert job.status == FolderUploadStatus.PENDING

    def test_job_defaults(self):
        """Test job default values."""
        now = datetime.now(timezone.utc)
        job = FolderUploadJob(
            folder_id="folder123",
            root_path="/test/path",
            status=FolderUploadStatus.PENDING,
            created_at=now,
            updated_at=now,
        )
        assert job.total_files_found == 0
        assert job.files_uploaded == 0
        assert job.document_ids == []
        assert job.errors == []

    def test_job_to_dict(self):
        """Test job serialization."""
        now = datetime.now(timezone.utc)
        job = FolderUploadJob(
            folder_id="folder123",
            root_path="/test/path",
            status=FolderUploadStatus.COMPLETED,
            created_at=now,
            updated_at=now,
            total_files_found=10,
            included_count=8,
            files_uploaded=8,
        )

        data = job.to_dict()
        assert data["folder_id"] == "folder123"
        assert data["status"] == "completed"
        assert data["scan"]["total_files_found"] == 10
        assert data["progress"]["files_uploaded"] == 8
        assert data["progress"]["percent_complete"] == 100.0


class TestFolderUploadHandler:
    """Tests for FolderUploadHandler class."""

    def test_handler_creation(self, handler):
        """Test creating handler instance."""
        assert handler is not None

    def test_handler_routes(self):
        """Test that handler has route definitions."""
        assert hasattr(FolderUploadHandler, "ROUTES")
        routes = FolderUploadHandler.ROUTES
        assert "/api/v1/documents/folder/scan" in routes
        assert "/api/v1/documents/folder/upload" in routes
        assert "/api/v1/documents/folders" in routes

    def test_can_handle_folder_routes(self, handler):
        """Test can_handle for folder routes."""
        assert handler.can_handle("/api/v1/documents/folder/scan") is True
        assert handler.can_handle("/api/v1/documents/folder/upload") is True
        assert handler.can_handle("/api/v1/documents/folders") is True

    def test_can_handle_status_routes(self, handler):
        """Test can_handle for status routes."""
        assert handler.can_handle("/api/v1/documents/folder/upload/folder123/status") is True

    def test_can_handle_folder_id_routes(self, handler):
        """Test can_handle for folder ID routes."""
        assert handler.can_handle("/api/v1/documents/folders/folder123") is True

    def test_can_handle_invalid_routes(self, handler):
        """Test can_handle rejects invalid routes."""
        assert handler.can_handle("/api/v1/files/folder") is False
        assert handler.can_handle("/api/v1/invalid/route") is False


class TestFolderScan:
    """Tests for folder scan endpoint."""

    @pytest.mark.asyncio
    async def test_scan_missing_path(self, handler):
        """Test scan requires path."""
        mock_handler = MagicMock()

        with (
            patch.object(handler, "read_json_body_validated", return_value=({}, None)),
        ):
            result = await handler._scan_folder(mock_handler)
            assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_scan_path_not_exists(self, handler, upload_root):
        """Test scan with non-existent path inside the upload root."""
        mock_handler = MagicMock()

        with patch.object(
            handler,
            "read_json_body_validated",
            return_value=({"path": str(upload_root / "missing")}, None),
        ):
            result = await handler._scan_folder(mock_handler)
            assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_scan_path_not_directory(self, handler, upload_root):
        """Test scan with non-directory path."""
        mock_handler = MagicMock()
        (upload_root / "file.txt").write_text("not a folder")

        with patch.object(
            handler,
            "read_json_body_validated",
            return_value=({"path": str(upload_root / "file.txt")}, None),
        ):
            result = await handler._scan_folder(mock_handler)
            assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_scan_refused_without_upload_root(self, handler, tmp_path, monkeypatch):
        """Without configured upload directories the scan is refused."""
        monkeypatch.delenv("ARAGORA_ALLOWED_UPLOAD_DIRS", raising=False)

        with patch.object(
            handler, "read_json_body_validated", return_value=({"path": str(tmp_path)}, None)
        ):
            result = await handler._scan_folder(MagicMock())
            assert result.status_code == 403


class TestFolderUploadStart:
    """Tests for starting folder upload."""

    def test_start_upload_missing_path(self, handler):
        """Test start upload requires path."""
        mock_handler = MagicMock()

        with (
            patch.object(handler, "read_json_body_validated", return_value=({}, None)),
        ):
            result = handler._start_upload(mock_handler, SCOPE)
            assert result.status_code == 400

    def test_start_upload_path_not_exists(self, handler, upload_root):
        """Test start upload with non-existent path inside the upload root."""
        mock_handler = MagicMock()

        with patch.object(
            handler,
            "read_json_body_validated",
            return_value=({"path": str(upload_root / "missing")}, None),
        ):
            result = handler._start_upload(mock_handler, SCOPE)
            assert result.status_code == 404
            assert FolderUploadHandler._jobs == {}

    def test_start_upload_outside_root_is_refused(self, handler, upload_root, tmp_path_factory):
        """A path outside the upload root is refused without creating a job."""
        outside = tmp_path_factory.mktemp("outside")

        with patch.object(
            handler, "read_json_body_validated", return_value=({"path": str(outside)}, None)
        ):
            result = handler._start_upload(MagicMock(), SCOPE)
            assert result.status_code == 403
            assert FolderUploadHandler._jobs == {}


class TestGetFolderUploadStatus:
    """Tests for getting folder upload status."""

    def test_get_status_not_found(self, handler):
        """Test getting status for non-existent folder."""
        result = handler._get_upload_status("invalid-folder", SCOPE)
        assert result.status_code == 404

    def test_get_status_success(self, handler):
        """Test getting status for existing folder."""
        now = datetime.now(timezone.utc)
        job = FolderUploadJob(
            folder_id="folder123",
            root_path="/test/path",
            status=FolderUploadStatus.UPLOADING,
            created_at=now,
            updated_at=now,
            total_files_found=10,
            files_uploaded=5,
            org_id="test_org",
        )
        FolderUploadHandler._jobs["folder123"] = job

        result = handler._get_upload_status("folder123", SCOPE)
        assert result.status_code == 200


class TestFolderList:
    """Tests for listing folder uploads."""

    def test_list_folders_empty(self, handler):
        """Test listing folders when none exist."""
        result = handler._list_folders({}, SCOPE)
        assert result.status_code == 200

        import json

        body = json.loads(result.body)
        assert body["folders"] == []
        assert body["count"] == 0

    def test_list_folders_with_jobs(self, handler):
        """Test listing folders with existing jobs."""
        now = datetime.now(timezone.utc)
        job = FolderUploadJob(
            folder_id="folder123",
            root_path="/test/path",
            status=FolderUploadStatus.COMPLETED,
            created_at=now,
            updated_at=now,
            org_id="test_org",
        )
        FolderUploadHandler._jobs["folder123"] = job
        FolderUploadHandler._jobs["other"] = FolderUploadJob(
            folder_id="other",
            root_path="/test/other",
            status=FolderUploadStatus.COMPLETED,
            created_at=now,
            updated_at=now,
            org_id="other_org",
        )

        result = handler._list_folders({}, SCOPE)
        assert result.status_code == 200

        import json

        body = json.loads(result.body)
        assert body["count"] == 1


class TestFolderDelete:
    """Tests for deleting folder uploads."""

    def test_delete_folder_not_found(self, handler):
        """Test deleting non-existent folder."""
        result = handler._delete_folder("invalid-folder", SCOPE)
        assert result.status_code == 404

    def test_delete_folder_success(self, handler):
        """Test successful folder deletion."""
        now = datetime.now(timezone.utc)
        job = FolderUploadJob(
            folder_id="folder123",
            root_path="/test/path",
            status=FolderUploadStatus.COMPLETED,
            created_at=now,
            updated_at=now,
            user_id="test_user",  # Match mock user
            org_id="test_org",
        )
        FolderUploadHandler._jobs["folder123"] = job

        result = handler._delete_folder("folder123", SCOPE)
        assert result.status_code == 200
        assert "folder123" not in FolderUploadHandler._jobs

    def test_delete_other_org_folder_is_not_found(self, handler):
        """Another org's folder answers 404 and is left in place."""
        now = datetime.now(timezone.utc)
        FolderUploadHandler._jobs["theirs"] = FolderUploadJob(
            folder_id="theirs",
            root_path="/test/path",
            status=FolderUploadStatus.COMPLETED,
            created_at=now,
            updated_at=now,
            user_id="test_user",
            org_id="other_org",
        )

        result = handler._delete_folder("theirs", SCOPE)
        assert result.status_code == 404
        assert "theirs" in FolderUploadHandler._jobs


class TestFolderJobStatusUpdate:
    """Tests for job status update methods."""

    def test_update_job_status(self, handler):
        """Test updating job status."""
        now = datetime.now(timezone.utc)
        job = FolderUploadJob(
            folder_id="folder123",
            root_path="/test/path",
            status=FolderUploadStatus.PENDING,
            created_at=now,
            updated_at=now,
        )
        FolderUploadHandler._jobs["folder123"] = job

        handler._update_job_status("folder123", FolderUploadStatus.UPLOADING)

        assert FolderUploadHandler._jobs["folder123"].status == FolderUploadStatus.UPLOADING

    def test_update_job_error(self, handler):
        """Test adding error to job."""
        now = datetime.now(timezone.utc)
        job = FolderUploadJob(
            folder_id="folder123",
            root_path="/test/path",
            status=FolderUploadStatus.UPLOADING,
            created_at=now,
            updated_at=now,
        )
        FolderUploadHandler._jobs["folder123"] = job

        handler._update_job_error("folder123", "Test error")

        assert len(FolderUploadHandler._jobs["folder123"].errors) == 1
        assert FolderUploadHandler._jobs["folder123"].errors[0]["error"] == "Test error"
