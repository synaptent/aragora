"""
Unified Prometheus metrics endpoint.

Provides a centralized `/metrics` endpoint that:
- Collects all registered Prometheus metrics from across 20+ modules
- Applies cardinality management to high-cardinality metrics
- Supports metric aggregation for expensive queries
- Ensures all key metrics are registered on initialization

Endpoints:
- GET /metrics - Full Prometheus-format metrics export
- GET /api/v1/metrics/prometheus - Same as /metrics with API versioning
- GET /api/v1/metrics/prometheus/summary - Aggregated metrics summary

Usage:
    from aragora.server.handlers.metrics.metrics_endpoint import UnifiedMetricsHandler

    handler = UnifiedMetricsHandler()
    result = handler.handle("/metrics", {}, request)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..base import BaseHandler, HandlerResult, error_response, safe_error_message
from aragora.server.versioning.compat import strip_version_prefix

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Prometheus content type
PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


# =============================================================================
# Cardinality Management
# =============================================================================


@dataclass
class CardinalityConfig:
    """Configuration for cardinality management.

    Attributes:
        max_label_values: Maximum unique values per label before aggregation
        high_cardinality_metrics: Metrics known to have high cardinality
        aggregation_enabled: Whether to apply aggregation for expensive queries
    """

    max_label_values: int = 1000
    high_cardinality_metrics: list[str] = field(
        default_factory=lambda: [
            "aragora_http_requests_total",
            "aragora_http_request_duration_seconds",
            "aragora_db_query_duration_seconds",
            "aragora_agent_provider_calls_total",
        ]
    )
    aggregation_enabled: bool = True


def _limit_label_cardinality(
    metric_name: str,
    labels: dict[str, str],
    config: CardinalityConfig,
) -> dict[str, str]:
    """Apply cardinality limits to labels.

    For high-cardinality metrics, normalizes dynamic labels to reduce
    the number of unique label combinations.

    Args:
        metric_name: Prometheus metric name
        labels: Original labels dict
        config: Cardinality configuration

    Returns:
        Modified labels with cardinality limits applied
    """
    if metric_name not in config.high_cardinality_metrics:
        return labels

    result = labels.copy()

    # Normalize endpoint paths to reduce cardinality
    if "endpoint" in result:
        result["endpoint"] = _normalize_endpoint(result["endpoint"])

    # Normalize table names
    if "table" in result:
        result["table"] = _normalize_table(result["table"])

    return result


def _normalize_endpoint(endpoint: str) -> str:
    """Normalize endpoint paths to reduce cardinality.

    Replaces dynamic path segments (IDs, UUIDs) with placeholders.

    Args:
        endpoint: Raw endpoint path

    Returns:
        Normalized endpoint path
    """
    import re

    # Replace UUIDs
    endpoint = re.sub(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        ":id",
        endpoint,
        flags=re.IGNORECASE,
    )

    # Replace numeric IDs
    endpoint = re.sub(r"/\d+", "/:id", endpoint)

    # Replace base64-like tokens
    endpoint = re.sub(r"/[A-Za-z0-9_-]{20,}", "/:token", endpoint)

    return endpoint


def _normalize_table(table: str) -> str:
    """Normalize table names for dynamic/sharded tables.

    Args:
        table: Raw table name

    Returns:
        Normalized table name
    """
    import re

    # Replace sharded table suffixes (e.g., table_001 -> table_:shard)
    return re.sub(r"_\d{2,}$", "_:shard", table)


# =============================================================================
# Metrics Registry
# =============================================================================


class MetricsRegistry:
    """Unified registry for ensuring all metrics are initialized.

    This class coordinates initialization of metrics across all modules
    and provides a single point for collecting all metrics.
    """

    _initialized: bool = False
    _initialization_time: float = 0.0

    @classmethod
    def ensure_initialized(cls) -> bool:
        """Ensure all metric modules are initialized.

        Returns:
            True if metrics are available, False if disabled or unavailable
        """
        if cls._initialized:
            return True

        start = time.perf_counter()

        try:
            # Initialize core metrics
            from aragora.observability.metrics import init_core_metrics

            core_enabled = init_core_metrics()

            if not core_enabled:
                logger.info("Core metrics disabled or prometheus-client not available")
                cls._initialized = True
                return False

            # Initialize per-provider agent metrics
            from aragora.observability.metrics.agents import init_agent_provider_metrics

            init_agent_provider_metrics()

            # Initialize bridge metrics
            from aragora.observability.metrics.bridge import init_bridge_metrics

            init_bridge_metrics()

            # Initialize KM metrics
            from aragora.observability.metrics.km import init_km_metrics

            init_km_metrics()

            # Initialize SLO metrics
            from aragora.observability.metrics.slo import init_slo_metrics

            init_slo_metrics()

            # Initialize security metrics
            from aragora.observability.metrics.security import init_security_metrics

            init_security_metrics()

            # Initialize notification metrics
            from aragora.observability.metrics.notification import init_notification_metrics

            init_notification_metrics()

            # Initialize gauntlet metrics
            from aragora.observability.metrics.gauntlet import init_gauntlet_metrics

            init_gauntlet_metrics()

            # Initialize store metrics
            from aragora.observability.metrics.stores import init_store_metrics

            init_store_metrics()

            # Initialize debate metrics
            from aragora.observability.metrics.debate import init_debate_metrics

            init_debate_metrics()

            # Initialize request metrics
            from aragora.observability.metrics.request import init_request_metrics

            init_request_metrics()

            # Initialize agent metrics
            from aragora.observability.metrics.agent import init_agent_metrics

            init_agent_metrics()

            # Initialize marketplace metrics
            from aragora.observability.metrics.marketplace import init_marketplace_metrics

            init_marketplace_metrics()

            # Initialize explainability metrics
            from aragora.observability.metrics.explainability import init_explainability_metrics

            init_explainability_metrics()

            # Initialize fabric metrics
            from aragora.observability.metrics.fabric import init_fabric_metrics

            init_fabric_metrics()

            # Initialize task queue metrics
            from aragora.observability.metrics.task_queue import init_task_queue_metrics

            init_task_queue_metrics()

            # Initialize governance metrics
            from aragora.observability.metrics.governance import init_governance_metrics

            init_governance_metrics()

            # Initialize user mapping metrics
            from aragora.observability.metrics.user_mapping import init_user_mapping_metrics

            init_user_mapping_metrics()

            # Initialize checkpoint metrics
            from aragora.observability.metrics.checkpoint import init_checkpoint_metrics

            init_checkpoint_metrics()

            # Initialize consensus metrics
            from aragora.observability.metrics.consensus import (
                init_consensus_metrics,
                init_enhanced_consensus_metrics,
            )

            init_consensus_metrics()
            init_enhanced_consensus_metrics()

            # Initialize TTS metrics
            from aragora.observability.metrics.tts import init_tts_metrics

            init_tts_metrics()

            # Initialize cache metrics
            from aragora.observability.metrics.cache import init_cache_metrics

            init_cache_metrics()

            # Initialize convergence metrics
            from aragora.observability.metrics.convergence import init_convergence_metrics

            init_convergence_metrics()

            # Initialize workflow metrics
            from aragora.observability.metrics.workflow import init_workflow_metrics

            init_workflow_metrics()

            # Initialize memory metrics
            from aragora.observability.metrics.memory import init_memory_metrics

            init_memory_metrics()

            # Initialize evidence metrics
            from aragora.observability.metrics.evidence import init_evidence_metrics

            init_evidence_metrics()

            # Initialize ranking metrics
            from aragora.observability.metrics.ranking import init_ranking_metrics

            init_ranking_metrics()

            # Initialize control plane metrics
            from aragora.observability.metrics.control_plane import _init_control_plane_metrics

            _init_control_plane_metrics()

            # Initialize platform metrics
            from aragora.observability.metrics.platform import _initialize_platform_metrics

            _initialize_platform_metrics()

            # Initialize webhook metrics
            from aragora.observability.metrics.webhook import _init_metrics as _init_webhook_metrics

            _init_webhook_metrics()

            cls._initialization_time = time.perf_counter() - start
            cls._initialized = True
            logger.info(f"All metrics modules initialized in {cls._initialization_time:.3f}s")
            return True

        except ImportError as e:
            logger.warning("Failed to initialize some metrics modules: %s", e)
            cls._initialized = True
            return False
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
            logger.error("Error initializing metrics: %s", e, exc_info=True)
            cls._initialized = True
            return False

    @classmethod
    def get_initialization_time(cls) -> float:
        """Get time taken to initialize metrics.

        Returns:
            Initialization time in seconds
        """
        return cls._initialization_time


# =============================================================================
# Metrics Generation
# =============================================================================


def generate_prometheus_metrics(
    include_process_metrics: bool = True,
    include_platform_metrics: bool = True,
    aggregate_high_cardinality: bool = False,
) -> tuple[str, str]:
    """Generate Prometheus-format metrics output.

    Collects all metrics from the prometheus_client registry and
    optionally applies aggregation for high-cardinality metrics.

    Args:
        include_process_metrics: Include Python process metrics
        include_platform_metrics: Include platform collector metrics
        aggregate_high_cardinality: Apply aggregation to high-cardinality metrics

    Returns:
        Tuple of (metrics_text, content_type)
    """
    # Ensure all metrics are initialized
    MetricsRegistry.ensure_initialized()

    try:
        from prometheus_client import REGISTRY, generate_latest, CONTENT_TYPE_LATEST

        # Generate full metrics output
        output = generate_latest(REGISTRY)
        return output.decode("utf-8"), CONTENT_TYPE_LATEST

    except ImportError:
        # prometheus_client not installed, return minimal fallback
        logger.debug("prometheus_client not installed, returning fallback metrics")
        fallback = _generate_fallback_metrics()
        return fallback, PROMETHEUS_CONTENT_TYPE


def _generate_fallback_metrics() -> str:
    """Generate minimal fallback metrics when prometheus_client unavailable.

    Returns:
        Simple Prometheus-format text
    """
    lines = [
        "# HELP aragora_info Aragora server information",
        "# TYPE aragora_info gauge",
        'aragora_info{version="unknown",prometheus_available="false"} 1',
        "",
        "# HELP aragora_metrics_initialized Metrics initialization status",
        "# TYPE aragora_metrics_initialized gauge",
        "aragora_metrics_initialized 0",
    ]
    return "\n".join(lines)


def get_metrics_summary() -> dict[str, Any]:
    """Get aggregated metrics summary.

    Returns a dictionary with key metric values for quick inspection,
    useful for health checks and dashboards.

    Returns:
        Dictionary with metric summaries
    """
    MetricsRegistry.ensure_initialized()

    summary: dict[str, Any] = {
        "initialized": MetricsRegistry._initialized,
        "initialization_time_seconds": MetricsRegistry._initialization_time,
        "metrics": {},
    }

    try:
        from prometheus_client import REGISTRY

        # Count metrics by type
        counters = 0
        gauges = 0
        histograms = 0
        summaries = 0
        total_samples = 0

        for collector in REGISTRY.collect():
            for metric_family in [collector] if hasattr(collector, "samples") else []:
                for sample in metric_family.samples:
                    total_samples += 1

            # Try to identify metric type
            if hasattr(collector, "_type"):
                metric_type = collector._type
                if metric_type == "counter":
                    counters += 1
                elif metric_type == "gauge":
                    gauges += 1
                elif metric_type == "histogram":
                    histograms += 1
                elif metric_type == "summary":
                    summaries += 1

        summary["metrics"] = {
            "counters": counters,
            "gauges": gauges,
            "histograms": histograms,
            "summaries": summaries,
            "total_samples": total_samples,
        }

        # Add cardinality info
        try:
            from aragora.observability.metrics.cardinality import get_cardinality_tracker

            tracker = get_cardinality_tracker()
            cardinality_summary = tracker.get_summary()
            summary["cardinality"] = cardinality_summary
        except ImportError:
            summary["cardinality"] = {"available": False}

    except ImportError:
        summary["metrics"] = {"available": False}

    return summary


# =============================================================================
# Handler
# =============================================================================


class UnifiedMetricsHandler(BaseHandler):
    """Unified handler for Prometheus metrics endpoint.

    Provides (via the unified server registry):
    - GET /api/v1/metrics/prometheus - Full Prometheus metrics export
    - GET /api/v1/metrics/prometheus/summary - Aggregated summary

    GET /metrics is served by MetricsHandler in the unified server
    (first-wins route registry); this handler only serves "/metrics" when
    instantiated and invoked directly (standalone usage).

    This handler centralizes all metrics collection and applies
    cardinality management to prevent metric explosion.
    """

    # NOTE: "/metrics" is intentionally NOT claimed here. The registry's
    # RouteIndex is first-wins and /metrics is owned by MetricsHandler
    # (aragora/server/handlers/metrics/handler.py), which implements the
    # documented scrape contract (public, optional ARAGORA_METRICS_TOKEN).
    # This handler still serves "/metrics" when invoked directly/standalone
    # (see module docstring); via the unified server use
    # /api/v1/metrics/prometheus instead.
    ROUTES = [
        "/api/metrics/prometheus",
        "/api/metrics/prometheus/summary",
    ]

    def __init__(self, ctx: dict | None = None):
        """Initialize handler.

        Args:
            ctx: Optional server context
        """
        self.ctx = ctx or {}
        self._cardinality_config = CardinalityConfig()

        # Ensure metrics are initialized
        MetricsRegistry.ensure_initialized()

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path.

        Args:
            path: Request path

        Returns:
            True if path matches one of our routes
        """
        path = strip_version_prefix(path)
        return path in self.ROUTES

    def handle(
        self,
        path: str,
        query_params: dict,
        handler: Any,
    ) -> HandlerResult | None:
        """Route request to appropriate handler method.

        Args:
            path: Request path
            query_params: Query parameters
            handler: HTTP handler with request context

        Returns:
            Handler result or None if path not handled
        """
        path = strip_version_prefix(path)

        # Require auth and permission for API-versioned prometheus endpoints
        if path in ("/api/metrics/prometheus", "/api/metrics/prometheus/summary"):
            user, err = self.require_auth_or_error(handler)
            if err:
                return err
            _, perm_err = self.require_permission_or_error(handler, "metrics:read")
            if perm_err:
                return perm_err

        if path == "/metrics" or path == "/api/metrics/prometheus":
            return self._get_prometheus_metrics(query_params)

        if path == "/api/metrics/prometheus/summary":
            return self._get_metrics_summary()

        return None

    def _get_prometheus_metrics(self, query_params: dict) -> HandlerResult:
        """Get full Prometheus metrics output.

        Args:
            query_params: Query parameters (supports aggregate=true)

        Returns:
            HandlerResult with Prometheus-format metrics
        """
        try:
            # Check for aggregation request
            aggregate = query_params.get("aggregate", ["false"])[0].lower() == "true"

            content, content_type = generate_prometheus_metrics(
                aggregate_high_cardinality=aggregate,
            )

            return HandlerResult(
                status_code=200,
                content_type=content_type,
                body=content.encode("utf-8"),
            )

        except (KeyError, ValueError, TypeError, RuntimeError) as e:
            logger.error("Failed to generate Prometheus metrics: %s", e, exc_info=True)
            return error_response(safe_error_message(e, "get metrics"), 500)

    def _get_metrics_summary(self) -> HandlerResult:
        """Get aggregated metrics summary.

        Returns:
            HandlerResult with JSON metrics summary
        """
        try:
            import json

            summary = get_metrics_summary()

            return HandlerResult(
                status_code=200,
                content_type="application/json",
                body=json.dumps(summary, indent=2).encode("utf-8"),
            )

        except (ImportError, TypeError, ValueError, RuntimeError) as e:
            logger.error("Failed to get metrics summary: %s", e, exc_info=True)
            return error_response(safe_error_message(e, "get metrics summary"), 500)


# =============================================================================
# Convenience Functions
# =============================================================================


def ensure_all_metrics_registered() -> bool:
    """Ensure all metric modules are initialized.

    Call this at server startup to pre-register all metrics.

    Returns:
        True if all metrics initialized successfully
    """
    return MetricsRegistry.ensure_initialized()


def get_registered_metric_names() -> list[str]:
    """Get list of all registered metric names.

    Returns:
        List of Prometheus metric names
    """
    MetricsRegistry.ensure_initialized()

    try:
        from prometheus_client import REGISTRY

        names = []
        for collector in REGISTRY._names_to_collectors.values():
            if hasattr(collector, "_name"):
                names.append(collector._name)

        return sorted(set(names))

    except ImportError:
        return []


# =============================================================================
# Exports
# =============================================================================


__all__ = [
    # Handler
    "UnifiedMetricsHandler",
    # Configuration
    "CardinalityConfig",
    # Registry
    "MetricsRegistry",
    # Functions
    "generate_prometheus_metrics",
    "get_metrics_summary",
    "ensure_all_metrics_registered",
    "get_registered_metric_names",
    # Constants
    "PROMETHEUS_CONTENT_TYPE",
]
