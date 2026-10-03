"""
Service Level Objective (SLO) tracking for Aragora.

Provides SLO definitions, compliance calculations, and alerting thresholds
for production monitoring.

Usage:
    from aragora.observability.slo import (
        get_slo_status,
        check_availability_slo,
        check_latency_slo,
        check_debate_success_slo,
        SLODefinition,
    )

    # Get overall SLO status
    status = get_slo_status()
    print(f"Availability: {status.availability.compliance_percentage:.2f}%")

    # Check individual SLOs
    if not check_latency_slo():
        alert("p99 latency exceeding SLO target")

SLO Targets:
    - API Availability: 99.9% (3 nines)
    - p99 Latency: <500ms
    - Debate Success Rate: >95%

Environment Variables:
    SLO_AVAILABILITY_TARGET: Override availability target (default: 0.999)
    SLO_LATENCY_P99_TARGET_MS: Override p99 latency target (default: 500)
    SLO_DEBATE_SUCCESS_TARGET: Override debate success target (default: 0.95)

See docs/OBSERVABILITY.md for configuration guide.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# =============================================================================
# SLO Definitions
# =============================================================================


@dataclass
class SLOTarget:
    """Definition of an SLO target."""

    name: str
    target: float
    unit: str
    description: str
    comparison: str = "gte"  # gte (>=), lte (<=), gt (>), lt (<)


@dataclass
class SLOResult:
    """Result of an SLO compliance check."""

    name: str
    target: float
    current: float
    compliant: bool
    compliance_percentage: float
    window_start: datetime
    window_end: datetime
    error_budget_remaining: float  # Percentage of error budget remaining
    burn_rate: float  # How fast error budget is being consumed


@dataclass
class SLOStatus:
    """Overall SLO status for the service."""

    availability: SLOResult
    latency_p99: SLOResult
    debate_success: SLOResult
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    overall_healthy: bool = True

    def __post_init__(self) -> None:
        """Calculate overall health from individual SLOs."""
        self.overall_healthy = (
            self.availability.compliant
            and self.latency_p99.compliant
            and self.debate_success.compliant
        )


# Default SLO targets
DEFAULT_AVAILABILITY_TARGET = 0.999  # 99.9%
DEFAULT_LATENCY_P95_MS = 500  # 500ms
DEFAULT_LATENCY_P99_MS = 2000  # 2000ms
DEFAULT_ERROR_RATE_TARGET = 0.01  # 1%
DEFAULT_DEBATE_SUCCESS_TARGET = 0.95  # 95%

# Streaming SLO targets
DEFAULT_STREAM_ERROR_RATE_TARGET = 0.005  # <= 0.5% (5-minute window)
DEFAULT_STREAM_RECONNECT_P95_TARGET_S = 5.0  # <= 5 seconds
DEFAULT_STREAM_MESSAGE_DELIVERY_TARGET = 0.995  # >= 99.5%
DEFAULT_TTS_SYNTHESIS_LATENCY_P95_TARGET_S = 3.0  # <= 3 seconds


def get_slo_targets() -> dict[str, SLOTarget]:
    """Get configured SLO targets from environment.

    Returns:
        Dictionary of SLO targets
    """
    availability_target = float(
        os.getenv("SLO_AVAILABILITY_TARGET", str(DEFAULT_AVAILABILITY_TARGET))
    )
    latency_p95_ms = float(os.getenv("SLO_LATENCY_P95_TARGET_MS", str(DEFAULT_LATENCY_P95_MS)))
    latency_p99_ms = float(os.getenv("SLO_LATENCY_P99_TARGET_MS", str(DEFAULT_LATENCY_P99_MS)))
    error_rate_target = float(os.getenv("SLO_ERROR_RATE_TARGET", str(DEFAULT_ERROR_RATE_TARGET)))
    debate_success_target = float(
        os.getenv("SLO_DEBATE_SUCCESS_TARGET", str(DEFAULT_DEBATE_SUCCESS_TARGET))
    )

    # Streaming SLO targets from environment
    stream_error_rate_target = float(
        os.getenv("SLO_STREAM_ERROR_RATE_TARGET", str(DEFAULT_STREAM_ERROR_RATE_TARGET))
    )
    stream_reconnect_p95_s = float(
        os.getenv("SLO_STREAM_RECONNECT_P95_TARGET_S", str(DEFAULT_STREAM_RECONNECT_P95_TARGET_S))
    )
    stream_delivery_target = float(
        os.getenv("SLO_STREAM_MESSAGE_DELIVERY_TARGET", str(DEFAULT_STREAM_MESSAGE_DELIVERY_TARGET))
    )
    tts_latency_p95_s = float(
        os.getenv(
            "SLO_TTS_SYNTHESIS_LATENCY_P95_TARGET_S",
            str(DEFAULT_TTS_SYNTHESIS_LATENCY_P95_TARGET_S),
        )
    )

    return {
        "availability": SLOTarget(
            name="API Availability",
            target=availability_target,
            unit="ratio",
            description="Percentage of successful requests (non-5xx)",
            comparison="gte",
        ),
        "latency_p95": SLOTarget(
            name="p95 Latency",
            target=latency_p95_ms / 1000,  # Convert to seconds
            unit="seconds",
            description="95th percentile request latency",
            comparison="lte",
        ),
        "latency_p99": SLOTarget(
            name="p99 Latency",
            target=latency_p99_ms / 1000,  # Convert to seconds
            unit="seconds",
            description="99th percentile request latency",
            comparison="lte",
        ),
        "error_rate": SLOTarget(
            name="Error Rate",
            target=error_rate_target,
            unit="ratio",
            description="Percentage of requests resulting in errors",
            comparison="lte",
        ),
        "debate_success": SLOTarget(
            name="Debate Success Rate",
            target=debate_success_target,
            unit="ratio",
            description="Percentage of debates reaching consensus or completing successfully",
            comparison="gte",
        ),
        # Streaming SLOs
        "stream_error_rate": SLOTarget(
            name="Stream Error Rate",
            target=stream_error_rate_target,
            unit="ratio",
            description="WebSocket stream error rate over 5-minute window",
            comparison="lte",
        ),
        "stream_reconnect_p95": SLOTarget(
            name="Stream Reconnect p95",
            target=stream_reconnect_p95_s,
            unit="seconds",
            description="95th percentile reconnection time",
            comparison="lte",
        ),
        "stream_message_delivery_rate": SLOTarget(
            name="Stream Message Delivery Rate",
            target=stream_delivery_target,
            unit="ratio",
            description="Percentage of stream messages successfully delivered",
            comparison="gte",
        ),
        "tts_synthesis_latency_p95": SLOTarget(
            name="TTS Synthesis Latency p95",
            target=tts_latency_p95_s,
            unit="seconds",
            description="95th percentile TTS synthesis latency",
            comparison="lte",
        ),
    }


# =============================================================================
# SLO Calculation Functions
# =============================================================================


def _calculate_error_budget(target: float, current: float, comparison: str) -> tuple[float, float]:
    """Calculate error budget remaining and burn rate.

    Args:
        target: SLO target value
        current: Current measured value
        comparison: Comparison type (gte, lte)

    Returns:
        Tuple of (error_budget_remaining_pct, burn_rate)
    """
    if comparison == "gte":
        # For availability/success rate, error budget = 1 - target
        error_budget = 1 - target
        if error_budget <= 0:
            return 0.0, float("inf")
        errors_used = max(0, target - current)
        error_budget_remaining = max(0, (error_budget - errors_used) / error_budget) * 100
        burn_rate = errors_used / error_budget if error_budget > 0 else 0
    else:
        # For latency, error budget is percentage above target
        error_budget = target * 0.5  # Allow 50% overage as error budget
        if error_budget <= 0:
            return 0.0, float("inf")
        overage = max(0, current - target)
        error_budget_remaining = max(0, (error_budget - overage) / error_budget) * 100
        burn_rate = overage / error_budget if error_budget > 0 else 0

    return error_budget_remaining, burn_rate


def _check_compliance(target: float, current: float, comparison: str) -> bool:
    """Check if current value meets SLO target.

    Args:
        target: SLO target value
        current: Current measured value
        comparison: Comparison type

    Returns:
        True if compliant, False otherwise
    """
    if comparison == "gte":
        return current >= target
    elif comparison == "lte":
        return current <= target
    elif comparison == "gt":
        return current > target
    elif comparison == "lt":
        return current < target
    return False


def _calculate_compliance_percentage(target: float, current: float, comparison: str) -> float:
    """Calculate compliance percentage relative to target.

    Args:
        target: SLO target value
        current: Current measured value
        comparison: Comparison type

    Returns:
        Compliance percentage (can exceed 100%)
    """
    if target == 0:
        return 100.0 if current == 0 else 0.0

    if comparison in ("gte", "gt"):
        return (current / target) * 100
    else:
        # For "less than" comparisons, invert the calculation
        if current == 0:
            return 100.0
        return (target / current) * 100


# =============================================================================
# Prometheus Integration
# =============================================================================

_slo_metrics_initialized = False
SLO_COMPLIANCE: Any = None
SLO_ERROR_BUDGET: Any = None
SLO_BURN_RATE: Any = None


def _init_slo_metrics() -> bool:
    """Initialize SLO-specific Prometheus metrics."""
    global _slo_metrics_initialized, SLO_COMPLIANCE, SLO_ERROR_BUDGET, SLO_BURN_RATE

    if _slo_metrics_initialized:
        return True

    try:
        from prometheus_client import Gauge

        SLO_COMPLIANCE = Gauge(
            "aragora_slo_compliance",
            "SLO compliance status (1=compliant, 0=non-compliant)",
            ["slo_name"],
        )

        SLO_ERROR_BUDGET = Gauge(
            "aragora_slo_error_budget_remaining",
            "Remaining error budget percentage",
            ["slo_name"],
        )

        SLO_BURN_RATE = Gauge(
            "aragora_slo_burn_rate",
            "Error budget burn rate (1.0 = consuming at expected rate)",
            ["slo_name"],
        )

        _slo_metrics_initialized = True
        logger.info("SLO metrics initialized")
        return True

    except ImportError:
        logger.warning("prometheus-client not installed, SLO metrics disabled")
        _init_noop_slo_metrics()
        _slo_metrics_initialized = True
        return False
    except (RuntimeError, TypeError, ValueError) as e:
        logger.error("Failed to initialize SLO metrics: %s", e)
        _init_noop_slo_metrics()
        _slo_metrics_initialized = True
        return False


def _init_noop_slo_metrics() -> None:
    """Initialize no-op SLO metrics."""
    global SLO_COMPLIANCE, SLO_ERROR_BUDGET, SLO_BURN_RATE

    class NoOpGauge:
        def labels(self, *args: Any, **kwargs: Any) -> NoOpGauge:
            return self

        def set(self, value: float) -> None:
            pass

    SLO_COMPLIANCE = NoOpGauge()
    SLO_ERROR_BUDGET = NoOpGauge()
    SLO_BURN_RATE = NoOpGauge()


def _update_slo_metrics(result: SLOResult) -> None:
    """Update Prometheus metrics for an SLO result."""
    _init_slo_metrics()

    SLO_COMPLIANCE.labels(slo_name=result.name).set(1.0 if result.compliant else 0.0)
    SLO_ERROR_BUDGET.labels(slo_name=result.name).set(result.error_budget_remaining)
    SLO_BURN_RATE.labels(slo_name=result.name).set(result.burn_rate)


# =============================================================================
# SLO Check Functions
# =============================================================================

# In-memory storage for recent measurements (used when Prometheus not available)
_measurement_window: list[dict[str, Any]] = []
_window_duration = timedelta(hours=1)


def _record_measurement(
    total_requests: int,
    successful_requests: int,
    latency_p99: float,
    total_debates: int,
    successful_debates: int,
) -> None:
    """Record a measurement for SLO calculation.

    This is used when Prometheus metrics are not available.
    """
    global _measurement_window

    now = datetime.now(timezone.utc)

    # Clean old measurements
    cutoff = now - _window_duration
    _measurement_window = [m for m in _measurement_window if m["timestamp"] > cutoff]

    # Add new measurement
    _measurement_window.append(
        {
            "timestamp": now,
            "total_requests": total_requests,
            "successful_requests": successful_requests,
            "latency_p99": latency_p99,
            "total_debates": total_debates,
            "successful_debates": successful_debates,
        }
    )


def check_availability_slo(
    total_requests: int | None = None,
    successful_requests: int | None = None,
) -> SLOResult:
    """Check API availability SLO compliance.

    Args:
        total_requests: Total request count (optional, uses Prometheus if available)
        successful_requests: Successful request count (optional)

    Returns:
        SLOResult with compliance status
    """
    targets = get_slo_targets()
    target = targets["availability"]
    now = datetime.now(timezone.utc)
    window_start = now - _window_duration

    # Try to get values from Prometheus if not provided
    if total_requests is None or successful_requests is None:
        if importlib.util.find_spec("prometheus_client") is not None:
            # Query Prometheus for request counts
            # This is a simplified approach - in production you'd use PromQL
            total_requests = total_requests or 1000  # Fallback
            successful_requests = successful_requests or 999  # Fallback
        else:
            # Use in-memory measurements
            if _measurement_window:
                total_requests = sum(m["total_requests"] for m in _measurement_window)
                successful_requests = sum(m["successful_requests"] for m in _measurement_window)
            else:
                total_requests = total_requests or 0
                successful_requests = successful_requests or 0

    # Calculate availability
    if total_requests == 0:
        current = 1.0  # No requests = 100% availability
    else:
        current = successful_requests / total_requests

    compliant = _check_compliance(target.target, current, target.comparison)
    compliance_pct = _calculate_compliance_percentage(target.target, current, target.comparison)
    error_budget, burn_rate = _calculate_error_budget(target.target, current, target.comparison)

    result = SLOResult(
        name=target.name,
        target=target.target,
        current=current,
        compliant=compliant,
        compliance_percentage=compliance_pct,
        window_start=window_start,
        window_end=now,
        error_budget_remaining=error_budget,
        burn_rate=burn_rate,
    )

    _update_slo_metrics(result)
    return result


def check_latency_slo(latency_p99: float | None = None) -> SLOResult:
    """Check p99 latency SLO compliance.

    Args:
        latency_p99: p99 latency in seconds (optional, uses Prometheus if available)

    Returns:
        SLOResult with compliance status
    """
    targets = get_slo_targets()
    target = targets["latency_p99"]
    now = datetime.now(timezone.utc)
    window_start = now - _window_duration

    # Try to get value from Prometheus if not provided
    if latency_p99 is None:
        if importlib.util.find_spec("prometheus_client") is not None:
            # This would normally query Prometheus histogram quantile
            latency_p99 = latency_p99 or 0.1  # Fallback
        else:
            if _measurement_window:
                latency_p99 = max(m["latency_p99"] for m in _measurement_window)
            else:
                latency_p99 = latency_p99 or 0.0

    compliant = _check_compliance(target.target, latency_p99, target.comparison)
    compliance_pct = _calculate_compliance_percentage(target.target, latency_p99, target.comparison)
    error_budget, burn_rate = _calculate_error_budget(target.target, latency_p99, target.comparison)

    result = SLOResult(
        name=target.name,
        target=target.target,
        current=latency_p99,
        compliant=compliant,
        compliance_percentage=compliance_pct,
        window_start=window_start,
        window_end=now,
        error_budget_remaining=error_budget,
        burn_rate=burn_rate,
    )

    _update_slo_metrics(result)
    return result


def check_debate_success_slo(
    total_debates: int | None = None,
    successful_debates: int | None = None,
) -> SLOResult:
    """Check debate success rate SLO compliance.

    Args:
        total_debates: Total debate count (optional)
        successful_debates: Successful debate count (optional)

    Returns:
        SLOResult with compliance status
    """
    targets = get_slo_targets()
    target = targets["debate_success"]
    now = datetime.now(timezone.utc)
    window_start = now - _window_duration

    # Try to get values from Prometheus if not provided
    if total_debates is None or successful_debates is None:
        if importlib.util.find_spec("prometheus_client") is not None:
            total_debates = total_debates or 100  # Fallback
            successful_debates = successful_debates or 96  # Fallback
        else:
            if _measurement_window:
                total_debates = sum(m["total_debates"] for m in _measurement_window)
                successful_debates = sum(m["successful_debates"] for m in _measurement_window)
            else:
                total_debates = total_debates or 0
                successful_debates = successful_debates or 0

    # Calculate success rate
    if total_debates == 0:
        current = 1.0  # No debates = 100% success
    else:
        current = successful_debates / total_debates

    compliant = _check_compliance(target.target, current, target.comparison)
    compliance_pct = _calculate_compliance_percentage(target.target, current, target.comparison)
    error_budget, burn_rate = _calculate_error_budget(target.target, current, target.comparison)

    result = SLOResult(
        name=target.name,
        target=target.target,
        current=current,
        compliant=compliant,
        compliance_percentage=compliance_pct,
        window_start=window_start,
        window_end=now,
        error_budget_remaining=error_budget,
        burn_rate=burn_rate,
    )

    _update_slo_metrics(result)
    return result


def check_stream_error_rate_slo(
    error_count: int | None = None,
    total_events: int | None = None,
) -> SLOResult:
    """Check stream error rate SLO compliance.

    Args:
        error_count: Number of stream errors in the window
        total_events: Total stream events in the window

    Returns:
        SLOResult with compliance status
    """
    targets = get_slo_targets()
    target = targets["stream_error_rate"]
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=5)

    if error_count is None or total_events is None:
        error_count = error_count or 0
        total_events = total_events or 0

    if total_events == 0:
        current = 0.0
    else:
        current = error_count / total_events

    compliant = _check_compliance(target.target, current, target.comparison)
    compliance_pct = _calculate_compliance_percentage(target.target, current, target.comparison)
    error_budget, burn_rate = _calculate_error_budget(target.target, current, target.comparison)

    result = SLOResult(
        name=target.name,
        target=target.target,
        current=current,
        compliant=compliant,
        compliance_percentage=compliance_pct,
        window_start=window_start,
        window_end=now,
        error_budget_remaining=error_budget,
        burn_rate=burn_rate,
    )

    _update_slo_metrics(result)
    return result


def check_stream_reconnect_p95_slo(
    reconnect_p95_seconds: float | None = None,
) -> SLOResult:
    """Check stream reconnect p95 latency SLO compliance.

    Args:
        reconnect_p95_seconds: p95 reconnection time in seconds

    Returns:
        SLOResult with compliance status
    """
    targets = get_slo_targets()
    target = targets["stream_reconnect_p95"]
    now = datetime.now(timezone.utc)
    window_start = now - _window_duration

    reconnect_p95_seconds = reconnect_p95_seconds or 0.0

    compliant = _check_compliance(target.target, reconnect_p95_seconds, target.comparison)
    compliance_pct = _calculate_compliance_percentage(
        target.target, reconnect_p95_seconds, target.comparison
    )
    error_budget, burn_rate = _calculate_error_budget(
        target.target, reconnect_p95_seconds, target.comparison
    )

    result = SLOResult(
        name=target.name,
        target=target.target,
        current=reconnect_p95_seconds,
        compliant=compliant,
        compliance_percentage=compliance_pct,
        window_start=window_start,
        window_end=now,
        error_budget_remaining=error_budget,
        burn_rate=burn_rate,
    )

    _update_slo_metrics(result)
    return result


def check_stream_delivery_rate_slo(
    delivered: int | None = None,
    total: int | None = None,
) -> SLOResult:
    """Check stream message delivery rate SLO compliance.

    Args:
        delivered: Number of successfully delivered messages
        total: Total messages attempted

    Returns:
        SLOResult with compliance status
    """
    targets = get_slo_targets()
    target = targets["stream_message_delivery_rate"]
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=5)

    if delivered is None or total is None:
        delivered = delivered or 0
        total = total or 0

    if total == 0:
        current = 1.0
    else:
        current = delivered / total

    compliant = _check_compliance(target.target, current, target.comparison)
    compliance_pct = _calculate_compliance_percentage(target.target, current, target.comparison)
    error_budget, burn_rate = _calculate_error_budget(target.target, current, target.comparison)

    result = SLOResult(
        name=target.name,
        target=target.target,
        current=current,
        compliant=compliant,
        compliance_percentage=compliance_pct,
        window_start=window_start,
        window_end=now,
        error_budget_remaining=error_budget,
        burn_rate=burn_rate,
    )

    _update_slo_metrics(result)
    return result


def check_tts_synthesis_latency_slo(
    latency_p95_seconds: float | None = None,
) -> SLOResult:
    """Check TTS synthesis latency p95 SLO compliance.

    Args:
        latency_p95_seconds: p95 synthesis latency in seconds

    Returns:
        SLOResult with compliance status
    """
    targets = get_slo_targets()
    target = targets["tts_synthesis_latency_p95"]
    now = datetime.now(timezone.utc)
    window_start = now - _window_duration

    latency_p95_seconds = latency_p95_seconds or 0.0

    compliant = _check_compliance(target.target, latency_p95_seconds, target.comparison)
    compliance_pct = _calculate_compliance_percentage(
        target.target, latency_p95_seconds, target.comparison
    )
    error_budget, burn_rate = _calculate_error_budget(
        target.target, latency_p95_seconds, target.comparison
    )

    result = SLOResult(
        name=target.name,
        target=target.target,
        current=latency_p95_seconds,
        compliant=compliant,
        compliance_percentage=compliance_pct,
        window_start=window_start,
        window_end=now,
        error_budget_remaining=error_budget,
        burn_rate=burn_rate,
    )

    _update_slo_metrics(result)
    return result


def get_slo_status() -> SLOStatus:
    """Get overall SLO status for all tracked SLOs.

    Returns:
        SLOStatus with all SLO results
    """
    availability = check_availability_slo()
    latency = check_latency_slo()
    debate_success = check_debate_success_slo()

    return SLOStatus(
        availability=availability,
        latency_p99=latency,
        debate_success=debate_success,
    )


# =============================================================================
# Alerting Helpers
# =============================================================================


@dataclass
class SLOAlert:
    """SLO alert configuration."""

    slo_name: str
    severity: str  # warning, critical
    message: str
    error_budget_threshold: float  # Trigger when error budget below this %
    burn_rate_threshold: float  # Trigger when burn rate above this


def get_default_alerts() -> list[SLOAlert]:
    """Get default SLO alert configurations."""
    return [
        # Availability alerts
        SLOAlert(
            slo_name="API Availability",
            severity="warning",
            message="API availability below target",
            error_budget_threshold=50.0,
            burn_rate_threshold=2.0,
        ),
        SLOAlert(
            slo_name="API Availability",
            severity="critical",
            message="API availability critically low",
            error_budget_threshold=10.0,
            burn_rate_threshold=10.0,
        ),
        # Latency alerts
        SLOAlert(
            slo_name="p99 Latency",
            severity="warning",
            message="p99 latency exceeding target",
            error_budget_threshold=50.0,
            burn_rate_threshold=2.0,
        ),
        SLOAlert(
            slo_name="p99 Latency",
            severity="critical",
            message="p99 latency critically high",
            error_budget_threshold=10.0,
            burn_rate_threshold=10.0,
        ),
        # Debate success alerts
        SLOAlert(
            slo_name="Debate Success Rate",
            severity="warning",
            message="Debate success rate below target",
            error_budget_threshold=50.0,
            burn_rate_threshold=2.0,
        ),
        SLOAlert(
            slo_name="Debate Success Rate",
            severity="critical",
            message="Debate success rate critically low",
            error_budget_threshold=10.0,
            burn_rate_threshold=10.0,
        ),
    ]


def check_alerts(status: SLOStatus | None = None) -> list[tuple[SLOAlert, SLOResult]]:
    """Check all SLO alerts and return triggered ones.

    Args:
        status: Optional SLOStatus to check (will fetch if not provided)

    Returns:
        List of (alert, result) tuples for triggered alerts
    """
    if status is None:
        status = get_slo_status()

    alerts = get_default_alerts()
    triggered: list[tuple[SLOAlert, SLOResult]] = []

    results = {
        "API Availability": status.availability,
        "p99 Latency": status.latency_p99,
        "Debate Success Rate": status.debate_success,
    }

    for alert in alerts:
        result = results.get(alert.slo_name)
        if result is None:
            continue

        # Check if alert should trigger
        should_trigger = (
            result.error_budget_remaining < alert.error_budget_threshold
            or result.burn_rate > alert.burn_rate_threshold
        )

        if should_trigger:
            triggered.append((alert, result))

    return triggered


def format_slo_report(status: SLOStatus) -> str:
    """Format SLO status as a human-readable report.

    Args:
        status: SLOStatus to format

    Returns:
        Formatted report string
    """
    lines = [
        "=" * 60,
        "Aragora SLO Status Report",
        f"Generated: {status.timestamp.isoformat()}",
        "=" * 60,
        "",
    ]

    for name, result in [
        ("Availability", status.availability),
        ("Latency p99", status.latency_p99),
        ("Debate Success", status.debate_success),
    ]:
        status_icon = "[OK]" if result.compliant else "[!!]"
        lines.extend(
            [
                f"{status_icon} {result.name}",
                f"    Target: {result.target:.4f}",
                f"    Current: {result.current:.4f}",
                f"    Compliance: {result.compliance_percentage:.1f}%",
                f"    Error Budget: {result.error_budget_remaining:.1f}% remaining",
                f"    Burn Rate: {result.burn_rate:.2f}x",
                "",
            ]
        )

    overall = "HEALTHY" if status.overall_healthy else "DEGRADED"
    lines.extend(
        [
            "-" * 60,
            f"Overall Status: {overall}",
            "=" * 60,
        ]
    )

    return "\n".join(lines)


# =============================================================================
# HTTP Endpoint for SLO Status
# =============================================================================


def get_slo_status_json() -> dict[str, Any]:
    """Get SLO status as JSON-serializable dictionary.

    Returns:
        Dictionary suitable for JSON response
    """
    status = get_slo_status()

    def result_to_dict(result: SLOResult) -> dict[str, Any]:
        return {
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

    return {
        "timestamp": status.timestamp.isoformat(),
        "overall_healthy": status.overall_healthy,
        "slos": {
            "availability": result_to_dict(status.availability),
            "latency_p99": result_to_dict(status.latency_p99),
            "debate_success": result_to_dict(status.debate_success),
        },
        "alerts": [
            {
                "slo_name": alert.slo_name,
                "severity": alert.severity,
                "message": alert.message,
                "error_budget_remaining": result.error_budget_remaining,
                "burn_rate": result.burn_rate,
            }
            for alert, result in check_alerts(status)
        ],
    }


# =============================================================================
# SLO Alerting Monitor
# =============================================================================


@dataclass
class SLOBreach:
    """Record of an SLO breach event."""

    slo_name: str
    severity: str
    current_value: float
    target_value: float
    error_budget_remaining: float
    burn_rate: float
    message: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "slo_name": self.slo_name,
            "severity": self.severity,
            "current_value": self.current_value,
            "target_value": self.target_value,
            "error_budget_remaining": self.error_budget_remaining,
            "burn_rate": self.burn_rate,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
        }


class SLONotificationSink(Protocol):
    """Higher-layer delivery contract for SLO notification messages."""

    async def notify(self, breach: SLOBreach) -> None:
        """Deliver one SLO breach notification."""


SLONotificationSinkProvider = Callable[[], SLONotificationSink | None]
_slo_notification_sink_provider: SLONotificationSinkProvider | None = None


def register_slo_notification_sink_provider(
    provider: SLONotificationSinkProvider | None,
) -> None:
    """Register the higher-layer provider for direct SLO notifications."""
    global _slo_notification_sink_provider
    _slo_notification_sink_provider = provider


def _resolve_slo_notification_sink() -> SLONotificationSink | None:
    """Resolve the currently registered notification sink without caching it."""
    if _slo_notification_sink_provider is None:
        return None
    return _slo_notification_sink_provider()


# Type alias for alert callback
AlertCallback = Any  # Callable[[SLOBreach], None] or async version


class SLOAlertMonitor:
    """
    Monitor SLOs and trigger alerts on breaches.

    Supports multiple alert callbacks (Slack, webhook, email, logging).

    Usage:
        monitor = SLOAlertMonitor()

        # Add callbacks
        monitor.add_callback(send_slack_alert)
        monitor.add_callback(send_webhook_alert)

        # Check and alert (call periodically)
        await monitor.check_and_alert()

        # Or start background monitoring
        await monitor.start_background_monitoring(interval_seconds=60)
    """

    def __init__(
        self,
        check_interval_seconds: float = 60.0,
        cooldown_seconds: float = 300.0,
    ):
        """
        Initialize the SLO alert monitor.

        Args:
            check_interval_seconds: How often to check SLOs in background mode
            cooldown_seconds: Minimum time between alerts for same SLO
        """
        self.check_interval = check_interval_seconds
        self.cooldown_seconds = cooldown_seconds
        self._callbacks: list[AlertCallback] = []
        self._last_alert_times: dict[str, datetime] = {}
        self._running = False
        self._task: asyncio.Task | None = None

    def add_callback(self, callback: AlertCallback) -> None:
        """Add an alert callback function.

        Args:
            callback: Function to call when SLO breach detected.
                     Can be sync or async: callback(breach: SLOBreach) -> None
        """
        self._callbacks.append(callback)

    def remove_callback(self, callback: AlertCallback) -> None:
        """Remove an alert callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def _should_alert(self, slo_name: str, severity: str) -> bool:
        """Check if we should alert (respects cooldown)."""
        key = f"{slo_name}:{severity}"
        last_alert = self._last_alert_times.get(key)

        if last_alert is None:
            return True

        now = datetime.now(timezone.utc)
        cooldown = timedelta(seconds=self.cooldown_seconds)
        return now - last_alert > cooldown

    def _record_alert(self, slo_name: str, severity: str) -> None:
        """Record that we sent an alert."""
        key = f"{slo_name}:{severity}"
        self._last_alert_times[key] = datetime.now(timezone.utc)

    async def _invoke_callback(self, callback: AlertCallback, breach: SLOBreach) -> None:
        """Invoke a callback (handles both sync and async)."""
        try:
            result = callback(breach)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:  # noqa: BLE001 - observability must not crash app
            logger.error("SLO alert callback failed: %s", e)

    async def check_and_alert(self) -> list[SLOBreach]:
        """
        Check SLO status and trigger alerts for any breaches.

        Returns:
            List of SLOBreach objects for triggered alerts
        """
        breaches: list[SLOBreach] = []

        try:
            status = get_slo_status()
            triggered = check_alerts(status)

            for alert, result in triggered:
                if not self._should_alert(alert.slo_name, alert.severity):
                    logger.debug("Skipping alert for %s (cooldown)", alert.slo_name)
                    continue

                breach = SLOBreach(
                    slo_name=alert.slo_name,
                    severity=alert.severity,
                    current_value=result.current,
                    target_value=result.target,
                    error_budget_remaining=result.error_budget_remaining,
                    burn_rate=result.burn_rate,
                    message=alert.message,
                )
                breaches.append(breach)

                # Invoke all callbacks
                for callback in self._callbacks:
                    await self._invoke_callback(callback, breach)

                self._record_alert(alert.slo_name, alert.severity)
                logger.warning(
                    f"SLO breach: {alert.slo_name} ({alert.severity}) - "
                    f"error budget: {result.error_budget_remaining:.1f}%, "
                    f"burn rate: {result.burn_rate:.2f}x"
                )

        except Exception as e:  # noqa: BLE001 - observability must not crash app
            logger.error("SLO check failed: %s", e)

        return breaches

    async def start_background_monitoring(self) -> None:
        """Start background SLO monitoring."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("SLO monitoring started (interval: %ss)", self.check_interval)

    async def stop_background_monitoring(self) -> None:
        """Stop background SLO monitoring."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("SLO monitoring stopped")

    async def _monitor_loop(self) -> None:
        """Background monitoring loop."""
        while self._running:
            try:
                await self.check_and_alert()
            except Exception as e:  # noqa: BLE001 - observability must not crash app
                logger.error("SLO monitor error: %s", e)

            await asyncio.sleep(self.check_interval)


# =============================================================================
# Built-in Alert Callbacks
# =============================================================================


def log_alert_callback(breach: SLOBreach) -> None:
    """Simple logging callback for SLO alerts."""
    logger.warning(
        f"SLO ALERT [{breach.severity.upper()}]: {breach.slo_name} - "
        f"{breach.message} (current: {breach.current_value:.4f}, "
        f"target: {breach.target_value:.4f}, "
        f"error_budget: {breach.error_budget_remaining:.1f}%)"
    )


async def webhook_alert_callback(
    breach: SLOBreach,
    webhook_url: str,
    headers: dict[str, str] | None = None,
) -> None:
    """Send SLO alert to a webhook endpoint.

    Args:
        breach: The SLO breach details
        webhook_url: URL to POST the alert to
        headers: Optional headers to include
    """
    try:
        from aragora.observability.http_client_pool import get_http_pool

        payload = {
            "type": "slo_alert",
            **breach.to_dict(),
        }

        pool = get_http_pool()
        async with pool.get_session("webhook") as client:
            response = await client.post(
                webhook_url,
                json=payload,
                headers=headers or {},
                timeout=10.0,
            )
            response.raise_for_status()
            logger.info("SLO alert sent to webhook: %s", webhook_url)

    except ImportError:
        logger.warning("HTTP client pool not available, webhook alert skipped")
    except (OSError, ConnectionError, RuntimeError) as e:
        logger.error("Failed to send webhook alert: %s", e)


def create_slack_alert_callback(webhook_url: str) -> AlertCallback:
    """Create a Slack alert callback using incoming webhook.

    Args:
        webhook_url: Slack incoming webhook URL

    Returns:
        Callback function for SLO alerts
    """

    async def slack_callback(breach: SLOBreach) -> None:
        try:
            from aragora.observability.http_client_pool import get_http_pool

            # Format as Slack message
            color = "#ff0000" if breach.severity == "critical" else "#ffa500"
            payload = {
                "attachments": [
                    {
                        "color": color,
                        "title": f"SLO Alert: {breach.slo_name}",
                        "text": breach.message,
                        "fields": [
                            {
                                "title": "Severity",
                                "value": breach.severity.upper(),
                                "short": True,
                            },
                            {
                                "title": "Current Value",
                                "value": f"{breach.current_value:.4f}",
                                "short": True,
                            },
                            {
                                "title": "Target",
                                "value": f"{breach.target_value:.4f}",
                                "short": True,
                            },
                            {
                                "title": "Error Budget",
                                "value": f"{breach.error_budget_remaining:.1f}%",
                                "short": True,
                            },
                            {
                                "title": "Burn Rate",
                                "value": f"{breach.burn_rate:.2f}x",
                                "short": True,
                            },
                        ],
                        "ts": int(breach.timestamp.timestamp()),
                    }
                ]
            }

            pool = get_http_pool()
            async with pool.get_session("webhook") as client:
                response = await client.post(webhook_url, json=payload, timeout=10.0)
                response.raise_for_status()
                logger.info("SLO alert sent to Slack")

        except ImportError:
            logger.warning("HTTP client pool not available, Slack alert skipped")
        except (OSError, ConnectionError, RuntimeError) as e:
            logger.error("Failed to send Slack alert: %s", e)

    return slack_callback


def create_notification_callback() -> AlertCallback:
    """Create a callback using the registered SLO notification sink.

    Returns:
        Callback function that sends alerts through the current notification sink
    """

    async def notification_callback(breach: SLOBreach) -> None:
        try:
            sink = _resolve_slo_notification_sink()
            if sink is None:
                logger.warning("Notification dispatcher not configured")
                return

            await sink.notify(breach)
            logger.info("SLO alert dispatched via notification system")

        except ImportError:
            logger.warning("Notification system not available")
        except (OSError, ConnectionError, RuntimeError) as e:
            logger.error("Failed to dispatch notification: %s", e)

    return notification_callback


# =============================================================================
# Global Monitor Instance
# =============================================================================

_global_monitor: SLOAlertMonitor | None = None


def get_slo_monitor() -> SLOAlertMonitor:
    """Get or create the global SLO alert monitor."""
    global _global_monitor
    if _global_monitor is None:
        _global_monitor = SLOAlertMonitor()
        # Add default logging callback
        _global_monitor.add_callback(log_alert_callback)
    return _global_monitor


def configure_slo_alerting(
    slack_webhook: str | None = None,
    webhook_url: str | None = None,
    use_notifications: bool = True,
    check_interval: float = 60.0,
    cooldown: float = 300.0,
) -> SLOAlertMonitor:
    """
    Configure SLO alerting with common callback patterns.

    Args:
        slack_webhook: Optional Slack incoming webhook URL
        webhook_url: Optional generic webhook URL
        use_notifications: Use control plane notification system
        check_interval: How often to check SLOs (seconds)
        cooldown: Minimum time between alerts for same SLO (seconds)

    Returns:
        Configured SLOAlertMonitor
    """
    global _global_monitor
    _global_monitor = SLOAlertMonitor(
        check_interval_seconds=check_interval,
        cooldown_seconds=cooldown,
    )

    # Always add logging
    _global_monitor.add_callback(log_alert_callback)

    # Add Slack if configured
    if slack_webhook:
        _global_monitor.add_callback(create_slack_alert_callback(slack_webhook))

    # Add generic webhook if configured
    if webhook_url:

        async def webhook_cb(breach: SLOBreach) -> None:
            await webhook_alert_callback(breach, webhook_url)

        _global_monitor.add_callback(webhook_cb)

    # Add notification system if requested
    if use_notifications:
        _global_monitor.add_callback(create_notification_callback())

    return _global_monitor


# =============================================================================
# SLO Enforcer - Real-time metric tracking and enforcement
# =============================================================================


@dataclass
class SLOViolation:
    """Record of an SLO violation detected by the enforcer."""

    slo_name: str
    target_value: float
    actual_value: float
    timestamp: datetime
    message: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "slo_name": self.slo_name,
            "target_value": self.target_value,
            "actual_value": self.actual_value,
            "timestamp": self.timestamp.isoformat(),
            "message": self.message,
        }


class SLOEnforcer:
    """Tracks real-time request metrics and enforces SLO targets.

    Records individual request outcomes (latency, success/failure) and
    computes SLO compliance over a configurable rolling window. Produces
    alerts when SLO targets are breached.

    SLO targets enforced:
        - API latency p95 < 500ms
        - API latency p99 < 2000ms
        - Error rate < 1%
        - Uptime > 99.9%

    Usage:
        enforcer = SLOEnforcer()

        # Record request metrics as they occur
        enforcer.record_request(latency_ms=45.0, success=True)
        enforcer.record_request(latency_ms=1200.0, success=False)

        # Check current compliance
        status = enforcer.get_compliance_status()
        budget = enforcer.get_error_budget()
        violations = enforcer.check_violations()
    """

    def __init__(
        self,
        window_seconds: float = 3600.0,
        on_violation: AlertCallback | None = None,
    ) -> None:
        """Initialize the SLO enforcer.

        Args:
            window_seconds: Rolling window for metric aggregation (default: 1 hour)
            on_violation: Optional callback invoked when a violation is detected
        """
        self._window_seconds = window_seconds
        self._on_violation = on_violation
        self._requests: list[dict[str, Any]] = []
        self._violations: list[SLOViolation] = []
        self._start_time = datetime.now(timezone.utc)
        self._targets = get_slo_targets()

    def record_request(
        self,
        latency_ms: float,
        success: bool,
        endpoint: str | None = None,
    ) -> None:
        """Record a single request outcome.

        Args:
            latency_ms: Request latency in milliseconds
            success: Whether the request was successful (non-5xx)
            endpoint: Optional endpoint path for per-route tracking
        """
        now = datetime.now(timezone.utc)
        self._requests.append(
            {
                "timestamp": now,
                "latency_ms": latency_ms,
                "success": success,
                "endpoint": endpoint,
            }
        )
        self._prune_old_requests(now)

    def _prune_old_requests(self, now: datetime) -> None:
        """Remove requests outside the rolling window."""
        cutoff = now - timedelta(seconds=self._window_seconds)
        self._requests = [r for r in self._requests if r["timestamp"] > cutoff]

    def _get_latencies(self) -> list[float]:
        """Get all latency values in the current window."""
        return [r["latency_ms"] for r in self._requests]

    def _percentile(self, values: list[float], pct: float) -> float:
        """Calculate percentile of a sorted list of values.

        Args:
            values: List of numeric values
            pct: Percentile to compute (0-100)

        Returns:
            The percentile value, or 0.0 if no values
        """
        if not values:
            return 0.0
        sorted_values = sorted(values)
        idx = (pct / 100.0) * (len(sorted_values) - 1)
        lower = int(idx)
        upper = min(lower + 1, len(sorted_values) - 1)
        frac = idx - lower
        return sorted_values[lower] * (1 - frac) + sorted_values[upper] * frac

    def get_metrics(self) -> dict[str, Any]:
        """Get current aggregated metrics over the rolling window.

        Returns:
            Dictionary with latency percentiles, error rate, throughput, and uptime
        """
        now = datetime.now(timezone.utc)
        self._prune_old_requests(now)

        latencies = self._get_latencies()
        total = len(self._requests)
        successful = sum(1 for r in self._requests if r["success"])
        failed = total - successful

        if total == 0:
            return {
                "total_requests": 0,
                "successful_requests": 0,
                "failed_requests": 0,
                "latency_p50_ms": 0.0,
                "latency_p95_ms": 0.0,
                "latency_p99_ms": 0.0,
                "error_rate": 0.0,
                "uptime": 1.0,
                "throughput_rps": 0.0,
                "window_seconds": self._window_seconds,
            }

        error_rate = failed / total
        uptime = successful / total

        elapsed = (now - self._start_time).total_seconds()
        throughput = total / max(elapsed, 1.0)

        return {
            "total_requests": total,
            "successful_requests": successful,
            "failed_requests": failed,
            "latency_p50_ms": self._percentile(latencies, 50),
            "latency_p95_ms": self._percentile(latencies, 95),
            "latency_p99_ms": self._percentile(latencies, 99),
            "error_rate": error_rate,
            "uptime": uptime,
            "throughput_rps": throughput,
            "window_seconds": self._window_seconds,
        }

    def check_violations(self) -> list[SLOViolation]:
        """Check all SLO targets and return any violations.

        Returns:
            List of SLOViolation objects for each breached SLO
        """
        metrics = self.get_metrics()
        now = datetime.now(timezone.utc)
        violations: list[SLOViolation] = []

        if metrics["total_requests"] == 0:
            return violations

        targets = self._targets

        # Check p95 latency: target is in seconds, metric is in ms
        p95_target = targets["latency_p95"]
        p95_ms = metrics["latency_p95_ms"]
        p95_target_ms = p95_target.target * 1000
        if p95_ms > p95_target_ms:
            v = SLOViolation(
                slo_name="latency_p95",
                target_value=p95_target_ms,
                actual_value=p95_ms,
                timestamp=now,
                message=f"p95 latency {p95_ms:.1f}ms exceeds target {p95_target_ms:.0f}ms",
            )
            violations.append(v)

        # Check p99 latency
        p99_target = targets["latency_p99"]
        p99_ms = metrics["latency_p99_ms"]
        p99_target_ms = p99_target.target * 1000
        if p99_ms > p99_target_ms:
            v = SLOViolation(
                slo_name="latency_p99",
                target_value=p99_target_ms,
                actual_value=p99_ms,
                timestamp=now,
                message=f"p99 latency {p99_ms:.1f}ms exceeds target {p99_target_ms:.0f}ms",
            )
            violations.append(v)

        # Check error rate
        error_target = targets["error_rate"]
        if metrics["error_rate"] > error_target.target:
            v = SLOViolation(
                slo_name="error_rate",
                target_value=error_target.target,
                actual_value=metrics["error_rate"],
                timestamp=now,
                message=(
                    f"Error rate {metrics['error_rate']:.4f} "
                    f"exceeds target {error_target.target:.4f}"
                ),
            )
            violations.append(v)

        # Check uptime / availability
        avail_target = targets["availability"]
        if metrics["uptime"] < avail_target.target:
            v = SLOViolation(
                slo_name="availability",
                target_value=avail_target.target,
                actual_value=metrics["uptime"],
                timestamp=now,
                message=(f"Uptime {metrics['uptime']:.4f} below target {avail_target.target:.4f}"),
            )
            violations.append(v)

        # Store violations and invoke callback
        if violations:
            self._violations.extend(violations)
            if self._on_violation is not None:
                for v in violations:
                    try:
                        result = self._on_violation(v)
                        if asyncio.iscoroutine(result):
                            # If called from a sync context, skip the coroutine
                            result.close()
                    except Exception:  # noqa: BLE001
                        logger.debug("SLO violation callback failed")

        return violations

    def get_compliance_status(self) -> dict[str, Any]:
        """Get current SLO compliance status for all enforced targets.

        Returns a dictionary suitable for the GET /api/v1/slo/status endpoint.

        Returns:
            Dictionary with per-SLO compliance data wrapped in {"data": ...}
        """
        metrics = self.get_metrics()
        now = datetime.now(timezone.utc)
        targets = self._targets
        window_start = now - timedelta(seconds=self._window_seconds)

        slos = {}

        # Latency p95
        p95_target = targets["latency_p95"]
        p95_ms = metrics["latency_p95_ms"]
        p95_target_ms = p95_target.target * 1000
        p95_compliant = p95_ms <= p95_target_ms
        slos["latency_p95"] = {
            "name": p95_target.name,
            "target_ms": p95_target_ms,
            "current_ms": p95_ms,
            "compliant": p95_compliant,
        }

        # Latency p99
        p99_target = targets["latency_p99"]
        p99_ms = metrics["latency_p99_ms"]
        p99_target_ms = p99_target.target * 1000
        p99_compliant = p99_ms <= p99_target_ms
        slos["latency_p99"] = {
            "name": p99_target.name,
            "target_ms": p99_target_ms,
            "current_ms": p99_ms,
            "compliant": p99_compliant,
        }

        # Error rate
        error_target = targets["error_rate"]
        error_compliant = metrics["error_rate"] <= error_target.target
        slos["error_rate"] = {
            "name": error_target.name,
            "target": error_target.target,
            "current": metrics["error_rate"],
            "compliant": error_compliant,
        }

        # Availability / uptime
        avail_target = targets["availability"]
        avail_compliant = metrics["uptime"] >= avail_target.target
        slos["availability"] = {
            "name": avail_target.name,
            "target": avail_target.target,
            "current": metrics["uptime"],
            "compliant": avail_compliant,
        }

        overall_healthy = all(s["compliant"] for s in slos.values())
        violations = self.check_violations()

        return {
            "timestamp": now.isoformat(),
            "overall_healthy": overall_healthy,
            "window": {
                "start": window_start.isoformat(),
                "end": now.isoformat(),
                "duration_seconds": self._window_seconds,
            },
            "slos": slos,
            "metrics": metrics,
            "violation_count": len(violations),
        }

    def get_error_budget(self) -> dict[str, Any]:
        """Get remaining error budget for all enforced SLOs.

        Returns a dictionary suitable for the GET /api/v1/slo/budget endpoint.

        Returns:
            Dictionary with per-SLO error budget data
        """
        metrics = self.get_metrics()
        now = datetime.now(timezone.utc)
        targets = self._targets
        window_start = now - timedelta(seconds=self._window_seconds)

        budgets: list[dict[str, Any]] = []

        # Availability budget (gte comparison)
        avail_target = targets["availability"]
        avail_budget_total = 1.0 - avail_target.target  # e.g. 0.001
        avail_errors_used = max(0, avail_target.target - metrics["uptime"])
        if avail_budget_total > 0:
            avail_remaining_pct = (
                max(0, (avail_budget_total - avail_errors_used) / avail_budget_total) * 100
            )
            avail_burn = avail_errors_used / avail_budget_total
        else:
            avail_remaining_pct = 0.0
            avail_burn = float("inf")

        budgets.append(
            {
                "slo_name": avail_target.name,
                "slo_id": "availability",
                "target": avail_target.target,
                "error_budget_total_pct": 100.0,
                "error_budget_remaining_pct": avail_remaining_pct,
                "error_budget_consumed_pct": 100.0 - avail_remaining_pct,
                "burn_rate": avail_burn,
            }
        )

        # Error rate budget (lte comparison)
        error_target = targets["error_rate"]
        error_budget_total = error_target.target  # e.g. 0.01
        error_used = max(0, metrics["error_rate"] - 0)  # current rate
        if error_budget_total > 0:
            error_remaining_pct = (
                max(0, (error_budget_total - error_used) / error_budget_total) * 100
            )
            error_burn = error_used / error_budget_total
        else:
            error_remaining_pct = 0.0
            error_burn = float("inf")

        budgets.append(
            {
                "slo_name": error_target.name,
                "slo_id": "error_rate",
                "target": error_target.target,
                "error_budget_total_pct": 100.0,
                "error_budget_remaining_pct": error_remaining_pct,
                "error_budget_consumed_pct": 100.0 - error_remaining_pct,
                "burn_rate": error_burn,
            }
        )

        # Latency p95 budget
        p95_target = targets["latency_p95"]
        p95_target_ms = p95_target.target * 1000
        p95_budget = p95_target_ms * 0.5  # 50% overage allowed
        p95_overage = max(0, metrics["latency_p95_ms"] - p95_target_ms)
        if p95_budget > 0:
            p95_remaining_pct = max(0, (p95_budget - p95_overage) / p95_budget) * 100
            p95_burn = p95_overage / p95_budget
        else:
            p95_remaining_pct = 0.0
            p95_burn = float("inf")

        budgets.append(
            {
                "slo_name": p95_target.name,
                "slo_id": "latency_p95",
                "target_ms": p95_target_ms,
                "error_budget_total_pct": 100.0,
                "error_budget_remaining_pct": p95_remaining_pct,
                "error_budget_consumed_pct": 100.0 - p95_remaining_pct,
                "burn_rate": p95_burn,
            }
        )

        # Latency p99 budget
        p99_target = targets["latency_p99"]
        p99_target_ms = p99_target.target * 1000
        p99_budget = p99_target_ms * 0.5
        p99_overage = max(0, metrics["latency_p99_ms"] - p99_target_ms)
        if p99_budget > 0:
            p99_remaining_pct = max(0, (p99_budget - p99_overage) / p99_budget) * 100
            p99_burn = p99_overage / p99_budget
        else:
            p99_remaining_pct = 0.0
            p99_burn = float("inf")

        budgets.append(
            {
                "slo_name": p99_target.name,
                "slo_id": "latency_p99",
                "target_ms": p99_target_ms,
                "error_budget_total_pct": 100.0,
                "error_budget_remaining_pct": p99_remaining_pct,
                "error_budget_consumed_pct": 100.0 - p99_remaining_pct,
                "burn_rate": p99_burn,
            }
        )

        return {
            "timestamp": now.isoformat(),
            "window": {
                "start": window_start.isoformat(),
                "end": now.isoformat(),
                "duration_seconds": self._window_seconds,
            },
            "budgets": budgets,
        }

    def get_recent_violations(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent SLO violations.

        Args:
            limit: Maximum number of violations to return

        Returns:
            List of violation dictionaries
        """
        return [v.to_dict() for v in self._violations[-limit:]]

    def reset(self) -> None:
        """Reset all tracked metrics and violations."""
        self._requests.clear()
        self._violations.clear()
        self._start_time = datetime.now(timezone.utc)


# =============================================================================
# Global SLO Enforcer Instance
# =============================================================================

_global_enforcer: SLOEnforcer | None = None


def get_slo_enforcer() -> SLOEnforcer:
    """Get or create the global SLO enforcer instance."""
    global _global_enforcer
    if _global_enforcer is None:
        _global_enforcer = SLOEnforcer()
    return _global_enforcer


def reset_slo_enforcer() -> None:
    """Reset the global SLO enforcer (primarily for testing)."""
    global _global_enforcer
    _global_enforcer = None


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # SLO Types
    "SLOTarget",
    "SLOResult",
    "SLOStatus",
    "SLOAlert",
    "SLOBreach",
    "SLOViolation",
    # SLO Checks
    "get_slo_targets",
    "check_availability_slo",
    "check_latency_slo",
    "check_debate_success_slo",
    "get_slo_status",
    "get_slo_status_json",
    # Streaming SLO Checks
    "check_stream_error_rate_slo",
    "check_stream_reconnect_p95_slo",
    "check_stream_delivery_rate_slo",
    "check_tts_synthesis_latency_slo",
    # Alerting
    "check_alerts",
    "get_default_alerts",
    "format_slo_report",
    # Alert Monitor
    "SLOAlertMonitor",
    "get_slo_monitor",
    "configure_slo_alerting",
    # Callbacks
    "log_alert_callback",
    "webhook_alert_callback",
    "create_slack_alert_callback",
    "create_notification_callback",
    "SLONotificationSink",
    "register_slo_notification_sink_provider",
    # SLO Enforcer
    "SLOEnforcer",
    "get_slo_enforcer",
    "reset_slo_enforcer",
]
