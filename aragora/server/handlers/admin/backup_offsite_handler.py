"""
Backup Offsite and Restore Drill HTTP Handlers.

Provides REST API endpoints for backup status, offsite operations,
and restore drill management:

Endpoints:
    GET  /api/v1/backup/status   - Current backup status and last successful backup
    GET  /api/v1/backup/drills   - List restore drill results
    POST /api/v1/backup/drill    - Trigger a manual restore drill

SOC 2 Compliance: CC9.1, CC9.2 (Business Continuity)
"""

from __future__ import annotations

import logging
from typing import Any

from aragora.rbac.decorators import require_permission
from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    json_response,
)
from aragora.server.handlers.utils.decorators import handle_errors
from aragora.server.handlers.utils.lazy_stores import LazyStoreFactory
from aragora.server.handlers.utils.rate_limit import rate_limit
from aragora.server.validation.query_params import safe_query_int

logger = logging.getLogger(__name__)


class BackupOffsiteHandler(BaseHandler):
    """
    HTTP handler for backup status, offsite operations, and restore drills.

    Provides REST API access to:
    - Backup status overview (last backup, total counts, latest drill)
    - Restore drill history for compliance auditing
    - Manual restore drill triggers
    """

    ROUTES = [
        "/api/v1/backup/status",
        "/api/v1/backup/drills",
        "/api/v1/backup/drill",
    ]

    def __init__(self, server_context: dict[str, Any]):
        """Initialize with server context."""
        super().__init__(server_context)
        self._manager_factory = LazyStoreFactory(
            store_name="backup_manager",
            import_path="aragora.backup.manager",
            factory_name="get_backup_manager",
            logger_context="BackupOffsite",
        )
        self._manager = None  # Set by tests or lazy init

    def _get_manager(self):
        """Get or create backup manager (lazy initialization)."""
        if self._manager is None:
            self._manager = self._manager_factory.get()
        return self._manager

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can process the request."""
        if path == "/api/v1/backup/status" and method == "GET":
            return True
        if path == "/api/v1/backup/drills" and method == "GET":
            return True
        if path == "/api/v1/backup/drill" and method == "POST":
            return True
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

        try:
            if path == "/api/v1/backup/status" and method == "GET":
                return await self._get_status()

            if path == "/api/v1/backup/drills" and method == "GET":
                return await self._list_drills(query_params)

            if path == "/api/v1/backup/drill" and method == "POST":
                return await self._trigger_drill(body)

            return error_response("Not found", 404)

        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
            logger.exception("Error handling backup offsite request: %s", e)
            return error_response("Internal server error", 500)

    @require_permission("backups:read")
    async def _get_status(self) -> HandlerResult:
        """
        Get current backup status.

        Returns backup overview including last successful backup, total
        counts, and latest drill result.
        """
        manager = self._get_manager()
        status = manager.get_backup_status()

        return json_response({"data": status})

    @require_permission("backups:read")
    async def _list_drills(self, query_params: dict[str, str]) -> HandlerResult:
        """
        List restore drill results for compliance auditing.

        Query params:
            limit: Max results (default 50, max 200)
        """
        manager = self._get_manager()
        limit = safe_query_int(query_params, "limit", default=50, min_val=1, max_val=200)

        drills = manager.get_drill_history(limit=limit)

        return json_response(
            {
                "data": {
                    "drills": [d.to_dict() for d in drills],
                    "total": len(drills),
                }
            }
        )

    @handle_errors("backup restore drill")
    @require_permission("backups:create")
    async def _trigger_drill(self, body: dict[str, Any]) -> HandlerResult:
        """
        Trigger a manual restore drill.

        Body:
            backup_id: Optional ID of backup to drill (uses latest if omitted)
        """
        manager = self._get_manager()
        backup_id = body.get("backup_id")

        report = manager.restore_drill(backup_id=backup_id)

        return json_response(
            {
                "data": report.to_dict(),
            },
            status=201 if report.status == "passed" else 200,
        )


def create_backup_offsite_handler(
    server_context: dict[str, Any],
) -> BackupOffsiteHandler:
    """Factory function for handler registration."""
    return BackupOffsiteHandler(server_context)
