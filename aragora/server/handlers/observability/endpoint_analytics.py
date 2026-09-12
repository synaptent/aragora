"""
API Endpoint Performance Analytics handler.

Provides REST APIs for analyzing API endpoint performance metrics:

Endpoint Performance:
- GET /api/analytics/endpoints - List all endpoints with aggregated metrics
- GET /api/analytics/endpoints/slowest - Top N slowest endpoints by latency
- GET /api/analytics/endpoints/errors - Top N endpoints by error rate
- GET /api/analytics/endpoints/{endpoint}/performance - Detailed metrics for endpoint

This handler aggregates Prometheus metrics to provide actionable endpoint analytics.
"""

from __future__ import annotations

import logging
import re
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote

from aragora.server.versioning.compat import strip_version_prefix

from ..base import (
    HandlerResult,
    error_response,
    json_response,
    safe_error_message,
)
from ..secure import SecureHandler, ForbiddenError, UnauthorizedError
from ..utils.rate_limit import RateLimiter, get_client_ip
from aragora.server.validation.query_params import safe_query_float, safe_query_int

logger = logging.getLogger(__name__)

# Permission required for endpoint analytics access
ENDPOINT_ANALYTICS_PERMISSION = "analytics.read"

# Rate limiter for endpoint analytics (60 requests per minute)
_endpoint_analytics_limiter = RateLimiter(requests_per_minute=60)


@dataclass
class EndpointMetrics:
    """Aggregated metrics for a single endpoint."""

    endpoint: str
    method: str = "GET"
    total_requests: int = 0
    success_count: int = 0
    error_count: int = 0
    latencies: list[float] = field(default_factory=list)

    # Computed on finalize
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    min_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    error_rate: float = 0.0
    requests_per_second: float = 0.0

    def finalize(self, window_seconds: float = 300.0) -> None:
        """Compute aggregated metrics from raw data."""
        if self.total_requests > 0:
            self.error_rate = (self.error_count / self.total_requests) * 100.0
            self.requests_per_second = self.total_requests / window_seconds

        if self.latencies:
            sorted_latencies = sorted(self.latencies)
            self.avg_latency_ms = statistics.mean(sorted_latencies) * 1000
            self.min_latency_ms = sorted_latencies[0] * 1000
            self.max_latency_ms = sorted_latencies[-1] * 1000

            # Percentiles
            n = len(sorted_latencies)
            self.p50_latency_ms = sorted_latencies[int(n * 0.5)] * 1000
            self.p95_latency_ms = sorted_latencies[int(n * 0.95)] * 1000
            self.p99_latency_ms = sorted_latencies[min(int(n * 0.99), n - 1)] * 1000

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON response."""
        return {
            "endpoint": self.endpoint,
            "method": self.method,
            "total_requests": self.total_requests,
            "success_count": self.success_count,
            "error_count": self.error_count,
            "error_rate_percent": round(self.error_rate, 2),
            "requests_per_second": round(self.requests_per_second, 3),
            "latency": {
                "avg_ms": round(self.avg_latency_ms, 2),
                "p50_ms": round(self.p50_latency_ms, 2),
                "p95_ms": round(self.p95_latency_ms, 2),
                "p99_ms": round(self.p99_latency_ms, 2),
                "min_ms": round(self.min_latency_ms, 2),
                "max_ms": round(self.max_latency_ms, 2),
            },
        }


class EndpointMetricsStore:
    """In-memory store for endpoint metrics.

    This supplements Prometheus metrics with detailed per-request tracking
    for analytics purposes. Data is ephemeral and reset on restart.
    """

    def __init__(self, max_entries_per_endpoint: int = 10000):
        self._metrics: dict[str, EndpointMetrics] = {}
        self._max_entries = max_entries_per_endpoint
        self._window_start = time.time()
        self._lock_time = time.time()

    def record_request(
        self,
        endpoint: str,
        method: str,
        status_code: int,
        latency_seconds: float,
    ) -> None:
        """Record a request for an endpoint.

        Args:
            endpoint: Normalized endpoint path
            method: HTTP method
            status_code: Response status code
            latency_seconds: Request latency in seconds
        """
        key = f"{method}:{endpoint}"

        if key not in self._metrics:
            self._metrics[key] = EndpointMetrics(endpoint=endpoint, method=method)

        metrics = self._metrics[key]
        metrics.total_requests += 1

        if 200 <= status_code < 400:
            metrics.success_count += 1
        else:
            metrics.error_count += 1

        # Keep latencies bounded
        if len(metrics.latencies) < self._max_entries:
            metrics.latencies.append(latency_seconds)

    def get_all_endpoints(self, window_seconds: float = 300.0) -> list[EndpointMetrics]:
        """Get metrics for all endpoints."""
        results = []
        for metrics in self._metrics.values():
            metrics.finalize(window_seconds)
            results.append(metrics)
        return results

    def get_endpoint(self, endpoint: str, method: str = "GET") -> EndpointMetrics | None:
        """Get metrics for a specific endpoint."""
        key = f"{method}:{endpoint}"
        metrics = self._metrics.get(key)
        if metrics:
            metrics.finalize()
        return metrics

    def reset(self) -> None:
        """Reset all metrics."""
        self._metrics.clear()
        self._window_start = time.time()


# Global metrics store
_metrics_store = EndpointMetricsStore()


def get_metrics_store() -> EndpointMetricsStore:
    """Get the global metrics store."""
    return _metrics_store


def record_endpoint_request(
    endpoint: str,
    method: str,
    status_code: int,
    latency_seconds: float,
) -> None:
    """Record an endpoint request for analytics.

    This should be called from middleware or request handlers.
    """
    _metrics_store.record_request(endpoint, method, status_code, latency_seconds)


class EndpointAnalyticsHandler(SecureHandler):
    """Handler for API endpoint performance analytics.

    Requires authentication and analytics:read permission (RBAC).
    """

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES = [
        "/api/analytics/endpoints",
        "/api/analytics/endpoints/slowest",
        "/api/analytics/endpoints/errors",
        "/api/analytics/endpoints/health",
    ]

    # Pattern for endpoint-specific performance
    ENDPOINT_PATTERN = re.compile(r"^/api/analytics/endpoints/([^/]+)/performance$")

    RESOURCE_TYPE = "endpoint_analytics"

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        normalized = strip_version_prefix(path)
        if normalized in self.ROUTES:
            return True
        return bool(self.ENDPOINT_PATTERN.match(normalized))

    async def handle(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route GET requests to appropriate methods with RBAC."""
        normalized = strip_version_prefix(path)

        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _endpoint_analytics_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for endpoint analytics: %s", client_ip)
            return error_response(
                "Rate limit exceeded. Please try again later.",
                429,
                code="RATE_LIMIT_EXCEEDED",
            )

        # RBAC: Require authentication and analytics:read permission
        try:
            auth_context = await self.get_auth_context(handler, require_auth=True)
            self.check_permission(auth_context, ENDPOINT_ANALYTICS_PERMISSION)
        except UnauthorizedError:
            return error_response("Authentication required", 401, code="AUTH_REQUIRED")
        except ForbiddenError as e:
            logger.warning("Endpoint analytics access denied: %s", e)
            return error_response("Permission denied", 403, code="PERMISSION_DENIED")

        # Route to specific handlers
        if normalized == "/api/analytics/endpoints":
            return self._get_all_endpoints(query_params)
        elif normalized == "/api/analytics/endpoints/slowest":
            return self._get_slowest_endpoints(query_params)
        elif normalized == "/api/analytics/endpoints/errors":
            return self._get_error_endpoints(query_params)
        elif normalized == "/api/analytics/endpoints/health":
            return self._get_health_summary(query_params)

        # Check for specific endpoint performance
        match = self.ENDPOINT_PATTERN.match(normalized)
        if match:
            endpoint_name = unquote(match.group(1))
            return self._get_endpoint_performance(endpoint_name, query_params)

        return error_response(
            f"Unknown endpoint analytics path: {path}",
            404,
            code="NOT_FOUND",
        )

    def _get_all_endpoints(self, query_params: dict) -> HandlerResult:
        """GET /api/analytics/endpoints - List all endpoints with metrics."""
        try:
            # Get window from query params (default 5 minutes)
            window_seconds = safe_query_float(
                query_params, "window", default=300.0, max_val=86400.0
            )
            sort_by = query_params.get("sort", "requests")  # requests, latency, errors
            order = query_params.get("order", "desc")
            limit = safe_query_int(query_params, "limit", default=100, max_val=500)

            endpoints = _metrics_store.get_all_endpoints(window_seconds)

            # Sort
            if sort_by == "latency":
                endpoints.sort(key=lambda e: e.p95_latency_ms, reverse=(order == "desc"))
            elif sort_by == "errors":
                endpoints.sort(key=lambda e: e.error_rate, reverse=(order == "desc"))
            else:  # requests
                endpoints.sort(key=lambda e: e.total_requests, reverse=(order == "desc"))

            # Limit
            endpoints = endpoints[:limit]

            return json_response(
                {
                    "endpoints": [e.to_dict() for e in endpoints],
                    "total_endpoints": len(_metrics_store._metrics),
                    "window_seconds": window_seconds,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
            )

        except (TypeError, ValueError, KeyError, AttributeError) as e:
            logger.exception("Error getting endpoint metrics: %s", e)
            return error_response(
                safe_error_message(e, "endpoint metrics"),
                500,
                code="ENDPOINT_METRICS_ERROR",
            )

    def _get_slowest_endpoints(self, query_params: dict) -> HandlerResult:
        """GET /api/analytics/endpoints/slowest - Top N slowest endpoints."""
        try:
            limit = safe_query_int(query_params, "limit", default=10, max_val=100)
            percentile = query_params.get("percentile", "p95")  # p50, p95, p99
            if percentile not in ("p50", "p95", "p99"):
                return error_response(
                    f"Invalid percentile: {percentile}. Must be p50, p95, or p99.",
                    400,
                    code="INVALID_PERCENTILE",
                )

            endpoints = _metrics_store.get_all_endpoints()

            # Sort by specified percentile
            if percentile == "p50":
                endpoints.sort(key=lambda e: e.p50_latency_ms, reverse=True)
            elif percentile == "p99":
                endpoints.sort(key=lambda e: e.p99_latency_ms, reverse=True)
            else:  # p95 default
                endpoints.sort(key=lambda e: e.p95_latency_ms, reverse=True)

            slowest = endpoints[:limit]

            return json_response(
                {
                    "slowest_endpoints": [e.to_dict() for e in slowest],
                    "percentile": percentile,
                    "limit": limit,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
            )

        except (TypeError, ValueError, KeyError, AttributeError) as e:
            logger.exception("Error getting slowest endpoints: %s", e)
            return error_response(
                safe_error_message(e, "slowest endpoints"),
                500,
                code="SLOWEST_ENDPOINTS_ERROR",
            )

    def _get_error_endpoints(self, query_params: dict) -> HandlerResult:
        """GET /api/analytics/endpoints/errors - Top N endpoints by error rate."""
        try:
            limit = safe_query_int(query_params, "limit", default=10, max_val=100)
            min_requests = safe_query_int(query_params, "min_requests", default=10, max_val=100000)

            endpoints = _metrics_store.get_all_endpoints()

            # Filter by minimum requests to avoid noise
            endpoints = [e for e in endpoints if e.total_requests >= min_requests]

            # Sort by error rate
            endpoints.sort(key=lambda e: e.error_rate, reverse=True)

            top_errors = endpoints[:limit]

            return json_response(
                {
                    "error_endpoints": [e.to_dict() for e in top_errors],
                    "min_requests_threshold": min_requests,
                    "limit": limit,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
            )

        except (TypeError, ValueError, KeyError, AttributeError) as e:
            logger.exception("Error getting error endpoints: %s", e)
            return error_response(
                safe_error_message(e, "error endpoints"),
                500,
                code="ERROR_ENDPOINTS_ERROR",
            )

    def _get_endpoint_performance(self, endpoint_name: str, query_params: dict) -> HandlerResult:
        """GET /api/analytics/endpoints/{endpoint}/performance - Specific endpoint metrics."""
        try:
            method = query_params.get("method", "GET").upper()

            # Try exact match first
            metrics = _metrics_store.get_endpoint(endpoint_name, method)

            if not metrics:
                # Try with leading slash
                if not endpoint_name.startswith("/"):
                    metrics = _metrics_store.get_endpoint(f"/{endpoint_name}", method)

            if not metrics:
                return error_response(
                    f"No metrics found for endpoint: {endpoint_name}",
                    404,
                    code="ENDPOINT_NOT_FOUND",
                )

            return json_response(
                {
                    "endpoint": metrics.to_dict(),
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
            )

        except (TypeError, ValueError, KeyError, AttributeError) as e:
            logger.exception("Error getting endpoint performance: %s", e)
            return error_response(
                safe_error_message(e, "endpoint performance"),
                500,
                code="ENDPOINT_PERFORMANCE_ERROR",
            )

    def _get_health_summary(self, query_params: dict) -> HandlerResult:
        """GET /api/analytics/endpoints/health - Overall API health summary."""
        try:
            endpoints = _metrics_store.get_all_endpoints()

            if not endpoints:
                return json_response(
                    {
                        "status": "unknown",
                        "message": "No endpoint metrics available",
                        "total_endpoints": 0,
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                    }
                )

            # Calculate overall metrics
            total_requests = sum(e.total_requests for e in endpoints)
            total_errors = sum(e.error_count for e in endpoints)
            overall_error_rate = (total_errors / total_requests * 100) if total_requests > 0 else 0

            # Average latencies
            all_latencies = [e.p95_latency_ms for e in endpoints if e.p95_latency_ms > 0]
            avg_p95_latency = statistics.mean(all_latencies) if all_latencies else 0

            # Determine health status
            if overall_error_rate > 5 or avg_p95_latency > 2000:
                status = "degraded"
            elif overall_error_rate > 1 or avg_p95_latency > 500:
                status = "warning"
            else:
                status = "healthy"

            # Count endpoints by health
            healthy_count = sum(1 for e in endpoints if e.error_rate < 1 and e.p95_latency_ms < 500)
            warning_count = sum(
                1 for e in endpoints if 1 <= e.error_rate < 5 or 500 <= e.p95_latency_ms < 2000
            )
            degraded_count = sum(
                1 for e in endpoints if e.error_rate >= 5 or e.p95_latency_ms >= 2000
            )

            return json_response(
                {
                    "status": status,
                    "summary": {
                        "total_endpoints": len(endpoints),
                        "total_requests": total_requests,
                        "total_errors": total_errors,
                        "overall_error_rate_percent": round(overall_error_rate, 2),
                        "avg_p95_latency_ms": round(avg_p95_latency, 2),
                    },
                    "endpoint_health": {
                        "healthy": healthy_count,
                        "warning": warning_count,
                        "degraded": degraded_count,
                    },
                    "thresholds": {
                        "error_rate_warning": "1%",
                        "error_rate_degraded": "5%",
                        "latency_warning_ms": 500,
                        "latency_degraded_ms": 2000,
                    },
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
            )

        except (TypeError, ValueError, KeyError, AttributeError) as e:
            logger.exception("Error getting health summary: %s", e)
            return error_response(
                safe_error_message(e, "health summary"),
                500,
                code="HEALTH_SUMMARY_ERROR",
            )


__all__ = [
    "EndpointAnalyticsHandler",
    "EndpointMetrics",
    "EndpointMetricsStore",
    "get_metrics_store",
    "record_endpoint_request",
]
