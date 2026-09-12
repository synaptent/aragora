"""
Backup HTTP Handlers for Aragora.

Provides REST API endpoints for backup and disaster recovery:
- List and manage backups
- Trigger manual backups
- Verify backup integrity
- Test restore (dry-run)
- Cleanup expired backups

Endpoints:
    GET  /api/v2/backups                            - List backups with filters
    POST /api/v2/backups                            - Create new backup
    GET  /api/v2/backups/:backup_id                 - Get specific backup metadata
    POST /api/v2/backups/:backup_id/verify          - Verify backup integrity
    POST /api/v2/backups/:backup_id/verify-comprehensive - Comprehensive verification
    POST /api/v2/backups/:backup_id/restore-test    - Dry-run restore test
    DELETE /api/v2/backups/:backup_id               - Delete a backup
    POST /api/v2/backups/cleanup                    - Run retention policy cleanup
    GET  /api/v2/backups/stats                      - Backup statistics

These endpoints support enterprise disaster recovery requirements.
"""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aragora.backup.manager import get_default_backup_source_path
from aragora.rbac.decorators import require_permission
from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    json_response,
)
from aragora.server.handlers.utils.lazy_stores import LazyStoreFactory
from aragora.server.handlers.utils.rate_limit import rate_limit
from aragora.server.validation.query_params import safe_query_int
from aragora.utils.paths import PathTraversalError, safe_path

logger = logging.getLogger(__name__)


# SECURITY: Allowed base directories for backup source paths.
# Only files within these directories can be backed up via the API.
def _get_data_dir_resolved() -> Path:
    from aragora.persistence.db_config import get_nomic_dir

    return get_nomic_dir().resolve()


_ALLOWED_BACKUP_SOURCE_DIRS: list[Path] = [
    _get_data_dir_resolved(),
    Path("/var/aragora/data"),
    Path("/var/lib/aragora"),
]

# SECURITY: Allowed base directories for restore target paths.
# Restores can only target paths within these directories.
_ALLOWED_RESTORE_DIRS: list[Path] = [
    Path(
        os.environ.get(
            "ARAGORA_RESTORE_DIR", os.path.join(tempfile.gettempdir(), "aragora_restore")
        )
    ).resolve(),
    Path("/var/aragora/restore"),
]


class BackupHandler(BaseHandler):
    """
    HTTP handler for backup and disaster recovery operations.

    Provides REST API access to backup management with verification
    and dry-run restore capabilities.
    """

    ROUTES = [
        "/api/v2/backups",
        "/api/v2/backups/*",
        "/api/v1/backups/cleanup",
        "/api/v1/backups/stats",
    ]

    def __init__(self, server_context: dict[str, Any]):
        """Initialize with server context."""
        super().__init__(server_context)
        self._manager_factory = LazyStoreFactory(
            store_name="backup_manager",
            import_path="aragora.backup.manager",
            factory_name="get_backup_manager",
            logger_context="Backup",
        )
        self._manager = None  # Set by tests or lazy init

    def _get_manager(self):
        """Get or create backup manager (lazy initialization)."""
        if self._manager is None:
            self._manager = self._manager_factory.get()
        return self._manager

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can process the request."""
        if path.startswith("/api/v2/backups"):
            return method in ("GET", "POST", "DELETE")
        return False

    @rate_limit(requests_per_minute=30)
    async def handle(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """Route request to appropriate handler method."""
        method: str = getattr(handler, "command", "GET") if handler else "GET"
        body: dict[str, Any] = (self.read_json_body(handler) or {}) if handler else {}
        query_params = query_params or {}
        if path.rstrip("/") == "/api/v2/backups":
            path = "/api/v2/backups"

        try:
            # Stats endpoint
            if path == "/api/v2/backups/stats" and method == "GET":
                return await self._get_stats()

            # Cleanup endpoint
            if path == "/api/v2/backups/cleanup" and method == "POST":
                return await self._cleanup_expired(body)

            # List backups
            if path == "/api/v2/backups" and method == "GET":
                return await self._list_backups(query_params)

            # Create backup
            if path == "/api/v2/backups" and method == "POST":
                return await self._create_backup(body)

            # Backup-specific routes
            if path.startswith("/api/v2/backups/"):
                parts = path.split("/")
                if len(parts) < 5:
                    return error_response("Invalid backup path", 400)

                backup_id = parts[4]

                # Verify endpoint
                if len(parts) > 5 and parts[5] == "verify" and method == "POST":
                    return await self._verify_backup(backup_id)

                # Comprehensive verify endpoint
                if len(parts) > 5 and parts[5] == "verify-comprehensive" and method == "POST":
                    return await self._verify_comprehensive(backup_id)

                # Restore test endpoint
                if len(parts) > 5 and parts[5] == "restore-test" and method == "POST":
                    return await self._restore_test(backup_id, body)

                # Delete backup
                if method == "DELETE":
                    return await self._delete_backup(backup_id)

                # Get single backup
                if method == "GET":
                    return await self._get_backup(backup_id)

            return error_response("Not found", 404)

        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
            logger.exception("Error handling backup request: %s", e)
            return error_response("Internal server error", 500)

    @require_permission("backups:read")
    async def _list_backups(self, query_params: dict[str, str]) -> HandlerResult:
        """
        List backups with filtering and pagination.

        Query params:
            limit: Max results (default 20, max 100)
            offset: Pagination offset
            source: Filter by source database path
            status: Filter by status (completed, verified, failed)
            since: ISO date/timestamp for start
            backup_type: Filter by type (full, incremental, differential)
        """
        manager = self._get_manager()

        # Parse filters
        source_path = query_params.get("source")
        status_str = query_params.get("status")
        since_str = query_params.get("since")

        # Parse status enum
        status = None
        if status_str:
            from aragora.backup.manager import BackupStatus

            try:
                status = BackupStatus(status_str.lower())
            except ValueError:
                return error_response(
                    f"Invalid status: {status_str}. Valid: pending, in_progress, "
                    "completed, verified, failed, expired",
                    400,
                )

        # Parse since timestamp
        since = None
        if since_str:
            since = self._parse_timestamp(since_str)

        # Get backups from manager
        backups = manager.list_backups(
            source_path=source_path,
            status=status,
            since=since,
        )

        # Apply pagination
        limit = safe_query_int(query_params, "limit", default=20, min_val=1, max_val=100)
        offset = safe_query_int(query_params, "offset", default=0, min_val=0, max_val=10000)
        total = len(backups)
        backups = backups[offset : offset + limit]

        return json_response(
            {
                "backups": [b.to_dict() for b in backups],
                "pagination": {
                    "limit": limit,
                    "offset": offset,
                    "total": total,
                    "has_more": offset + len(backups) < total,
                },
            }
        )

    @require_permission("backups:read")
    async def _get_backup(self, backup_id: str) -> HandlerResult:
        """Get a specific backup by ID."""
        manager = self._get_manager()
        backups = manager.list_backups()

        # Find backup by ID
        backup = next((b for b in backups if b.id == backup_id), None)

        if not backup:
            return error_response("Backup not found", 404)

        return json_response(backup.to_dict())

    @require_permission("backups:create")
    async def _create_backup(self, body: dict[str, Any]) -> HandlerResult:
        """
        Create a new backup.

        Body:
            source_path: Path to the database to backup (required)
            backup_type: Type of backup (full, incremental, differential)
            metadata: Additional metadata to store
        """
        source_path = body.get("source_path")
        validated_path = None
        if not source_path:
            default_source = get_default_backup_source_path()
            if not default_source.exists():
                return error_response("Default backup source not found", 404)
            validated_path = default_source.resolve()

        # SECURITY: Validate source_path to prevent path traversal attacks.
        # Only allow paths within configured allowed directories.
        if validated_path is None:
            for allowed_base in _ALLOWED_BACKUP_SOURCE_DIRS:
                if not allowed_base.exists():
                    continue
                try:
                    validated_path = safe_path(allowed_base, source_path, must_exist=True)
                    break
                except PathTraversalError:
                    logger.debug(
                        "Path traversal attempt blocked for backup source: %s (base: %s)",
                        source_path,
                        allowed_base,
                    )
                    continue
                except FileNotFoundError:
                    # Path within allowed dir but doesn't exist - try next base
                    continue

        if validated_path is None:
            logger.warning("Backup source path validation failed: %s", source_path)
            return error_response(
                "Invalid source path. Path must be within allowed backup directories.",
                400,
            )

        backup_type_str = body.get("backup_type", "full")
        metadata = body.get("metadata", {})

        from aragora.backup.manager import BackupType

        try:
            backup_type = BackupType(backup_type_str.lower())
        except ValueError:
            return error_response(
                f"Invalid backup_type: {backup_type_str}. Valid: full, incremental, differential",
                400,
            )

        manager = self._get_manager()

        try:
            backup = manager.create_backup(
                source_path=validated_path,
                backup_type=backup_type,
                metadata=metadata,
            )

            return json_response(
                {
                    "backup": backup.to_dict(),
                    "message": f"Backup created: {backup.id}",
                },
                status=201,
            )

        except FileNotFoundError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Resource not found", 404)
        except (OSError, RuntimeError, AttributeError, TypeError) as e:
            logger.exception("Backup creation failed: %s", e)
            return error_response("Backup operation failed", 500)

    @require_permission("backups:verify")
    async def _verify_backup(self, backup_id: str) -> HandlerResult:
        """Verify backup integrity with restore test."""
        manager = self._get_manager()

        result = manager.verify_backup(backup_id, test_restore=True)

        return json_response(
            {
                "backup_id": result.backup_id,
                "verified": result.verified,
                "checksum_valid": result.checksum_valid,
                "restore_tested": result.restore_tested,
                "tables_valid": result.tables_valid,
                "row_counts_valid": result.row_counts_valid,
                "errors": result.errors,
                "warnings": result.warnings,
                "verified_at": result.verified_at.isoformat(),
                "duration_seconds": result.duration_seconds,
            }
        )

    @require_permission("backups:verify")
    async def _verify_comprehensive(self, backup_id: str) -> HandlerResult:
        """
        Perform comprehensive verification of a backup.

        Includes:
        - Basic verification (checksum, row counts, tables)
        - Schema validation (columns, types, constraints, indexes)
        - Referential integrity (foreign keys, orphans)
        - Per-table checksums
        """
        manager = self._get_manager()

        result = manager.verify_restore_comprehensive(backup_id)

        return json_response(result.to_dict())

    @require_permission("backups:restore")
    async def _restore_test(self, backup_id: str, body: dict[str, Any]) -> HandlerResult:
        """
        Test restore a backup (dry-run).

        Body:
            target_path: Optional target path for restore test
        """
        target_path = body.get("target_path", "restore_test.db")

        # SECURITY: Validate target_path to prevent path traversal attacks (CWE-22)
        validated_target = None
        for allowed_base in _ALLOWED_RESTORE_DIRS:
            try:
                if not allowed_base.exists():
                    allowed_base.mkdir(parents=True, exist_ok=True)
                validated_target = safe_path(allowed_base, target_path, must_exist=False)
                break
            except PathTraversalError:
                logger.debug(
                    "Path traversal attempt blocked for restore target: %s (base: %s)",
                    target_path,
                    allowed_base,
                )
                continue
            except OSError as e:
                logger.debug("Failed to validate restore path %s: %s", target_path, e)
                continue

        if validated_target is None:
            logger.warning("Restore target path validation failed: %s", target_path)
            return error_response(
                "Invalid target path. Path must be within allowed restore directories.",
                400,
            )

        manager = self._get_manager()

        try:
            # Dry run - doesn't actually restore
            success = manager.restore_backup(
                backup_id=backup_id,
                target_path=str(validated_target),
                dry_run=True,
            )

            return json_response(
                {
                    "backup_id": backup_id,
                    "restore_test_passed": success,
                    "target_path": str(validated_target),
                    "dry_run": True,
                    "message": "Dry-run restore test completed successfully",
                }
            )

        except ValueError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Invalid request", 400)
        except FileNotFoundError:
            return error_response("Resource not found", 404)

    @require_permission("backups:delete")
    async def _delete_backup(self, backup_id: str) -> HandlerResult:
        """Delete a backup by ID."""
        manager = self._get_manager()
        backups = manager.list_backups()

        # Find backup by ID
        backup = next((b for b in backups if b.id == backup_id), None)

        if not backup:
            return error_response("Backup not found", 404)

        from pathlib import Path

        try:
            backup_path = Path(backup.backup_path)
            if backup_path.exists():
                backup_path.unlink()
                logger.info("Deleted backup file: %s", backup_path)

            # Remove from manager's tracking
            if backup_id in manager._backups:
                del manager._backups[backup_id]
                manager._save_manifest()

            return json_response(
                {
                    "deleted": True,
                    "backup_id": backup_id,
                    "message": f"Backup {backup_id} deleted",
                }
            )

        except (OSError, KeyError, AttributeError) as e:
            logger.exception("Failed to delete backup: %s", e)
            return error_response("Delete operation failed", 500)

    @require_permission("backups:delete")
    async def _cleanup_expired(self, body: dict[str, Any]) -> HandlerResult:
        """
        Run retention policy cleanup.

        Body:
            dry_run: If true, only report what would be deleted (default: true)
        """
        dry_run = body.get("dry_run", True)

        manager = self._get_manager()

        deleted_ids = manager.apply_retention_policy(dry_run=dry_run)

        return json_response(
            {
                "dry_run": dry_run,
                "backup_ids": deleted_ids,
                "count": len(deleted_ids),
                "message": (
                    f"Would delete {len(deleted_ids)} backups"
                    if dry_run
                    else f"Deleted {len(deleted_ids)} expired backups"
                ),
            }
        )

    @require_permission("backups:read")
    async def _get_stats(self) -> HandlerResult:
        """Get backup statistics."""
        manager = self._get_manager()
        backups = manager.list_backups()

        from aragora.backup.manager import BackupStatus

        # Compute statistics
        total_size = sum(b.compressed_size_bytes for b in backups)
        verified_count = sum(1 for b in backups if b.verified)
        failed_count = sum(1 for b in backups if b.status == BackupStatus.FAILED)

        # Get latest backup
        latest = manager.get_latest_backup()

        stats = {
            "total_backups": len(backups),
            "verified_backups": verified_count,
            "failed_backups": failed_count,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "latest_backup": latest.to_dict() if latest else None,
            "retention_policy": {
                "keep_daily": manager.retention_policy.keep_daily,
                "keep_weekly": manager.retention_policy.keep_weekly,
                "keep_monthly": manager.retention_policy.keep_monthly,
                "min_backups": manager.retention_policy.min_backups,
            },
        }

        return json_response(
            {
                "stats": stats,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    def _parse_timestamp(self, value: str | None) -> datetime | None:
        """Parse timestamp from string (ISO date or unix timestamp)."""
        if not value:
            return None

        try:
            # Try as unix timestamp
            ts = float(value)
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except ValueError:
            logger.debug("Date value %r is not a valid unix timestamp, trying ISO format", value)

        try:
            # Try as ISO date
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt
        except (ValueError, AttributeError):
            logger.debug("Date value %r is not a valid ISO date format", value)

        return None


# Handler factory function for registration
def create_backup_handler(server_context: dict[str, Any]) -> BackupHandler:
    """Factory function for handler registration."""
    return BackupHandler(server_context)
