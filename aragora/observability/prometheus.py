"""
Prometheus metrics for Aragora server.

Provides OpenMetrics-compliant metrics for monitoring:
- Debate operations (latency, token usage, outcomes)
- Agent performance (generation time, failures)
- HTTP request metrics (latency per endpoint)
- WebSocket connections
- Rate limiter state
- Cache statistics

Architecture:
- prometheus_definitions.py: Metric objects and SimpleMetrics fallback
- prometheus_recording.py: Recording functions (record_*, set_*)
- prometheus_decorators.py: Timing decorators (@timed_http_request, etc.)
- prometheus.py: This file -- thin re-export layer for backward compatibility
"""

import logging

logger = logging.getLogger(__name__)

# ============================================================================
# Re-export metric definitions and constants
# ============================================================================

from aragora.observability.prometheus_definitions import *  # noqa: F401, F403, E402
from aragora.observability.prometheus_definitions import (  # noqa: F401, E402
    PROMETHEUS_AVAILABLE,
    CONTENT_TYPE_LATEST,
    SimpleMetrics,
    _simple_metrics,
)

# Make generate_latest and REGISTRY available if prometheus is installed
if PROMETHEUS_AVAILABLE:
    from prometheus_client import (  # noqa: F401
        REGISTRY,
        generate_latest,
    )


# ============================================================================
# Public API
# ============================================================================


def get_metrics_output() -> tuple[str, str]:
    """
    Get metrics in Prometheus format.

    Returns:
        Tuple of (content, content_type)
    """
    if PROMETHEUS_AVAILABLE:
        return generate_latest(REGISTRY).decode("utf-8"), CONTENT_TYPE_LATEST
    else:
        return _simple_metrics.generate_output(), CONTENT_TYPE_LATEST


def is_prometheus_available() -> bool:
    """Check if prometheus_client is installed."""
    return PROMETHEUS_AVAILABLE


def get_prometheus_metrics() -> str:
    """Get metrics text in Prometheus format."""
    content, _ = get_metrics_output()
    return content


# ============================================================================
# Recording Functions (delegated to prometheus_recording.py)
# ============================================================================

from aragora.observability.prometheus_recording import (  # noqa: F401, E402
    record_debate_completed,
    record_tokens_used,
    record_cost_usd,
    record_debate_cost,
    set_budget_utilization,
    record_agent_generation,
    record_agent_failure,
    set_circuit_breaker_state,
    initialize_circuit_breaker_metrics,
    export_circuit_breaker_metrics,
    record_http_request,
    set_websocket_connections,
    record_websocket_message,
    record_rate_limit_hit,
    set_rate_limit_tokens_tracked,
    set_cache_size,
    record_cache_hit,
    record_cache_miss,
    set_server_info,
    record_db_query,
    record_db_error,
    set_db_pool_size,
    set_memory_tier_size,
    record_memory_tier_transition,
    record_memory_operation,
    record_external_agent_task,
    record_external_agent_duration,
    record_external_agent_tokens,
    record_external_agent_tool_blocked,
    record_external_agent_cost,
    record_v1_api_request,
    update_v1_days_until_sunset,
    record_v1_api_sunset_blocked,
)

# ============================================================================
# Decorators (delegated to prometheus_decorators.py)
# ============================================================================

from aragora.observability.prometheus_decorators import (  # noqa: F401, E402
    timed_http_request,
    timed_agent_generation,
    timed_db_query,
    timed_db_query_async,
)


# ============================================================================
# Extracted domain-specific modules (import directly)
# ============================================================================
# Nomic metrics: aragora/server/prometheus_nomic.py
# Control Plane metrics: aragora/server/prometheus_control_plane.py
# RLM metrics: aragora/server/prometheus_rlm.py
# Knowledge metrics: aragora/server/prometheus_knowledge.py

__all__ = [
    # Core
    "PROMETHEUS_AVAILABLE",
    "SimpleMetrics",
    "_simple_metrics",
    "get_metrics_output",
    "is_prometheus_available",
    "get_prometheus_metrics",
    # Recording functions (from prometheus_recording)
    "record_debate_completed",
    "record_tokens_used",
    "record_cost_usd",
    "record_debate_cost",
    "set_budget_utilization",
    "record_agent_generation",
    "record_agent_failure",
    "set_circuit_breaker_state",
    "initialize_circuit_breaker_metrics",
    "export_circuit_breaker_metrics",
    "record_http_request",
    "set_websocket_connections",
    "record_websocket_message",
    "record_rate_limit_hit",
    "set_rate_limit_tokens_tracked",
    "set_cache_size",
    "record_cache_hit",
    "record_cache_miss",
    "set_server_info",
    "record_db_query",
    "record_db_error",
    "set_db_pool_size",
    "set_memory_tier_size",
    "record_memory_tier_transition",
    "record_memory_operation",
    "record_external_agent_task",
    "record_external_agent_duration",
    "record_external_agent_tokens",
    "record_external_agent_tool_blocked",
    "record_external_agent_cost",
    # Decorators (from prometheus_decorators)
    "timed_http_request",
    "timed_agent_generation",
    "timed_db_query",
    "timed_db_query_async",
    # V1 API Deprecation (from prometheus_recording)
    "record_v1_api_request",
    "update_v1_days_until_sunset",
    "record_v1_api_sunset_blocked",
]
