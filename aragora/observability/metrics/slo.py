"""
SLO (Service Level Objective) Prometheus metrics.

Provides metrics for monitoring SLO compliance:
- SLO check totals by operation and result
- SLO violation counters
- Latency histograms per operation
- Webhook notifications for violations

Usage:
    from aragora.observability.metrics.slo import (
        record_slo_check,
        record_slo_violation,
        track_operation_slo,
    )

    # Record an SLO check
    record_slo_check("km_query", passed=True, percentile="p99")

    # Record a violation with context
    record_slo_violation("km_query", "p99", latency_ms=550.0, threshold_ms=500.0)

    # Context manager for automatic SLO tracking
    with track_operation_slo("km_query") as ctx:
        result = await mound.query(...)
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from collections.abc import Callable, Generator

from aragora.observability.config import get_metrics_config
from aragora.observability.metrics.base import NoOpMetric

logger = logging.getLogger(__name__)

__all__ = [
    # Core metrics
    "init_slo_metrics",
    "record_slo_check",
    "record_slo_violation",
    "record_operation_latency",
    "check_and_record_slo",
    "check_and_record_slo_with_recovery",
    "track_operation_slo",
    "get_slo_metrics_summary",
    # Burn rate calculation
    "calculate_burn_rate",
    "get_burn_rate_thresholds",
    "BurnRateAlert",
    # Webhook integration
    "init_slo_webhooks",
    "notify_slo_violation",
    "notify_slo_recovery",
    "get_slo_webhook_status",
    "get_violation_state",
    "SLOWebhookConfig",
    "SEVERITY_ORDER",
    "SLOEventSink",
    "register_slo_event_sink_provider",
    # Callback registration for external alert bridges
    "register_violation_callback",
    "register_recovery_callback",
    "unregister_violation_callback",
    "unregister_recovery_callback",
    "clear_all_callbacks",
]

# Webhook notification callback (set by init_slo_webhooks)
_webhook_callback: Callable[[dict[str, Any]], bool] | None = None
_webhook_sink: SLOEventSink | None = None
_webhook_config: SLOWebhookConfig | None = None
_webhook_init_requested = False


class SLOEventSink(Protocol):
    """Higher-layer webhook delivery contract."""

    def enqueue(self, event: dict[str, Any]) -> bool:
        """Queue an SLO event for delivery."""


SLOEventSinkProvider = Callable[[], SLOEventSink | None]
_slo_event_sink_provider: SLOEventSinkProvider | None = None


def register_slo_event_sink_provider(provider: SLOEventSinkProvider | None) -> None:
    """Register the integrations-side provider for SLO event delivery.

    An initialized integration switches only after the replacement provider
    resolves successfully, so concurrent delivery never observes an empty
    callback and a transient replacement failure cannot disable the old sink.
    """
    global _slo_event_sink_provider, _webhook_callback, _webhook_sink
    global _webhook_init_requested

    if provider is None:
        _slo_event_sink_provider = None
        _webhook_callback = None
        _webhook_sink = None
        _webhook_init_requested = False
        return

    if _webhook_init_requested:
        try:
            replacement = provider()
        except (ImportError, OSError, ConnectionError, RuntimeError, TypeError, ValueError) as e:
            logger.warning("Failed to replace SLO webhook provider: %s", e)
            return
        if replacement is None:
            logger.warning("SLO webhook provider replacement returned no sink")
            return

        config = _webhook_config or SLOWebhookConfig()
        replacement_callback = _build_slo_violation_callback(config)
        _slo_event_sink_provider = provider
        _webhook_sink = replacement
        _webhook_callback = replacement_callback
        return

    _slo_event_sink_provider = provider
    _webhook_callback = None
    _webhook_sink = None


def _resolve_slo_event_sink(*, refresh: bool = False) -> SLOEventSink | None:
    """Resolve the current integrations-side sink without importing upward."""
    global _webhook_sink

    if _webhook_sink is not None and not refresh:
        return _webhook_sink
    if _slo_event_sink_provider is None:
        return None
    try:
        resolved = _slo_event_sink_provider()
    except (ImportError, OSError, ConnectionError, RuntimeError, TypeError, ValueError) as e:
        logger.debug("Webhook dispatcher not available: %s", e)
        return _webhook_sink
    if resolved is not None:
        _webhook_sink = resolved
    elif refresh:
        _webhook_sink = None
    return _webhook_sink


# Violation buffer for batching webhook notifications
_violation_buffer: list[dict[str, Any]] = []
_buffer_lock: Any | None = None  # threading.Lock set on init


# Config for webhook notifications
@dataclass
class SLOWebhookConfig:
    """Configuration for SLO webhook notifications."""

    enabled: bool = True
    min_severity: str = "minor"  # minor, moderate, major, critical
    batch_size: int = 10  # Max violations per webhook call
    cooldown_seconds: float = 60.0  # Min time between notifications for same operation


# Severity ordering for filtering
SEVERITY_ORDER = {"minor": 0, "moderate": 1, "major": 2, "critical": 3}


def _build_slo_violation_callback(
    config: SLOWebhookConfig,
) -> Callable[[dict[str, Any]], bool]:
    """Create a violation callback that follows the provider's current sink."""

    def send_violation_webhook(violation_data: dict[str, Any]) -> bool:
        severity = violation_data.get("severity", "minor")
        if SEVERITY_ORDER.get(severity, 0) < SEVERITY_ORDER.get(config.min_severity, 0):
            return False

        operation = violation_data.get("operation", "unknown")
        percentile = violation_data.get("percentile", "p99")
        timestamp_ms = int(time.time() * 1000)
        event = {
            "type": "slo_violation",
            "idempotency_key": f"{operation}:{percentile}:{timestamp_ms}",
            "timestamp": datetime.now().isoformat(),
            "operation": operation,
            "percentile": percentile,
            "severity": severity,
            "latency_ms": violation_data.get("latency_ms", 0),
            "threshold_ms": violation_data.get("threshold_ms", 0),
            "margin_ms": violation_data.get("margin_ms", 0),
            "margin_percent": violation_data.get("margin_percent", 0),
            "context": violation_data.get("context", {}),
        }
        sink = _resolve_slo_event_sink(refresh=True)
        if sink is None:
            return False
        return sink.enqueue(event)

    return send_violation_webhook


# Cooldown tracking
_last_notification: dict[str, float] = {}

# Track violation state for recovery detection
_violation_state: dict[str, dict[str, Any]] = {}  # operation -> {in_violation, last_severity, ...}

# External callback lists for alert bridges (e.g., PagerDuty, Slack)
# These are async-compatible callbacks that receive violation/recovery data
_violation_callbacks: list[Callable[[dict[str, Any]], Any]] = []
_recovery_callbacks: list[Callable[[dict[str, Any]], Any]] = []

# Prometheus metrics - initialized lazily
_initialized = False

# Metric instances (set during initialization)
SLO_CHECKS_TOTAL: Any = None
SLO_VIOLATIONS_TOTAL: Any = None
SLO_LATENCY_HISTOGRAM: Any = None
SLO_VIOLATION_MARGIN: Any = None  # How much over the threshold


def _slo_metrics_ready() -> bool:
    """Return whether the lazy-init flag and metric objects are coherent."""
    return _initialized and all(
        metric is not None
        for metric in (
            SLO_CHECKS_TOTAL,
            SLO_VIOLATIONS_TOTAL,
            SLO_LATENCY_HISTOGRAM,
            SLO_VIOLATION_MARGIN,
        )
    )


def _init_noop_metrics() -> None:
    """Initialize the complete SLO metric set with no-op collectors."""
    global _initialized
    global SLO_CHECKS_TOTAL, SLO_VIOLATIONS_TOTAL
    global SLO_LATENCY_HISTOGRAM, SLO_VIOLATION_MARGIN

    SLO_CHECKS_TOTAL = NoOpMetric()
    SLO_VIOLATIONS_TOTAL = NoOpMetric()
    SLO_LATENCY_HISTOGRAM = NoOpMetric()
    SLO_VIOLATION_MARGIN = NoOpMetric()
    _initialized = True


def init_slo_metrics() -> bool:
    """Initialize SLO Prometheus metrics lazily.

    Returns:
        True if metrics were successfully initialized
    """
    global _initialized
    global SLO_CHECKS_TOTAL, SLO_VIOLATIONS_TOTAL
    global SLO_LATENCY_HISTOGRAM, SLO_VIOLATION_MARGIN

    if _slo_metrics_ready():
        return True
    if _initialized:
        logger.warning("SLO metric state was incomplete; reinitializing all metric objects")
        _initialized = False

    config = get_metrics_config()
    if not config.enabled:
        _init_noop_metrics()
        return False

    try:
        from prometheus_client import Counter, Histogram, Gauge

        SLO_CHECKS_TOTAL = Counter(
            "aragora_slo_checks_total",
            "Total number of SLO checks performed",
            ["operation", "percentile", "result"],
        )

        SLO_VIOLATIONS_TOTAL = Counter(
            "aragora_slo_violations_total",
            "Total number of SLO violations",
            ["operation", "percentile", "severity"],
        )

        # Buckets aligned with typical SLO thresholds
        SLO_LATENCY_HISTOGRAM = Histogram(
            "aragora_slo_operation_latency_ms",
            "Operation latency in milliseconds for SLO tracking",
            ["operation"],
            buckets=[10, 25, 50, 100, 150, 200, 300, 500, 1000, 2000, 5000, 10000, 30000],
        )

        SLO_VIOLATION_MARGIN = Gauge(
            "aragora_slo_violation_margin_ms",
            "How much the latency exceeded the SLO threshold (0 if within SLO)",
            ["operation", "percentile"],
        )

        _initialized = True
        logger.info("SLO metrics initialized")
        return True

    except (ImportError, ValueError):
        logger.warning("prometheus-client not installed, SLO metrics disabled")
        _init_noop_metrics()
        return False


def record_slo_check(
    operation: str,
    passed: bool,
    percentile: str = "p99",
) -> None:
    """Record an SLO check result.

    Args:
        operation: Operation name (e.g., "km_query", "consensus_ingestion")
        passed: Whether the check passed
        percentile: SLO percentile checked (p50, p90, p99)
    """
    init_slo_metrics()

    result = "pass" if passed else "fail"
    SLO_CHECKS_TOTAL.labels(
        operation=operation,
        percentile=percentile,
        result=result,
    ).inc()


def record_slo_violation(
    operation: str,
    percentile: str,
    latency_ms: float,
    threshold_ms: float,
    severity: str | None = None,
    context: dict[str, Any] | None = None,
    notify_webhook: bool = True,
) -> str:
    """Record an SLO violation with context and optionally notify via webhook.

    Args:
        operation: Operation name
        percentile: SLO percentile that was violated
        latency_ms: Actual latency in milliseconds
        threshold_ms: SLO threshold in milliseconds
        severity: Violation severity (auto-calculated if not provided)
        context: Optional additional context for webhook notification
        notify_webhook: Whether to send webhook notification (default True)

    Returns:
        The calculated severity level
    """
    init_slo_metrics()

    # Auto-calculate severity based on how much threshold was exceeded
    if severity is None:
        margin_pct = ((latency_ms - threshold_ms) / threshold_ms) * 100 if threshold_ms > 0 else 0
        if margin_pct < 20:
            severity = "minor"  # < 20% over
        elif margin_pct < 50:
            severity = "moderate"  # 20-50% over
        elif margin_pct < 100:
            severity = "major"  # 50-100% over
        else:
            severity = "critical"  # > 100% over (2x threshold)

    SLO_VIOLATIONS_TOTAL.labels(
        operation=operation,
        percentile=percentile,
        severity=severity,
    ).inc()

    # Record the margin for alerting
    margin = max(0, latency_ms - threshold_ms)
    SLO_VIOLATION_MARGIN.labels(
        operation=operation,
        percentile=percentile,
    ).set(margin)

    # Send webhook notification if enabled
    if notify_webhook:
        notify_slo_violation(
            operation=operation,
            percentile=percentile,
            latency_ms=latency_ms,
            threshold_ms=threshold_ms,
            severity=severity,
            context=context,
        )

    return severity


def record_operation_latency(operation: str, latency_ms: float) -> None:
    """Record operation latency for SLO histogram.

    Args:
        operation: Operation name
        latency_ms: Latency in milliseconds
    """
    init_slo_metrics()

    SLO_LATENCY_HISTOGRAM.labels(operation=operation).observe(latency_ms)


def check_and_record_slo(
    operation: str,
    latency_ms: float,
    percentile: str = "p99",
) -> tuple[bool, str]:
    """Check SLO and record metrics in one call.

    Combines check_latency_slo with metric recording.

    Args:
        operation: Operation name (must match SLOConfig attributes)
        latency_ms: Measured latency in milliseconds
        percentile: SLO percentile to check (p50, p90, p99)

    Returns:
        Tuple of (is_within_slo, message)
    """
    from aragora.config.performance_slos import check_latency_slo, get_slo_config

    init_slo_metrics()

    # Record latency in histogram
    record_operation_latency(operation, latency_ms)

    # Check against SLO
    passed, message = check_latency_slo(operation, latency_ms, percentile)

    # Record the check result
    record_slo_check(operation, passed, percentile)

    # If failed, record violation with threshold
    if not passed:
        config = get_slo_config()
        slo = getattr(config, operation, None)
        if slo:
            threshold_ms = getattr(slo, f"{percentile}_ms", slo.p99_ms)
            record_slo_violation(operation, percentile, latency_ms, threshold_ms)
            logger.warning(message)

    return passed, message


@contextmanager
def track_operation_slo(
    operation: str,
    percentile: str = "p99",
    log_violations: bool = True,
) -> Generator[dict, None, None]:
    """Context manager for tracking operation SLO compliance.

    Automatically measures latency and records SLO metrics.

    Args:
        operation: Operation name (must match SLOConfig attributes)
        percentile: SLO percentile to check
        log_violations: Whether to log warning on violation

    Yields:
        Dict that can be used to store context (e.g., {"size_bytes": 1024})

    Example:
        with track_operation_slo("km_query") as ctx:
            result = await mound.query(...)
            ctx["result_count"] = len(result.items)
    """
    init_slo_metrics()

    ctx: dict = {}
    start_time = time.perf_counter()

    try:
        yield ctx
    finally:
        latency_ms = (time.perf_counter() - start_time) * 1000
        passed, message = check_and_record_slo(operation, latency_ms, percentile)

        if not passed and log_violations:
            logger.warning(
                "SLO violation: %s (context: %s)",
                message,
                ctx if ctx else "none",
            )


def get_slo_metrics_summary() -> dict:
    """Get a summary of SLO metrics for observability endpoints.

    Returns:
        Dict with metric summaries
    """
    init_slo_metrics()

    # This would need prometheus_client inspection which varies
    # Return basic status for now
    return {
        "initialized": _initialized,
        "metrics_enabled": get_metrics_config().enabled,
        "webhooks_enabled": _webhook_callback is not None,
        "tracked_operations": [
            "km_query",
            "km_ingestion",
            "km_checkpoint",
            "consensus_ingestion",
            "consensus_detection",
            "adapter_sync",
            "event_dispatch",
            "handler_execution",
            "memory_store",
            "memory_recall",
            "debate_round",
            "api_endpoint",
        ],
    }


# --- Webhook Integration ---


def init_slo_webhooks(
    webhook_config: SLOWebhookConfig | None = None,
) -> bool:
    """Initialize SLO webhook notifications.

    Connects SLO violations to the registered higher-layer event sink. The
    application composition root must register a provider before calling this
    function; server startup does so via ``register_observability_sinks``.

    Args:
        webhook_config: Optional configuration for webhook behavior

    Returns:
        True if webhooks were successfully initialized
    """
    global _webhook_callback, _webhook_sink, _buffer_lock
    global _webhook_config, _webhook_init_requested

    try:
        import threading

        _buffer_lock = threading.Lock()
        _webhook_config = webhook_config or SLOWebhookConfig()
        _webhook_init_requested = True

        dispatcher = _resolve_slo_event_sink(refresh=True)
        if dispatcher is None:
            _webhook_callback = None
            _webhook_sink = None
            logger.warning(
                "SLO event sink provider not registered or unavailable; webhooks disabled"
            )
            return False
        _webhook_sink = dispatcher

        # Create callback that sends to webhook dispatcher
        config = _webhook_config or SLOWebhookConfig()
        _webhook_callback = _build_slo_violation_callback(config)
        logger.info("SLO webhook notifications initialized")
        return True

    except ImportError as e:
        logger.debug("Could not initialize SLO webhooks: %s", e)
        return False
    except (RuntimeError, TypeError, AttributeError, ValueError) as e:
        logger.warning("Failed to initialize SLO webhooks: %s", e)
        return False


def notify_slo_violation(
    operation: str,
    percentile: str,
    latency_ms: float,
    threshold_ms: float,
    severity: str,
    context: dict[str, Any] | None = None,
    cooldown_seconds: float = 60.0,
) -> bool:
    """Send SLO violation notification via webhook and registered callbacks.

    Args:
        operation: Operation name that violated SLO
        percentile: SLO percentile that was violated
        latency_ms: Actual latency in milliseconds
        threshold_ms: SLO threshold in milliseconds
        severity: Violation severity (minor, moderate, major, critical)
        context: Optional additional context
        cooldown_seconds: Minimum time between notifications for same operation

    Returns:
        True if notification was sent successfully (webhook or any callback)
    """
    # Check cooldown
    now = time.time()
    last_time = _last_notification.get(operation, 0)
    if now - last_time < cooldown_seconds:
        logger.debug("SLO webhook cooldown for %s, skipping notification", operation)
        return False

    margin_ms = latency_ms - threshold_ms
    margin_percent = (margin_ms / threshold_ms) * 100 if threshold_ms > 0 else 0

    violation_data = {
        "operation": operation,
        "percentile": percentile,
        "latency_ms": latency_ms,
        "threshold_ms": threshold_ms,
        "margin_ms": margin_ms,
        "margin_percent": margin_percent,
        "severity": severity,
        "context": context or {},
        "timestamp": datetime.now().isoformat(),
    }

    result = False

    # Send to webhook dispatcher
    if _webhook_callback is not None:
        try:
            result = _webhook_callback(violation_data)
        except (OSError, ConnectionError, RuntimeError, TypeError, ValueError) as e:
            logger.debug("Failed to send SLO violation webhook: %s", e)

    # Invoke registered external callbacks (e.g., SLO Alert Bridge)
    if _violation_callbacks:
        _invoke_callbacks(_violation_callbacks, violation_data)
        result = True  # Consider success if we have callbacks

    if result:
        _last_notification[operation] = now

    return result


def get_slo_webhook_status() -> dict[str, Any]:
    """Get status of SLO webhook integration.

    Returns:
        Dict with webhook status information
    """
    return {
        "enabled": _webhook_callback is not None,
        "cooldown_active": {op: time.time() - ts < 60.0 for op, ts in _last_notification.items()},
        "buffer_size": len(_violation_buffer),
        "operations_in_violation": [
            op for op, state in _violation_state.items() if state.get("in_violation", False)
        ],
    }


def notify_slo_recovery(
    operation: str,
    percentile: str,
    latency_ms: float,
    threshold_ms: float,
    violation_duration_seconds: float,
    context: dict[str, Any] | None = None,
) -> bool:
    """Send SLO recovery notification via webhook and registered callbacks.

    Called when an operation returns to SLO compliance after being in violation.

    Args:
        operation: Operation name that recovered
        percentile: SLO percentile that was violated
        latency_ms: Current latency (now within SLO)
        threshold_ms: SLO threshold in milliseconds
        violation_duration_seconds: How long the violation lasted
        context: Optional additional context

    Returns:
        True if notification was sent successfully (webhook or any callback)
    """
    recovery_data = {
        "operation": operation,
        "percentile": percentile,
        "latency_ms": latency_ms,
        "threshold_ms": threshold_ms,
        "margin_ms": threshold_ms - latency_ms,  # How much under threshold
        "violation_duration_seconds": violation_duration_seconds,
        "context": context or {},
        "timestamp": datetime.now().isoformat(),
    }

    result = False

    # Send to webhook dispatcher. Recovery delivery historically worked
    # without explicit webhook initialization, so resolve the registered sink
    # directly while keeping the dependency direction inverted.
    try:
        sink = _resolve_slo_event_sink(refresh=True)
        if sink is not None:
            event = {
                "type": "slo_recovery",
                **recovery_data,
            }
            result = sink.enqueue(event)

    except (OSError, ConnectionError, RuntimeError, TypeError, ValueError) as e:
        logger.debug("Failed to send SLO recovery webhook: %s", e)

    # Invoke registered external callbacks (e.g., SLO Alert Bridge)
    if _recovery_callbacks:
        _invoke_callbacks(_recovery_callbacks, recovery_data)
        result = True  # Consider success if we have callbacks

    return result


def check_and_record_slo_with_recovery(
    operation: str,
    latency_ms: float,
    percentile: str = "p99",
    context: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Check SLO, record metrics, and handle violation/recovery state.

    This is an enhanced version of check_and_record_slo that also:
    - Tracks violation state for each operation
    - Sends recovery notifications when an operation returns to compliance

    Args:
        operation: Operation name (must match SLOConfig attributes)
        latency_ms: Measured latency in milliseconds
        percentile: SLO percentile to check (p50, p90, p99)
        context: Optional context to include in webhook notifications

    Returns:
        Tuple of (is_within_slo, message)
    """
    from aragora.config.performance_slos import check_latency_slo, get_slo_config

    init_slo_metrics()

    # Record latency in histogram
    record_operation_latency(operation, latency_ms)

    # Check against SLO
    passed, message = check_latency_slo(operation, latency_ms, percentile)

    # Record the check result
    record_slo_check(operation, passed, percentile)

    # Get current violation state for this operation
    current_state = _violation_state.get(operation, {"in_violation": False})

    if not passed:
        # SLO violated
        config = get_slo_config()
        slo = getattr(config, operation, None)
        if slo:
            threshold_ms = getattr(slo, f"{percentile}_ms", slo.p99_ms)
            severity = record_slo_violation(
                operation,
                percentile,
                latency_ms,
                threshold_ms,
                context=context,
                notify_webhook=True,
            )

            # Update violation state
            if not current_state.get("in_violation"):
                # Entering violation state
                _violation_state[operation] = {
                    "in_violation": True,
                    "violation_start": time.time(),
                    "last_severity": severity,
                    "percentile": percentile,
                    "threshold_ms": threshold_ms,
                }
            else:
                # Already in violation, update severity if worse
                if SEVERITY_ORDER.get(severity, 0) > SEVERITY_ORDER.get(
                    current_state.get("last_severity", "minor"), 0
                ):
                    _violation_state[operation]["last_severity"] = severity

            logger.warning(message)

    else:
        # SLO passed
        if current_state.get("in_violation"):
            # Recovering from violation!
            violation_start = current_state.get("violation_start", time.time())
            violation_duration = time.time() - violation_start
            threshold_ms = current_state.get("threshold_ms", 0)

            # Send recovery notification
            notify_slo_recovery(
                operation=operation,
                percentile=current_state.get("percentile", percentile),
                latency_ms=latency_ms,
                threshold_ms=threshold_ms,
                violation_duration_seconds=violation_duration,
                context=context,
            )

            logger.info(
                f"SLO recovered for {operation}: latency={latency_ms:.1f}ms "
                f"(threshold={threshold_ms:.1f}ms), "
                f"violation lasted {violation_duration:.1f}s"
            )

            # Clear violation state
            _violation_state[operation] = {"in_violation": False}

    return passed, message


def get_violation_state(operation: str | None = None) -> dict[str, Any]:
    """Get current violation state for operation(s).

    Args:
        operation: Specific operation to check, or None for all

    Returns:
        Dict with violation state information
    """
    if operation:
        return _violation_state.get(operation, {"in_violation": False})
    return dict(_violation_state)


# --- External Callback Registration ---
# Allows external modules (like SLO Alert Bridge) to receive violation/recovery events


def register_violation_callback(
    callback: Callable[[dict[str, Any]], Any],
) -> None:
    """Register a callback to be invoked on SLO violations.

    Callbacks receive a dict with violation details:
    - operation: str - Operation name
    - percentile: str - SLO percentile violated (p50, p90, p99)
    - latency_ms: float - Actual latency
    - threshold_ms: float - SLO threshold
    - severity: str - minor, moderate, major, critical
    - margin_ms: float - How much over threshold
    - margin_percent: float - Percentage over threshold
    - context: dict - Additional context
    - timestamp: str - ISO timestamp

    Callbacks can be sync or async. Async callbacks will be scheduled
    on the current event loop if available.

    Args:
        callback: Function to call on violations
    """
    if callback not in _violation_callbacks:
        _violation_callbacks.append(callback)
        logger.debug("Registered SLO violation callback: %s", callback.__name__)


def register_recovery_callback(
    callback: Callable[[dict[str, Any]], Any],
) -> None:
    """Register a callback to be invoked on SLO recoveries.

    Callbacks receive a dict with recovery details:
    - operation: str - Operation name
    - percentile: str - SLO percentile that was violated
    - latency_ms: float - Current latency (within SLO)
    - threshold_ms: float - SLO threshold
    - margin_ms: float - How much under threshold
    - violation_duration_seconds: float - How long violation lasted
    - context: dict - Additional context
    - timestamp: str - ISO timestamp

    Args:
        callback: Function to call on recoveries
    """
    if callback not in _recovery_callbacks:
        _recovery_callbacks.append(callback)
        logger.debug("Registered SLO recovery callback: %s", callback.__name__)


def unregister_violation_callback(
    callback: Callable[[dict[str, Any]], Any],
) -> bool:
    """Unregister a previously registered violation callback.

    Args:
        callback: The callback to remove

    Returns:
        True if callback was found and removed
    """
    try:
        _violation_callbacks.remove(callback)
        logger.debug("Unregistered SLO violation callback: %s", callback.__name__)
        return True
    except ValueError:
        return False


def unregister_recovery_callback(
    callback: Callable[[dict[str, Any]], Any],
) -> bool:
    """Unregister a previously registered recovery callback.

    Args:
        callback: The callback to remove

    Returns:
        True if callback was found and removed
    """
    try:
        _recovery_callbacks.remove(callback)
        logger.debug("Unregistered SLO recovery callback: %s", callback.__name__)
        return True
    except ValueError:
        return False


def clear_all_callbacks() -> None:
    """Clear all registered callbacks. Primarily for testing."""
    _violation_callbacks.clear()
    _recovery_callbacks.clear()
    logger.debug("Cleared all SLO callbacks")


def _invoke_callbacks(
    callbacks: list[Callable[[dict[str, Any]], Any]],
    data: dict[str, Any],
) -> None:
    """Invoke all registered callbacks with the given data.

    Handles both sync and async callbacks. Async callbacks are scheduled
    on the event loop if available, otherwise run synchronously.

    Args:
        callbacks: List of callbacks to invoke
        data: Data to pass to callbacks
    """
    import asyncio
    import inspect

    for callback in callbacks:
        try:
            if inspect.iscoroutinefunction(callback):
                # Async callback - try to schedule on event loop
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(callback(data))
                except RuntimeError:
                    # No running loop - run in new loop
                    asyncio.run(callback(data))
            else:
                # Sync callback
                callback(data)
        except Exception as e:  # noqa: BLE001 - observability callbacks must not crash app
            logger.warning("SLO callback %s failed: %s", callback.__name__, e)


# =============================================================================
# SLO Burn Rate Calculation
# =============================================================================


@dataclass
class BurnRateAlert:
    """Alert for SLO burn rate threshold exceeded.

    Attributes:
        slo_name: Name of the SLO
        burn_rate: Current burn rate
        threshold: Threshold that was exceeded
        window: Time window for burn rate calculation
        level: Alert level (fast_burn or slow_burn)
        error_budget_consumed: Percentage of error budget consumed
    """

    slo_name: str
    burn_rate: float
    threshold: float
    window: str
    level: str  # "fast_burn" or "slow_burn"
    error_budget_consumed: float
    timestamp: float = 0.0

    def __post_init__(self) -> None:
        if self.timestamp == 0.0:
            self.timestamp = time.time()


def calculate_burn_rate(
    error_rate: float,
    slo_target: float,
    window_hours: float = 1.0,
    budget_hours: float = 720.0,  # 30 days
) -> float:
    """Calculate SLO burn rate.

    Burn rate indicates how fast you're consuming your error budget.
    A burn rate of 1.0 means you'll exhaust the budget exactly on time.
    A burn rate of 10.0 means you'll exhaust it 10x faster.

    Formula:
        burn_rate = error_rate / (1 - slo_target)

    For example, with 99.9% SLO (0.1% error budget):
        - 0.1% error rate = burn rate of 1.0 (on target)
        - 1.0% error rate = burn rate of 10.0 (10x over)

    Args:
        error_rate: Current error rate (0.0 to 1.0)
        slo_target: SLO target (e.g., 0.999 for 99.9%)
        window_hours: Time window for error rate measurement
        budget_hours: Total error budget period (default: 30 days)

    Returns:
        Burn rate multiplier (1.0 = consuming at target rate)
    """
    error_budget = 1.0 - slo_target
    if error_budget <= 0:
        return 0.0

    burn_rate = error_rate / error_budget
    return max(0.0, burn_rate)


def get_burn_rate_thresholds() -> dict[str, dict[str, float]]:
    """Get standard burn rate thresholds for multi-window alerting.

    Returns thresholds based on Google SRE burn rate methodology:
    - Fast burn: 14.4x rate over 1h (exhausts 2% budget in 1h)
    - Slow burn: 6.0x rate over 6h (exhausts 5% budget in 6h)
    - Very slow: 3.0x rate over 24h (exhausts 10% budget in 24h)

    Returns:
        Dict with threshold configurations
    """
    return {
        "fast_burn": {
            "burn_rate_threshold": 14.4,
            "short_window_hours": 1.0,
            "long_window_hours": 5.0 / 60,  # 5 minutes
            "budget_consumption_percent": 2.0,
        },
        "slow_burn": {
            "burn_rate_threshold": 6.0,
            "short_window_hours": 6.0,
            "long_window_hours": 0.5,  # 30 minutes
            "budget_consumption_percent": 5.0,
        },
        "very_slow_burn": {
            "burn_rate_threshold": 3.0,
            "short_window_hours": 24.0,
            "long_window_hours": 2.0,
            "budget_consumption_percent": 10.0,
        },
        "budget_exhaustion": {
            "burn_rate_threshold": 1.0,
            "short_window_hours": 720.0,  # 30 days
            "long_window_hours": 24.0,
            "budget_consumption_percent": 100.0,
        },
    }


def check_burn_rate_thresholds(
    error_rate: float,
    slo_target: float,
    slo_name: str = "default",
) -> list[BurnRateAlert]:
    """Check if burn rate exceeds any thresholds.

    Args:
        error_rate: Current error rate (0.0 to 1.0)
        slo_target: SLO target (e.g., 0.999 for 99.9%)
        slo_name: Name of the SLO for alerting

    Returns:
        List of BurnRateAlert for exceeded thresholds
    """
    burn_rate = calculate_burn_rate(error_rate, slo_target)
    thresholds = get_burn_rate_thresholds()

    alerts = []
    for level, config in thresholds.items():
        if burn_rate >= config["burn_rate_threshold"]:
            alerts.append(
                BurnRateAlert(
                    slo_name=slo_name,
                    burn_rate=burn_rate,
                    threshold=config["burn_rate_threshold"],
                    window=f"{config['short_window_hours']}h",
                    level=level,
                    error_budget_consumed=config["budget_consumption_percent"],
                )
            )

    return alerts
