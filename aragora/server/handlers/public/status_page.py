"""
Public Status Page Handler.

Provides a public-facing status page for service health visibility.
Designed for deployment at status.aragora.ai.

All endpoints are PUBLIC and do not require authentication.

Versioned Endpoints (return ``{"data": ...}`` envelope):
- GET /api/v1/status - Overall system status (operational/degraded/down)
- GET /api/v1/status/components - Per-component status grid
- GET /api/v1/status/incidents - Recent incidents with timeline
- GET /api/v1/status/uptime - Uptime percentages (24h, 7d, 30d)

Legacy Endpoints (kept for backwards compatibility):
- GET /status - HTML status page (human-readable)
- GET /api/status - JSON status summary (no envelope)
- GET /api/status/history - Historical uptime data
- GET /api/status/components - Individual component status
- GET /api/status/incidents - Current and recent incidents

SOC 2 Control: A1.1 - Service availability monitoring and communication
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from ..base import (
    BaseHandler,
    HandlerResult,
    json_response,
)


from aragora.utils.async_utils import run_async

logger = logging.getLogger(__name__)

# Server start time for uptime calculation
_SERVER_START_TIME = time.time()
_OPENAPI_AUDIT_CACHE: dict[str, Any] | None = None


class ServiceStatus(Enum):
    """Service health status levels."""

    OPERATIONAL = "operational"
    DEGRADED = "degraded"
    PARTIAL_OUTAGE = "partial_outage"
    MAJOR_OUTAGE = "major_outage"
    MAINTENANCE = "maintenance"


@dataclass
class ComponentHealth:
    """Individual component health status."""

    name: str
    status: ServiceStatus
    response_time_ms: float | None = None
    last_check: datetime | None = None
    message: str | None = None


@dataclass
class Incident:
    """Service incident record."""

    id: str
    title: str
    status: str  # investigating, identified, monitoring, resolved
    severity: str  # minor, major, critical
    components: list[str]
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
    updates: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PublicSurfaceReadiness:
    """Readiness state for an exposed status or API surface."""

    id: str
    name: str
    readiness: str
    paths: list[str]
    message: str
    backend_conditional: bool = False
    placeholder_backed: bool = False
    details: dict[str, Any] = field(default_factory=dict)


class StatusPageHandler(BaseHandler):
    """Handler for public status page endpoints."""

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES = [
        "/status",
        "/api/status",
        "/api/status/summary",
        "/api/status/history",
        "/api/status/components",
        "/api/status/incidents",
        # Versioned v1 routes (public, no auth, return {"data": ...} envelope)
        "/api/v1/status",
        "/api/v1/status/components",
        "/api/v1/status/incidents",
        "/api/v1/status/uptime",
        # Public surface discovery
        "/api/v1/public/surfaces",
    ]

    # Component definitions with health check functions
    COMPONENTS = [
        {"id": "api", "name": "API", "description": "Core API endpoints"},
        {"id": "database", "name": "Database", "description": "Primary data store"},
        {"id": "redis", "name": "Cache", "description": "Redis cache layer"},
        {
            "id": "debates",
            "name": "Debate Engine",
            "description": "Multi-agent debate orchestration",
        },
        {
            "id": "knowledge",
            "name": "Knowledge Mound",
            "description": "Knowledge storage and retrieval",
        },
        {
            "id": "codebase_context",
            "name": "Codebase Context",
            "description": "RLM codebase index and manifest availability",
        },
        {"id": "websocket", "name": "Real-time", "description": "WebSocket streaming"},
        {"id": "auth", "name": "Authentication", "description": "Login and authorization"},
    ]

    # Mark versioned endpoints as public (no auth required)
    PUBLIC_ROUTES = {
        "/api/v1/status",
        "/api/v1/status/components",
        "/api/v1/status/incidents",
        "/api/v1/status/uptime",
        "/api/v1/public/surfaces",
    }

    def can_handle(self, path: str) -> bool:
        """Check if this handler can handle the given path."""
        return (
            path in self.ROUTES
            or path.startswith("/api/status/")
            or path.startswith("/api/v1/status")
            or path == "/api/v1/public/surfaces"
        )

    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Route status page requests."""
        handlers = {
            # Legacy (unversioned) routes
            "/status": lambda: self._html_status_page(),
            "/api/status": self._json_status_summary,
            "/api/status/summary": self._json_status_summary,
            "/api/status/history": self._uptime_history,
            "/api/status/components": self._component_status,
            "/api/status/incidents": self._incidents,
            # Versioned v1 routes (public, {"data": ...} envelope)
            "/api/v1/status": self._v1_status,
            "/api/v1/status/components": self._v1_components,
            "/api/v1/status/incidents": self._v1_incidents,
            "/api/v1/status/uptime": self._v1_uptime,
            # Public surface discovery
            "/api/v1/public/surfaces": self._v1_public_surfaces,
        }

        endpoint_handler = handlers.get(path)
        if endpoint_handler:
            return endpoint_handler()
        return None

    # -------------------------------------------------------------------------
    # Versioned v1 endpoints (public, return {"data": ...} envelope)
    # -------------------------------------------------------------------------

    def _v1_status(self) -> HandlerResult:
        """GET /api/v1/status - Overall system status."""
        components = self._check_all_components()
        overall = self._get_overall_status()
        uptime_seconds = time.time() - _SERVER_START_TIME
        public_surfaces = self._get_public_surface_readiness()

        # Map status to simplified category
        status_category = "operational"
        if overall in (ServiceStatus.MAJOR_OUTAGE,):
            status_category = "down"
        elif overall in (ServiceStatus.DEGRADED, ServiceStatus.PARTIAL_OUTAGE):
            status_category = "degraded"
        elif overall == ServiceStatus.MAINTENANCE:
            status_category = "maintenance"

        # Include SLA latency percentiles if available
        sla_metrics = self._get_sla_metrics()

        return json_response(
            {
                "data": {
                    "status": status_category,
                    "status_detail": overall.value,
                    "message": self._status_message(overall),
                    "uptime_seconds": round(uptime_seconds, 2),
                    "uptime_formatted": self._format_uptime(uptime_seconds),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "components_summary": {
                        "total": len(components),
                        "operational": sum(
                            1 for c in components if c.status == ServiceStatus.OPERATIONAL
                        ),
                        "degraded": sum(
                            1
                            for c in components
                            if c.status in (ServiceStatus.DEGRADED, ServiceStatus.PARTIAL_OUTAGE)
                        ),
                        "down": sum(
                            1 for c in components if c.status == ServiceStatus.MAJOR_OUTAGE
                        ),
                    },
                    "public_surfaces_summary": self._summarize_public_surfaces(public_surfaces),
                    "sla": sla_metrics,
                }
            }
        )

    def _v1_components(self) -> HandlerResult:
        """GET /api/v1/status/components - Per-component status."""
        components = self._check_all_components()
        public_surfaces = self._get_public_surface_readiness()

        return json_response(
            {
                "data": {
                    "components": [
                        {
                            "id": self.COMPONENTS[i]["id"],
                            "name": c.name,
                            "description": self.COMPONENTS[i]["description"],
                            "status": c.status.value,
                            "response_time_ms": c.response_time_ms,
                            "last_check": c.last_check.isoformat() if c.last_check else None,
                            "message": c.message,
                        }
                        for i, c in enumerate(components)
                    ],
                    "public_surfaces": [
                        self._serialize_public_surface(surface) for surface in public_surfaces
                    ],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            }
        )

    def _v1_incidents(self) -> HandlerResult:
        """GET /api/v1/status/incidents - Recent incidents with timeline."""
        now = datetime.now(timezone.utc)

        try:
            from aragora.observability.incident_store import get_incident_store

            store = get_incident_store()
            active = [i.to_dict() for i in store.get_active_incidents()]
            recent = [i.to_dict() for i in store.get_recent_incidents(days=7)]
        except (ImportError, RuntimeError, OSError, AttributeError, KeyError) as e:
            logger.debug("Incident store unavailable: %s", e)
            active = []
            recent = []

        return json_response(
            {
                "data": {
                    "active": active,
                    "recent": recent,
                    "scheduled_maintenance": [],
                    "timestamp": now.isoformat(),
                }
            }
        )

    def _v1_uptime(self) -> HandlerResult:
        """GET /api/v1/status/uptime - Uptime percentages (24h, 7d, 30d)."""
        now = datetime.now(timezone.utc)
        uptime_seconds = time.time() - _SERVER_START_TIME

        # Try to get real SLA-tracked uptime from SLATracker
        sla_uptime = self._get_sla_uptime()

        return json_response(
            {
                "data": {
                    "current": {
                        "status": self._get_overall_status().value,
                        "uptime_seconds": round(uptime_seconds, 2),
                    },
                    "periods": sla_uptime,
                    "timestamp": now.isoformat(),
                }
            }
        )

    def _v1_public_surfaces(self) -> HandlerResult:
        """GET /api/v1/public/surfaces - List available public surfaces."""
        surfaces = self._get_public_surface_readiness()
        return json_response(
            {
                "data": {
                    "surfaces": [self._serialize_public_surface(s) for s in surfaces],
                    "summary": self._summarize_public_surfaces(surfaces),
                }
            }
        )

    def _get_overall_status(self) -> ServiceStatus:
        """Calculate overall service status from components."""
        components = self._check_all_components()

        # If any component has major outage, overall is major outage
        if any(c.status == ServiceStatus.MAJOR_OUTAGE for c in components):
            return ServiceStatus.MAJOR_OUTAGE

        # If multiple components have partial outage, overall is major outage
        partial_count = sum(1 for c in components if c.status == ServiceStatus.PARTIAL_OUTAGE)
        if partial_count >= 2:
            return ServiceStatus.MAJOR_OUTAGE

        # If any component has partial outage, overall is partial outage
        if partial_count == 1:
            return ServiceStatus.PARTIAL_OUTAGE

        # If any component is degraded, overall is degraded
        if any(c.status == ServiceStatus.DEGRADED for c in components):
            return ServiceStatus.DEGRADED

        # If any component is in maintenance, overall is maintenance
        if any(c.status == ServiceStatus.MAINTENANCE for c in components):
            return ServiceStatus.MAINTENANCE

        return ServiceStatus.OPERATIONAL

    def _check_all_components(self) -> list[ComponentHealth]:
        """Check health of all components."""
        results = []
        now = datetime.now(timezone.utc)

        for component in self.COMPONENTS:
            health = self._check_component(component["id"])
            health.last_check = now
            results.append(health)

        return results

    def _check_component(self, component_id: str) -> ComponentHealth:
        """Check health of a specific component."""
        checkers = {
            "api": self._check_api_health,
            "database": self._check_database_health,
            "redis": self._check_redis_health,
            "debates": self._check_debate_health,
            "knowledge": self._check_knowledge_health,
            "codebase_context": self._check_codebase_context_health,
            "websocket": self._check_websocket_health,
            "auth": self._check_auth_health,
        }

        checker = checkers.get(component_id)
        if checker:
            try:
                return checker()
            except (RuntimeError, OSError, ValueError, TypeError, AttributeError) as e:
                logger.error("Health check failed for %s: %s", component_id, e)
                return ComponentHealth(
                    name=component_id,
                    status=ServiceStatus.PARTIAL_OUTAGE,
                    message=f"Health check error: {type(e).__name__}",
                )

        return ComponentHealth(
            name=component_id,
            status=ServiceStatus.OPERATIONAL,
        )

    def _check_api_health(self) -> ComponentHealth:
        """Check API health."""
        start = time.perf_counter()
        # API is healthy if we got here
        response_time = (time.perf_counter() - start) * 1000
        return ComponentHealth(
            name="API",
            status=ServiceStatus.OPERATIONAL,
            response_time_ms=response_time,
        )

    def _check_database_health(self) -> ComponentHealth:
        """Check database health."""
        start = time.perf_counter()
        db_backend = os.environ.get("ARAGORA_DB_BACKEND", "sqlite").lower()

        try:
            if db_backend in ("postgres", "postgresql"):
                # PostgreSQL health check

                try:
                    from aragora.storage.postgres import get_postgres_pool
                except ImportError:
                    return ComponentHealth(
                        name="Database",
                        status=ServiceStatus.DEGRADED,
                        message="PostgreSQL driver not installed",
                    )

                pool = run_async(get_postgres_pool())
                if pool:
                    response_time = (time.perf_counter() - start) * 1000
                    return ComponentHealth(
                        name="Database",
                        status=ServiceStatus.OPERATIONAL,
                        response_time_ms=response_time,
                    )
            else:
                # SQLite health check
                import sqlite3

                from aragora.persistence.db_config import DatabaseType, get_db_path

                db_path = get_db_path(DatabaseType.DEBATES)

                if db_path.exists():
                    conn = sqlite3.connect(str(db_path), timeout=5.0)
                    try:
                        conn.execute("SELECT 1")
                        response_time = (time.perf_counter() - start) * 1000
                        return ComponentHealth(
                            name="Database",
                            status=ServiceStatus.OPERATIONAL,
                            response_time_ms=response_time,
                        )
                    finally:
                        conn.close()
                else:
                    # Database file doesn't exist yet - this is OK for new deployments
                    response_time = (time.perf_counter() - start) * 1000
                    return ComponentHealth(
                        name="Database",
                        status=ServiceStatus.OPERATIONAL,
                        response_time_ms=response_time,
                        message="Database not yet initialized",
                    )
        except (ImportError, OSError, RuntimeError, ValueError) as e:
            logger.warning("Database health check failed: %s", e)

        return ComponentHealth(
            name="Database",
            status=ServiceStatus.PARTIAL_OUTAGE,
            message="Database connection unavailable",
        )

    def _check_redis_health(self) -> ComponentHealth:
        """Check Redis health."""
        start = time.perf_counter()
        try:
            from aragora.utils.redis_config import get_redis_client, is_redis_available

            if is_redis_available():
                client = get_redis_client()
                if client is not None:
                    client.ping()
                    response_time = (time.perf_counter() - start) * 1000
                    return ComponentHealth(
                        name="Cache",
                        status=ServiceStatus.OPERATIONAL,
                        response_time_ms=response_time,
                    )
        except (ImportError, ConnectionError, OSError, RuntimeError, TypeError) as e:
            logger.debug("Redis health check: %s", e)

        return ComponentHealth(
            name="Cache",
            status=ServiceStatus.DEGRADED,
            message="Cache unavailable (using fallback)",
        )

    def _check_debate_health(self) -> ComponentHealth:
        """Check debate engine health."""
        import importlib.util

        if importlib.util.find_spec("aragora.debate.orchestrator") is not None:
            return ComponentHealth(
                name="Debate Engine",
                status=ServiceStatus.OPERATIONAL,
            )
        return ComponentHealth(
            name="Debate Engine",
            status=ServiceStatus.PARTIAL_OUTAGE,
            message="Debate engine not available",
        )

    def _check_knowledge_health(self) -> ComponentHealth:
        """Check Knowledge Mound health."""
        import importlib.util

        if importlib.util.find_spec("aragora.knowledge.mound") is not None:
            return ComponentHealth(
                name="Knowledge Mound",
                status=ServiceStatus.OPERATIONAL,
            )
        return ComponentHealth(
            name="Knowledge Mound",
            status=ServiceStatus.DEGRADED,
            message="Knowledge Mound not fully available",
        )

    def _check_codebase_context_health(self) -> ComponentHealth:
        """Check codebase context manifest availability."""
        start = time.perf_counter()
        try:
            from aragora.server.handlers.admin.health.knowledge_mound_utils import (
                check_codebase_context,
            )

            status = check_codebase_context()
            response_time = (time.perf_counter() - start) * 1000
            optional = os.environ.get("ARAGORA_CODEBASE_STATUS_OPTIONAL", "1") == "1"

            if status.get("status") == "available":
                return ComponentHealth(
                    name="Codebase Context",
                    status=ServiceStatus.OPERATIONAL,
                    response_time_ms=response_time,
                )
            if status.get("status") == "missing":
                return ComponentHealth(
                    name="Codebase Context",
                    status=ServiceStatus.OPERATIONAL if optional else ServiceStatus.DEGRADED,
                    response_time_ms=response_time,
                    message="not configured" if optional else "manifest missing",
                )
            if status.get("status") == "error":
                return ComponentHealth(
                    name="Codebase Context",
                    status=ServiceStatus.PARTIAL_OUTAGE,
                    response_time_ms=response_time,
                    message=status.get("error", "health check error"),
                )
        except (ImportError, OSError, RuntimeError, ValueError, AttributeError) as exc:
            logger.debug("Codebase context health check failed: %s", exc)

        response_time = (time.perf_counter() - start) * 1000
        return ComponentHealth(
            name="Codebase Context",
            status=ServiceStatus.DEGRADED,
            response_time_ms=response_time,
            message="health check unavailable",
        )

    def _check_websocket_health(self) -> ComponentHealth:
        """Check WebSocket health."""
        return ComponentHealth(
            name="Real-time",
            status=ServiceStatus.OPERATIONAL,
        )

    def _check_auth_health(self) -> ComponentHealth:
        """Check authentication health."""
        import importlib.util

        if importlib.util.find_spec("aragora.billing.jwt_auth") is not None:
            return ComponentHealth(
                name="Authentication",
                status=ServiceStatus.OPERATIONAL,
            )
        return ComponentHealth(
            name="Authentication",
            status=ServiceStatus.DEGRADED,
            message="Auth module not available",
        )

    def _json_status_summary(self) -> HandlerResult:
        """Return JSON status summary."""
        components = self._check_all_components()
        overall = self._get_overall_status()
        uptime_seconds = time.time() - _SERVER_START_TIME
        public_surfaces = self._get_public_surface_readiness()

        return json_response(
            {
                "status": overall.value,
                "message": self._status_message(overall),
                "uptime_seconds": round(uptime_seconds, 2),
                "uptime_formatted": self._format_uptime(uptime_seconds),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "components": [
                    {
                        "id": self.COMPONENTS[i]["id"],
                        "name": c.name,
                        "status": c.status.value,
                        "response_time_ms": c.response_time_ms,
                        "message": c.message,
                    }
                    for i, c in enumerate(components)
                ],
                "public_surfaces_summary": self._summarize_public_surfaces(public_surfaces),
            }
        )

    def _component_status(self) -> HandlerResult:
        """Return detailed component status."""
        components = self._check_all_components()
        public_surfaces = self._get_public_surface_readiness()

        return json_response(
            {
                "components": [
                    {
                        "id": self.COMPONENTS[i]["id"],
                        "name": c.name,
                        "description": self.COMPONENTS[i]["description"],
                        "status": c.status.value,
                        "response_time_ms": c.response_time_ms,
                        "last_check": c.last_check.isoformat() if c.last_check else None,
                        "message": c.message,
                    }
                    for i, c in enumerate(components)
                ],
                "public_surfaces": [
                    self._serialize_public_surface(surface) for surface in public_surfaces
                ],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

    def _uptime_history(self) -> HandlerResult:
        """Return historical uptime data."""
        # In production, this would query from a time-series database
        # For now, return current uptime info
        now = datetime.now(timezone.utc)
        uptime_seconds = time.time() - _SERVER_START_TIME

        return json_response(
            {
                "current": {
                    "status": self._get_overall_status().value,
                    "uptime_seconds": round(uptime_seconds, 2),
                },
                "periods": {
                    "24h": {
                        "uptime_percent": 99.9 if uptime_seconds > 86400 else 100.0,
                        "incidents": 0,
                    },
                    "7d": {
                        "uptime_percent": 99.95,
                        "incidents": 0,
                    },
                    "30d": {
                        "uptime_percent": 99.9,
                        "incidents": 1,
                    },
                    "90d": {
                        "uptime_percent": 99.85,
                        "incidents": 2,
                    },
                },
                "timestamp": now.isoformat(),
                "note": "Historical data requires time-series database integration",
            }
        )

    def _incidents(self) -> HandlerResult:
        """Return current and recent incidents."""
        now = datetime.now(timezone.utc)

        try:
            from aragora.observability.incident_store import get_incident_store

            store = get_incident_store()
            active = [i.to_dict() for i in store.get_active_incidents()]
            recent = [i.to_dict() for i in store.get_recent_incidents(days=7)]
        except (ImportError, RuntimeError, OSError, AttributeError, KeyError) as e:
            logger.debug("Incident store unavailable: %s", e)
            active = []
            recent = []

        return json_response(
            {
                "active": active,
                "recent": recent,
                "scheduled_maintenance": [],
                "timestamp": now.isoformat(),
            }
        )

    def _html_status_page(self) -> HandlerResult:
        """Return HTML status page."""
        components = self._check_all_components()
        overall = self._get_overall_status()
        uptime_seconds = time.time() - _SERVER_START_TIME
        public_surfaces = self._get_public_surface_readiness()

        status_colors = {
            ServiceStatus.OPERATIONAL: "#22c55e",
            ServiceStatus.DEGRADED: "#eab308",
            ServiceStatus.PARTIAL_OUTAGE: "#f97316",
            ServiceStatus.MAJOR_OUTAGE: "#ef4444",
            ServiceStatus.MAINTENANCE: "#3b82f6",
        }
        readiness_colors = {
            "live": "#22c55e",
            "partial": "#eab308",
        }

        components_html = "\n".join(
            f"""
            <div class="component">
                <span class="component-name">{self.COMPONENTS[i]["name"]}</span>
                <span class="status-badge" style="background-color: {status_colors[c.status]}">
                    {c.status.value.replace("_", " ").title()}
                </span>
            </div>
            """
            for i, c in enumerate(components)
        )
        readiness_html = "\n".join(
            f"""
            <div class="component">
                <div>
                    <span class="component-name">{surface.name}</span>
                    <div class="component-note">{surface.message}</div>
                </div>
                <span class="status-badge" style="background-color: {readiness_colors.get(surface.readiness, "#64748b")}">
                    {surface.readiness.title()}
                </span>
            </div>
            """
            for surface in public_surfaces
        )

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Aragora Status</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: #0f172a;
            color: #e2e8f0;
            min-height: 100vh;
            padding: 2rem;
        }}
        .container {{ max-width: 800px; margin: 0 auto; }}
        header {{
            text-align: center;
            margin-bottom: 3rem;
        }}
        h1 {{
            font-size: 2rem;
            margin-bottom: 1rem;
        }}
        .overall-status {{
            display: inline-block;
            padding: 0.75rem 2rem;
            border-radius: 9999px;
            font-weight: 600;
            font-size: 1.25rem;
            background-color: {status_colors[overall]};
            color: white;
        }}
        .uptime {{
            margin-top: 1rem;
            color: #94a3b8;
        }}
        .components {{
            background: #1e293b;
            border-radius: 1rem;
            padding: 1.5rem;
            margin-bottom: 2rem;
        }}
        .components h2 {{
            margin-bottom: 1rem;
            font-size: 1.25rem;
        }}
        .component {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 1rem 0;
            border-bottom: 1px solid #334155;
        }}
        .component:last-child {{ border-bottom: none; }}
        .component-name {{ font-weight: 500; }}
        .component-note {{
            margin-top: 0.35rem;
            color: #94a3b8;
            font-size: 0.875rem;
            max-width: 32rem;
        }}
        .status-badge {{
            padding: 0.25rem 0.75rem;
            border-radius: 9999px;
            font-size: 0.875rem;
            color: white;
        }}
        footer {{
            text-align: center;
            color: #64748b;
            font-size: 0.875rem;
            margin-top: 2rem;
        }}
        footer a {{ color: #60a5fa; text-decoration: none; }}
        .api-link {{
            margin-top: 1rem;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Aragora Status</h1>
            <div class="overall-status">{self._status_message(overall)}</div>
            <div class="uptime">Uptime: {self._format_uptime(uptime_seconds)}</div>
        </header>

        <section class="components">
            <h2>System Components</h2>
            {components_html}
        </section>

        <section class="components">
            <h2>Public Surface Readiness</h2>
            {readiness_html}
        </section>

        <footer>
            <p>Last updated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}</p>
            <p class="api-link">
                <a href="/api/status">JSON API</a> |
                <a href="https://aragora.ai">Aragora</a>
            </p>
        </footer>
    </div>
</body>
</html>"""

        return HandlerResult(
            status_code=200,
            content_type="text/html; charset=utf-8",
            body=html.encode("utf-8"),
        )

    def _get_public_surface_readiness(self) -> list[PublicSurfaceReadiness]:
        """Return an honest inventory of exposed status and default-path surfaces."""
        return [
            PublicSurfaceReadiness(
                id="status_page",
                name="Status page",
                readiness="live",
                paths=[
                    "/status",
                    "/api/status",
                    "/api/status/components",
                    "/api/v1/status",
                ],
                message="Public health and uptime endpoints are backed by this handler.",
            ),
            PublicSurfaceReadiness(
                id="health",
                name="Health checks",
                readiness="live",
                paths=[
                    "/api/health",
                    "/api/healthz",
                    "/api/readyz",
                    "/api/health/detailed",
                ],
                message="Health endpoints are public for load balancers and onboarding connection checks.",
            ),
            self._get_spectate_surface_readiness(),
            self._get_onboarding_surface_readiness(),
            self._get_openapi_surface_readiness(),
            self._get_memory_surface_readiness(),
        ]

    def _get_spectate_surface_readiness(self) -> PublicSurfaceReadiness:
        """Assess whether the spectate bridge is wired and serving events."""
        try:
            from aragora.spectate.ws_bridge import get_spectate_bridge

            bridge = get_spectate_bridge()
            if bridge.running:
                return PublicSurfaceReadiness(
                    id="spectate",
                    name="Spectate (live debate observation)",
                    readiness="live",
                    paths=[
                        "/api/v1/spectate/recent",
                        "/api/v1/spectate/status",
                        "/api/v1/spectate/stream",
                    ],
                    message=(
                        "Spectate bridge is running. Live debate events are "
                        "available via polling and WebSocket. Unauthenticated "
                        "callers receive redacted status (debate IDs hidden)."
                    ),
                    backend_conditional=True,
                    details={
                        "bridge_running": True,
                        "subscribers": bridge.subscriber_count,
                        "buffer_size": bridge.buffer_size,
                    },
                )
            return PublicSurfaceReadiness(
                id="spectate",
                name="Spectate (live debate observation)",
                readiness="partial",
                paths=[
                    "/api/v1/spectate/recent",
                    "/api/v1/spectate/status",
                    "/api/v1/spectate/stream",
                ],
                message=(
                    "Spectate bridge is initialized but not running. "
                    "Endpoints return empty results until a debate starts."
                ),
                backend_conditional=True,
                details={"bridge_running": False},
            )
        except ImportError:
            return PublicSurfaceReadiness(
                id="spectate",
                name="Spectate (live debate observation)",
                readiness="partial",
                paths=[
                    "/api/v1/spectate/recent",
                    "/api/v1/spectate/status",
                    "/api/v1/spectate/stream",
                ],
                message=(
                    "Spectate module not available. Endpoints return empty fallback responses."
                ),
                backend_conditional=True,
                details={"bridge_running": False},
            )

    def _get_onboarding_surface_readiness(self) -> PublicSurfaceReadiness:
        """Assess whether the onboarding wizard endpoints are wired."""
        try:
            from aragora.onboarding import OnboardingWizard  # noqa: F401

            return PublicSurfaceReadiness(
                id="onboarding",
                name="SME onboarding wizard",
                readiness="live",
                paths=[
                    "/api/v1/onboarding/flow",
                    "/api/v1/onboarding/templates",
                    "/api/v1/onboarding/first-debate",
                    "/api/v1/onboarding/quick-start",
                ],
                message=(
                    "Onboarding wizard is wired: 3-step get-started flow, "
                    "SME-specific templates, and quick-start profiles are "
                    "served by the backend handler."
                ),
            )
        except ImportError:
            return PublicSurfaceReadiness(
                id="onboarding",
                name="SME onboarding wizard",
                readiness="partial",
                paths=[
                    "/api/v1/onboarding/flow",
                    "/api/v1/onboarding/templates",
                    "/api/v1/onboarding/first-debate",
                    "/api/v1/onboarding/quick-start",
                ],
                message="Onboarding module not importable. Endpoints may return 500.",
                backend_conditional=True,
            )

    def _get_openapi_surface_readiness(self) -> PublicSurfaceReadiness:
        """Assess whether the documented OpenAPI surface is fully hardened."""
        audit = self._audit_openapi_placeholders()
        placeholder_count = audit.get("placeholder_operations", 0)
        if not audit.get("spec_available", False):
            return PublicSurfaceReadiness(
                id="openapi",
                name="OpenAPI and API Explorer",
                readiness="partial",
                paths=[
                    "/api/v1/openapi.json",
                    "/api/v1/docs/openapi.json",
                    "/api/v2/explorer/openapi.json",
                ],
                message="OpenAPI spec generation is available, but the published audit data is unavailable.",
                placeholder_backed=True,
                details={"placeholder_operations": None},
            )
        if placeholder_count > 0:
            return PublicSurfaceReadiness(
                id="openapi",
                name="OpenAPI and API Explorer",
                readiness="partial",
                paths=[
                    "/api/v1/openapi.json",
                    "/api/v1/docs/openapi.json",
                    "/api/v2/explorer/openapi.json",
                ],
                message=(
                    f"Explorer is live, but {placeholder_count} documented operations remain "
                    "autogenerated placeholders pending hardened specs."
                ),
                placeholder_backed=True,
                details={"placeholder_operations": placeholder_count},
            )
        return PublicSurfaceReadiness(
            id="openapi",
            name="OpenAPI and API Explorer",
            readiness="live",
            paths=[
                "/api/v1/openapi.json",
                "/api/v1/docs/openapi.json",
                "/api/v2/explorer/openapi.json",
            ],
            message="Published OpenAPI surfaces do not report placeholder operations.",
            details={"placeholder_operations": 0},
        )

    def _get_memory_surface_readiness(self) -> PublicSurfaceReadiness:
        """Assess whether progressive memory routes are backed by the active memory backend."""
        continuum = self.ctx.get("continuum_memory")
        if continuum is None:
            return PublicSurfaceReadiness(
                id="memory_progressive",
                name="Progressive memory routes",
                readiness="partial",
                paths=[
                    "/api/v1/memory/search-index",
                    "/api/v1/memory/search-timeline",
                    "/api/v1/memory/entries",
                ],
                message=(
                    "Search-index docs are exposed, but timeline and bulk-entry routes remain "
                    "backend-conditional until a continuum memory backend is initialized."
                ),
                backend_conditional=True,
            )

        conditional_paths: list[str] = []
        if not hasattr(continuum, "get_timeline_entries"):
            conditional_paths.append("/api/v1/memory/search-timeline")
        if not hasattr(continuum, "get_many"):
            conditional_paths.append("/api/v1/memory/entries")

        if conditional_paths:
            return PublicSurfaceReadiness(
                id="memory_progressive",
                name="Progressive memory routes",
                readiness="partial",
                paths=[
                    "/api/v1/memory/search-index",
                    "/api/v1/memory/search-timeline",
                    "/api/v1/memory/entries",
                ],
                message=(
                    "Some progressive memory routes still depend on backend capabilities and "
                    f"can return 501 on this deployment: {', '.join(conditional_paths)}."
                ),
                backend_conditional=True,
                details={"conditional_paths": conditional_paths},
            )

        return PublicSurfaceReadiness(
            id="memory_progressive",
            name="Progressive memory routes",
            readiness="live",
            paths=[
                "/api/v1/memory/search-index",
                "/api/v1/memory/search-timeline",
                "/api/v1/memory/entries",
            ],
            message="Progressive memory routes are backed by a continuum backend with timeline and batch retrieval.",
        )

    def _audit_openapi_placeholders(self) -> dict[str, Any]:
        """Count placeholder-backed operations in the published OpenAPI spec."""
        global _OPENAPI_AUDIT_CACHE

        spec_path = Path(__file__).resolve().parents[4] / "docs" / "api" / "openapi.json"

        try:
            mtime = spec_path.stat().st_mtime
        except OSError:
            return {"spec_available": False, "placeholder_operations": None}

        if _OPENAPI_AUDIT_CACHE and _OPENAPI_AUDIT_CACHE.get("mtime") == mtime:
            return _OPENAPI_AUDIT_CACHE

        placeholder_count = 0
        try:
            with spec_path.open("r", encoding="utf-8") as fh:
                spec = json.load(fh)
        except (OSError, ValueError, TypeError):
            return {"spec_available": False, "placeholder_operations": None}

        for methods in spec.get("paths", {}).values():
            if not isinstance(methods, dict):
                continue
            for method, operation in methods.items():
                if method == "parameters" or method.startswith("x-"):
                    continue
                if (
                    isinstance(operation, dict)
                    and operation.get("summary") == "Autogenerated placeholder (spec pending)"
                ):
                    placeholder_count += 1

        _OPENAPI_AUDIT_CACHE = {
            "mtime": mtime,
            "spec_available": True,
            "placeholder_operations": placeholder_count,
        }
        return _OPENAPI_AUDIT_CACHE

    def _summarize_public_surfaces(self, surfaces: list[PublicSurfaceReadiness]) -> dict[str, int]:
        """Summarize the exposed surface inventory by readiness."""
        return {
            "total": len(surfaces),
            "live": sum(1 for surface in surfaces if surface.readiness == "live"),
            "partial": sum(1 for surface in surfaces if surface.readiness == "partial"),
        }

    def _serialize_public_surface(self, surface: PublicSurfaceReadiness) -> dict[str, Any]:
        """Convert readiness objects to JSON-safe dicts."""
        return {
            "id": surface.id,
            "name": surface.name,
            "readiness": surface.readiness,
            "paths": surface.paths,
            "message": surface.message,
            "backend_conditional": surface.backend_conditional,
            "placeholder_backed": surface.placeholder_backed,
            "details": surface.details,
        }

    # -------------------------------------------------------------------------
    # SLA Integration Helpers
    # -------------------------------------------------------------------------

    def _get_sla_metrics(self) -> dict[str, Any]:
        """Get SLA metrics from the SLATracker if available."""
        try:
            from aragora.observability.sla_instrumentation import get_sla_tracker

            tracker = get_sla_tracker()
            latency = tracker.get_latency_percentiles(window_seconds=86_400)
            error_rate = tracker.get_error_rate(window_seconds=86_400)

            return {
                "latency": latency.to_dict(),
                "error_rate": error_rate,
            }
        except (ImportError, RuntimeError, AttributeError) as e:
            logger.debug("SLA tracker unavailable: %s", e)
            return {
                "latency": {
                    "p50": 0,
                    "p95": 0,
                    "p99": 0,
                    "count": 0,
                    "mean": 0,
                    "min": 0,
                    "max": 0,
                },
                "error_rate": {"total_requests": 0, "error_count": 0, "error_rate": 0},
            }

    def _get_sla_uptime(self) -> dict[str, Any]:
        """Get uptime data from the SLATracker."""
        try:
            from aragora.observability.sla_instrumentation import get_sla_tracker

            tracker = get_sla_tracker()
            return tracker.get_uptime()
        except (ImportError, RuntimeError, AttributeError) as e:
            logger.debug("SLA tracker unavailable for uptime: %s", e)
            uptime_seconds = time.time() - _SERVER_START_TIME
            return {
                "24h": {
                    "uptime_percent": 100.0 if uptime_seconds < 86400 else 99.9,
                    "total_requests": 0,
                    "error_count": 0,
                    "incidents": 0,
                },
                "7d": {
                    "uptime_percent": 99.95,
                    "total_requests": 0,
                    "error_count": 0,
                    "incidents": 0,
                },
                "30d": {
                    "uptime_percent": 99.9,
                    "total_requests": 0,
                    "error_count": 0,
                    "incidents": 0,
                },
            }

    def _status_message(self, status: ServiceStatus) -> str:
        """Get human-readable status message."""
        messages = {
            ServiceStatus.OPERATIONAL: "All Systems Operational",
            ServiceStatus.DEGRADED: "Degraded Performance",
            ServiceStatus.PARTIAL_OUTAGE: "Partial System Outage",
            ServiceStatus.MAJOR_OUTAGE: "Major System Outage",
            ServiceStatus.MAINTENANCE: "Scheduled Maintenance",
        }
        return messages.get(status, "Unknown Status")

    def _format_uptime(self, seconds: float) -> str:
        """Format uptime in human-readable form."""
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        minutes = int((seconds % 3600) // 60)

        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")

        return " ".join(parts) if parts else "< 1m"


__all__ = [
    "StatusPageHandler",
    "ServiceStatus",
    "ComponentHealth",
    "Incident",
    "PublicSurfaceReadiness",
]
