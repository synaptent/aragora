"""
Folder upload endpoint handlers.

Endpoints:
- POST /api/documents/folder/scan - Scan a folder and return what would be uploaded
- POST /api/documents/folder/upload - Start folder upload
- GET /api/documents/folder/upload/{folder_id}/status - Get upload progress
- GET /api/documents/folders - List uploaded folder sets
- GET /api/documents/folders/{folder_id} - Get folder details
- DELETE /api/documents/folders/{folder_id} - Delete an uploaded folder set

Every route needs a caller with an org. Folder uploads belong to the org of the
user who started them and their documents are stored under that org; another
org's folder answers like a missing one.

Scan and upload read server directories, so they only accept folders inside an
import root configured for the caller's org in ARAGORA_ORG_IMPORT_ROOTS (see
aragora.documents.folder.import_roots) and are refused while the org has none.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from aragora.documents.folder.import_roots import (
    file_in_folder,
    inside_roots,
    open_folder,
    org_import_roots,
    protected_paths,
    read_file_in_folder,
    still_folder,
)
from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
    safe_error_message,
)
from ..utils.file_validation import validate_file_upload, MAX_FILE_SIZE
from ..utils.rate_limit import rate_limit
from aragora.rbac.decorators import require_permission
from aragora.server.validation.query_params import safe_query_int
from aragora.tenancy.record_scope import (
    OrgScope,
    record_not_found,
    record_visible,
    require_org_scope,
)

logger = logging.getLogger(__name__)


def _import_roots_not_configured() -> HandlerResult:
    return json_response(
        {
            "error": "Folder scan and upload are disabled: no import root is configured "
            "for your organization (ARAGORA_ORG_IMPORT_ROOTS)",
            "code": "import_roots_not_configured",
        },
        status=403,
    )


def _path_not_allowed() -> HandlerResult:
    logger.warning("Folder path outside the caller's import roots refused")
    return json_response(
        {"error": "Access denied: path not in allowed directories", "code": "path_not_allowed"},
        status=403,
    )


def _validate_upload_path(folder_path: str, roots: Sequence[Path]) -> Path | HandlerResult:
    """Resolve a requested folder, or return the error response refusing it.

    Containment is checked on the fully resolved path (symlinks and ``..``
    included) before the path is tested for existence, so a path outside every
    allowed directory gets the same answer whether or not it exists.
    """
    if not inside_roots(folder_path, roots):
        return _path_not_allowed()

    path = Path(folder_path).resolve()
    if not path.exists():
        return error_response(f"Path does not exist: {folder_path}", 404)
    if not path.is_dir():
        return error_response(f"Path is not a directory: {folder_path}", 400)
    return path


def _drop_entries_outside(result, folder: Path) -> None:
    """Remove every scan entry whose resolved path leaves the resolved ``folder``."""
    own, link = [folder], "Symlink points outside root: "
    result.included_files = [f for f in result.included_files if inside_roots(f.absolute_path, own)]
    result.excluded_files = [f for f in result.excluded_files if inside_roots(folder / f.path, own)]
    result.warnings = [w for w in result.warnings if not w.startswith(link)]


class FolderUploadStatus(Enum):
    """Status of a folder upload job."""

    PENDING = "pending"
    SCANNING = "scanning"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class FolderUploadJob:
    """Tracks state of an in-progress folder upload."""

    folder_id: str
    root_path: str
    status: FolderUploadStatus
    created_at: datetime
    updated_at: datetime
    user_id: str | None = None
    org_id: str | None = None  # Owning org; None means unknown owner

    # Scan results
    total_files_found: int = 0
    included_count: int = 0
    excluded_count: int = 0
    total_size_bytes: int = 0

    # Upload progress
    files_uploaded: int = 0
    files_failed: int = 0
    bytes_uploaded: int = 0

    # Results
    document_ids: list[str] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)

    # Configuration used
    config: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "folder_id": self.folder_id,
            "root_path": self.root_path,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "user_id": self.user_id,
            "org_id": self.org_id,
            "scan": {
                "total_files_found": self.total_files_found,
                "included_count": self.included_count,
                "excluded_count": self.excluded_count,
                "total_size_bytes": self.total_size_bytes,
            },
            "progress": {
                "files_uploaded": self.files_uploaded,
                "files_failed": self.files_failed,
                "bytes_uploaded": self.bytes_uploaded,
                "percent_complete": (
                    round(self.files_uploaded / self.included_count * 100, 1)
                    if self.included_count > 0
                    else 0
                ),
            },
            "results": {
                "document_ids": self.document_ids,
                "errors": self.errors[-10:],  # Last 10 errors
                "error_count": len(self.errors),
            },
            "config": self.config,
        }


class FolderUploadHandler(BaseHandler):
    """Handler for folder upload endpoints."""

    def __init__(self, ctx: dict | None = None, server_context: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = server_context or ctx or {}

    ROUTES = [
        "/api/v1/documents/folder/scan",
        "/api/v1/documents/folder/upload",
        "/api/v1/documents/folders",
    ]

    # In-memory job storage (would be persisted in production)
    _jobs: dict[str, FolderUploadJob] = {}
    _jobs_lock = threading.Lock()

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        if path in self.ROUTES:
            return True
        # Handle /api/documents/folder/upload/{folder_id}/status
        if path.startswith("/api/v1/documents/folder/upload/") and path.endswith("/status"):
            return True
        # Handle /api/v1/documents/folders/{folder_id}
        if path.startswith("/api/v1/documents/folders/") and path.count("/") == 5:
            return True
        return False

    @handle_errors("folder upload retrieval")
    @require_permission("upload:create")
    @rate_limit(requests_per_minute=30)
    def handle(self, path: str, query_params: dict, handler) -> HandlerResult | None:
        """Route GET folder requests."""
        if path == "/api/v1/documents/folders":
            scope, scope_err = require_org_scope(handler)
            if scope is None:
                return scope_err
            return self._list_folders(query_params, scope)

        # GET /api/documents/folder/upload/{folder_id}/status
        if path.startswith("/api/v1/documents/folder/upload/") and path.endswith("/status"):
            scope, scope_err = require_org_scope(handler)
            if scope is None:
                return scope_err
            folder_id = path.split("/")[-2]
            return self._get_upload_status(folder_id, scope)

        # GET /api/v1/documents/folders/{folder_id}
        if path.startswith("/api/v1/documents/folders/"):
            scope, scope_err = require_org_scope(handler)
            if scope is None:
                return scope_err
            folder_id, err = self.extract_path_param(path, 5, "folder_id")
            if err:
                return err
            return self._get_folder(folder_id, scope)

        return None

    @handle_errors("folder upload creation")
    @require_permission("upload:create")
    @rate_limit(requests_per_minute=10)
    async def handle_post(self, path: str, query_params: dict, handler) -> HandlerResult | None:
        """Route POST folder requests."""
        if path not in ("/api/v1/documents/folder/scan", "/api/v1/documents/folder/upload"):
            return None
        scope, scope_err = require_org_scope(handler)
        if scope is None:
            return scope_err
        store_dir = getattr(self.get_document_store(), "storage_dir", None)
        roots = org_import_roots(scope.org_id, protected_paths(self.get_nomic_dir(), store_dir))
        if not roots:
            return _import_roots_not_configured()

        if path == "/api/v1/documents/folder/scan":
            return await self._scan_folder(handler, roots)
        return self._start_upload(handler, scope, roots)

    @handle_errors("folder upload deletion")
    @require_permission("documents:delete")
    def handle_delete(self, path: str, query_params: dict, handler) -> HandlerResult | None:
        """Route DELETE folder requests."""
        if path.startswith("/api/v1/documents/folders/"):
            scope, scope_err = require_org_scope(handler)
            if scope is None:
                return scope_err
            folder_id, err = self.extract_path_param(path, 5, "folder_id")
            if err:
                return err
            # Positional, so the permission decorator finds the request's auth context.
            return self._delete_folder(folder_id, scope, handler)
        return None

    @handle_errors("folder scan")
    async def _scan_folder(self, handler, roots: Sequence[Path]) -> HandlerResult:
        """Scan a folder and return what would be uploaded.

        Request body:
        {
            "path": "/absolute/path/to/folder",
            "config": {
                "maxDepth": 10,
                "excludePatterns": ["**/.git/**"],
                "maxFileSizeMb": 100,
                "maxTotalSizeMb": 500,
                "maxFileCount": 1000
            }
        }
        """
        body, err = self.read_json_body_validated(handler)
        if err:
            return err

        folder_path = body.get("path")
        if not folder_path:
            return error_response("Missing required field: path", 400)

        path = _validate_upload_path(folder_path, roots)
        if isinstance(path, HandlerResult):
            return path

        # Build config from request
        config_data = body.get("config", {})

        try:
            from aragora.documents.folder import FolderScanner, FolderUploadConfig

            config = FolderUploadConfig(
                max_depth=config_data.get("maxDepth", 10),
                follow_symlinks=config_data.get("followSymlinks", False),
                exclude_patterns=config_data.get("excludePatterns", [])
                + list(FolderUploadConfig().exclude_patterns),
                include_patterns=config_data.get("includePatterns", []),
                max_file_size_mb=config_data.get("maxFileSizeMb", 100),
                max_total_size_mb=config_data.get("maxTotalSizeMb", 500),
                max_file_count=config_data.get("maxFileCount", 1000),
            )

            scanner = FolderScanner(config)

            try:
                folder_fd = open_folder(path, roots)
            except OSError:
                return _path_not_allowed()  # swapped for a link since the check
            try:
                result = await scanner.scan(path)
                unchanged = still_folder(folder_fd, path)
            finally:
                os.close(folder_fd)
            if not unchanged:
                return _path_not_allowed()
            _drop_entries_outside(result, path)

            return json_response(result.to_dict())

        except ImportError as e:
            logger.error("Folder scanner not available: %s", e)
            return error_response("Folder scanning not available", 503)
        except ValueError:
            return error_response("Invalid request", 400)
        except (RuntimeError, OSError, TypeError, KeyError) as e:
            logger.error("Folder scan error: %s", e)
            return error_response(safe_error_message(e, "Scan"), 500)

    @handle_errors("folder upload")
    def _start_upload(self, handler, scope: OrgScope, roots: Sequence[Path]) -> HandlerResult:
        """Start an async folder upload.

        Request body:
        {
            "path": "/absolute/path/to/folder",
            "config": {
                "maxDepth": 10,
                "excludePatterns": ["**/.git/**"],
                "maxFileSizeMb": 100,
                "maxTotalSizeMb": 500,
                "maxFileCount": 1000
            }
        }

        Returns:
        {
            "folder_id": "uuid",
            "status": "scanning",
            "message": "Upload started"
        }
        """
        body, err = self.read_json_body_validated(handler)
        if err:
            return err

        folder_path = body.get("path")
        if not folder_path:
            return error_response("Missing required field: path", 400)

        path = _validate_upload_path(folder_path, roots)
        if isinstance(path, HandlerResult):
            return path

        # Create job
        folder_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        job = FolderUploadJob(
            folder_id=folder_id,
            root_path=str(path),
            status=FolderUploadStatus.PENDING,
            created_at=now,
            updated_at=now,
            user_id=scope.user_id,
            org_id=scope.org_id,
            config=body.get("config", {}),
        )

        with FolderUploadHandler._jobs_lock:
            FolderUploadHandler._jobs[folder_id] = job

        # Start async upload in background
        thread = threading.Thread(
            target=self._run_upload_job,
            args=(folder_id, path, body.get("config", {}), scope, list(roots)),
            daemon=True,
        )
        thread.start()

        return json_response(
            {
                "folder_id": folder_id,
                "status": "scanning",
                "message": "Upload started. Poll /api/documents/folder/upload/{folder_id}/status for progress.",
            }
        )

    def _run_upload_job(
        self,
        folder_id: str,
        path: Path,
        config_data: dict,
        scope: OrgScope,
        roots: Sequence[Path],
    ) -> None:
        """Run folder upload job in background thread, storing documents under the scope's org.

        ``path`` is the folder as resolved when the request was checked against ``roots``.
        It is held open from those roots and every file is read through that handle, so
        nothing outside it is read even if the folder or a file is swapped for a link.
        """
        folder_fd: int | None = None
        try:
            self._update_job_status(folder_id, FolderUploadStatus.SCANNING)
            folder_fd = open_folder(path, roots)

            from aragora.documents.folder import FolderScanner, FolderUploadConfig

            config = FolderUploadConfig(
                max_depth=config_data.get("maxDepth", 10),
                follow_symlinks=config_data.get("followSymlinks", False),
                exclude_patterns=config_data.get("excludePatterns", [])
                + list(FolderUploadConfig().exclude_patterns),
                include_patterns=config_data.get("includePatterns", []),
                max_file_size_mb=config_data.get("maxFileSizeMb", 100),
                max_total_size_mb=config_data.get("maxTotalSizeMb", 500),
                max_file_count=config_data.get("maxFileCount", 1000),
            )

            scanner = FolderScanner(config)

            # Run scan
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                scan_result = loop.run_until_complete(scanner.scan(path))
            finally:
                loop.close()
            if not still_folder(folder_fd, path):
                raise PermissionError("folder was replaced during the scan")
            _drop_entries_outside(scan_result, path)

            # Update job with scan results
            with FolderUploadHandler._jobs_lock:
                if folder_id in FolderUploadHandler._jobs:
                    job = FolderUploadHandler._jobs[folder_id]
                    job.total_files_found = scan_result.total_files_found
                    job.included_count = scan_result.included_count
                    job.excluded_count = scan_result.excluded_count
                    job.total_size_bytes = scan_result.included_size_bytes
                    job.updated_at = datetime.now(timezone.utc)

            if scan_result.included_count == 0:
                self._update_job_status(folder_id, FolderUploadStatus.COMPLETED)
                return

            # Start uploading
            self._update_job_status(folder_id, FolderUploadStatus.UPLOADING)

            store = self.get_document_store()
            if not store:
                self._update_job_error(folder_id, "Document storage not configured")
                self._update_job_status(folder_id, FolderUploadStatus.FAILED)
                return

            try:
                from aragora.server.documents import parse_document
            except ImportError:
                self._update_job_error(folder_id, "Document parsing not available")
                self._update_job_status(folder_id, FolderUploadStatus.FAILED)
                return

            # Upload each file
            for file_info in scan_result.included_files:
                try:
                    file_path = Path(file_info.absolute_path)
                    rel = file_in_folder(path, file_path)
                    if rel is None:
                        continue  # replaced by a link leaving the folder after the scan

                    # Validate file before reading (check filename security and size)
                    # Note: size is from scan, actual read will verify
                    file_validation = validate_file_upload(
                        filename=file_path.name,
                        size=file_info.size_bytes,
                        content_type=None,  # Inferred from extension
                    )
                    if not file_validation.valid:
                        raise ValueError(file_validation.error_message or "File validation failed")

                    content = read_file_in_folder(folder_fd, rel, MAX_FILE_SIZE + 1)

                    # Verify actual size matches expected
                    if len(content) > MAX_FILE_SIZE:
                        raise ValueError(
                            f"File too large: {len(content)} bytes exceeds {MAX_FILE_SIZE} byte limit"
                        )

                    doc = parse_document(
                        content, file_path.name, org_id=scope.org_id, created_by=scope.user_id
                    )
                    doc_id = store.add(doc)

                    with FolderUploadHandler._jobs_lock:
                        if folder_id in FolderUploadHandler._jobs:
                            job = FolderUploadHandler._jobs[folder_id]
                            job.files_uploaded += 1
                            job.bytes_uploaded += file_info.size_bytes
                            job.document_ids.append(doc_id)
                            job.updated_at = datetime.now(timezone.utc)

                    logger.debug("Uploaded %s -> %s", file_path.name, doc_id)

                except (OSError, ValueError, RuntimeError, TypeError, KeyError) as e:
                    logger.warning("Failed to upload %s: %s", file_info.path, e)
                    with FolderUploadHandler._jobs_lock:
                        if folder_id in FolderUploadHandler._jobs:
                            job = FolderUploadHandler._jobs[folder_id]
                            job.files_failed += 1
                            job.errors.append(
                                {
                                    "file": file_info.path,
                                    "error": "File upload failed",
                                }
                            )
                            job.updated_at = datetime.now(timezone.utc)

            self._update_job_status(folder_id, FolderUploadStatus.COMPLETED)

        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
            logger.error("Folder upload job %s failed: %s", folder_id, e)
            self._update_job_error(folder_id, "Folder upload failed")
            self._update_job_status(folder_id, FolderUploadStatus.FAILED)
        finally:
            if folder_fd is not None:
                os.close(folder_fd)

    def _update_job_status(self, folder_id: str, status: FolderUploadStatus) -> None:
        """Update job status."""
        with FolderUploadHandler._jobs_lock:
            if folder_id in FolderUploadHandler._jobs:
                job = FolderUploadHandler._jobs[folder_id]
                job.status = status
                job.updated_at = datetime.now(timezone.utc)

    def _update_job_error(self, folder_id: str, error: str) -> None:
        """Add error to job."""
        with FolderUploadHandler._jobs_lock:
            if folder_id in FolderUploadHandler._jobs:
                job = FolderUploadHandler._jobs[folder_id]
                job.errors.append({"error": error, "fatal": True})
                job.updated_at = datetime.now(timezone.utc)

    def get_document_store(self):
        """Get document store instance."""
        return self.ctx.get("document_store")

    def _visible_job(self, folder_id: str, scope: OrgScope) -> FolderUploadJob | None:
        with FolderUploadHandler._jobs_lock:
            job = FolderUploadHandler._jobs.get(folder_id)
        if job is None or not record_visible(job.org_id, scope):
            return None
        return job

    def _get_upload_status(self, folder_id: str, scope: OrgScope) -> HandlerResult:
        """Get status of a folder upload job."""
        job = self._visible_job(folder_id, scope)
        if not job:
            return record_not_found("Folder")

        return json_response(job.to_dict())

    def _list_folders(self, query_params: dict, scope: OrgScope) -> HandlerResult:
        """List the caller org's folder upload jobs."""
        with FolderUploadHandler._jobs_lock:
            jobs = [
                job
                for job in FolderUploadHandler._jobs.values()
                if record_visible(job.org_id, scope)
            ]

        # Sort by created_at descending
        jobs.sort(key=lambda j: j.created_at, reverse=True)

        # Apply limit
        limit = safe_query_int(query_params, "limit", default=50, min_val=1, max_val=500)
        jobs = jobs[:limit]

        return json_response(
            {
                "folders": [job.to_dict() for job in jobs],
                "count": len(jobs),
            }
        )

    def _get_folder(self, folder_id: str, scope: OrgScope) -> HandlerResult:
        """Get details of a specific folder upload."""
        job = self._visible_job(folder_id, scope)
        if not job:
            return record_not_found("Folder")

        return json_response(job.to_dict())

    @handle_errors("folder delete")
    @require_permission("documents:delete")
    def _delete_folder(self, folder_id: str, scope: OrgScope, handler=None) -> HandlerResult:
        """Delete a folder upload and optionally its documents."""
        with FolderUploadHandler._jobs_lock:
            job = FolderUploadHandler._jobs.get(folder_id)

            if not job or not record_visible(job.org_id, scope):
                return record_not_found("Folder")

            # Within the org, only the user who started the upload may delete it
            if job.user_id and job.user_id != scope.user_id:
                return error_response("Not authorized to delete this folder", 403)

            # Remove job
            del FolderUploadHandler._jobs[folder_id]

        logger.info("Deleted folder upload: %s", folder_id)
        return json_response(
            {
                "success": True,
                "message": f"Folder {folder_id} deleted",
                "documents_deleted": 0,  # Documents are kept by default
            }
        )
