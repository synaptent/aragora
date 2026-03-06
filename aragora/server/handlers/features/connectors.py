"""
Enterprise Connectors API Handler.

Provides management and monitoring of enterprise data source connectors:
- List available and configured connectors
- Configure connector credentials
- Start/stop sync operations
- View sync history and statistics

Usage:
    GET    /api/connectors                    - List all connectors
    GET    /api/connectors/{id}               - Get connector details
    POST   /api/connectors                    - Configure new connector
    PUT    /api/connectors/{id}               - Update connector config
    DELETE /api/connectors/{id}               - Remove connector
    POST   /api/connectors/{id}/sync          - Start sync
    POST   /api/connectors/sync/{sync_id}/cancel - Cancel running sync
    POST   /api/connectors/test               - Test connection
    GET    /api/connectors/sync-history       - Get sync history
    GET    /api/connectors/stats              - Get aggregate stats
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, TypedDict
from uuid import uuid4

from aragora.rbac.decorators import require_permission


class ConnectorTypeMeta(TypedDict, total=False):
    """Metadata for a connector type."""

    name: str
    description: str
    category: str
    coming_soon: bool
    expected_sync_duration: int


from aragora.server.handlers.secure import SecureHandler, ForbiddenError, UnauthorizedError
from aragora.server.handlers.utils import parse_json_body
from aragora.server.handlers.utils.responses import error_response

logger = logging.getLogger(__name__)

# Persistent storage
try:
    from aragora.connectors.enterprise.sync_store import (
        SyncStore,
        get_sync_store,
    )

    HAS_SYNC_STORE = True
except ImportError:
    HAS_SYNC_STORE = False
    logger.warning(
        "ENTERPRISE CONNECTORS: sync_store module not available - using in-memory fallback. "
        "CONNECTOR CONFIGURATIONS WILL BE LOST ON RESTART! "
        "To fix: ensure aragora.connectors.enterprise.sync_store is importable."
    )

# In-memory fallback storage (used when sync_store not available)
_connectors: dict[str, dict[str, Any]] = {}
_sync_jobs: dict[str, dict[str, Any]] = {}
_sync_history: list[dict[str, Any]] = []

# Global store instance (lazily initialized)
_store: SyncStore | None = None


async def _get_store() -> SyncStore | None:
    """Get the sync store, initializing if needed."""
    global _store
    if _store is None and HAS_SYNC_STORE:
        try:
            _store = await get_sync_store()
            logger.info("Using persistent sync store for enterprise connectors")
        except (ConnectionError, TimeoutError, OSError, ValueError, TypeError, RuntimeError) as e:
            logger.warning(
                "ENTERPRISE CONNECTORS: Failed to initialize sync store: %s. Using in-memory fallback - CONFIGURATIONS WILL BE LOST ON RESTART!",
                e,
            )
    return _store


# Connector type metadata
CONNECTOR_TYPES: dict[str, ConnectorTypeMeta] = {
    "github": {
        "name": "GitHub Enterprise",
        "description": "Sync repositories, issues, and pull requests from GitHub",
        "category": "git",
    },
    "s3": {
        "name": "Amazon S3",
        "description": "Index documents from S3 buckets",
        "category": "documents",
    },
    "sharepoint": {
        "name": "Microsoft SharePoint",
        "description": "Sync document libraries from SharePoint Online",
        "category": "documents",
    },
    "postgresql": {
        "name": "PostgreSQL",
        "description": "Sync data from PostgreSQL databases",
        "category": "database",
    },
    "mongodb": {
        "name": "MongoDB",
        "description": "Index collections from MongoDB",
        "category": "database",
    },
    "confluence": {
        "name": "Atlassian Confluence",
        "description": "Index spaces and pages from Confluence",
        "category": "collaboration",
    },
    "notion": {
        "name": "Notion",
        "description": "Sync workspaces and databases from Notion",
        "category": "collaboration",
    },
    "slack": {
        "name": "Slack",
        "description": "Index channel messages and threads",
        "category": "collaboration",
    },
    "fhir": {
        "name": "FHIR (Healthcare)",
        "description": "Connect to FHIR-compliant healthcare systems",
        "category": "healthcare",
    },
    "gdrive": {
        "name": "Google Drive",
        "description": "Sync documents from Google Drive",
        "category": "documents",
        "coming_soon": True,
    },
    "docusign": {
        "name": "DocuSign",
        "description": "E-signature integration for contracts and documents",
        "category": "legal",
    },
    "pagerduty": {
        "name": "PagerDuty",
        "description": "Incident management and on-call scheduling",
        "category": "devops",
    },
    "plaid": {
        "name": "Plaid",
        "description": "Bank account connectivity and transaction sync",
        "category": "accounting",
    },
    "qbo": {
        "name": "QuickBooks Online",
        "description": "Accounting integration for invoices, bills, and journal entries",
        "category": "accounting",
    },
    "gusto": {
        "name": "Gusto",
        "description": "Payroll integration for employee pay data",
        "category": "accounting",
    },
}


class ConnectorsHandler(SecureHandler):
    """Handler for enterprise connector endpoints.

    Extends SecureHandler for JWT-based authentication, RBAC permission
    enforcement, and security audit logging.

    Provides CRUD operations and sync management for data source connectors.
    """

    def __init__(self, ctx: dict | None = None, server_context: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = server_context or ctx or {}

    RESOURCE_TYPE = "connector"

    ROUTES = [
        "/api/v1/connectors",
        "/api/v1/connectors/{connector_id}",
        "/api/v1/connectors/{connector_id}/sync",
        "/api/v1/connectors/sync/{sync_id}/cancel",
        "/api/v1/connectors/test",
        "/api/v1/connectors/sync-history",
        "/api/v1/connectors/stats",
        "/api/v1/connectors/health",
        "/api/v1/connectors/types",
    ]

    async def _check_permission(self, request: Any, permission: str) -> Any:
        """Check if user has the required permission using RBAC system.

        Returns error response if permission denied or auth fails, None if allowed.
        """
        try:
            auth_context = await self.get_auth_context(request, require_auth=True)
            self.check_permission(auth_context, permission)
            return None
        except UnauthorizedError:
            return error_response("Authentication required", 401)
        except ForbiddenError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Permission denied", 403)

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can handle the given path."""
        return path.startswith("/api/v1/connectors/")

    async def handle_request(self, request: Any) -> dict[str, Any]:
        """Route request to appropriate handler."""
        method = request.method
        path = str(request.path)

        # Parse IDs from path
        connector_id = None
        sync_id = None

        if "/connectors/" in path:
            parts = path.split("/connectors/")
            if len(parts) > 1:
                remaining = parts[1].split("/")
                # First segment after /connectors/ is the connector_id (unless it's a special route)
                if remaining[0] not in ("sync-history", "stats", "health", "test", "types", "sync"):
                    connector_id = remaining[0]

        # For sync cancel operations, parse sync_id from /sync/{sync_id}/cancel
        if "/connectors/sync/" in path:
            parts = path.split("/connectors/sync/")
            if len(parts) > 1:
                remaining = parts[1].split("/")
                sync_id = remaining[0]

        # Route to appropriate handler with permission checks
        if path.endswith("/connectors") and method == "GET":
            if err := await self._check_permission(request, "connectors:read"):
                return err
            return await self._list_connectors(request)
        elif path.endswith("/connectors") and method == "POST":
            if err := await self._check_permission(request, "connectors:create"):
                return err
            return await self._create_connector(request)
        elif path.endswith("/types"):
            # Connector types metadata is public
            return await self._list_types(request)
        elif path.endswith("/sync-history"):
            if err := await self._check_permission(request, "connectors:read"):
                return err
            return await self._get_sync_history(request)
        elif path.endswith("/stats"):
            if err := await self._check_permission(request, "connectors:read"):
                return err
            return await self._get_stats(request)
        elif path.endswith("/health"):
            if err := await self._check_permission(request, "connectors:read"):
                return err
            return await self._get_health(request)
        elif path.endswith("/test") and method == "POST":
            if err := await self._check_permission(request, "connectors:configure"):
                return err
            return await self._test_connection(request)
        elif sync_id and path.endswith("/cancel"):
            if err := await self._check_permission(request, "connectors:configure"):
                return err
            return await self._cancel_sync(request, sync_id)
        elif connector_id and path.endswith("/sync") and method == "POST":
            if err := await self._check_permission(request, "connectors:configure"):
                return err
            return await self._start_sync(request, connector_id)
        elif connector_id and method == "GET":
            if err := await self._check_permission(request, "connectors:read"):
                return err
            return await self._get_connector(request, connector_id)
        elif connector_id and method == "PUT":
            if err := await self._check_permission(request, "connectors:configure"):
                return err
            return await self._update_connector(request, connector_id)
        elif connector_id and method == "DELETE":
            if err := await self._check_permission(request, "connectors:delete"):
                return err
            return await self._delete_connector(request, connector_id)

        return self._error_response(404, "Endpoint not found")

    async def _list_connectors(self, request: Any) -> dict[str, Any]:
        """
        List all configured connectors.

        Query params:
        - status: filter by status (connected, disconnected, syncing, error)
        - type: filter by connector type
        - category: filter by category (git, documents, database, collaboration)
        """
        status_filter = request.query.get("status")
        type_filter = request.query.get("type")
        category_filter = request.query.get("category")

        # Try persistent store first
        store = await _get_store()
        if store:
            connector_configs = await store.list_connectors(
                status=status_filter,
                connector_type=type_filter,
            )
            connectors = [
                {
                    "id": c.id,
                    "type": c.connector_type,
                    "name": c.name,
                    "status": c.status,
                    "config": c.config,
                    "created_at": c.created_at.isoformat(),
                    "updated_at": c.updated_at.isoformat(),
                    "items_synced": c.items_indexed,
                    "last_sync": c.last_sync_at.isoformat() if c.last_sync_at else None,
                    "error_message": c.error_message,
                }
                for c in connector_configs
            ]
        else:
            connectors = list(_connectors.values())

        # Add active sync info
        for connector in connectors:
            active_sync = next(
                (
                    s
                    for s in _sync_jobs.values()
                    if s["connector_id"] == connector["id"] and s["status"] == "running"
                ),
                None,
            )
            if active_sync:
                connector["status"] = "syncing"
                connector["sync_progress"] = active_sync.get("progress", 0)

        # Apply category filter (not handled by store)
        if category_filter:
            empty_meta: ConnectorTypeMeta = {}
            connectors = [
                c
                for c in connectors
                if CONNECTOR_TYPES.get(str(c["type"]), empty_meta).get("category")
                == category_filter
            ]

        return self._json_response(
            200,
            {
                "connectors": connectors,
                "total": len(connectors),
                "connected": sum(
                    1 for c in connectors if c["status"] in ("connected", "syncing", "configured")
                ),
                "disconnected": sum(1 for c in connectors if c["status"] == "disconnected"),
                "errors": sum(1 for c in connectors if c["status"] == "error"),
            },
        )

    async def _get_connector(self, request: Any, connector_id: str) -> dict[str, Any]:
        """Get details for a specific connector."""
        store = await _get_store()

        if store:
            config = await store.get_connector(connector_id)
            if not config:
                return self._error_response(404, f"Connector {connector_id} not found")

            connector = {
                "id": config.id,
                "type": config.connector_type,
                "name": config.name,
                "status": config.status,
                "config": config.config,
                "created_at": config.created_at.isoformat(),
                "updated_at": config.updated_at.isoformat(),
                "items_synced": config.items_indexed,
                "last_sync": config.last_sync_at.isoformat() if config.last_sync_at else None,
                "error_message": config.error_message,
            }

            # Add recent sync history from store
            history = await store.get_sync_history(connector_id, limit=5)
            connector["recent_syncs"] = [
                {
                    "id": j.id,
                    "status": j.status,
                    "started_at": j.started_at.isoformat(),
                    "completed_at": j.completed_at.isoformat() if j.completed_at else None,
                    "items_synced": j.items_synced,
                    "items_failed": j.items_failed,
                    "duration_seconds": j.duration_seconds,
                }
                for j in history
            ]
        else:
            connector = _connectors.get(connector_id)
            if not connector:
                return self._error_response(404, f"Connector {connector_id} not found")

            # Add recent sync history
            connector["recent_syncs"] = [
                s for s in _sync_history if s["connector_id"] == connector_id
            ][-5:]

        # Add type metadata
        empty_meta: ConnectorTypeMeta = {}
        type_meta = CONNECTOR_TYPES.get(str(connector["type"]), empty_meta)
        connector["type_name"] = type_meta.get("name", connector["type"])
        connector["category"] = type_meta.get("category", "unknown")

        return self._json_response(200, connector)

    async def _create_connector(self, request: Any) -> dict[str, Any]:
        """Configure a new connector."""
        try:
            body = await self._get_json_body(request)
        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Handler error: %s", e)
            return self._error_response(400, "Invalid request body")

        connector_type = body.get("type")
        if not connector_type:
            return self._error_response(400, "Connector type is required")

        if connector_type not in CONNECTOR_TYPES:
            return self._error_response(400, f"Unknown connector type: {connector_type}")

        if CONNECTOR_TYPES[connector_type].get("coming_soon"):
            return self._error_response(400, f"Connector type {connector_type} is coming soon")

        # Create connector
        connector_id = str(uuid4())
        type_meta = CONNECTOR_TYPES[connector_type]
        name = body.get("name", type_meta.get("name", connector_type))
        config = body.get("config", {})

        # Save to persistent store if available
        store = await _get_store()
        if store:
            await store.save_connector(
                connector_id=connector_id,
                connector_type=connector_type,
                name=name,
                config=config,
            )

        # Also keep in memory for active operations
        connector = {
            "id": connector_id,
            "type": connector_type,
            "name": name,
            "description": type_meta.get("description", ""),
            "status": "configured",
            "config": config,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "items_synced": 0,
            "last_sync": None,
        }

        _connectors[connector_id] = connector

        logger.info("Created connector %s of type %s", connector_id, connector_type)

        return self._json_response(201, connector)

    async def _update_connector(self, request: Any, connector_id: str) -> dict[str, Any]:
        """Update connector configuration."""
        connector = _connectors.get(connector_id)
        if not connector:
            return self._error_response(404, f"Connector {connector_id} not found")

        try:
            body = await self._get_json_body(request)
        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Handler error: %s", e)
            return self._error_response(400, "Invalid request body")

        # Update allowed fields
        if "name" in body:
            connector["name"] = body["name"]
        if "config" in body:
            connector["config"].update(body["config"])

        connector["updated_at"] = datetime.now(timezone.utc).isoformat()

        # If config is updated and was previously connected, mark as needing reconnection
        if "config" in body and connector["status"] == "connected":
            connector["status"] = "configuring"

        _connectors[connector_id] = connector

        logger.info("Updated connector %s", connector_id)

        return self._json_response(200, connector)

    @require_permission("connectors:delete")
    async def _delete_connector(self, request: Any, connector_id: str) -> dict[str, Any]:
        """Remove a connector (doesn't delete synced data)."""
        if connector_id not in _connectors:
            return self._error_response(404, f"Connector {connector_id} not found")

        # Cancel any active syncs
        for sync_id, sync_job in list(_sync_jobs.items()):
            if sync_job["connector_id"] == connector_id and sync_job["status"] == "running":
                sync_job["status"] = "cancelled"
                sync_job["completed_at"] = datetime.now(timezone.utc).isoformat()

        del _connectors[connector_id]

        logger.info("Deleted connector %s", connector_id)

        return self._json_response(200, {"message": "Connector removed successfully"})

    async def _start_sync(self, request: Any, connector_id: str) -> dict[str, Any]:
        """Start a sync operation for a connector."""
        connector = _connectors.get(connector_id)
        if not connector:
            return self._error_response(404, f"Connector {connector_id} not found")

        # Check if already syncing
        active_sync = next(
            (
                s
                for s in _sync_jobs.values()
                if s["connector_id"] == connector_id and s["status"] == "running"
            ),
            None,
        )
        if active_sync:
            return self._error_response(409, "Sync already in progress")

        # Create sync job
        sync_id = str(uuid4())
        sync_job = {
            "id": sync_id,
            "connector_id": connector_id,
            "connector_name": connector["name"],
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
            "items_processed": 0,
            "items_total": None,
            "progress": 0,
            "error_message": None,
        }

        _sync_jobs[sync_id] = sync_job
        connector["status"] = "syncing"

        # Start background sync task
        task = asyncio.create_task(self._run_sync(sync_id, connector_id))
        task.add_done_callback(
            lambda t: logger.error("Connector sync %s failed: %s", sync_id, t.exception())
            if not t.cancelled() and t.exception()
            else None
        )

        logger.info("Started sync %s for connector %s", sync_id, connector_id)

        return self._json_response(
            202,
            {
                "message": "Sync started",
                "sync_id": sync_id,
                "connector_id": connector_id,
            },
        )

    async def _run_sync(self, sync_id: str, connector_id: str) -> None:
        """Background task to run sync operation.

        Real connector sync required -- use the Gmail connector directly.
        This stub marks the sync as failed since simulated sync has been removed.
        """
        sync_job = _sync_jobs.get(sync_id)
        connector = _connectors.get(connector_id)

        if not sync_job or not connector:
            return

        sync_job["status"] = "failed"
        sync_job["error_message"] = "Real connector sync required -- use Gmail connector directly"
        sync_job["completed_at"] = datetime.now(timezone.utc).isoformat()
        connector["status"] = "error"
        connector["error_message"] = "Real connector sync required -- use Gmail connector directly"
        _sync_history.append(dict(sync_job))

        logger.error(
            "Sync %s for connector %s failed: simulated sync removed, real connector required",
            sync_id,
            connector_id,
        )

    async def _cancel_sync(self, request: Any, sync_id: str) -> dict[str, Any]:
        """Cancel a running sync operation."""
        sync_job = _sync_jobs.get(sync_id)
        if not sync_job:
            return self._error_response(404, f"Sync job {sync_id} not found")

        if sync_job["status"] != "running":
            return self._error_response(400, "Sync is not running")

        sync_job["status"] = "cancelled"

        # Update connector status
        connector = _connectors.get(sync_job["connector_id"])
        if connector:
            connector["status"] = "connected" if connector.get("last_sync") else "disconnected"

        logger.info("Cancelled sync %s", sync_id)

        return self._json_response(200, {"message": "Sync cancelled"})

    async def _test_connection(self, request: Any) -> dict[str, Any]:
        """Test a connector configuration without saving."""
        try:
            body = await self._get_json_body(request)
        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Handler error: %s", e)
            return self._error_response(400, "Invalid request body")

        connector_id = body.get("connector_id")

        return self._json_response(
            501,
            {
                "success": False,
                "error": "Real connector test required -- use Gmail connector directly",
                "connector_id": connector_id,
            },
        )

    async def _get_sync_history(self, request: Any) -> dict[str, Any]:
        """Get sync history for all connectors."""
        connector_id = request.query.get("connector_id")
        limit = int(request.query.get("limit", 50))

        store = await _get_store()
        if store:
            jobs = await store.get_sync_history(connector_id, limit=limit)
            history = [
                {
                    "id": j.id,
                    "connector_id": j.connector_id,
                    "status": j.status,
                    "started_at": j.started_at.isoformat(),
                    "completed_at": j.completed_at.isoformat() if j.completed_at else None,
                    "items_processed": j.items_synced,
                    "items_failed": j.items_failed,
                    "duration_seconds": j.duration_seconds,
                    "error_message": j.error_message,
                }
                for j in jobs
            ]
        else:
            history = _sync_history.copy()

            if connector_id:
                history = [h for h in history if h["connector_id"] == connector_id]

            # Sort by start time descending
            history.sort(key=lambda x: str(x.get("started_at", "") or ""), reverse=True)

            # Apply limit
            history = history[:limit]

        return self._json_response(
            200,
            {
                "history": history,
                "total": len(history),
            },
        )

    async def _get_stats(self, request: Any) -> dict[str, Any]:
        """Get aggregate statistics for all connectors."""
        store = await _get_store()

        if store:
            connector_configs = await store.list_connectors()
            sync_stats = await store.get_sync_stats()

            connectors = [
                {"type": c.connector_type, "status": c.status, "items_synced": c.items_indexed}
                for c in connector_configs
            ]
            total_items = sum(c.items_indexed for c in connector_configs)
            connected = sum(
                1 for c in connector_configs if c.status in ("connected", "configured", "active")
            )
            syncing = sum(1 for c in connector_configs if c.status == "active")
            errors = sum(1 for c in connector_configs if c.status == "error")

            return self._json_response(
                200,
                {
                    "total_connectors": len(connectors),
                    "connected": connected,
                    "syncing": syncing,
                    "errors": errors,
                    "total_items_synced": total_items,
                    "syncs_last_24h": sync_stats["total_syncs"],
                    "successful_syncs_24h": sync_stats["successful_syncs"],
                    "failed_syncs_24h": sync_stats["failed_syncs"],
                    "active_syncs": sync_stats["active_syncs"],
                    "avg_sync_duration": sync_stats["avg_duration_seconds"],
                    "by_category": self._count_by_category(connectors),
                },
            )

        # Fallback to in-memory
        connectors = list(_connectors.values())

        total_items = sum(int(str(c.get("items_synced", 0) or 0)) for c in connectors)
        connected = sum(1 for c in connectors if c["status"] in ("connected", "syncing"))
        syncing = sum(1 for c in connectors if c["status"] == "syncing")
        errors = sum(1 for c in connectors if c["status"] == "error")

        # Calculate syncs in last 24h
        from datetime import timedelta

        one_day_ago = datetime.now(timezone.utc) - timedelta(days=1)
        recent_syncs = [
            h
            for h in _sync_history
            if datetime.fromisoformat(h["started_at"].replace("Z", "+00:00")) >= one_day_ago
        ]

        successful_syncs = sum(1 for s in recent_syncs if s["status"] == "completed")
        failed_syncs = sum(1 for s in recent_syncs if s["status"] == "failed")

        return self._json_response(
            200,
            {
                "total_connectors": len(connectors),
                "connected": connected,
                "syncing": syncing,
                "errors": errors,
                "total_items_synced": total_items,
                "syncs_last_24h": len(recent_syncs),
                "successful_syncs_24h": successful_syncs,
                "failed_syncs_24h": failed_syncs,
                "by_category": self._count_by_category(connectors),
            },
        )

    async def _get_health(self, request: Any) -> dict[str, Any]:
        """
        Get health scores for all connectors.

        Health score is calculated based on:
        - Success rate (60% weight): Percentage of successful syncs
        - Latency score (40% weight): Based on sync duration vs. expected

        Response:
        {
            "connectors": [
                {
                    "connector_id": "...",
                    "connector_type": "sharepoint",
                    "health_score": 0.85,
                    "status": "healthy",
                    "metrics": {
                        "success_rate": 0.95,
                        "avg_duration_seconds": 45.2,
                        "syncs_24h": 12,
                        "failures_24h": 1,
                        "last_sync": "2026-01-21T10:30:00Z",
                        "items_synced": 15000
                    },
                    "issues": []
                }
            ],
            "summary": {
                "total": 5,
                "healthy": 4,
                "degraded": 1,
                "unhealthy": 0,
                "overall_score": 0.92
            }
        }
        """
        store = await _get_store()
        connectors_health: list[dict[str, Any]] = []

        if store:
            connector_configs = await store.list_connectors()

            for config in connector_configs:
                # Get per-connector stats
                stats = await store.get_sync_stats(connector_id=config.id)
                history = await store.get_sync_history(connector_id=config.id, limit=100)

                # Calculate success rate
                total_syncs = stats.get("total_syncs", 0)
                successful = stats.get("successful_syncs", 0)
                success_rate = successful / total_syncs if total_syncs > 0 else 1.0

                # Calculate latency score (lower is better, normalized to 0-1)
                avg_duration: float = stats.get("avg_duration_seconds", 0) or 0
                empty_meta: ConnectorTypeMeta = {}
                connector_type_info = CONNECTOR_TYPES.get(config.connector_type, empty_meta)
                expected_duration: int = connector_type_info.get("expected_sync_duration", 60)
                if avg_duration <= expected_duration:
                    latency_score = 1.0
                else:
                    # Degrade linearly, floor at 0.3
                    latency_score = max(
                        0.3, 1.0 - (avg_duration - expected_duration) / expected_duration
                    )

                # Calculate overall health score
                health_score = (success_rate * 0.6) + (latency_score * 0.4)

                # Determine status
                if health_score >= 0.9:
                    status = "healthy"
                elif health_score >= 0.7:
                    status = "degraded"
                else:
                    status = "unhealthy"

                # Identify issues
                issues = []
                if success_rate < 0.9:
                    issues.append(f"Low success rate: {success_rate * 100:.1f}%")
                if avg_duration > expected_duration * 2:
                    issues.append(
                        f"High sync duration: {avg_duration:.0f}s (expected: {expected_duration}s)"
                    )
                if config.status == "error":
                    issues.append("Connector in error state")
                if total_syncs == 0:
                    issues.append("No syncs recorded")

                # Get last sync time
                last_sync: str | None = None
                if history:
                    last_sync_dt = history[0].completed_at or history[0].started_at
                    last_sync = last_sync_dt.isoformat() if last_sync_dt else None

                # Syncs in last 24 hours
                from datetime import timedelta

                one_day_ago = datetime.now(timezone.utc) - timedelta(days=1)
                syncs_24h = sum(1 for h in history if h.started_at and h.started_at >= one_day_ago)
                failures_24h = sum(
                    1
                    for h in history
                    if h.started_at and h.started_at >= one_day_ago and h.status == "failed"
                )

                connectors_health.append(
                    {
                        "connector_id": config.id,
                        "connector_type": config.connector_type,
                        "name": config.name or config.id,
                        "health_score": round(health_score, 3),
                        "status": status,
                        "metrics": {
                            "success_rate": round(success_rate, 3),
                            "avg_duration_seconds": round(avg_duration, 1),
                            "total_syncs": total_syncs,
                            "syncs_24h": syncs_24h,
                            "failures_24h": failures_24h,
                            "last_sync": last_sync,
                            "items_synced": config.items_indexed,
                        },
                        "issues": issues,
                    }
                )

        else:
            # Fallback to in-memory
            for connector_id, connector_config in _connectors.items():
                connector_history = [
                    h for h in _sync_history if h.get("connector_id") == connector_id
                ]
                total_syncs = len(connector_history)
                successful = sum(1 for h in connector_history if h.get("status") == "completed")
                success_rate = successful / total_syncs if total_syncs > 0 else 1.0
                health_score = success_rate  # Simplified for in-memory

                status = (
                    "healthy"
                    if health_score >= 0.9
                    else ("degraded" if health_score >= 0.7 else "unhealthy")
                )

                connectors_health.append(
                    {
                        "connector_id": connector_id,
                        "connector_type": connector_config.get("type", "unknown"),
                        "name": connector_config.get("name", connector_id),
                        "health_score": round(health_score, 3),
                        "status": status,
                        "metrics": {
                            "success_rate": round(success_rate, 3),
                            "total_syncs": total_syncs,
                            "items_synced": connector_config.get("items_synced", 0),
                        },
                        "issues": [],
                    }
                )

        # Calculate summary
        total = len(connectors_health)
        healthy = sum(1 for c in connectors_health if c["status"] == "healthy")
        degraded = sum(1 for c in connectors_health if c["status"] == "degraded")
        unhealthy = sum(1 for c in connectors_health if c["status"] == "unhealthy")
        overall_score: float = (
            sum(float(c["health_score"]) for c in connectors_health) / total if total > 0 else 1.0
        )

        # Sort by health score (worst first for quick visibility)
        connectors_health.sort(key=lambda c: float(c["health_score"]))

        return self._json_response(
            200,
            {
                "connectors": connectors_health,
                "summary": {
                    "total": total,
                    "healthy": healthy,
                    "degraded": degraded,
                    "unhealthy": unhealthy,
                    "overall_score": round(overall_score, 3),
                },
            },
        )

    async def _list_types(self, request: Any) -> dict[str, Any]:
        """List all available connector types."""
        types: list[dict[str, Any]] = []
        for type_id, type_meta in CONNECTOR_TYPES.items():
            type_entry: dict[str, Any] = {"type": type_id, **type_meta}
            types.append(type_entry)

        return self._json_response(200, {"types": types})

    def _count_by_category(self, connectors: list[dict[str, Any]]) -> dict[str, int]:
        """Count connectors by category."""
        empty_meta: ConnectorTypeMeta = {}
        counts: dict[str, int] = {}
        for connector in connectors:
            category = CONNECTOR_TYPES.get(connector["type"], empty_meta).get("category", "other")
            counts[category] = counts.get(category, 0) + 1
        return counts

    async def _get_json_body(self, request: Any) -> dict[str, Any]:
        """Parse JSON body from request.

        Wraps parse_json_body and returns just the dict, raising on error.
        """
        body, _err = await parse_json_body(request, context="connectors")
        return body if body is not None else {}

    def _json_response(self, status: int, data: Any) -> dict[str, Any]:
        """Create a JSON response."""

        return {
            "status_code": status,
            "headers": {"Content-Type": "application/json"},
            "body": data,
        }

    def _error_response(self, status: int, message: str) -> dict[str, Any]:
        """Create an error response."""
        return self._json_response(status, {"error": message})


__all__ = ["ConnectorsHandler"]
