"""
Core recording functions for Aragora server Prometheus metrics.

Extracted from prometheus.py for maintainability.
Provides recording functions for debate, agent, HTTP, WebSocket, cache,
database, memory, cost, and V1 API deprecation metrics.
"""

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

from aragora.observability.prometheus_definitions import (
    PROMETHEUS_AVAILABLE,
    _simple_metrics,
)

if PROMETHEUS_AVAILABLE:
    from aragora.observability.prometheus_definitions import (
        AGENT_CIRCUIT_BREAKER,
        AGENT_FAILURES,
        AGENT_GENERATION_DURATION,
        BUDGET_UTILIZATION,
        CACHE_HITS,
        CACHE_MISSES,
        CACHE_SIZE,
        COST_PER_DEBATE,
        COST_USD_TOTAL,
        DB_CONNECTION_POOL_SIZE,
        DB_ERRORS_TOTAL,
        DB_QUERY_DURATION,
        DB_QUERY_TOTAL,
        DEBATE_DURATION,
        DEBATE_ROUNDS,
        DEBATE_TOKENS,
        DEBATES_TOTAL,
        EXTERNAL_AGENT_COST_TOTAL,
        EXTERNAL_AGENT_TASK_DURATION,
        EXTERNAL_AGENT_TASKS_TOTAL,
        EXTERNAL_AGENT_TOKENS_TOTAL,
        EXTERNAL_AGENT_TOOLS_BLOCKED,
        HTTP_REQUEST_DURATION,
        HTTP_REQUESTS_TOTAL,
        MEMORY_OPERATIONS,
        MEMORY_TIER_SIZE,
        MEMORY_TIER_TRANSITIONS,
        RATE_LIMIT_HITS,
        RATE_LIMIT_TOKENS_TRACKED,
        V1_API_DAYS_UNTIL_SUNSET,
        V1_API_REQUESTS,
        V1_API_SUNSET_BLOCKED,
        WEBSOCKET_CONNECTIONS,
        WEBSOCKET_MESSAGES,
        ARAGORA_INFO,
    )

_v1_sunset_days_provider: Callable[[], int] | None = None


def register_v1_sunset_days_provider(provider: Callable[[], int] | None) -> None:
    """Register the server-owned provider for the V1 sunset gauge value."""
    global _v1_sunset_days_provider
    _v1_sunset_days_provider = provider


# ============================================================================
# Debate Recording Functions
# ============================================================================


def record_debate_completed(
    duration_seconds: float,
    rounds_used: int,
    outcome: str,
    agent_count: int,
) -> None:
    """Record a completed debate."""
    if PROMETHEUS_AVAILABLE:
        DEBATE_DURATION.labels(outcome=outcome, agent_count=str(agent_count)).observe(
            duration_seconds
        )
        DEBATE_ROUNDS.labels(outcome=outcome).observe(rounds_used)
        DEBATES_TOTAL.labels(outcome=outcome).inc()
    else:
        _simple_metrics.observe_histogram(
            "aragora_debate_duration_seconds",
            duration_seconds,
            {"outcome": outcome, "agent_count": str(agent_count)},
        )
        _simple_metrics.inc_counter("aragora_debates_total", {"outcome": outcome})


def record_tokens_used(model: str, input_tokens: int, output_tokens: int) -> None:
    """Record token usage."""
    if PROMETHEUS_AVAILABLE:
        DEBATE_TOKENS.labels(model=model, direction="input").inc(input_tokens)
        DEBATE_TOKENS.labels(model=model, direction="output").inc(output_tokens)
    else:
        _simple_metrics.inc_counter(
            "aragora_debate_tokens_total",
            {"model": model, "direction": "input"},
            input_tokens,
        )
        _simple_metrics.inc_counter(
            "aragora_debate_tokens_total",
            {"model": model, "direction": "output"},
            output_tokens,
        )


# ============================================================================
# Cost Recording Functions
# ============================================================================


def record_cost_usd(provider: str, model: str, agent_id: str, cost_usd: float) -> None:
    """Record cost in USD (stored as micro-dollars for precision)."""
    micro_dollars = int(cost_usd * 1_000_000)
    if PROMETHEUS_AVAILABLE:
        COST_USD_TOTAL.labels(provider=provider, model=model, agent_id=agent_id).inc(micro_dollars)
    else:
        _simple_metrics.inc_counter(
            "aragora_cost_usd_total",
            {"provider": provider, "model": model, "agent_id": agent_id},
            micro_dollars,
        )


def record_debate_cost(provider: str, cost_usd: float) -> None:
    """Record cost for a completed debate."""
    micro_dollars = int(cost_usd * 1_000_000)
    if PROMETHEUS_AVAILABLE:
        COST_PER_DEBATE.labels(provider=provider).observe(micro_dollars)
    else:
        _simple_metrics.observe_histogram(
            "aragora_debate_cost_usd",
            micro_dollars,
            {"provider": provider},
        )


def set_budget_utilization(workspace_id: str, budget_type: str, utilization_percent: float) -> None:
    """Set current budget utilization percentage."""
    if PROMETHEUS_AVAILABLE:
        BUDGET_UTILIZATION.labels(workspace_id=workspace_id, budget_type=budget_type).set(
            utilization_percent
        )
    else:
        _simple_metrics.set_gauge(
            "aragora_budget_utilization_percent",
            utilization_percent,
            {"workspace_id": workspace_id, "budget_type": budget_type},
        )


# ============================================================================
# Agent Recording Functions
# ============================================================================


def record_agent_generation(agent_type: str, model: str, duration_seconds: float) -> None:
    """Record agent generation time."""
    if PROMETHEUS_AVAILABLE:
        AGENT_GENERATION_DURATION.labels(agent_type=agent_type, model=model).observe(
            duration_seconds
        )
    else:
        _simple_metrics.observe_histogram(
            "aragora_agent_generation_seconds",
            duration_seconds,
            {"agent_type": agent_type, "model": model},
        )


def record_agent_failure(agent_type: str, error_type: str) -> None:
    """Record an agent failure."""
    if PROMETHEUS_AVAILABLE:
        AGENT_FAILURES.labels(agent_type=agent_type, error_type=error_type).inc()
    else:
        _simple_metrics.inc_counter(
            "aragora_agent_failures_total",
            {"agent_type": agent_type, "error_type": error_type},
        )


def set_circuit_breaker_state(agent_type: str, state: int) -> None:
    """Set circuit breaker state (0=closed, 1=open, 2=half-open)."""
    if PROMETHEUS_AVAILABLE:
        AGENT_CIRCUIT_BREAKER.labels(agent_type=agent_type).set(state)
    else:
        _simple_metrics.set_gauge(
            "aragora_agent_circuit_breaker_state",
            state,
            {"agent_type": agent_type},
        )


def initialize_circuit_breaker_metrics() -> None:
    """Initialize circuit breaker metrics integration."""
    try:
        from aragora.resilience import set_metrics_callback

        set_metrics_callback(set_circuit_breaker_state)
        logger.info("Circuit breaker metrics integration initialized")
    except ImportError:
        logger.debug("Resilience module not available for metrics integration")


def export_circuit_breaker_metrics() -> None:
    """Export all circuit breaker states to Prometheus."""
    try:
        from aragora.resilience import get_circuit_breaker_metrics

        metrics = get_circuit_breaker_metrics()
        for name, cb_data in metrics.get("circuit_breakers", {}).items():
            status = cb_data.get("status", "closed")
            state_value = {"closed": 0, "open": 1, "half-open": 2}.get(status, 0)
            set_circuit_breaker_state(name, state_value)

            entity_mode = cb_data.get("entity_mode", {})
            for entity in entity_mode.get("open_entities", []):
                set_circuit_breaker_state(f"{name}:{entity}", 1)

    except ImportError:
        pass
    except (ValueError, TypeError, RuntimeError, AttributeError) as e:
        logger.debug("Error exporting circuit breaker metrics: %s", e)


# ============================================================================
# HTTP Recording Functions
# ============================================================================


def record_http_request(method: str, endpoint: str, status: int, duration_seconds: float) -> None:
    """Record an HTTP request."""
    if PROMETHEUS_AVAILABLE:
        HTTP_REQUEST_DURATION.labels(method=method, endpoint=endpoint, status=str(status)).observe(
            duration_seconds
        )
        HTTP_REQUESTS_TOTAL.labels(method=method, endpoint=endpoint, status=str(status)).inc()
    else:
        _simple_metrics.observe_histogram(
            "aragora_http_request_duration_seconds",
            duration_seconds,
            {"method": method, "endpoint": endpoint, "status": str(status)},
        )
        _simple_metrics.inc_counter(
            "aragora_http_requests_total",
            {"method": method, "endpoint": endpoint, "status": str(status)},
        )


# ============================================================================
# WebSocket Recording Functions
# ============================================================================


def set_websocket_connections(count: int) -> None:
    """Set active WebSocket connection count."""
    if PROMETHEUS_AVAILABLE:
        WEBSOCKET_CONNECTIONS.set(count)
    else:
        _simple_metrics.set_gauge("aragora_websocket_connections_active", count)


def record_websocket_message(direction: str, message_type: str) -> None:
    """Record a WebSocket message."""
    if PROMETHEUS_AVAILABLE:
        WEBSOCKET_MESSAGES.labels(direction=direction, message_type=message_type).inc()
    else:
        _simple_metrics.inc_counter(
            "aragora_websocket_messages_total",
            {"direction": direction, "message_type": message_type},
        )


# ============================================================================
# Rate Limit Recording Functions
# ============================================================================


def record_rate_limit_hit(limit_type: str) -> None:
    """Record a rate limit hit."""
    if PROMETHEUS_AVAILABLE:
        RATE_LIMIT_HITS.labels(limit_type=limit_type).inc()
    else:
        _simple_metrics.inc_counter("aragora_rate_limit_hits_total", {"limit_type": limit_type})


def set_rate_limit_tokens_tracked(count: int) -> None:
    """Set number of tokens being tracked for rate limiting."""
    if PROMETHEUS_AVAILABLE:
        RATE_LIMIT_TOKENS_TRACKED.set(count)
    else:
        _simple_metrics.set_gauge("aragora_rate_limit_tokens_tracked", count)


# ============================================================================
# Cache Recording Functions
# ============================================================================


def set_cache_size(cache_name: str, size: int) -> None:
    """Set cache size."""
    if PROMETHEUS_AVAILABLE:
        CACHE_SIZE.labels(cache_name=cache_name).set(size)
    else:
        _simple_metrics.set_gauge("aragora_cache_size_entries", size, {"cache_name": cache_name})


def record_cache_hit(cache_name: str) -> None:
    """Record a cache hit."""
    if PROMETHEUS_AVAILABLE:
        CACHE_HITS.labels(cache_name=cache_name).inc()
    else:
        _simple_metrics.inc_counter("aragora_cache_hits_total", {"cache_name": cache_name})


def record_cache_miss(cache_name: str) -> None:
    """Record a cache miss."""
    if PROMETHEUS_AVAILABLE:
        CACHE_MISSES.labels(cache_name=cache_name).inc()
    else:
        _simple_metrics.inc_counter("aragora_cache_misses_total", {"cache_name": cache_name})


# ============================================================================
# Server Info
# ============================================================================


def set_server_info(version: str, python_version: str, start_time: float) -> None:
    """Set server information."""
    if PROMETHEUS_AVAILABLE:
        ARAGORA_INFO.info(
            {
                "version": version,
                "python_version": python_version,
                "start_time": str(int(start_time)),
            }
        )
    else:
        _simple_metrics.set_info(
            "aragora",
            {
                "version": version,
                "python_version": python_version,
                "start_time": str(int(start_time)),
            },
        )


# ============================================================================
# Database Recording Functions
# ============================================================================


def record_db_query(operation: str, table: str, duration_seconds: float) -> None:
    """Record a database query."""
    if PROMETHEUS_AVAILABLE:
        DB_QUERY_DURATION.labels(operation=operation, table=table).observe(duration_seconds)
        DB_QUERY_TOTAL.labels(operation=operation, table=table).inc()
    else:
        _simple_metrics.observe_histogram(
            "aragora_db_query_duration_seconds",
            duration_seconds,
            {"operation": operation, "table": table},
        )
        _simple_metrics.inc_counter(
            "aragora_db_queries_total",
            {"operation": operation, "table": table},
        )


def record_db_error(error_type: str, operation: str) -> None:
    """Record a database error."""
    if PROMETHEUS_AVAILABLE:
        DB_ERRORS_TOTAL.labels(error_type=error_type, operation=operation).inc()
    else:
        _simple_metrics.inc_counter(
            "aragora_db_errors_total",
            {"error_type": error_type, "operation": operation},
        )


def set_db_pool_size(active: int, idle: int) -> None:
    """Set database connection pool sizes."""
    if PROMETHEUS_AVAILABLE:
        DB_CONNECTION_POOL_SIZE.labels(state="active").set(active)
        DB_CONNECTION_POOL_SIZE.labels(state="idle").set(idle)
    else:
        _simple_metrics.set_gauge("aragora_db_connection_pool_size", active, {"state": "active"})
        _simple_metrics.set_gauge("aragora_db_connection_pool_size", idle, {"state": "idle"})


# ============================================================================
# Memory Recording Functions
# ============================================================================


def set_memory_tier_size(tier: str, size: int) -> None:
    """Set the number of memories in a tier."""
    if PROMETHEUS_AVAILABLE:
        MEMORY_TIER_SIZE.labels(tier=tier).set(size)
    else:
        _simple_metrics.set_gauge("aragora_memory_tier_size", size, {"tier": tier})


def record_memory_tier_transition(from_tier: str, to_tier: str) -> None:
    """Record a memory tier transition."""
    if PROMETHEUS_AVAILABLE:
        MEMORY_TIER_TRANSITIONS.labels(from_tier=from_tier, to_tier=to_tier).inc()
    else:
        _simple_metrics.inc_counter(
            "aragora_memory_tier_transitions_total",
            {"from_tier": from_tier, "to_tier": to_tier},
        )


def record_memory_operation(operation: str) -> None:
    """Record a memory operation."""
    if PROMETHEUS_AVAILABLE:
        MEMORY_OPERATIONS.labels(operation=operation).inc()
    else:
        _simple_metrics.inc_counter(
            "aragora_memory_operations_total",
            {"operation": operation},
        )


# ============================================================================
# External Agent Gateway Recording Functions
# ============================================================================


def record_external_agent_task(adapter: str, status: str) -> None:
    """Record an external agent task event."""
    if PROMETHEUS_AVAILABLE:
        EXTERNAL_AGENT_TASKS_TOTAL.labels(adapter=adapter, status=status).inc()
    else:
        _simple_metrics.inc_counter(
            "aragora_external_agent_tasks_total",
            {"adapter": adapter, "status": status},
        )


def record_external_agent_duration(adapter: str, task_type: str, seconds: float) -> None:
    """Record external agent task duration."""
    if PROMETHEUS_AVAILABLE:
        EXTERNAL_AGENT_TASK_DURATION.labels(adapter=adapter, task_type=task_type).observe(seconds)
    else:
        _simple_metrics.observe_histogram(
            "aragora_external_agent_task_duration_seconds",
            seconds,
            {"adapter": adapter, "task_type": task_type},
        )


def record_external_agent_tokens(adapter: str, tokens: int) -> None:
    """Record tokens used by an external agent."""
    if PROMETHEUS_AVAILABLE:
        EXTERNAL_AGENT_TOKENS_TOTAL.labels(adapter=adapter).inc(tokens)
    else:
        _simple_metrics.inc_counter(
            "aragora_external_agent_tokens_total",
            {"adapter": adapter},
            tokens,
        )


def record_external_agent_tool_blocked(adapter: str, tool: str) -> None:
    """Record a blocked tool invocation."""
    if PROMETHEUS_AVAILABLE:
        EXTERNAL_AGENT_TOOLS_BLOCKED.labels(adapter=adapter, tool=tool).inc()
    else:
        _simple_metrics.inc_counter(
            "aragora_external_agent_tools_blocked_total",
            {"adapter": adapter, "tool": tool},
        )


def record_external_agent_cost(adapter: str, cost_usd: float) -> None:
    """Record cost for an external agent task (stored as micro-dollars)."""
    micro_dollars = int(cost_usd * 1_000_000)
    if PROMETHEUS_AVAILABLE:
        EXTERNAL_AGENT_COST_TOTAL.labels(adapter=adapter).inc(micro_dollars)
    else:
        _simple_metrics.inc_counter(
            "aragora_external_agent_cost_microdollars_total",
            {"adapter": adapter},
            micro_dollars,
        )


# ============================================================================
# V1 API Deprecation Recording Functions
# ============================================================================


def record_v1_api_request(endpoint: str, method: str) -> None:
    """Record a request to a deprecated V1 API endpoint."""
    if PROMETHEUS_AVAILABLE:
        V1_API_REQUESTS.labels(endpoint=endpoint, method=method).inc()
    else:
        _simple_metrics.inc_counter(
            "aragora_v1_api_requests_total",
            {"endpoint": endpoint, "method": method},
        )


def update_v1_days_until_sunset() -> None:
    """Update the gauge showing days until V1 API sunset."""
    if _v1_sunset_days_provider is None:
        return

    try:
        days = _v1_sunset_days_provider()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        logger.warning("Failed to collect registered V1 sunset days: %s", exc)
        return

    if PROMETHEUS_AVAILABLE:
        V1_API_DAYS_UNTIL_SUNSET.set(days)
    else:
        _simple_metrics.set_gauge("aragora_v1_api_days_until_sunset", days)


def record_v1_api_sunset_blocked(endpoint: str, method: str) -> None:
    """Record a request blocked due to V1 API sunset."""
    if PROMETHEUS_AVAILABLE:
        V1_API_SUNSET_BLOCKED.labels(endpoint=endpoint, method=method).inc()
    else:
        _simple_metrics.inc_counter(
            "aragora_v1_api_sunset_blocked_total",
            {"endpoint": endpoint, "method": method},
        )
