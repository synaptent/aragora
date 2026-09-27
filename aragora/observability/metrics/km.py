"""
Knowledge Mound metrics.

Provides Prometheus metrics for tracking Knowledge Mound operations,
cache performance, adapter syncs, and health status.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from aragora.observability.metrics.base import NoOpMetric, get_metrics_enabled

logger = logging.getLogger(__name__)

# Global metric variables
KM_OPERATIONS_TOTAL: Any = None
KM_OPERATION_LATENCY: Any = None
KM_CACHE_HITS_TOTAL: Any = None
KM_CACHE_MISSES_TOTAL: Any = None
KM_HEALTH_STATUS: Any = None
KM_ADAPTER_SYNCS_TOTAL: Any = None
KM_FEDERATED_QUERIES_TOTAL: Any = None
KM_EVENTS_EMITTED_TOTAL: Any = None
KM_ACTIVE_ADAPTERS: Any = None

# Control Plane integration metrics
KM_CP_TASK_OUTCOMES_TOTAL: Any = None
KM_CP_CAPABILITY_RECORDS_TOTAL: Any = None
KM_CP_CROSS_WORKSPACE_SHARES_TOTAL: Any = None
KM_CP_RECOMMENDATIONS_TOTAL: Any = None

# Bidirectional flow metrics
KM_FORWARD_SYNC_LATENCY: Any = None
KM_REVERSE_QUERY_LATENCY: Any = None
KM_SEMANTIC_SEARCH_TOTAL: Any = None
KM_VALIDATION_FEEDBACK_TOTAL: Any = None
KM_CROSS_DEBATE_REUSE_TOTAL: Any = None
KM_LARA_ROUTING_TOTAL: Any = None

# Calibration fusion metrics (Phase A3)
KM_CALIBRATION_FUSIONS_TOTAL: Any = None
KM_CALIBRATION_CONSENSUS_STRENGTH: Any = None
KM_CALIBRATION_AGREEMENT_RATIO: Any = None
KM_CALIBRATION_OUTLIERS_DETECTED: Any = None

_initialized = False
_km_health_provider: Callable[[], int] | None = None


def register_km_health_provider(provider: Callable[[], int] | None) -> None:
    """Register the knowledge-side provider for the current KM health gauge."""
    global _km_health_provider
    _km_health_provider = provider


def init_km_metrics() -> None:
    """Initialize Knowledge Mound metrics."""
    global _initialized
    global KM_OPERATIONS_TOTAL, KM_OPERATION_LATENCY
    global KM_CACHE_HITS_TOTAL, KM_CACHE_MISSES_TOTAL
    global KM_HEALTH_STATUS, KM_ADAPTER_SYNCS_TOTAL
    global KM_FEDERATED_QUERIES_TOTAL, KM_EVENTS_EMITTED_TOTAL
    global KM_ACTIVE_ADAPTERS
    # Control Plane metrics
    global KM_CP_TASK_OUTCOMES_TOTAL, KM_CP_CAPABILITY_RECORDS_TOTAL
    global KM_CP_CROSS_WORKSPACE_SHARES_TOTAL, KM_CP_RECOMMENDATIONS_TOTAL
    # Bidirectional flow metrics
    global KM_FORWARD_SYNC_LATENCY, KM_REVERSE_QUERY_LATENCY
    global KM_SEMANTIC_SEARCH_TOTAL, KM_VALIDATION_FEEDBACK_TOTAL
    global KM_CROSS_DEBATE_REUSE_TOTAL
    global KM_LARA_ROUTING_TOTAL
    # Calibration fusion metrics
    global KM_CALIBRATION_FUSIONS_TOTAL, KM_CALIBRATION_CONSENSUS_STRENGTH
    global KM_CALIBRATION_AGREEMENT_RATIO, KM_CALIBRATION_OUTLIERS_DETECTED

    if _initialized:
        return

    if not get_metrics_enabled():
        _init_noop_metrics()
        _initialized = True
        return

    try:
        from prometheus_client import Counter, Gauge, Histogram

        KM_OPERATIONS_TOTAL = Counter(
            "aragora_km_operations_total",
            "Total Knowledge Mound operations",
            ["operation", "status"],
        )

        KM_OPERATION_LATENCY = Histogram(
            "aragora_km_operation_latency_seconds",
            "Knowledge Mound operation latency",
            ["operation"],
            buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
        )

        KM_CACHE_HITS_TOTAL = Counter(
            "aragora_km_cache_hits_total",
            "Knowledge Mound cache hits",
            ["adapter"],
        )

        KM_CACHE_MISSES_TOTAL = Counter(
            "aragora_km_cache_misses_total",
            "Knowledge Mound cache misses",
            ["adapter"],
        )

        KM_HEALTH_STATUS = Gauge(
            "aragora_km_health_status",
            "Knowledge Mound health status (0=unknown, 1=unhealthy, 2=degraded, 3=healthy)",
        )

        KM_ADAPTER_SYNCS_TOTAL = Counter(
            "aragora_km_adapter_syncs_total",
            "Knowledge Mound adapter sync operations",
            ["adapter", "direction", "status"],
        )

        KM_FEDERATED_QUERIES_TOTAL = Counter(
            "aragora_km_federated_queries_total",
            "Knowledge Mound federated query operations",
            ["adapters_queried", "status"],
        )

        KM_EVENTS_EMITTED_TOTAL = Counter(
            "aragora_km_events_emitted_total",
            "Knowledge Mound WebSocket events emitted",
            ["event_type"],
        )

        KM_ACTIVE_ADAPTERS = Gauge(
            "aragora_km_active_adapters",
            "Number of active Knowledge Mound adapters",
        )

        # Control Plane integration metrics
        KM_CP_TASK_OUTCOMES_TOTAL = Counter(
            "aragora_km_cp_task_outcomes_total",
            "Task outcomes stored via Control Plane adapter",
            ["task_type", "success"],
        )

        KM_CP_CAPABILITY_RECORDS_TOTAL = Counter(
            "aragora_km_cp_capability_records_total",
            "Capability records stored via Control Plane adapter",
            ["capability"],
        )

        KM_CP_CROSS_WORKSPACE_SHARES_TOTAL = Counter(
            "aragora_km_cp_cross_workspace_shares_total",
            "Cross-workspace insights shared via Control Plane adapter",
            ["source_workspace"],
        )

        KM_CP_RECOMMENDATIONS_TOTAL = Counter(
            "aragora_km_cp_recommendations_total",
            "Agent recommendations queried from Control Plane adapter",
            ["capability"],
        )

        # Bidirectional flow metrics
        KM_FORWARD_SYNC_LATENCY = Histogram(
            "aragora_km_forward_sync_latency_seconds",
            "Forward sync latency (source → KM)",
            ["adapter"],
            buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
        )

        KM_REVERSE_QUERY_LATENCY = Histogram(
            "aragora_km_reverse_query_latency_seconds",
            "Reverse query latency (KM → consumer)",
            ["adapter"],
            buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
        )

        KM_SEMANTIC_SEARCH_TOTAL = Counter(
            "aragora_km_semantic_search_total",
            "Semantic search operations by adapter",
            ["adapter", "status"],
        )

        KM_VALIDATION_FEEDBACK_TOTAL = Counter(
            "aragora_km_validation_feedback_total",
            "Validation feedback events (positive/negative)",
            ["adapter", "feedback_type"],
        )

        KM_CROSS_DEBATE_REUSE_TOTAL = Counter(
            "aragora_km_cross_debate_reuse_total",
            "Knowledge items reused across debates",
            ["source_type"],
        )

        KM_LARA_ROUTING_TOTAL = Counter(
            "aragora_km_lara_routing_total",
            "LaRA routing decisions by route",
            ["route"],
        )

        # Calibration fusion metrics (Phase A3)
        KM_CALIBRATION_FUSIONS_TOTAL = Counter(
            "aragora_km_calibration_fusions_total",
            "Total calibration fusion operations",
            ["strategy", "status"],
        )

        KM_CALIBRATION_CONSENSUS_STRENGTH = Histogram(
            "aragora_km_calibration_consensus_strength",
            "Distribution of calibration consensus strength",
            buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
        )

        KM_CALIBRATION_AGREEMENT_RATIO = Histogram(
            "aragora_km_calibration_agreement_ratio",
            "Distribution of calibration agreement ratios",
            buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
        )

        KM_CALIBRATION_OUTLIERS_DETECTED = Counter(
            "aragora_km_calibration_outliers_detected_total",
            "Total outliers detected in calibration fusions",
        )

        _initialized = True
        logger.debug("Knowledge Mound metrics initialized")

    except (ImportError, ValueError):
        _init_noop_metrics()
        _initialized = True


def _init_noop_metrics() -> None:
    """Initialize no-op metrics when Prometheus is disabled."""
    global KM_OPERATIONS_TOTAL, KM_OPERATION_LATENCY
    global KM_CACHE_HITS_TOTAL, KM_CACHE_MISSES_TOTAL
    global KM_HEALTH_STATUS, KM_ADAPTER_SYNCS_TOTAL
    global KM_FEDERATED_QUERIES_TOTAL, KM_EVENTS_EMITTED_TOTAL
    global KM_ACTIVE_ADAPTERS
    # Control Plane metrics
    global KM_CP_TASK_OUTCOMES_TOTAL, KM_CP_CAPABILITY_RECORDS_TOTAL
    global KM_CP_CROSS_WORKSPACE_SHARES_TOTAL, KM_CP_RECOMMENDATIONS_TOTAL
    # Bidirectional flow metrics
    global KM_FORWARD_SYNC_LATENCY, KM_REVERSE_QUERY_LATENCY
    global KM_SEMANTIC_SEARCH_TOTAL, KM_VALIDATION_FEEDBACK_TOTAL
    global KM_CROSS_DEBATE_REUSE_TOTAL
    global KM_LARA_ROUTING_TOTAL
    # Calibration fusion metrics
    global KM_CALIBRATION_FUSIONS_TOTAL, KM_CALIBRATION_CONSENSUS_STRENGTH
    global KM_CALIBRATION_AGREEMENT_RATIO, KM_CALIBRATION_OUTLIERS_DETECTED

    KM_OPERATIONS_TOTAL = NoOpMetric()
    KM_OPERATION_LATENCY = NoOpMetric()
    KM_CACHE_HITS_TOTAL = NoOpMetric()
    KM_CACHE_MISSES_TOTAL = NoOpMetric()
    KM_HEALTH_STATUS = NoOpMetric()
    KM_ADAPTER_SYNCS_TOTAL = NoOpMetric()
    KM_FEDERATED_QUERIES_TOTAL = NoOpMetric()
    KM_EVENTS_EMITTED_TOTAL = NoOpMetric()
    KM_ACTIVE_ADAPTERS = NoOpMetric()
    # Control Plane metrics
    KM_CP_TASK_OUTCOMES_TOTAL = NoOpMetric()
    KM_CP_CAPABILITY_RECORDS_TOTAL = NoOpMetric()
    KM_CP_CROSS_WORKSPACE_SHARES_TOTAL = NoOpMetric()
    KM_CP_RECOMMENDATIONS_TOTAL = NoOpMetric()
    # Bidirectional flow metrics
    KM_FORWARD_SYNC_LATENCY = NoOpMetric()
    KM_REVERSE_QUERY_LATENCY = NoOpMetric()
    KM_SEMANTIC_SEARCH_TOTAL = NoOpMetric()
    KM_VALIDATION_FEEDBACK_TOTAL = NoOpMetric()
    KM_CROSS_DEBATE_REUSE_TOTAL = NoOpMetric()
    KM_LARA_ROUTING_TOTAL = NoOpMetric()
    # Calibration fusion metrics
    KM_CALIBRATION_FUSIONS_TOTAL = NoOpMetric()
    KM_CALIBRATION_CONSENSUS_STRENGTH = NoOpMetric()
    KM_CALIBRATION_AGREEMENT_RATIO = NoOpMetric()
    KM_CALIBRATION_OUTLIERS_DETECTED = NoOpMetric()


def _ensure_init() -> None:
    """Ensure metrics are initialized."""
    if not _initialized:
        init_km_metrics()


# =============================================================================
# Recording Functions
# =============================================================================


def record_km_operation(operation: str, success: bool, latency_seconds: float) -> None:
    """Record a Knowledge Mound operation.

    Args:
        operation: Operation type (query, store, get, delete, sync)
        success: Whether the operation succeeded
        latency_seconds: Operation latency in seconds
    """
    _ensure_init()
    status = "success" if success else "error"
    KM_OPERATIONS_TOTAL.labels(operation=operation, status=status).inc()
    KM_OPERATION_LATENCY.labels(operation=operation).observe(latency_seconds)


def record_lara_route(route: str) -> None:
    """Record a LaRA routing decision."""
    _ensure_init()
    KM_LARA_ROUTING_TOTAL.labels(route=route).inc()


def record_km_cache_access(hit: bool, adapter: str = "global") -> None:
    """Record a Knowledge Mound cache access.

    Args:
        hit: Whether it was a cache hit
        adapter: Adapter name or "global" for general cache
    """
    _ensure_init()
    if hit:
        KM_CACHE_HITS_TOTAL.labels(adapter=adapter).inc()
    else:
        KM_CACHE_MISSES_TOTAL.labels(adapter=adapter).inc()


def set_km_health_status(status: int) -> None:
    """Set the Knowledge Mound health status.

    Args:
        status: Health status (0=unknown, 1=unhealthy, 2=degraded, 3=healthy)
    """
    _ensure_init()
    KM_HEALTH_STATUS.set(status)


def record_km_adapter_sync(adapter: str, direction: str, success: bool) -> None:
    """Record a Knowledge Mound adapter sync operation.

    Args:
        adapter: Adapter name (continuum, consensus, elo, etc.)
        direction: Sync direction (forward, reverse)
        success: Whether the sync succeeded
    """
    _ensure_init()
    status = "success" if success else "error"
    KM_ADAPTER_SYNCS_TOTAL.labels(adapter=adapter, direction=direction, status=status).inc()


def record_km_federated_query(adapters_queried: int, success: bool) -> None:
    """Record a federated query operation.

    Args:
        adapters_queried: Number of adapters queried
        success: Whether the query succeeded
    """
    _ensure_init()
    status = "success" if success else "error"
    KM_FEDERATED_QUERIES_TOTAL.labels(adapters_queried=str(adapters_queried), status=status).inc()


def record_km_event_emitted(event_type: str) -> None:
    """Record a Knowledge Mound WebSocket event emission.

    Args:
        event_type: Event type (km_batch, knowledge_indexed, etc.)
    """
    _ensure_init()
    KM_EVENTS_EMITTED_TOTAL.labels(event_type=event_type).inc()


def set_km_active_adapters(count: int) -> None:
    """Set the number of active Knowledge Mound adapters.

    Args:
        count: Number of active adapters
    """
    _ensure_init()
    KM_ACTIVE_ADAPTERS.set(count)


# =============================================================================
# Control Plane Recording Functions
# =============================================================================


def record_cp_task_outcome(task_type: str, success: bool) -> None:
    """Record a Control Plane task outcome stored in KM.

    Args:
        task_type: Type of task (debate, code_review, etc.)
        success: Whether the task succeeded
    """
    _ensure_init()
    KM_CP_TASK_OUTCOMES_TOTAL.labels(task_type=task_type, success=str(success).lower()).inc()


def record_cp_capability_record(capability: str) -> None:
    """Record a Control Plane capability record stored in KM.

    Args:
        capability: Capability name
    """
    _ensure_init()
    KM_CP_CAPABILITY_RECORDS_TOTAL.labels(capability=capability).inc()


def record_cp_cross_workspace_share(source_workspace: str) -> None:
    """Record a cross-workspace insight share.

    Args:
        source_workspace: Source workspace ID
    """
    _ensure_init()
    KM_CP_CROSS_WORKSPACE_SHARES_TOTAL.labels(source_workspace=source_workspace).inc()


def record_cp_recommendation_query(capability: str) -> None:
    """Record a Control Plane recommendation query.

    Args:
        capability: Capability queried
    """
    _ensure_init()
    KM_CP_RECOMMENDATIONS_TOTAL.labels(capability=capability).inc()


# =============================================================================
# Bidirectional Flow Recording Functions
# =============================================================================


def record_forward_sync_latency(adapter: str, latency_seconds: float) -> None:
    """Record forward sync latency (source → KM).

    Args:
        adapter: Adapter name
        latency_seconds: Sync latency in seconds
    """
    _ensure_init()
    KM_FORWARD_SYNC_LATENCY.labels(adapter=adapter).observe(latency_seconds)


def record_reverse_query_latency(adapter: str, latency_seconds: float) -> None:
    """Record reverse query latency (KM → consumer).

    Args:
        adapter: Adapter name
        latency_seconds: Query latency in seconds
    """
    _ensure_init()
    KM_REVERSE_QUERY_LATENCY.labels(adapter=adapter).observe(latency_seconds)


def record_semantic_search(adapter: str, success: bool) -> None:
    """Record a semantic search operation.

    Args:
        adapter: Adapter name
        success: Whether the search succeeded
    """
    _ensure_init()
    status = "success" if success else "error"
    KM_SEMANTIC_SEARCH_TOTAL.labels(adapter=adapter, status=status).inc()


def record_validation_feedback(adapter: str, positive: bool) -> None:
    """Record validation feedback for a KM item.

    Args:
        adapter: Adapter name
        positive: Whether feedback is positive
    """
    _ensure_init()
    feedback_type = "positive" if positive else "negative"
    KM_VALIDATION_FEEDBACK_TOTAL.labels(adapter=adapter, feedback_type=feedback_type).inc()


def record_cross_debate_reuse(source_type: str) -> None:
    """Record when knowledge is reused across debates.

    Args:
        source_type: Type of source (consensus, insight, crux, etc.)
    """
    _ensure_init()
    KM_CROSS_DEBATE_REUSE_TOTAL.labels(source_type=source_type).inc()


# =============================================================================
# Calibration Fusion Recording Functions (Phase A3)
# =============================================================================


def record_calibration_fusion(
    strategy: str,
    success: bool,
    consensus_strength: float,
    agreement_ratio: float,
    outlier_count: int,
) -> None:
    """Record a calibration fusion operation with metrics.

    Args:
        strategy: Fusion strategy used (weighted_average, median, etc.)
        success: Whether the fusion succeeded
        consensus_strength: Consensus strength (0-1)
        agreement_ratio: Agent agreement ratio (0-1)
        outlier_count: Number of outliers detected
    """
    _ensure_init()
    status = "success" if success else "error"
    KM_CALIBRATION_FUSIONS_TOTAL.labels(strategy=strategy, status=status).inc()
    KM_CALIBRATION_CONSENSUS_STRENGTH.observe(consensus_strength)
    KM_CALIBRATION_AGREEMENT_RATIO.observe(agreement_ratio)
    if outlier_count > 0:
        for _ in range(outlier_count):
            KM_CALIBRATION_OUTLIERS_DETECTED.inc()


def sync_km_metrics_to_prometheus() -> None:
    """Sync KMMetrics to Prometheus metrics.

    Reads the current state from the global KMMetrics instance and
    updates Prometheus metrics accordingly. Call this periodically
    (e.g., every 30 seconds) to keep Prometheus in sync.
    """
    _ensure_init()

    if _km_health_provider is None:
        logger.debug("KM health provider not available for Prometheus sync")
        return

    try:
        set_km_health_status(_km_health_provider())
    except Exception as e:  # noqa: BLE001 - fire-and-forget telemetry sync
        logger.warning("Failed to sync KM metrics to Prometheus: %s", e)


__all__ = [
    # Core Metrics
    "KM_OPERATIONS_TOTAL",
    "KM_OPERATION_LATENCY",
    "KM_CACHE_HITS_TOTAL",
    "KM_CACHE_MISSES_TOTAL",
    "KM_HEALTH_STATUS",
    "KM_ADAPTER_SYNCS_TOTAL",
    "KM_FEDERATED_QUERIES_TOTAL",
    "KM_EVENTS_EMITTED_TOTAL",
    "KM_ACTIVE_ADAPTERS",
    # Control Plane Metrics
    "KM_CP_TASK_OUTCOMES_TOTAL",
    "KM_CP_CAPABILITY_RECORDS_TOTAL",
    "KM_CP_CROSS_WORKSPACE_SHARES_TOTAL",
    "KM_CP_RECOMMENDATIONS_TOTAL",
    # Bidirectional Flow Metrics
    "KM_FORWARD_SYNC_LATENCY",
    "KM_REVERSE_QUERY_LATENCY",
    "KM_SEMANTIC_SEARCH_TOTAL",
    "KM_VALIDATION_FEEDBACK_TOTAL",
    "KM_CROSS_DEBATE_REUSE_TOTAL",
    # Calibration Fusion Metrics (Phase A3)
    "KM_CALIBRATION_FUSIONS_TOTAL",
    "KM_CALIBRATION_CONSENSUS_STRENGTH",
    "KM_CALIBRATION_AGREEMENT_RATIO",
    "KM_CALIBRATION_OUTLIERS_DETECTED",
    # Core Recording Functions
    "record_km_operation",
    "record_km_cache_access",
    "set_km_health_status",
    "record_km_adapter_sync",
    "record_km_federated_query",
    "record_km_event_emitted",
    "set_km_active_adapters",
    "register_km_health_provider",
    "sync_km_metrics_to_prometheus",
    "init_km_metrics",
    # Control Plane Recording Functions
    "record_cp_task_outcome",
    "record_cp_capability_record",
    "record_cp_cross_workspace_share",
    "record_cp_recommendation_query",
    # Bidirectional Flow Recording Functions
    "record_forward_sync_latency",
    "record_reverse_query_latency",
    "record_semantic_search",
    "record_validation_feedback",
    "record_cross_debate_reuse",
    # Calibration Fusion Recording Functions
    "record_calibration_fusion",
]
