"""
Observability package for Aragora.

Provides structured logging, metrics, distributed tracing, and error tracking
for production deployments.

Usage:
    from aragora.observability import configure_logging, get_logger

    # Configure at startup
    configure_logging(environment="production", level="INFO")

    # Get a logger
    logger = get_logger(__name__)
    logger.info("debate_started", debate_id="123", agent_count=5)

Tracing:
    from aragora.observability import trace_handler, create_span, trace_debate_phase

    @trace_handler("debates.create")
    def handle_create_debate(self, handler):
        with create_span("validate_input"):
            ...

Metrics:
    from aragora.observability import record_request, record_agent_call, track_debate

    record_request("GET", "/api/debates", 200, 0.05)
    with track_debate():
        await arena.run()
"""

from __future__ import annotations

from aragora.observability.config import (
    MetricsConfig,
    TracingConfig,
    get_metrics_config,
    get_tracing_config,
    is_metrics_enabled,
    is_otlp_enabled,
    is_tracing_enabled,
)
from aragora.observability.otlp_export import (
    DEFAULT_ENDPOINTS,
    OTLPConfig,
    OTLPExporterType,
    configure_otlp_exporter,
    get_otlp_config,
    get_tracer_provider,
    reset_otlp_config,
    set_otlp_config,
    shutdown_otlp,
)

# Import logging APIs from observability.logging which has the canonical
# implementations with stable signatures (LogConfig, correlation helpers, etc).
import warnings as _warnings

with _warnings.catch_warnings():
    _warnings.simplefilter("ignore", DeprecationWarning)
    from aragora.observability.logging import (
        LogConfig,
        StructuredLogger,
        configure_logging,
        correlation_context,
        get_correlation_id,
        get_logger,
        set_correlation_id,
    )


from aragora.observability.metrics import (
    measure_async_latency,
    measure_latency,
    record_agent_call,
    record_agent_participation,
    record_cache_hit,
    record_cache_miss,
    record_debate_completion,
    record_memory_operation,
    record_phase_duration,
    record_request,
    set_consensus_rate,
    start_metrics_server,
    track_debate,
    track_phase,
    track_websocket_connection,
)
from aragora.observability.tracing import (
    add_span_attributes,
    build_trace_headers,
    create_span,
    get_tracer,
    record_exception,
    trace_agent_call,
    trace_async_handler,
    trace_consensus_check,
    trace_debate,
    trace_debate_phase,
    trace_decision,
    trace_decision_engine,
    trace_decision_routing,
    trace_handler,
    trace_memory_operation,
    trace_response_delivery,
    # New tracing utilities
    traced,
    AutoInstrumentation,
    instrument_all,
    trace_worker_job,
    trace_worker_batch,
    trace_external_call,
    trace_llm_call,
)
from aragora.observability.tracing import (
    shutdown as shutdown_tracing,
)
from aragora.observability.otel import (
    OTelConfig,
    OTLPHealthStatus,
    check_otlp_health,
    export_debate_span_to_otel,
    extract_context,
    get_otel_status,
    get_tracer as otel_get_tracer,
    inject_context,
    is_initialized as is_otel_initialized,
    record_span_error,
    reset_otel,
    set_span_ok,
    setup_otel,
    shutdown_otel,
    start_span,
    trace_agent_operation,
    trace_consensus_evaluation,
    trace_debate_lifecycle,
    trace_debate_round,
)
from aragora.observability.siem import (
    SIEMBackend,
    SIEMConfig,
    SecurityEventType,
    SecurityEvent,
    SIEMClient,
    get_siem_client,
    emit_security_event,
    emit_auth_event,
    emit_data_access_event,
    emit_privacy_event,
    shutdown_siem,
)
from aragora.observability.immutable_log import (
    ImmutableAuditLog,
    AuditEntry,
    AuditBackend,
    DailyAnchor,
    VerificationResult,
    LocalFileBackend,
    S3ObjectLockBackend,
    get_audit_log,
    init_audit_log,
    audit_finding_created,
    audit_finding_updated,
    audit_document_uploaded,
    audit_document_accessed,
    audit_session_started,
    audit_data_exported,
)
from aragora.observability.decision_metrics import (
    record_decision_request,
    record_decision_result,
    record_decision_error,
    record_decision_cache_hit,
    record_decision_cache_miss,
    record_decision_dedup_hit,
    track_decision,
    get_decision_metrics,
    get_decision_summary,
)
from aragora.observability.memory_profiler import (
    ConsensusMemoryProfiler,
    KMMemoryProfiler,
    MemoryCategory,
    MemoryGrowthTracker,
    MemoryProfiler,
    MemoryProfileResult,
    MemorySnapshot,
    consensus_profiler,
    km_profiler,
    profile_memory,
    track_memory,
)
from aragora.observability.n1_detector import (
    N1Detection,
    N1QueryDetector,
    N1QueryError,
    QueryRecord,
    detect_n1,
    get_current_detector,
    n1_detection_scope,
    record_query,
)
from aragora.observability.trace_correlation import (
    TraceContext,
    clear_traced_latency_samples,
    generate_exemplar_line,
    get_slow_traces,
    get_trace_context,
    get_traced_latency_samples,
    should_sample_trace_id,
    track_request_with_trace,
)
from aragora.observability.query_analyzer import (
    QueryPlanAnalyzer,
    QueryPlanIssue,
    SlowQuery,
    analyze_query,
    clear_slow_queries,
    get_analyzer,
    get_query_analysis_stats,
    get_slow_queries as get_slow_query_history,
)
from aragora.observability.slo_alert_bridge import (
    ActiveViolation,
    AlertChannel,
    AlertSeverity,
    SLOAlertBridge,
    SLOAlertConfig,
    get_slo_alert_bridge,
    init_slo_alerting,
    shutdown_slo_alerting,
)
from aragora.observability.alerting import (
    Alert,
    AlertManager,
    AlertRule,
    AlertState,
    AlertSeverity as AlertingSeverity,  # Alias to avoid conflict
    EmailNotificationChannel,
    MetricsCollector,
    MetricsSnapshot as AlertMetricsSnapshot,  # Alias to avoid conflict with memory_profiler
    PrometheusAlertManagerChannel,
    SlackNotificationChannel,
    create_critical_alert_rules,
    get_alert_manager,
    init_alerting,
    shutdown_alerting,
)

__all__ = [
    # Logging
    "configure_logging",
    "get_logger",
    "StructuredLogger",
    "LogContext",
    "LogConfig",
    "set_correlation_id",
    "get_correlation_id",
    "correlation_context",
    # Tracing
    "get_tracer",
    "create_span",
    "build_trace_headers",
    "trace_handler",
    "trace_async_handler",
    "trace_agent_call",
    "trace_debate",
    "trace_debate_phase",
    "trace_consensus_check",
    "trace_memory_operation",
    "trace_decision",
    "trace_decision_routing",
    "trace_decision_engine",
    "trace_response_delivery",
    "add_span_attributes",
    "record_exception",
    "shutdown_tracing",
    # New tracing utilities
    "traced",
    "AutoInstrumentation",
    "instrument_all",
    "trace_worker_job",
    "trace_worker_batch",
    "trace_external_call",
    "trace_llm_call",
    # Unified OTel Setup
    "OTelConfig",
    "setup_otel",
    "shutdown_otel",
    "is_otel_initialized",
    "reset_otel",
    "otel_get_tracer",
    "start_span",
    "record_span_error",
    "set_span_ok",
    "inject_context",
    "extract_context",
    "trace_debate_lifecycle",
    "trace_debate_round",
    "trace_agent_operation",
    "trace_consensus_evaluation",
    "export_debate_span_to_otel",
    # OTLP Health Check
    "OTLPHealthStatus",
    "check_otlp_health",
    "get_otel_status",
    # Metrics
    "start_metrics_server",
    "record_request",
    "record_agent_call",
    "track_debate",
    "set_consensus_rate",
    "record_memory_operation",
    "track_websocket_connection",
    "measure_latency",
    "measure_async_latency",
    "record_debate_completion",
    "record_phase_duration",
    "record_agent_participation",
    "track_phase",
    "record_cache_hit",
    "record_cache_miss",
    # Configuration
    "TracingConfig",
    "MetricsConfig",
    "get_tracing_config",
    "get_metrics_config",
    "is_tracing_enabled",
    "is_metrics_enabled",
    "is_otlp_enabled",
    # OTLP Export
    "OTLPExporterType",
    "OTLPConfig",
    "DEFAULT_ENDPOINTS",
    "configure_otlp_exporter",
    "get_otlp_config",
    "set_otlp_config",
    "reset_otlp_config",
    "get_tracer_provider",
    "shutdown_otlp",
    # SIEM
    "SIEMBackend",
    "SIEMConfig",
    "SecurityEventType",
    "SecurityEvent",
    "SIEMClient",
    "get_siem_client",
    "emit_security_event",
    "emit_auth_event",
    "emit_data_access_event",
    "emit_privacy_event",
    "shutdown_siem",
    # Immutable Audit Log
    "ImmutableAuditLog",
    "AuditEntry",
    "AuditBackend",
    "DailyAnchor",
    "VerificationResult",
    "LocalFileBackend",
    "S3ObjectLockBackend",
    "get_audit_log",
    "init_audit_log",
    "audit_finding_created",
    "audit_finding_updated",
    "audit_document_uploaded",
    "audit_document_accessed",
    "audit_session_started",
    "audit_data_exported",
    # Decision Metrics
    "record_decision_request",
    "record_decision_result",
    "record_decision_error",
    "record_decision_cache_hit",
    "record_decision_cache_miss",
    "record_decision_dedup_hit",
    "track_decision",
    "get_decision_metrics",
    "get_decision_summary",
    # Memory Profiling
    "MemoryProfiler",
    "MemoryProfileResult",
    "MemorySnapshot",
    "MemoryGrowthTracker",
    "MemoryCategory",
    "KMMemoryProfiler",
    "ConsensusMemoryProfiler",
    "profile_memory",
    "track_memory",
    "km_profiler",
    "consensus_profiler",
    # N+1 Query Detection
    "N1QueryDetector",
    "N1QueryError",
    "N1Detection",
    "QueryRecord",
    "detect_n1",
    "get_current_detector",
    "record_query",
    "n1_detection_scope",
    # Trace Correlation
    "TraceContext",
    "get_trace_context",
    "should_sample_trace_id",
    "track_request_with_trace",
    "get_traced_latency_samples",
    "clear_traced_latency_samples",
    "get_slow_traces",
    "generate_exemplar_line",
    # Query Plan Analysis
    "QueryPlanAnalyzer",
    "QueryPlanIssue",
    "SlowQuery",
    "get_analyzer",
    "analyze_query",
    "get_slow_query_history",
    "clear_slow_queries",
    "get_query_analysis_stats",
    # SLO Alerting
    "SLOAlertBridge",
    "SLOAlertConfig",
    "AlertSeverity",
    "AlertChannel",
    "ActiveViolation",
    "init_slo_alerting",
    "get_slo_alert_bridge",
    "shutdown_slo_alerting",
    # Production Alerting
    "Alert",
    "AlertManager",
    "AlertRule",
    "AlertState",
    "AlertingSeverity",
    "AlertMetricsSnapshot",
    "EmailNotificationChannel",
    "MetricsCollector",
    "PrometheusAlertManagerChannel",
    "SlackNotificationChannel",
    "create_critical_alert_rules",
    "get_alert_manager",
    "init_alerting",
    "shutdown_alerting",
]
