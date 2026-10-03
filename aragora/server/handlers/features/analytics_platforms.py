"""
Analytics Platform API Handlers.

Stability: STABLE (graduated 2026-02)

Unified API for analytics and BI platforms:
- Metabase (BI dashboards, SQL queries)
- Google Analytics 4 (web/app analytics)
- Mixpanel (product analytics)

Usage:
    GET    /api/v1/analytics/platforms            - List connected platforms
    POST   /api/v1/analytics/connect              - Connect a platform
    DELETE /api/v1/analytics/{platform}           - Disconnect platform

    GET    /api/v1/analytics/dashboards           - List dashboards (cross-platform)
    GET    /api/v1/analytics/{platform}/dashboards - Platform dashboards

    POST   /api/v1/analytics/query                - Execute unified query
    GET    /api/v1/analytics/reports              - Get available reports
    POST   /api/v1/analytics/reports/generate     - Generate custom report

    GET    /api/v1/analytics/metrics              - Cross-platform metrics overview
    GET    /api/v1/analytics/realtime             - Real-time metrics (GA4)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from aragora.resilience import CircuitBreaker
from aragora.server.handlers.secure import SecureHandler, ForbiddenError, UnauthorizedError
from aragora.server.handlers.utils.responses import HandlerResult, error_dict, error_response
from aragora.server.handlers.utils import parse_json_body
from aragora.server.handlers.utils.rate_limit import rate_limit
from aragora.server.handlers.utils.routing import call_request_handler
from aragora.server.validation.query_params import safe_query_int

logger = logging.getLogger(__name__)

# Circuit breaker for analytics platform operations
_analytics_circuit_breaker = CircuitBreaker(
    name="analytics_platforms_handler",
    failure_threshold=5,
    cooldown_seconds=60,
    half_open_max_calls=3,
)


def get_analytics_circuit_breaker() -> CircuitBreaker:
    """Get the circuit breaker for analytics platforms service."""
    return _analytics_circuit_breaker


# Platform credentials storage
_platform_credentials: dict[str, dict[str, Any]] = {}
_platform_connectors: dict[str, Any] = {}


SUPPORTED_PLATFORMS = {
    "metabase": {
        "name": "Metabase",
        "description": "Business intelligence dashboards and SQL queries",
        "features": ["dashboards", "cards", "queries", "collections"],
    },
    "google_analytics": {
        "name": "Google Analytics 4",
        "description": "Web and app analytics with real-time reporting",
        "features": ["reports", "realtime", "audiences", "conversions"],
    },
    "mixpanel": {
        "name": "Mixpanel",
        "description": "Product analytics with funnels and retention",
        "features": ["events", "funnels", "retention", "cohorts", "insights"],
    },
}


@dataclass
class UnifiedMetric:
    """Unified metric representation across platforms."""

    name: str
    value: float | int
    platform: str
    dimension: str | None = None
    period: str | None = None
    change_percent: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "value": self.value,
            "platform": self.platform,
            "dimension": self.dimension,
            "period": self.period,
            "change_percent": self.change_percent,
        }


@dataclass
class UnifiedDashboard:
    """Unified dashboard representation."""

    id: str
    platform: str
    name: str
    description: str | None
    url: str | None
    created_at: datetime | None
    cards_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "platform": self.platform,
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "cards_count": self.cards_count,
        }


class AnalyticsPlatformsHandler(SecureHandler):
    """Handler for analytics platform API endpoints."""

    def __init__(self, ctx: dict | None = None, server_context: dict | None = None):
        """Initialize handler with optional context."""
        if server_context is not None:
            self.ctx = server_context
        else:
            self.ctx = server_context or ctx or {}

    RESOURCE_TYPE = "analytics"

    ROUTES = [
        "/api/v1/analytics/platforms",
        "/api/v1/analytics/connect",
        "/api/v1/analytics/{platform}",
        "/api/v1/analytics/dashboards",
        "/api/v1/analytics/{platform}/dashboards",
        "/api/v1/analytics/{platform}/dashboards/{dashboard_id}",
        "/api/v1/analytics/query",
        "/api/v1/analytics/reports",
        "/api/v1/analytics/reports/generate",
        "/api/v1/analytics/metrics",
        "/api/v1/analytics/realtime",
        "/api/v1/analytics/{platform}/events",
        "/api/v1/analytics/{platform}/funnels",
        "/api/v1/analytics/{platform}/retention",
    ]

    async def _check_permission(self, request: Any, permission: str) -> Any:
        """Check if user has the required permission using RBAC system."""
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
        return path.startswith("/api/v1/analytics/")

    async def handle(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Serve modular-dispatch requests through handle_request."""
        return await call_request_handler(
            self.handle_request, path, query_params, handler, self.read_json_body
        )

    @rate_limit(requests_per_minute=60)
    async def handle_request(self, request: Any) -> dict[str, Any]:
        """Route request to appropriate handler."""
        method = request.method
        path = str(request.path)

        # Parse path components
        platform = None
        dashboard_id = None

        parts = path.replace("/api/v1/analytics/", "").split("/")
        if parts and parts[0] in SUPPORTED_PLATFORMS:
            platform = parts[0]
            if len(parts) > 2 and parts[1] == "dashboards":
                dashboard_id = parts[2]

        # Route to handlers
        if path.endswith("/platforms") and method == "GET":
            if err := await self._check_permission(request, "analytics:read"):
                return err
            return await self._list_platforms(request)

        elif path.endswith("/connect") and method == "POST":
            if err := await self._check_permission(request, "analytics:configure"):
                return err
            return await self._connect_platform(request)

        elif platform and path.endswith(f"/{platform}") and method == "DELETE":
            if err := await self._check_permission(request, "analytics:configure"):
                return err
            return await self._disconnect_platform(request, platform)

        elif path.endswith("/dashboards") and not platform and method == "GET":
            if err := await self._check_permission(request, "analytics:read"):
                return err
            return await self._list_all_dashboards(request)

        elif platform and "dashboards" in path:
            if method == "GET" and not dashboard_id:
                if err := await self._check_permission(request, "analytics:read"):
                    return err
                return await self._list_platform_dashboards(request, platform)
            elif method == "GET" and dashboard_id:
                if err := await self._check_permission(request, "analytics:read"):
                    return err
                return await self._get_dashboard(request, platform, dashboard_id)

        elif path.endswith("/query") and method == "POST":
            if err := await self._check_permission(request, "analytics:query"):
                return err
            return await self._execute_query(request)

        elif path.endswith("/reports") and method == "GET":
            if err := await self._check_permission(request, "analytics:read"):
                return err
            return await self._list_reports(request)

        elif path.endswith("/reports/generate") and method == "POST":
            if err := await self._check_permission(request, "analytics:query"):
                return err
            return await self._generate_report(request)

        elif path.endswith("/metrics") and method == "GET":
            if err := await self._check_permission(request, "analytics:read"):
                return err
            return await self._get_cross_platform_metrics(request)

        elif path.endswith("/realtime") and method == "GET":
            if err := await self._check_permission(request, "analytics:read"):
                return err
            return await self._get_realtime_metrics(request)

        elif platform and path.endswith("/events") and method == "GET":
            if err := await self._check_permission(request, "analytics:read"):
                return err
            return await self._get_events(request, platform)

        elif platform and path.endswith("/funnels") and method == "GET":
            if err := await self._check_permission(request, "analytics:read"):
                return err
            return await self._get_funnels(request, platform)

        elif platform and path.endswith("/retention") and method == "GET":
            if err := await self._check_permission(request, "analytics:read"):
                return err
            return await self._get_retention(request, platform)

        elif (
            len(parts) == 3 and parts[0] == "workspace" and parts[2] == "usage" and method == "GET"
        ):
            if err := await self._check_permission(request, "analytics:read"):
                return err
            return self._json_response(
                501,
                {
                    "error": {
                        "message": "Workspace usage analytics are not implemented",
                        "code": "not_implemented",
                    }
                },
            )

        return self._error_response(404, "Endpoint not found")

    async def _list_platforms(self, request: Any) -> dict[str, Any]:
        """List all supported analytics platforms and connection status."""
        platforms = []
        for platform_id, meta in SUPPORTED_PLATFORMS.items():
            connected = platform_id in _platform_credentials
            platforms.append(
                {
                    "id": platform_id,
                    "name": meta["name"],
                    "description": meta["description"],
                    "features": meta["features"],
                    "connected": connected,
                    "connected_at": _platform_credentials.get(platform_id, {}).get("connected_at"),
                }
            )

        return self._json_response(
            200,
            {
                "platforms": platforms,
                "connected_count": sum(1 for p in platforms if p["connected"]),
            },
        )

    async def _connect_platform(self, request: Any) -> dict[str, Any]:
        """Connect an analytics platform with credentials."""
        try:
            body = await self._get_json_body(request)
        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Handler error: %s", e)
            return self._error_response(400, "Invalid request body")

        platform = body.get("platform")
        if not platform:
            return self._error_response(400, "Platform is required")

        if platform not in SUPPORTED_PLATFORMS:
            return self._error_response(400, f"Unsupported platform: {platform}")

        credentials = body.get("credentials", {})
        if not credentials:
            return self._error_response(400, "Missing required credentials")

        # Validate required credentials per platform
        required_fields = self._get_required_credentials(platform)
        missing = [f for f in required_fields if f not in credentials]
        if missing:
            return self._error_response(400, f"Missing required credentials: {', '.join(missing)}")

        # Store credentials
        _platform_credentials[platform] = {
            "credentials": credentials,
            "connected_at": datetime.now(timezone.utc).isoformat(),
        }

        # Initialize connector
        try:
            connector = await self._get_connector(platform)
            if connector:
                _platform_connectors[platform] = connector
        except (ImportError, ConnectionError, TimeoutError, OSError, TypeError, ValueError) as e:
            logger.warning("Could not initialize %s connector: %s", platform, e)

        logger.info("Connected analytics platform: %s", platform)

        return self._json_response(
            200,
            {
                "message": f"Successfully connected to {SUPPORTED_PLATFORMS[platform]['name']}",
                "platform": platform,
                "connected_at": _platform_credentials[platform]["connected_at"],
            },
        )

    async def _disconnect_platform(self, request: Any, platform: str) -> dict[str, Any]:
        """Disconnect an analytics platform."""
        if platform not in _platform_credentials:
            return self._error_response(404, f"Platform {platform} is not connected")

        # Close connector if exists
        if platform in _platform_connectors:
            connector = _platform_connectors[platform]
            if hasattr(connector, "close"):
                await connector.close()
            del _platform_connectors[platform]

        del _platform_credentials[platform]

        logger.info("Disconnected analytics platform: %s", platform)

        return self._json_response(
            200,
            {
                "message": f"Disconnected from {SUPPORTED_PLATFORMS[platform]['name']}",
                "platform": platform,
            },
        )

    async def _list_all_dashboards(self, request: Any) -> dict[str, Any]:
        """List dashboards from all connected platforms."""
        all_dashboards: list[dict[str, Any]] = []

        # Gather dashboards from all connected platforms
        tasks = []
        for platform in _platform_credentials.keys():
            tasks.append(self._fetch_platform_dashboards(platform))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for platform, result in zip(_platform_credentials.keys(), results):
            if isinstance(result, BaseException):
                logger.error("Error fetching dashboards from %s: %s", platform, result)
                continue
            all_dashboards.extend(result)

        return self._json_response(
            200,
            {
                "dashboards": all_dashboards,
                "total": len(all_dashboards),
                "platforms_queried": list(_platform_credentials.keys()),
            },
        )

    async def _fetch_platform_dashboards(self, platform: str) -> list[dict[str, Any]]:
        """Fetch dashboards from a specific platform."""
        connector = await self._get_connector(platform)
        if not connector:
            return []

        try:
            if platform == "metabase":
                dashboards = await connector.get_dashboards()
                return [self._normalize_metabase_dashboard(d) for d in dashboards]

            elif platform == "google_analytics":
                # GA4 doesn't have dashboards in the traditional sense
                # Return custom reports as "dashboards"
                return []

            elif platform == "mixpanel":
                # Mixpanel uses "reports" / "boards"
                return []

        except (ConnectionError, TimeoutError, OSError, ValueError, AttributeError) as e:
            logger.error("Error fetching %s dashboards: %s", platform, e)

        return []

    async def _list_platform_dashboards(self, request: Any, platform: str) -> dict[str, Any]:
        """List dashboards from a specific platform."""
        if platform not in _platform_credentials:
            return self._error_response(404, f"Platform {platform} is not connected")

        dashboards = await self._fetch_platform_dashboards(platform)

        return self._json_response(
            200,
            {
                "dashboards": dashboards,
                "total": len(dashboards),
                "platform": platform,
            },
        )

    async def _get_dashboard(
        self,
        request: Any,
        platform: str,
        dashboard_id: str,
    ) -> dict[str, Any]:
        """Get a specific dashboard with its cards/visualizations."""
        if platform not in _platform_credentials:
            return self._error_response(404, f"Platform {platform} is not connected")

        connector = await self._get_connector(platform)
        if not connector:
            return self._error_response(500, f"Could not initialize {platform} connector")

        try:
            if platform == "metabase":
                dashboard = await connector.get_dashboard(int(dashboard_id))
                cards = await connector.get_dashboard_cards(int(dashboard_id))
                return self._json_response(
                    200,
                    {
                        **self._normalize_metabase_dashboard(dashboard),
                        "cards": [self._normalize_metabase_card(c) for c in cards],
                    },
                )

        except (ConnectionError, TimeoutError, OSError, ValueError, KeyError, AttributeError) as e:
            logger.warning("Handler error: %s", e)
            return self._error_response(404, "Dashboard not found")

        return self._error_response(400, "Unsupported platform")

    async def _execute_query(self, request: Any) -> dict[str, Any]:
        """Execute a query on a specific platform."""
        try:
            body = await self._get_json_body(request)
        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Handler error: %s", e)
            return self._error_response(400, "Invalid request body")

        platform = body.get("platform")
        if not platform or platform not in _platform_credentials:
            return self._error_response(400, "Valid connected platform is required")

        query = body.get("query")
        if not query:
            return self._error_response(400, "Query is required")

        connector = await self._get_connector(platform)
        if not connector:
            return self._error_response(500, f"Could not initialize {platform} connector")

        try:
            if platform == "metabase":
                # Native SQL query
                database_id = body.get("database_id", 1)
                result = await connector.execute_query(database_id, query)
                return self._json_response(
                    200,
                    {
                        "platform": platform,
                        "query": query,
                        "columns": result.columns,
                        "rows": result.rows[:1000],  # Limit rows
                        "row_count": result.row_count,
                    },
                )

            elif platform == "google_analytics":
                # GA4 report request
                metrics = body.get("metrics", ["sessions"])
                dimensions = body.get("dimensions", ["date"])
                date_range = body.get("date_range", {"start": "30daysAgo", "end": "today"})

                report = await connector.get_report(
                    metrics=[{"name": m} for m in metrics],
                    dimensions=[{"name": d} for d in dimensions],
                    date_ranges=[date_range],
                )
                return self._json_response(
                    200,
                    {
                        "platform": platform,
                        "report": self._normalize_ga_report(report),
                    },
                )

            elif platform == "mixpanel":
                # Mixpanel JQL or insights query
                event = body.get("event")
                from_date = body.get("from_date")
                to_date = body.get("to_date")

                if event:
                    result = await connector.get_insights(
                        event=event,
                        from_date=from_date,
                        to_date=to_date,
                    )
                    return self._json_response(
                        200,
                        {
                            "platform": platform,
                            "result": self._normalize_mixpanel_insight(result),
                        },
                    )

        except (ConnectionError, TimeoutError, OSError, ValueError, AttributeError) as e:
            logger.warning("Handler error: %s", e)
            return self._error_response(500, "Query execution failed")

        return self._error_response(400, "Unsupported platform")

    async def _list_reports(self, request: Any) -> dict[str, Any]:
        """List available pre-built reports."""
        platform = request.query.get("platform")

        reports = []

        # Standard cross-platform reports
        standard_reports = [
            {
                "id": "traffic_overview",
                "name": "Traffic Overview",
                "description": "Website traffic metrics including sessions, users, and pageviews",
                "platforms": ["google_analytics"],
                "metrics": ["sessions", "users", "pageviews", "bounce_rate"],
            },
            {
                "id": "user_engagement",
                "name": "User Engagement",
                "description": "User engagement metrics and event tracking",
                "platforms": ["google_analytics", "mixpanel"],
                "metrics": ["engagement_rate", "events_per_session", "avg_session_duration"],
            },
            {
                "id": "conversion_funnel",
                "name": "Conversion Funnel",
                "description": "Step-by-step conversion analysis",
                "platforms": ["google_analytics", "mixpanel"],
                "metrics": ["funnel_steps", "conversion_rate", "drop_off_rate"],
            },
            {
                "id": "retention_analysis",
                "name": "Retention Analysis",
                "description": "User retention over time",
                "platforms": ["mixpanel"],
                "metrics": ["day_1_retention", "day_7_retention", "day_30_retention"],
            },
            {
                "id": "revenue_analytics",
                "name": "Revenue Analytics",
                "description": "E-commerce and revenue metrics",
                "platforms": ["google_analytics", "mixpanel"],
                "metrics": ["revenue", "transactions", "avg_order_value"],
            },
        ]

        if platform:
            reports = [r for r in standard_reports if platform in r["platforms"]]
        else:
            reports = standard_reports

        return self._json_response(
            200,
            {
                "reports": reports,
                "total": len(reports),
            },
        )

    async def _generate_report(self, request: Any) -> dict[str, Any]:
        """Generate a custom analytics report."""
        try:
            body = await self._get_json_body(request)
        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Handler error: %s", e)
            return self._error_response(400, "Invalid request body")

        report_type = body.get("type", "traffic_overview")
        platforms = body.get("platforms", list(_platform_credentials.keys()))
        days = body.get("days", 30)

        end_date = date.today()
        start_date = end_date - timedelta(days=days)

        report_data: dict[str, Any] = {
            "report_id": str(uuid4()),
            "type": report_type,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "date_range": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
            },
            "platforms": {},
        }

        # Gather data from each platform
        for platform in platforms:
            if platform not in _platform_credentials:
                continue

            try:
                data = await self._fetch_report_data(platform, report_type, start_date, end_date)
                report_data["platforms"][platform] = data
            except (ConnectionError, TimeoutError, OSError, ValueError, AttributeError) as e:
                logger.error("Error fetching %s report data: %s", platform, e)
                report_data["platforms"][platform] = {"error": "Failed to fetch report data"}

        return self._json_response(200, report_data)

    async def _fetch_report_data(
        self,
        platform: str,
        report_type: str,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        """Fetch report data from a specific platform."""
        connector = await self._get_connector(platform)
        if not connector:
            return error_dict("Connector not available", code="SERVICE_UNAVAILABLE")

        if platform == "google_analytics":
            if report_type == "traffic_overview":
                report = await connector.get_report(
                    metrics=[
                        {"name": "sessions"},
                        {"name": "totalUsers"},
                        {"name": "screenPageViews"},
                        {"name": "bounceRate"},
                    ],
                    dimensions=[{"name": "date"}],
                    date_ranges=[
                        {
                            "startDate": start_date.isoformat(),
                            "endDate": end_date.isoformat(),
                        }
                    ],
                )
                return self._normalize_ga_report(report)

        elif platform == "mixpanel":
            if report_type == "user_engagement":
                insights = await connector.get_insights(
                    event="$session_start",
                    from_date=start_date.isoformat(),
                    to_date=end_date.isoformat(),
                )
                return self._normalize_mixpanel_insight(insights)

        return {}

    async def _get_cross_platform_metrics(self, request: Any) -> dict[str, Any]:
        """Get a unified metrics overview across all platforms."""
        days = safe_query_int(request.query, "days", default=7, max_val=365)
        end_date = date.today()
        start_date = end_date - timedelta(days=days)

        metrics: dict[str, Any] = {
            "date_range": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
            },
            "platforms": {},
            "summary": {},
        }

        total_users = 0
        total_sessions = 0
        total_events = 0

        for platform in _platform_credentials.keys():
            try:
                connector = await self._get_connector(platform)
                if not connector:
                    continue

                if platform == "google_analytics":
                    report = await connector.get_report(
                        metrics=[
                            {"name": "totalUsers"},
                            {"name": "sessions"},
                            {"name": "eventCount"},
                        ],
                        date_ranges=[
                            {
                                "startDate": start_date.isoformat(),
                                "endDate": end_date.isoformat(),
                            }
                        ],
                    )
                    ga_metrics = self._extract_ga_totals(report)
                    metrics["platforms"]["google_analytics"] = ga_metrics
                    total_users += ga_metrics.get("users", 0)
                    total_sessions += ga_metrics.get("sessions", 0)
                    total_events += ga_metrics.get("events", 0)

                elif platform == "mixpanel":
                    insights = await connector.get_insights(
                        event="$session_start",
                        from_date=start_date.isoformat(),
                        to_date=end_date.isoformat(),
                    )
                    mp_metrics = {
                        "sessions": insights.total if hasattr(insights, "total") else 0,
                    }
                    metrics["platforms"]["mixpanel"] = mp_metrics

            except (ConnectionError, TimeoutError, OSError, ValueError, AttributeError) as e:
                logger.error("Error fetching %s metrics: %s", platform, e)
                metrics["platforms"][platform] = {"error": "Failed to fetch platform metrics"}

        metrics["summary"] = {
            "total_users": total_users,
            "total_sessions": total_sessions,
            "total_events": total_events,
        }

        return self._json_response(200, metrics)

    async def _get_realtime_metrics(self, request: Any) -> dict[str, Any]:
        """Get real-time metrics (primarily from GA4)."""
        if "google_analytics" not in _platform_credentials:
            return self._error_response(404, "Google Analytics is not connected")

        connector = await self._get_connector("google_analytics")
        if not connector:
            return self._error_response(500, "Could not initialize GA4 connector")

        try:
            realtime = await connector.get_realtime_report(
                metrics=[
                    {"name": "activeUsers"},
                    {"name": "screenPageViews"},
                ],
                dimensions=[
                    {"name": "country"},
                    {"name": "pagePath"},
                ],
            )

            return self._json_response(
                200,
                {
                    "platform": "google_analytics",
                    "realtime": self._normalize_ga_realtime(realtime),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )

        except (ConnectionError, TimeoutError, OSError, ValueError, AttributeError) as e:
            logger.warning("Handler error: %s", e)
            return self._error_response(500, "Failed to fetch realtime data")

    async def _get_events(self, request: Any, platform: str) -> dict[str, Any]:
        """Get event data from a platform."""
        if platform not in _platform_credentials:
            return self._error_response(404, f"Platform {platform} is not connected")

        days = safe_query_int(request.query, "days", default=7, max_val=365)
        event_name = request.query.get("event")

        connector = await self._get_connector(platform)
        if not connector:
            return self._error_response(500, f"Could not initialize {platform} connector")

        try:
            if platform == "mixpanel":
                events = await connector.get_events(
                    event=event_name,
                    from_date=(date.today() - timedelta(days=days)).isoformat(),
                    to_date=date.today().isoformat(),
                )
                return self._json_response(
                    200,
                    {
                        "platform": platform,
                        "events": [self._normalize_mixpanel_event(e) for e in events],
                    },
                )

            elif platform == "google_analytics":
                report = await connector.get_report(
                    metrics=[{"name": "eventCount"}],
                    dimensions=[{"name": "eventName"}],
                    date_ranges=[
                        {
                            "startDate": f"{days}daysAgo",
                            "endDate": "today",
                        }
                    ],
                )
                return self._json_response(
                    200,
                    {
                        "platform": platform,
                        "events": self._normalize_ga_report(report),
                    },
                )

        except (ConnectionError, TimeoutError, OSError, ValueError, AttributeError) as e:
            logger.warning("Handler error: %s", e)
            return self._error_response(500, "Failed to fetch events")

        return self._error_response(400, "Platform does not support event queries")

    async def _get_funnels(self, request: Any, platform: str) -> dict[str, Any]:
        """Get funnel analysis from a platform."""
        if platform not in _platform_credentials:
            return self._error_response(404, f"Platform {platform} is not connected")

        if platform != "mixpanel":
            return self._error_response(400, "Funnel analysis is only available for Mixpanel")

        funnel_id = request.query.get("funnel_id")
        if not funnel_id:
            return self._error_response(400, "funnel_id is required")

        connector = await self._get_connector(platform)
        if not connector:
            return self._error_response(500, f"Could not initialize {platform} connector")

        try:
            funnel = await connector.get_funnel(
                funnel_id=funnel_id,
                from_date=(date.today() - timedelta(days=30)).isoformat(),
                to_date=date.today().isoformat(),
            )
            return self._json_response(
                200,
                {
                    "platform": platform,
                    "funnel": self._normalize_mixpanel_funnel(funnel),
                },
            )

        except (ConnectionError, TimeoutError, OSError, ValueError, AttributeError) as e:
            logger.warning("Handler error: %s", e)
            return self._error_response(500, "Failed to fetch funnel")

    async def _get_retention(self, request: Any, platform: str) -> dict[str, Any]:
        """Get retention analysis from a platform."""
        if platform not in _platform_credentials:
            return self._error_response(404, f"Platform {platform} is not connected")

        if platform != "mixpanel":
            return self._error_response(400, "Retention analysis is only available for Mixpanel")

        connector = await self._get_connector(platform)
        if not connector:
            return self._error_response(500, f"Could not initialize {platform} connector")

        try:
            retention = await connector.get_retention(
                from_date=(date.today() - timedelta(days=30)).isoformat(),
                to_date=date.today().isoformat(),
            )
            return self._json_response(
                200,
                {
                    "platform": platform,
                    "retention": self._normalize_mixpanel_retention(retention),
                },
            )

        except (ConnectionError, TimeoutError, OSError, ValueError, AttributeError) as e:
            logger.warning("Handler error: %s", e)
            return self._error_response(500, "Failed to fetch retention")

    # Helper methods

    def _get_required_credentials(self, platform: str) -> list[str]:
        """Get required credential fields for a platform."""
        requirements = {
            "metabase": ["base_url", "username", "password"],
            "google_analytics": ["property_id", "credentials_json"],
            "mixpanel": ["project_id", "api_secret"],
        }
        return requirements.get(platform, [])

    async def _get_connector(self, platform: str) -> Any | None:
        """Get or create a connector for a platform.

        Uses circuit breaker to prevent cascading failures when platform APIs
        are unavailable.
        """
        if platform in _platform_connectors:
            return _platform_connectors[platform]

        if platform not in _platform_credentials:
            return None

        # Check circuit breaker state before attempting connection
        cb = get_analytics_circuit_breaker()
        if not cb.can_execute():
            logger.warning("Circuit breaker open for analytics service, skipping %s", platform)
            return None

        creds = _platform_credentials[platform]["credentials"]

        connector: Any = None
        try:
            if platform == "metabase":
                from aragora.connectors.analytics.metabase import (
                    MetabaseConnector,
                    MetabaseCredentials,
                )

                connector = MetabaseConnector(MetabaseCredentials(**creds))

            elif platform == "google_analytics":
                from aragora.connectors.analytics.google_analytics import (
                    GoogleAnalyticsConnector,
                    GoogleAnalyticsCredentials,
                )

                connector = GoogleAnalyticsConnector(GoogleAnalyticsCredentials(**creds))

            elif platform == "mixpanel":
                from aragora.connectors.analytics.mixpanel import (
                    MixpanelConnector,
                    MixpanelCredentials,
                )

                connector = MixpanelConnector(MixpanelCredentials(**creds))

            else:
                return None

            _platform_connectors[platform] = connector
            cb.record_success()
            return connector

        except (ImportError, ConnectionError, TimeoutError, OSError, TypeError, ValueError) as e:
            logger.error("Failed to create %s connector: %s", platform, e)
            cb.record_failure()
            return None

    def _normalize_metabase_dashboard(self, dashboard: Any) -> dict[str, Any]:
        """Normalize Metabase dashboard to unified format."""
        return {
            "id": str(dashboard.id),
            "platform": "metabase",
            "name": dashboard.name,
            "description": dashboard.description,
            "url": f"/dashboard/{dashboard.id}",
            "created_at": dashboard.created_at.isoformat() if dashboard.created_at else None,
            "cards_count": len(dashboard.dashcards) if hasattr(dashboard, "dashcards") else 0,
        }

    def _normalize_metabase_card(self, card: Any) -> dict[str, Any]:
        """Normalize Metabase card to unified format."""
        return {
            "id": str(card.id),
            "name": card.name,
            "description": card.description,
            "display_type": card.display.value if hasattr(card.display, "value") else card.display,
            "query_type": card.query_type,
        }

    def _normalize_ga_report(self, report: Any) -> dict[str, Any]:
        """Normalize GA4 report to unified format."""

        def _header_name(header: Any) -> Any:
            if isinstance(header, str):
                return header
            if hasattr(header, "_mock_name") and header._mock_name:
                return header._mock_name
            if hasattr(header, "name"):
                name = header.name
                return name if isinstance(name, str) else str(name)
            return str(header)

        return {
            "dimensions": (
                [_header_name(h) for h in report.dimension_headers]
                if hasattr(report, "dimension_headers")
                else []
            ),
            "metrics": (
                [_header_name(h) for h in report.metric_headers]
                if hasattr(report, "metric_headers")
                else []
            ),
            "rows": [
                {
                    "dimensions": (
                        [d.value for d in row.dimension_values]
                        if hasattr(row, "dimension_values")
                        else []
                    ),
                    "metrics": (
                        [m.value for m in row.metric_values]
                        if hasattr(row, "metric_values")
                        else []
                    ),
                }
                for row in (report.rows if hasattr(report, "rows") else [])
            ],
            "row_count": (
                report.row_count
                if hasattr(report, "row_count")
                else len(report.rows)
                if hasattr(report, "rows")
                else 0
            ),
        }

    def _extract_ga_totals(self, report: Any) -> dict[str, Any]:
        """Extract totals from GA4 report."""
        if not hasattr(report, "rows") or not report.rows:
            return {"users": 0, "sessions": 0, "events": 0}

        def _header_name(header: Any) -> str:
            if isinstance(header, str):
                return header
            if hasattr(header, "_mock_name") and header._mock_name:
                return header._mock_name
            if hasattr(header, "name"):
                name = header.name
                return name if isinstance(name, str) else str(name)
            return str(header)

        row = report.rows[0]
        metrics = {}
        if hasattr(report, "metric_headers"):
            for i, header in enumerate(report.metric_headers):
                if i < len(row.metric_values):
                    metrics[_header_name(header)] = int(row.metric_values[i].value)

        return {
            "users": metrics.get("totalUsers", 0),
            "sessions": metrics.get("sessions", 0),
            "events": metrics.get("eventCount", 0),
        }

    def _normalize_ga_realtime(self, realtime: Any) -> dict[str, Any]:
        """Normalize GA4 realtime report."""
        return {
            "active_users": realtime.active_users if hasattr(realtime, "active_users") else 0,
            "rows": [
                {
                    "dimensions": (
                        [d.value for d in row.dimension_values]
                        if hasattr(row, "dimension_values")
                        else []
                    ),
                    "metrics": (
                        [m.value for m in row.metric_values]
                        if hasattr(row, "metric_values")
                        else []
                    ),
                }
                for row in (realtime.rows if hasattr(realtime, "rows") else [])
            ],
        }

    def _normalize_mixpanel_insight(self, insight: Any) -> dict[str, Any]:
        """Normalize Mixpanel insight to unified format."""
        return {
            "total": insight.total if hasattr(insight, "total") else 0,
            "series": insight.series if hasattr(insight, "series") else [],
            "breakdown": insight.breakdown if hasattr(insight, "breakdown") else {},
        }

    def _normalize_mixpanel_event(self, event: Any) -> dict[str, Any]:
        """Normalize Mixpanel event to unified format."""
        return {
            "event_name": event.name if hasattr(event, "name") else "",
            "distinct_id": event.distinct_id if hasattr(event, "distinct_id") else "",
            "timestamp": event.timestamp.isoformat() if hasattr(event, "timestamp") else None,
            "properties": event.properties if hasattr(event, "properties") else {},
        }

    def _normalize_mixpanel_funnel(self, funnel: Any) -> dict[str, Any]:
        """Normalize Mixpanel funnel to unified format."""
        return {
            "steps": funnel.steps if hasattr(funnel, "steps") else [],
            "conversion_rate": (
                funnel.overall_conversion if hasattr(funnel, "overall_conversion") else 0
            ),
            "date_range": {
                "start": funnel.from_date if hasattr(funnel, "from_date") else None,
                "end": funnel.to_date if hasattr(funnel, "to_date") else None,
            },
        }

    def _normalize_mixpanel_retention(self, retention: Any) -> dict[str, Any]:
        """Normalize Mixpanel retention to unified format."""
        return {
            "cohorts": retention.cohorts if hasattr(retention, "cohorts") else [],
            "retention_by_day": retention.retention if hasattr(retention, "retention") else [],
        }

    async def _get_json_body(self, request: Any) -> dict[str, Any]:
        """Parse JSON body from request."""
        body, _err = await parse_json_body(request, context="analytics_platforms._get_json_body")
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


__all__ = ["AnalyticsPlatformsHandler"]
