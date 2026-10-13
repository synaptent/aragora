"""
Metrics package for Aragora observability.

This package provides Prometheus metrics for monitoring request rates, latencies,
agent performance, and debate statistics.

Usage:
    from aragora.observability.metrics import record_request, record_agent_call

    # Record a request
    record_request("GET", "/api/debates", 200, 0.05)

    # Record an agent call
    record_agent_call("claude", success=True, latency=1.2)

Requirements:
    pip install prometheus-client

Environment Variables:
    METRICS_ENABLED: Set to "true" to enable metrics (default: true)
    METRICS_PORT: Port for /metrics endpoint (default: 9090)
"""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)

_initialized = False
_metrics_server: int | None = None

# =============================================================================
# Base utilities
# =============================================================================

from aragora.observability.metrics.base import (
    NoOpMetric,
    get_metrics_enabled,
    ensure_metrics_initialized,
    normalize_endpoint,
)

# =============================================================================
# Core initialization and server
# =============================================================================

from aragora.observability.metrics.core import (
    init_core_metrics,
    is_initialized,
    reset_initialization,
    _normalize_endpoint,
)

# =============================================================================
# Request metrics
# =============================================================================

from aragora.observability.metrics.request import (
    init_request_metrics,
    record_request,
    record_latency,
    measure_latency,
    measure_async_latency,
    REQUEST_COUNT,
    REQUEST_LATENCY,
)

# =============================================================================
# Agent metrics
# =============================================================================

from aragora.observability.metrics.agent import (
    init_agent_metrics,
    record_agent_call,
    record_agent_latency,
    record_agent_error,
    record_token_usage,
    track_agent_call,
    record_fallback_activation,
    record_fallback_success,
    AGENT_CALLS,
    AGENT_LATENCY,
    AGENT_ERRORS,
    AGENT_TOKEN_USAGE,
    FALLBACK_ACTIVATIONS,
    FALLBACK_SUCCESS,
    FALLBACK_LATENCY,
)

# Per-provider agent metrics
from aragora.observability.metrics.agents import (
    # Enums
    CircuitBreakerState,
    ErrorType,
    TokenType,
    # Init
    init_agent_provider_metrics,
    # Recording functions
    record_provider_call,
    record_provider_latency,
    record_provider_token_usage,
    set_connection_pool_active,
    set_connection_pool_waiting,
    record_rate_limit_detected,
    record_fallback_triggered,
    record_fallback_chain_depth,
    set_circuit_breaker_state,
    record_circuit_breaker_state_change,
    record_circuit_breaker_rejection,
    # Context managers
    track_agent_provider_call,
    track_agent_provider_call_async,
    AgentCallTracker,
    # Decorators
    with_agent_provider_metrics,
    with_agent_provider_metrics_sync,
    # Metrics objects
    AGENT_PROVIDER_CALLS,
    AGENT_PROVIDER_LATENCY,
    AGENT_TOKEN_USAGE as AGENT_PROVIDER_TOKEN_USAGE,
    AGENT_CONNECTION_POOL_ACTIVE,
    AGENT_CONNECTION_POOL_WAITING,
    AGENT_RATE_LIMIT_DETECTED,
    AGENT_RATE_LIMIT_BACKOFF_SECONDS,
    AGENT_FALLBACK_CHAIN_DEPTH,
    AGENT_FALLBACK_TRIGGERED,
    AGENT_CIRCUIT_BREAKER_STATE,
    AGENT_CIRCUIT_BREAKER_STATE_CHANGES,
    AGENT_CIRCUIT_BREAKER_REJECTIONS,
    AGENT_MODEL_CALLS,
)

# =============================================================================
# Debate metrics
# =============================================================================

from aragora.observability.metrics.debate import (
    init_debate_metrics,
    record_debate_completion,
    record_phase_duration,
    record_agent_participation,
    record_slow_debate,
    record_slow_round,
    record_round_latency,
    set_active_debates,
    increment_active_debates,
    decrement_active_debates,
    set_consensus_rate,
    track_debate,
    track_phase,
    DEBATE_DURATION,
    DEBATE_ROUNDS,
    DEBATE_PHASE_DURATION,
    AGENT_PARTICIPATION,
    SLOW_DEBATES_TOTAL,
    SLOW_ROUNDS_TOTAL,
    DEBATE_ROUND_LATENCY,
    ACTIVE_DEBATES,
    CONSENSUS_RATE,
)

# =============================================================================
# System metrics
# =============================================================================

from aragora.observability.metrics.system import (
    init_system_metrics,
    track_websocket_connection,
    set_websocket_connections,
    increment_websocket_connections,
    decrement_websocket_connections,
    WEBSOCKET_CONNECTIONS,
)

# =============================================================================
# Custom/application metrics
# =============================================================================

from aragora.observability.metrics.custom import (
    init_custom_metrics,
    record_gauntlet_export,
    track_gauntlet_export,
    record_backup_operation,
    record_backup_verification,
    record_backup_restore,
    track_handler,
    GAUNTLET_EXPORTS_TOTAL,
    GAUNTLET_EXPORT_LATENCY,
    GAUNTLET_EXPORT_SIZE,
    BACKUP_DURATION,
    BACKUP_SIZE,
    BACKUP_SUCCESS,
    LAST_BACKUP_TIMESTAMP,
    BACKUP_VERIFICATION_DURATION,
    BACKUP_VERIFICATION_SUCCESS,
    BACKUP_RESTORE_SUCCESS,
)

# =============================================================================
# Cache metrics
# =============================================================================

from aragora.observability.metrics.cache import (
    init_cache_metrics,
    record_cache_hit,
    record_cache_miss,
    record_knowledge_cache_hit,
    record_knowledge_cache_miss,
    record_rlm_cache_hit,
    record_rlm_cache_miss,
    CACHE_HITS,
    CACHE_MISSES,
    KNOWLEDGE_CACHE_HITS,
    KNOWLEDGE_CACHE_MISSES,
    RLM_CACHE_HITS,
    RLM_CACHE_MISSES,
)

# =============================================================================
# Memory metrics
# =============================================================================

from aragora.observability.metrics.memory import (
    init_memory_metrics,
    record_memory_operation,
    record_memory_coordinator_write,
    record_adaptive_round_change,
    MEMORY_OPERATIONS,
    MEMORY_COORDINATOR_WRITES,
    ADAPTIVE_ROUND_CHANGES,
)

# =============================================================================
# Convergence metrics
# =============================================================================

from aragora.observability.metrics.convergence import (
    init_convergence_metrics,
    record_convergence_check,
    record_process_evaluation_bonus,
    record_rlm_ready_quorum,
    CONVERGENCE_CHECKS_TOTAL,
    PROCESS_EVALUATION_BONUSES,
    RLM_READY_QUORUM_EVENTS,
)

# =============================================================================
# TTS metrics
# =============================================================================

from aragora.observability.metrics.tts import (
    init_tts_metrics,
    record_tts_synthesis,
    record_tts_latency,
    track_tts_synthesis,
    TTS_SYNTHESIS_TOTAL,
    TTS_SYNTHESIS_LATENCY,
)

# =============================================================================
# Workflow metrics
# =============================================================================

from aragora.observability.metrics.workflow import (
    init_workflow_metrics,
    record_workflow_trigger,
    record_workflow_template_created,
    record_workflow_template_execution,
    track_workflow_template_execution,
    WORKFLOW_TRIGGERS,
    WORKFLOW_TEMPLATES_CREATED,
    WORKFLOW_TEMPLATE_EXECUTIONS,
    WORKFLOW_TEMPLATE_EXECUTION_LATENCY,
)

# =============================================================================
# Evidence metrics
# =============================================================================

from aragora.observability.metrics.evidence import (
    init_evidence_metrics,
    record_evidence_stored,
    record_evidence_citation_bonus,
    record_culture_patterns,
    EVIDENCE_STORED,
    EVIDENCE_CITATION_BONUSES,
    CULTURE_PATTERNS,
)

# =============================================================================
# Ranking metrics
# =============================================================================

from aragora.observability.metrics.ranking import (
    init_ranking_metrics,
    record_calibration_adjustment,
    record_learning_bonus,
    record_voting_accuracy_update,
    record_selection_feedback_adjustment,
    record_performance_routing_decision,
    record_performance_routing_latency,
    track_performance_routing,
    record_novelty_score_calculation,
    record_novelty_penalty,
    record_echo_chamber_detection,
    record_relationship_bias_adjustment,
    record_rlm_selection_recommendation,
    record_calibration_cost_calculation,
    record_budget_filtering_event,
    record_outcome_complexity_adjustment,
    record_analytics_selection_recommendation,
    CALIBRATION_ADJUSTMENTS,
    LEARNING_BONUSES,
    VOTING_ACCURACY_UPDATES,
    SELECTION_FEEDBACK_ADJUSTMENTS,
    PERFORMANCE_ROUTING_DECISIONS,
    PERFORMANCE_ROUTING_LATENCY,
    NOVELTY_SCORE_CALCULATIONS,
    NOVELTY_PENALTIES,
    ECHO_CHAMBER_DETECTIONS,
    RELATIONSHIP_BIAS_ADJUSTMENTS,
    RLM_SELECTION_RECOMMENDATIONS,
    CALIBRATION_COST_CALCULATIONS,
    BUDGET_FILTERING_EVENTS,
    OUTCOME_COMPLEXITY_ADJUSTMENTS,
    ANALYTICS_SELECTION_RECOMMENDATIONS,
)

# =============================================================================
# Bridge metrics
# =============================================================================

from aragora.observability.metrics.bridge import (
    init_bridge_metrics,
    record_bridge_sync,
    record_bridge_sync_latency,
    record_bridge_error,
    track_bridge_sync,
    BRIDGE_SYNCS,
    BRIDGE_SYNC_LATENCY,
    BRIDGE_ERRORS,
)

# =============================================================================
# Knowledge Mound metrics
# =============================================================================

from aragora.observability.metrics.km import (
    init_km_metrics,
    record_km_operation,
    record_km_cache_access,
    set_km_health_status,
    record_km_adapter_sync,
    record_km_federated_query,
    record_km_event_emitted,
    set_km_active_adapters,
    sync_km_metrics_to_prometheus,
)

# =============================================================================
# Consensus metrics
# =============================================================================

from aragora.observability.metrics.consensus import (
    init_consensus_metrics,
    init_enhanced_consensus_metrics,
    record_consensus_ingestion,
    record_consensus_dissent,
    record_consensus_evolution,
    record_consensus_evidence_linked,
    record_consensus_agreement_ratio,
)

# =============================================================================
# Task queue metrics
# =============================================================================

from aragora.observability.metrics.task_queue import (
    init_task_queue_metrics,
    record_task_queue_operation,
    set_task_queue_size,
    record_task_queue_recovery,
    record_task_queue_cleanup,
    track_task_queue_operation,
)

# =============================================================================
# Governance metrics
# =============================================================================

from aragora.observability.metrics.governance import (
    init_governance_metrics,
    record_governance_decision,
    record_governance_verification,
    record_governance_approval,
    record_governance_store_latency,
    set_governance_artifacts_active,
    track_governance_store_operation,
)

# =============================================================================
# User mapping metrics
# =============================================================================

from aragora.observability.metrics.user_mapping import (
    init_user_mapping_metrics,
    record_user_mapping_operation,
    record_user_mapping_cache_hit,
    record_user_mapping_cache_miss,
    set_user_mappings_active,
)

# =============================================================================
# Checkpoint metrics
# =============================================================================

from aragora.observability.metrics.checkpoint import (
    init_checkpoint_metrics,
    record_checkpoint_operation,
    record_checkpoint_restore_result,
    track_checkpoint_operation,
)

# =============================================================================
# Notification metrics
# =============================================================================

from aragora.observability.metrics.notification import (
    init_notification_metrics,
    record_notification_sent,
    record_notification_error,
    set_notification_queue_size,
    track_notification_delivery,
)

# =============================================================================
# Marketplace metrics
# =============================================================================

from aragora.observability.metrics.marketplace import (
    init_marketplace_metrics,
    set_marketplace_templates_count,
    record_marketplace_download,
    record_marketplace_rating,
    record_marketplace_review,
    record_marketplace_operation_latency,
    track_marketplace_operation,
)

# =============================================================================
# Explainability metrics
# =============================================================================

from aragora.observability.metrics.explainability import (
    init_explainability_metrics,
    set_batch_explainability_jobs_active,
    record_batch_explainability_job,
    record_batch_explainability_debate,
    record_batch_explainability_error,
    track_batch_explainability_debate,
)

# =============================================================================
# Security metrics
# =============================================================================

from aragora.observability.metrics.security import (
    init_security_metrics,
    record_encryption_operation,
    record_encryption_error,
    track_encryption_operation,
    record_rbac_decision,
    track_rbac_evaluation,
    record_migration_record,
    record_migration_error,
)

# Alias for backward compatibility
record_rbac_check = record_rbac_decision
track_rbac_check = track_rbac_evaluation

# =============================================================================
# Webhook metrics
# =============================================================================

from aragora.observability.metrics.webhook import (
    record_webhook_delivery,
    record_webhook_retry,
    set_queue_size as set_webhook_queue_size,
    set_active_endpoints as set_webhook_active_endpoints,
    WebhookDeliveryTimer,
    track_webhook_delivery,
)

# =============================================================================
# SLO metrics
# =============================================================================

from aragora.observability.metrics.slo import (
    init_slo_metrics,
    record_slo_check,
    record_slo_violation,
    record_operation_latency,
    check_and_record_slo,
    track_operation_slo,
    get_slo_metrics_summary,
)

# =============================================================================
# Fabric metrics
# =============================================================================

from aragora.observability.metrics.fabric import (
    init_fabric_metrics,
    set_agents_active as set_fabric_agents_active,
    set_agents_health as set_fabric_agents_health,
    record_agent_spawned as record_fabric_agent_spawned,
    record_agent_terminated as record_fabric_agent_terminated,
    record_task_queued as record_fabric_task_queued,
    record_task_completed as record_fabric_task_completed,
    record_task_cancelled as record_fabric_task_cancelled,
    set_task_queue_depth as set_fabric_task_queue_depth,
    record_policy_decision as record_fabric_policy_decision,
    set_pending_approvals as set_fabric_pending_approvals,
    set_budget_usage as set_fabric_budget_usage,
    record_budget_alert as record_fabric_budget_alert,
    record_fabric_stats,
    track_fabric_task,
)


# =============================================================================
# Convenience function for KM inbound events
# =============================================================================


def record_km_inbound_event(event_type: str, source: str, success: bool = True) -> None:
    """Record an inbound event to Knowledge Mound."""
    record_km_operation("ingest", success, 0.0)
    record_km_event_emitted(f"inbound_{event_type}")


# =============================================================================
# Convenience wrapper functions for webhook metrics (compatibility layer)
# =============================================================================


def record_webhook_failure(endpoint: str, error_type: str) -> None:
    """Record a webhook delivery failure."""
    record_webhook_delivery(
        event_type=endpoint,
        success=False,
        duration_seconds=0.0,
        status_code=500 if error_type == "connection_error" else 400,
    )


def set_webhook_circuit_breaker_state(endpoint: str, state: str) -> None:
    """Set the circuit breaker state for a webhook endpoint."""
    # No-op for now - webhook module doesn't have this metric
    pass


# =============================================================================
# Compatibility initialization helpers
# =============================================================================


def _metrics_modules():
    from . import agent as agent_module
    from . import agents as agents_module
    from . import bridge as bridge_module
    from . import cache as cache_module
    from . import checkpoint as checkpoint_module
    from . import consensus as consensus_module
    from . import convergence as convergence_module
    from . import custom as custom_module
    from . import debate as debate_module
    from . import evidence as evidence_module
    from . import explainability as explainability_module
    from . import fabric as fabric_module
    from . import governance as governance_module
    from . import km as km_module
    from . import marketplace as marketplace_module
    from . import memory as memory_module
    from . import notification as notification_module
    from . import ranking as ranking_module
    from . import request as request_module
    from . import security as security_module
    from . import slo as slo_module
    from . import system as system_module
    from . import task_queue as task_queue_module
    from . import tts as tts_module
    from . import user_mapping as user_mapping_module
    from . import webhook as webhook_module
    from . import workflow as workflow_module

    return [
        request_module,
        agent_module,
        agents_module,
        debate_module,
        system_module,
        custom_module,
        cache_module,
        memory_module,
        convergence_module,
        tts_module,
        workflow_module,
        evidence_module,
        ranking_module,
        bridge_module,
        km_module,
        consensus_module,
        task_queue_module,
        governance_module,
        user_mapping_module,
        checkpoint_module,
        notification_module,
        marketplace_module,
        explainability_module,
        security_module,
        webhook_module,
        slo_module,
        fabric_module,
    ]


def _refresh_exports() -> None:
    """Refresh exported symbols to point at the latest module state."""
    export_names = set(__all__)
    modules = _metrics_modules()
    for module in modules:
        for name in export_names:
            if hasattr(module, name):
                globals()[name] = getattr(module, name)


def _init_noop_metrics() -> None:
    """Initialize NoOp metrics across all submodules."""
    global _initialized
    modules = _metrics_modules()
    for module in modules:
        init_noop = getattr(module, "_init_noop_metrics", None)
        if callable(init_noop):
            init_noop()
        if hasattr(module, "_initialized"):
            module._initialized = True
    _initialized = True
    _refresh_exports()


def _init_metrics() -> bool:
    """Initialize metrics with Prometheus if available."""
    global _initialized
    if _initialized:
        return get_metrics_enabled()
    enabled = ensure_metrics_initialized()
    _initialized = True
    _refresh_exports()
    return enabled


def start_metrics_server(port: int = 9090) -> bool:
    """Start the Prometheus metrics HTTP server."""
    global _metrics_server
    if not get_metrics_enabled():
        logger.warning("Metrics not enabled, server not started")
        return False
    if _metrics_server is not None:
        logger.warning("Metrics server already running")
        return True
    try:
        from prometheus_client import start_http_server

        start_http_server(port)
        _metrics_server = port
        try:
            from aragora.observability.metrics import server as _server

            _server._metrics_server = port
        except (ImportError, AttributeError, RuntimeError) as e:
            logger.debug("Could not sync metrics server state to submodule: %s", e)
        logger.info("Metrics server started on port %s", port)
        return True
    except ImportError as e:
        logger.error(
            "Failed to start metrics server: prometheus-client not installed",
            extra={"error": str(e)},
        )
        return False
    except OSError as e:
        logger.error(
            "Failed to start metrics server due to OS error",
            extra={"port": port, "error_type": type(e).__name__, "error": str(e)},
        )
        return False
    except (ValueError, TypeError, RuntimeError) as e:
        logger.error(
            "Failed to start metrics server due to configuration error",
            extra={"port": port, "error_type": type(e).__name__, "error": str(e)},
        )
        return False


def stop_metrics_server() -> bool:
    """Stop the Prometheus metrics server (marks as stopped)."""
    global _metrics_server
    if _metrics_server is None:
        return False
    port = _metrics_server
    _metrics_server = None
    try:
        from aragora.observability.metrics import server as _server

        _server._metrics_server = None
    except (ImportError, AttributeError, RuntimeError) as e:
        logger.debug("Could not sync metrics server shutdown to submodule: %s", e)
    logger.info("Metrics server on port %s marked for shutdown", port)
    return True


def is_metrics_server_running() -> bool:
    """Check if the metrics server is running."""
    return _metrics_server is not None


def get_metrics_server_port() -> int | None:
    """Get the metrics server port if running."""
    return _metrics_server


# =============================================================================
# Explicit exports
# =============================================================================

__all__ = [
    # Base
    "NoOpMetric",
    "get_metrics_enabled",
    "ensure_metrics_initialized",
    "normalize_endpoint",
    "_init_metrics",
    "_init_noop_metrics",
    # Core
    "init_core_metrics",
    "is_initialized",
    "reset_initialization",
    "_normalize_endpoint",
    # Server
    "start_metrics_server",
    "stop_metrics_server",
    "is_metrics_server_running",
    "get_metrics_server_port",
    # Request
    "init_request_metrics",
    "record_request",
    "record_latency",
    "measure_latency",
    "measure_async_latency",
    "REQUEST_COUNT",
    "REQUEST_LATENCY",
    # Agent
    "init_agent_metrics",
    "record_agent_call",
    "record_agent_latency",
    "record_agent_error",
    "record_token_usage",
    "track_agent_call",
    "record_fallback_activation",
    "record_fallback_success",
    "AGENT_CALLS",
    "AGENT_LATENCY",
    "AGENT_ERRORS",
    "AGENT_TOKEN_USAGE",
    "FALLBACK_ACTIVATIONS",
    "FALLBACK_SUCCESS",
    "FALLBACK_LATENCY",
    # Agent providers
    "CircuitBreakerState",
    "ErrorType",
    "TokenType",
    "init_agent_provider_metrics",
    "record_provider_call",
    "record_provider_latency",
    "record_provider_token_usage",
    "set_connection_pool_active",
    "set_connection_pool_waiting",
    "record_rate_limit_detected",
    "record_fallback_triggered",
    "record_fallback_chain_depth",
    "set_circuit_breaker_state",
    "record_circuit_breaker_state_change",
    "record_circuit_breaker_rejection",
    "track_agent_provider_call",
    "track_agent_provider_call_async",
    "AgentCallTracker",
    "with_agent_provider_metrics",
    "with_agent_provider_metrics_sync",
    "AGENT_PROVIDER_CALLS",
    "AGENT_PROVIDER_LATENCY",
    "AGENT_PROVIDER_TOKEN_USAGE",
    "AGENT_CONNECTION_POOL_ACTIVE",
    "AGENT_CONNECTION_POOL_WAITING",
    "AGENT_RATE_LIMIT_DETECTED",
    "AGENT_RATE_LIMIT_BACKOFF_SECONDS",
    "AGENT_FALLBACK_CHAIN_DEPTH",
    "AGENT_FALLBACK_TRIGGERED",
    "AGENT_CIRCUIT_BREAKER_STATE",
    "AGENT_CIRCUIT_BREAKER_STATE_CHANGES",
    "AGENT_CIRCUIT_BREAKER_REJECTIONS",
    "AGENT_MODEL_CALLS",
    # Debate
    "init_debate_metrics",
    "record_debate_completion",
    "record_phase_duration",
    "record_agent_participation",
    "record_slow_debate",
    "record_slow_round",
    "record_round_latency",
    "set_active_debates",
    "increment_active_debates",
    "decrement_active_debates",
    "set_consensus_rate",
    "track_debate",
    "track_phase",
    "DEBATE_DURATION",
    "DEBATE_ROUNDS",
    "DEBATE_PHASE_DURATION",
    "AGENT_PARTICIPATION",
    "SLOW_DEBATES_TOTAL",
    "SLOW_ROUNDS_TOTAL",
    "DEBATE_ROUND_LATENCY",
    "ACTIVE_DEBATES",
    "CONSENSUS_RATE",
    # System
    "init_system_metrics",
    "track_websocket_connection",
    "set_websocket_connections",
    "increment_websocket_connections",
    "decrement_websocket_connections",
    "WEBSOCKET_CONNECTIONS",
    # Custom
    "init_custom_metrics",
    "record_gauntlet_export",
    "track_gauntlet_export",
    "record_backup_operation",
    "record_backup_verification",
    "record_backup_restore",
    "track_handler",
    "GAUNTLET_EXPORTS_TOTAL",
    "GAUNTLET_EXPORT_LATENCY",
    "GAUNTLET_EXPORT_SIZE",
    "BACKUP_DURATION",
    "BACKUP_SIZE",
    "BACKUP_SUCCESS",
    "LAST_BACKUP_TIMESTAMP",
    "BACKUP_VERIFICATION_DURATION",
    "BACKUP_VERIFICATION_SUCCESS",
    "BACKUP_RESTORE_SUCCESS",
    # Cache
    "init_cache_metrics",
    "record_cache_hit",
    "record_cache_miss",
    "record_knowledge_cache_hit",
    "record_knowledge_cache_miss",
    "record_rlm_cache_hit",
    "record_rlm_cache_miss",
    "CACHE_HITS",
    "CACHE_MISSES",
    "KNOWLEDGE_CACHE_HITS",
    "KNOWLEDGE_CACHE_MISSES",
    "RLM_CACHE_HITS",
    "RLM_CACHE_MISSES",
    # Memory
    "init_memory_metrics",
    "record_memory_operation",
    "record_memory_coordinator_write",
    "record_adaptive_round_change",
    "MEMORY_OPERATIONS",
    "MEMORY_COORDINATOR_WRITES",
    "ADAPTIVE_ROUND_CHANGES",
    # Convergence
    "init_convergence_metrics",
    "record_convergence_check",
    "record_process_evaluation_bonus",
    "record_rlm_ready_quorum",
    "CONVERGENCE_CHECKS_TOTAL",
    "PROCESS_EVALUATION_BONUSES",
    "RLM_READY_QUORUM_EVENTS",
    # TTS
    "init_tts_metrics",
    "record_tts_synthesis",
    "record_tts_latency",
    "track_tts_synthesis",
    "TTS_SYNTHESIS_TOTAL",
    "TTS_SYNTHESIS_LATENCY",
    # Workflow
    "init_workflow_metrics",
    "record_workflow_trigger",
    "record_workflow_template_created",
    "record_workflow_template_execution",
    "track_workflow_template_execution",
    "WORKFLOW_TRIGGERS",
    "WORKFLOW_TEMPLATES_CREATED",
    "WORKFLOW_TEMPLATE_EXECUTIONS",
    "WORKFLOW_TEMPLATE_EXECUTION_LATENCY",
    # Evidence
    "init_evidence_metrics",
    "record_evidence_stored",
    "record_evidence_citation_bonus",
    "record_culture_patterns",
    "EVIDENCE_STORED",
    "EVIDENCE_CITATION_BONUSES",
    "CULTURE_PATTERNS",
    # Ranking
    "init_ranking_metrics",
    "record_calibration_adjustment",
    "record_learning_bonus",
    "record_voting_accuracy_update",
    "record_selection_feedback_adjustment",
    "record_performance_routing_decision",
    "record_performance_routing_latency",
    "track_performance_routing",
    "record_novelty_score_calculation",
    "record_novelty_penalty",
    "record_echo_chamber_detection",
    "record_relationship_bias_adjustment",
    "record_rlm_selection_recommendation",
    "record_calibration_cost_calculation",
    "record_budget_filtering_event",
    "record_outcome_complexity_adjustment",
    "record_analytics_selection_recommendation",
    "CALIBRATION_ADJUSTMENTS",
    "LEARNING_BONUSES",
    "VOTING_ACCURACY_UPDATES",
    "SELECTION_FEEDBACK_ADJUSTMENTS",
    "PERFORMANCE_ROUTING_DECISIONS",
    "PERFORMANCE_ROUTING_LATENCY",
    "NOVELTY_SCORE_CALCULATIONS",
    "NOVELTY_PENALTIES",
    "ECHO_CHAMBER_DETECTIONS",
    "RELATIONSHIP_BIAS_ADJUSTMENTS",
    "RLM_SELECTION_RECOMMENDATIONS",
    "CALIBRATION_COST_CALCULATIONS",
    "BUDGET_FILTERING_EVENTS",
    "OUTCOME_COMPLEXITY_ADJUSTMENTS",
    "ANALYTICS_SELECTION_RECOMMENDATIONS",
    # Bridge
    "init_bridge_metrics",
    "record_bridge_sync",
    "record_bridge_sync_latency",
    "record_bridge_error",
    "track_bridge_sync",
    "BRIDGE_SYNCS",
    "BRIDGE_SYNC_LATENCY",
    "BRIDGE_ERRORS",
    # KM
    "init_km_metrics",
    "record_km_operation",
    "record_km_cache_access",
    "set_km_health_status",
    "record_km_adapter_sync",
    "record_km_federated_query",
    "record_km_event_emitted",
    "set_km_active_adapters",
    "sync_km_metrics_to_prometheus",
    "record_km_inbound_event",
    # Consensus
    "init_consensus_metrics",
    "init_enhanced_consensus_metrics",
    "record_consensus_ingestion",
    "record_consensus_dissent",
    "record_consensus_evolution",
    "record_consensus_evidence_linked",
    "record_consensus_agreement_ratio",
    # Task queue
    "init_task_queue_metrics",
    "record_task_queue_operation",
    "set_task_queue_size",
    "record_task_queue_recovery",
    "record_task_queue_cleanup",
    "track_task_queue_operation",
    # Governance
    "init_governance_metrics",
    "record_governance_decision",
    "record_governance_verification",
    "record_governance_approval",
    "record_governance_store_latency",
    "set_governance_artifacts_active",
    "track_governance_store_operation",
    # User mapping
    "init_user_mapping_metrics",
    "record_user_mapping_operation",
    "record_user_mapping_cache_hit",
    "record_user_mapping_cache_miss",
    "set_user_mappings_active",
    # Checkpoint
    "init_checkpoint_metrics",
    "record_checkpoint_operation",
    "record_checkpoint_restore_result",
    "track_checkpoint_operation",
    # Notification
    "init_notification_metrics",
    "record_notification_sent",
    "record_notification_error",
    "set_notification_queue_size",
    "track_notification_delivery",
    # Marketplace
    "init_marketplace_metrics",
    "set_marketplace_templates_count",
    "record_marketplace_download",
    "record_marketplace_rating",
    "record_marketplace_review",
    "record_marketplace_operation_latency",
    "track_marketplace_operation",
    # Explainability
    "init_explainability_metrics",
    "set_batch_explainability_jobs_active",
    "record_batch_explainability_job",
    "record_batch_explainability_debate",
    "record_batch_explainability_error",
    "track_batch_explainability_debate",
    # Security
    "init_security_metrics",
    "record_encryption_operation",
    "record_encryption_error",
    "track_encryption_operation",
    "record_rbac_decision",
    "record_rbac_check",
    "track_rbac_evaluation",
    "track_rbac_check",
    "record_migration_record",
    "record_migration_error",
    # Webhook
    "record_webhook_delivery",
    "record_webhook_failure",
    "record_webhook_retry",
    "set_webhook_queue_size",
    "set_webhook_active_endpoints",
    "set_webhook_circuit_breaker_state",
    "WebhookDeliveryTimer",
    "track_webhook_delivery",
    # SLO
    "init_slo_metrics",
    "record_slo_check",
    "record_slo_violation",
    "record_operation_latency",
    "check_and_record_slo",
    "track_operation_slo",
    "get_slo_metrics_summary",
    # Fabric
    "init_fabric_metrics",
    "set_fabric_agents_active",
    "set_fabric_agents_health",
    "record_fabric_agent_spawned",
    "record_fabric_agent_terminated",
    "record_fabric_task_queued",
    "record_fabric_task_completed",
    "record_fabric_task_cancelled",
    "set_fabric_task_queue_depth",
    "record_fabric_policy_decision",
    "set_fabric_pending_approvals",
    "set_fabric_budget_usage",
    "record_fabric_budget_alert",
    "record_fabric_stats",
    "track_fabric_task",
    # Backward compatibility
    "_init_metrics",
    "_init_noop_metrics",
]


# Register module alias for compatibility with metrics.base
sys.modules.setdefault("_aragora_metrics_impl", sys.modules[__name__])


# =============================================================================
# Backward compatibility shims
# =============================================================================


def _init_metrics() -> bool:  # type: ignore[no-redef]
    """Initialize metrics (backward compatibility shim).

    This function is provided for backward compatibility with tests
    that expect the old metrics API. Modern code should use
    init_core_metrics() instead.

    Returns:
        True if initialization succeeded, False otherwise.
    """
    try:
        init_core_metrics()
        return True
    except (ImportError, ValueError, RuntimeError):
        return False


def _init_noop_metrics() -> bool:  # type: ignore[no-redef]
    """Initialize no-op metrics (backward compatibility shim).

    No-op metrics are always available (they don't require prometheus_client).

    Returns:
        True since no-op metrics are always available.
    """
    return True
