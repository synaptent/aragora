"""
SLO (Service Level Objective) endpoint handlers.

Stability: STABLE
Graduated from EXPERIMENTAL on 2026-02-01.

Exposes SLO status, error budgets, and violation data via HTTP API.

Endpoints:
- GET /api/slos/status - Overall SLO compliance status
- GET /api/slos/{slo_name} - Individual SLO details
- GET /api/slos/error-budget - Error budget timeline
- GET /api/slos/violations - Recent SLO violations
- GET /api/slos/targets - Configured SLO targets
- GET /api/v1/slos/status - Versioned endpoint
- GET /api/v1/slo/status - SLO enforcer real-time compliance status
- GET /api/v1/slo/budget - SLO enforcer error budget remaining
- GET /api/health/slos - Debate SLO health (green/yellow/red per SLO, multi-window)

RBAC Permissions:
- slo:read - View SLO status, details, error budgets, violations, and targets

Rate Limiting:
- 30 requests per minute per client IP

Usage:
    # Check overall SLO health
    curl http://localhost:8080/api/slos/status

    # Get specific SLO details
    curl http://localhost:8080/api/slos/availability

    # Get error budget information
    curl http://localhost:8080/api/slos/error-budget

    # Get real-time SLO enforcer compliance
    curl http://localhost:8080/api/v1/slo/status

    # Get remaining error budget from enforcer
    curl http://localhost:8080/api/v1/slo/budget

    # Get debate-specific SLO health (multi-window)
    curl http://localhost:8080/api/health/slos
    curl http://localhost:8080/api/health/slos?window=24h
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from aragora.observability.slo import (
    check_alerts,
    check_availability_slo,
    check_debate_success_slo,
    check_latency_slo,
    get_slo_enforcer,
    get_slo_status,
    get_slo_status_json,
    get_slo_targets,
)
from aragora.server.versioning.compat import strip_version_prefix

from ..base import BaseHandler, HandlerResult, error_response, json_response
from aragora.rbac.decorators import require_permission
from ..utils.rate_limit import RateLimiter, get_client_ip

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Default timeout for SLO service calls (in seconds)
SLO_SERVICE_TIMEOUT = 5.0

# Rate limiter for SLO endpoints (30 requests per minute)
_slo_limiter = RateLimiter(requests_per_minute=30)


class SLOHandler(BaseHandler):
    """Handler for SLO monitoring endpoints.

    Stability: STABLE

    Provides production-ready endpoints for monitoring Service Level Objectives,
    including overall status, individual SLO details, error budgets, and violations.

    Features:
    - RBAC protection with slo:read permission
    - Rate limiting (30 RPM per client)
    - Comprehensive error handling with proper HTTP status codes
    - API versioning support (/api/v1/slos/...)

    Example:
        handler = SLOHandler(ctx)
        if handler.can_handle("/api/slos/status"):
            result = handler.handle("/api/slos/status", {}, http_handler)
    """

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context.

        Args:
            ctx: Server context dictionary containing shared resources.
                 Optional for SLO handler as it uses the SLO observability module.
        """
        self.ctx = ctx or {}

    ROUTES = [
        "/api/slos/status",
        "/api/slos/error-budget",
        "/api/slos/violations",
        "/api/slos/targets",
        "/api/slos/availability",
        "/api/slos/latency",
        "/api/slos/debate-success",
        "/api/slos/*",  # Dynamic per-SLO routes handled in can_handle
        # SDK v2 aliases (singular /api/slo/)
        "/api/slo/status",
        "/api/slo/budget",
        "/api/v2/slo/status",
        # Debate SLO health endpoint
        "/api/health/slos",
    ]

    # Individual SLO names for dynamic routing
    SLO_NAMES = {"availability", "latency", "latency_p99", "debate_success", "debate-success"}

    # Sub-routes for individual SLOs (/api/slo/{name}/error-budget, etc.)
    SLO_SUB_ROUTES = {"error-budget", "violations", "compliant", "alerts"}

    @staticmethod
    def _normalize_slo_path(path: str) -> str:
        """Normalize /api/slo/ to /api/slos/ for consistent routing."""
        path = strip_version_prefix(path)
        # Normalize singular /api/slo/ to plural /api/slos/
        if path.startswith("/api/slo/"):
            path = "/api/slos/" + path[len("/api/slo/") :]
        return path

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        # Check /api/health/slos before normalization (different prefix)
        stripped = strip_version_prefix(path)
        if stripped == "/api/health/slos":
            return True

        path = self._normalize_slo_path(path)

        if path in self.ROUTES:
            return True

        # Handle dynamic /api/slos/{slo_name} routes
        if path.startswith("/api/slos/"):
            parts = path.rstrip("/").split("/")
            # /api/slos/{slo_name}
            if len(parts) == 4:
                return parts[3] in self.SLO_NAMES
            # /api/slos/{slo_name}/{sub_route}
            if len(parts) == 5:
                return parts[3] in self.SLO_NAMES and parts[4] in self.SLO_SUB_ROUTES

        return False

    @require_permission("slo:read")
    def handle(self, path: str, query_params: dict, handler: Any) -> HandlerResult | None:
        """Route SLO requests to appropriate methods."""
        # Check /api/health/slos before normalization
        stripped = strip_version_prefix(path)
        if stripped == "/api/health/slos":
            return self._handle_debate_slo_health(query_params, handler)

        path = self._normalize_slo_path(path)

        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _slo_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for SLO endpoint: %s", client_ip)
            return error_response(
                "Rate limit exceeded. Please try again later.", 429, code="RATE_LIMITED"
            )

        try:
            if path == "/api/slos/status":
                return self._handle_slo_status()
            elif path == "/api/slos/budget":
                return self._handle_enforcer_budget()
            elif path == "/api/slos/error-budget":
                return self._handle_error_budget()
            elif path == "/api/slos/violations":
                return self._handle_violations()
            elif path == "/api/slos/targets":
                return self._handle_targets()
            elif path == "/api/slos/availability":
                return self._handle_slo_detail("availability")
            elif path == "/api/slos/latency":
                return self._handle_slo_detail("latency_p99")
            elif path == "/api/slos/debate-success":
                return self._handle_slo_detail("debate_success")
            elif path.startswith("/api/slos/"):
                parts = path.rstrip("/").split("/")
                slo_name = parts[3] if len(parts) >= 4 else ""
                # Normalize name
                if slo_name == "latency":
                    slo_name = "latency_p99"
                elif slo_name == "debate-success":
                    slo_name = "debate_success"

                # Handle sub-routes: /api/slos/{name}/{sub}
                if len(parts) == 5:
                    sub_route = parts[4]
                    return self._handle_slo_sub_route(slo_name, sub_route)

                return self._handle_slo_detail(slo_name)
            else:
                return error_response(f"Unknown SLO endpoint: {path}", 404, code="UNKNOWN_ENDPOINT")

        except (KeyError, ValueError, AttributeError, TypeError, RuntimeError, OSError) as e:
            logger.exception("Error handling SLO request: %s", e)
            return error_response("Internal server error", 500, code="INTERNAL_ERROR")

    def _handle_slo_status(self) -> HandlerResult:
        """GET /api/slos/status - Overall SLO compliance status.

        Merges the existing SLO check data with real-time enforcer metrics.
        Returns ``{"data": {...}}`` envelope.
        """
        try:
            status_json = get_slo_status_json()
            enforcer = get_slo_enforcer()
            enforcer_status = enforcer.get_compliance_status()
            status_json["enforcer"] = enforcer_status
            return json_response({"data": status_json})
        except (KeyError, ValueError, AttributeError, TypeError, RuntimeError, OSError) as e:
            logger.exception("Failed to get SLO status: %s", e)
            return error_response("Internal server error", 500, code="SLO_STATUS_ERROR")

    def _handle_enforcer_budget(self) -> HandlerResult:
        """GET /api/v1/slo/budget - Remaining error budget from enforcer.

        Returns ``{"data": {...}}`` envelope with per-SLO error budget data.
        """
        try:
            enforcer = get_slo_enforcer()
            budget = enforcer.get_error_budget()
            return json_response({"data": budget})
        except (KeyError, ValueError, AttributeError, TypeError, RuntimeError, OSError) as e:
            logger.exception("Failed to get SLO budget: %s", e)
            return error_response("Internal server error", 500, code="SLO_BUDGET_ERROR")

    def _handle_slo_detail(self, slo_name: str) -> HandlerResult:
        """GET /api/slos/{slo_name} - Individual SLO details."""
        try:
            if slo_name == "availability":
                result = check_availability_slo()
            elif slo_name == "latency_p99":
                result = check_latency_slo()
            elif slo_name == "debate_success":
                result = check_debate_success_slo()
            else:
                return error_response(f"Unknown SLO: {slo_name}", 404, code="UNKNOWN_SLO")

            return json_response(
                {
                    "name": result.name,
                    "target": result.target,
                    "current": result.current,
                    "compliant": result.compliant,
                    "compliance_percentage": result.compliance_percentage,
                    "error_budget_remaining": result.error_budget_remaining,
                    "burn_rate": result.burn_rate,
                    "window": {
                        "start": result.window_start.isoformat(),
                        "end": result.window_end.isoformat(),
                    },
                }
            )
        except (KeyError, ValueError, AttributeError, TypeError, RuntimeError, OSError) as e:
            logger.exception("Failed to get SLO detail for %s: %s", slo_name, e)
            return error_response("Internal server error", 500, code="SLO_DETAIL_ERROR")

    def _handle_error_budget(self) -> HandlerResult:
        """GET /api/slos/error-budget - Error budget timeline."""
        try:
            status = get_slo_status()

            # Build error budget response
            budgets = []
            for name, result in [
                ("availability", status.availability),
                ("latency_p99", status.latency_p99),
                ("debate_success", status.debate_success),
            ]:
                budgets.append(
                    {
                        "slo_name": result.name,
                        "slo_id": name,
                        "target": result.target,
                        "error_budget_total": 100.0,  # Percentage
                        "error_budget_remaining": result.error_budget_remaining,
                        "error_budget_consumed": 100.0 - result.error_budget_remaining,
                        "burn_rate": result.burn_rate,
                        "projected_exhaustion": self._calculate_exhaustion_time(result),
                        "window": {
                            "start": result.window_start.isoformat(),
                            "end": result.window_end.isoformat(),
                        },
                    }
                )

            return json_response(
                {
                    "timestamp": status.timestamp.isoformat(),
                    "budgets": budgets,
                }
            )
        except (KeyError, ValueError, AttributeError, TypeError, RuntimeError, OSError) as e:
            logger.exception("Failed to get error budget: %s", e)
            return error_response("Internal server error", 500, code="ERROR_BUDGET_ERROR")

    def _handle_violations(self) -> HandlerResult:
        """GET /api/slos/violations - Recent SLO violations."""
        try:
            status = get_slo_status()
            alerts = check_alerts(status)

            violations = []
            for alert, result in alerts:
                violations.append(
                    {
                        "slo_name": alert.slo_name,
                        "severity": alert.severity,
                        "message": alert.message,
                        "current_value": result.current,
                        "target_value": result.target,
                        "error_budget_remaining": result.error_budget_remaining,
                        "burn_rate": result.burn_rate,
                        "detected_at": result.window_end.isoformat(),
                    }
                )

            return json_response(
                {
                    "timestamp": status.timestamp.isoformat(),
                    "violation_count": len(violations),
                    "violations": violations,
                    "overall_healthy": status.overall_healthy,
                }
            )
        except (KeyError, ValueError, AttributeError, TypeError, RuntimeError, OSError) as e:
            logger.exception("Failed to get violations: %s", e)
            return error_response("Internal server error", 500, code="VIOLATIONS_ERROR")

    def _handle_targets(self) -> HandlerResult:
        """GET /api/slos/targets - Get configured SLO targets."""
        try:
            targets = get_slo_targets()

            targets_response = []
            for key, target in targets.items():
                targets_response.append(
                    {
                        "id": key,
                        "name": target.name,
                        "target": target.target,
                        "unit": target.unit,
                        "description": target.description,
                        "comparison": target.comparison,
                    }
                )

            return json_response(
                {
                    "targets": targets_response,
                }
            )
        except (KeyError, ValueError, AttributeError, TypeError, RuntimeError, OSError) as e:
            logger.exception("Failed to get targets: %s", e)
            return error_response("Failed to retrieve targets", 500, code="TARGETS_ERROR")

    def _handle_slo_sub_route(self, slo_name: str, sub_route: str) -> HandlerResult:
        """Handle per-SLO sub-routes: /api/slos/{name}/{sub}."""
        try:
            if slo_name == "availability":
                result = check_availability_slo()
            elif slo_name == "latency_p99":
                result = check_latency_slo()
            elif slo_name == "debate_success":
                result = check_debate_success_slo()
            else:
                return error_response(f"Unknown SLO: {slo_name}", 404, code="UNKNOWN_SLO")

            if sub_route == "error-budget":
                return json_response(
                    {
                        "slo_name": result.name,
                        "error_budget_total": 100.0,
                        "error_budget_remaining": result.error_budget_remaining,
                        "error_budget_consumed": 100.0 - result.error_budget_remaining,
                        "burn_rate": result.burn_rate,
                        "projected_exhaustion": self._calculate_exhaustion_time(result),
                    }
                )
            elif sub_route == "violations":
                status = get_slo_status()
                alerts = check_alerts(status)
                violations = [
                    {
                        "severity": a.severity,
                        "message": a.message,
                        "detected_at": r.window_end.isoformat(),
                    }
                    for a, r in alerts
                    if a.slo_name == result.name
                ]
                return json_response({"slo_name": result.name, "violations": violations})
            elif sub_route == "compliant":
                return json_response(
                    {
                        "slo_name": result.name,
                        "compliant": result.compliant,
                        "current": result.current,
                        "target": result.target,
                    }
                )
            elif sub_route == "alerts":
                status = get_slo_status()
                alerts = check_alerts(status)
                slo_alerts = [
                    {
                        "severity": a.severity,
                        "message": a.message,
                        "burn_rate": r.burn_rate,
                    }
                    for a, r in alerts
                    if a.slo_name == result.name
                ]
                return json_response({"slo_name": result.name, "alerts": slo_alerts})
            else:
                return error_response(
                    f"Unknown sub-route: {sub_route}", 404, code="UNKNOWN_ENDPOINT"
                )

        except (KeyError, ValueError, AttributeError, TypeError, RuntimeError, OSError) as e:
            logger.exception("Failed to get SLO sub-route %s/%s: %s", slo_name, sub_route, e)
            return error_response("Operation failed", 500, code="SLO_SUB_ROUTE_ERROR")

    def _handle_debate_slo_health(self, query_params: dict, handler: Any) -> HandlerResult:
        """GET /api/health/slos - Debate SLO health with multi-window metrics.

        Reports green/yellow/red compliance for each of the five debate SLOs:
        - time_to_first_token p95
        - debate_completion p95
        - websocket_reconnection success rate
        - consensus_detection p95
        - agent_dispatch_concurrency ratio

        Query Parameters:
            window: Time window to evaluate ("1h", "24h", "7d"). Default: "1h"
            all_windows: If "true", return all three windows at once.

        Returns:
            ``{"data": {...}}`` envelope with per-SLO compliance data.
        """
        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _slo_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for debate SLO health: %s", client_ip)
            return error_response(
                "Rate limit exceeded. Please try again later.", 429, code="RATE_LIMITED"
            )

        try:
            from aragora.observability.debate_slos import get_debate_slo_tracker

            tracker = get_debate_slo_tracker()

            all_windows = query_params.get("all_windows", "false").lower() == "true"

            if all_windows:
                status_data = tracker.get_multi_window_status()
            else:
                window = query_params.get("window", "1h")
                if window not in ("1h", "24h", "7d"):
                    return error_response(
                        f"Invalid window: {window}. Must be 1h, 24h, or 7d.",
                        400,
                        code="INVALID_WINDOW",
                    )
                status = tracker.get_status(window)
                status_data = status.to_dict()

            return json_response({"data": status_data})

        except ImportError:
            logger.warning("Debate SLO tracker not available")
            return error_response("Debate SLO tracking not available", 503, code="SLO_UNAVAILABLE")
        except (KeyError, ValueError, AttributeError, TypeError, RuntimeError, OSError) as e:
            logger.exception("Failed to get debate SLO health: %s", e)
            return error_response("Internal server error", 500, code="DEBATE_SLO_ERROR")

    def _calculate_exhaustion_time(self, result: Any) -> str | None:
        """Calculate projected error budget exhaustion time.

        Args:
            result: SLOResult with burn_rate and error_budget_remaining

        Returns:
            ISO timestamp of projected exhaustion, or None if not applicable
        """
        from datetime import timedelta

        if result.burn_rate <= 0 or result.error_budget_remaining <= 0:
            return None

        # Calculate hours until exhaustion at current burn rate
        # Error budget window is 1 hour, so burn_rate of 1.0 = consuming at expected rate
        # If burn_rate > 1.0, exhaustion happens faster
        if result.burn_rate <= 1.0:
            return None  # Budget is sustainable

        # Hours remaining = (remaining / 100) / (burn_rate * expected_hourly_consumption)
        # Simplified: hours = remaining_pct / (burn_rate * (100 - target) * 100)
        hours_remaining = result.error_budget_remaining / (result.burn_rate * 10)
        hours_remaining = max(0, min(hours_remaining, 720))  # Cap at 30 days

        exhaustion_time = result.window_end + timedelta(hours=hours_remaining)
        return exhaustion_time.isoformat()


__all__ = ["SLOHandler"]
