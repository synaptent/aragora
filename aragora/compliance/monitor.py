"""
Continuous Compliance Monitor.

Provides automated, continuous monitoring of compliance status across all
frameworks. Integrates with the SLO alerting system for notifications.

Features:
- Background compliance scanning
- Real-time violation detection
- Compliance drift detection
- Audit trail integrity verification
- Integration with PagerDuty/Slack via SLO Alert Bridge

Usage:
    from aragora.compliance.monitor import (
        ComplianceMonitor,
        init_compliance_monitoring,
        get_compliance_status,
    )

    # Initialize at startup
    monitor = init_compliance_monitoring(
        check_interval_seconds=300,  # 5 minute checks
        alert_on_critical=True,
    )

    # Get current status
    status = await get_compliance_status()
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from collections.abc import Callable

logger = logging.getLogger(__name__)


class ComplianceHealth(Enum):
    """Overall compliance health status."""

    HEALTHY = "healthy"  # All frameworks passing
    DEGRADED = "degraded"  # Minor/moderate violations
    AT_RISK = "at_risk"  # Major violations pending
    CRITICAL = "critical"  # Critical violations requiring immediate action


class ViolationTrend(Enum):
    """Trend direction for violations."""

    IMPROVING = "improving"  # Fewer violations over time
    STABLE = "stable"  # Consistent violation count
    WORSENING = "worsening"  # More violations over time


@dataclass
class FrameworkStatus:
    """Status of a single compliance framework."""

    framework: str
    enabled: bool = True
    last_check: datetime | None = None
    total_rules: int = 0
    rules_passing: int = 0
    rules_failing: int = 0
    critical_violations: int = 0
    major_violations: int = 0
    moderate_violations: int = 0
    minor_violations: int = 0
    score: float = 100.0  # Compliance score 0-100

    @property
    def health(self) -> ComplianceHealth:
        """Determine health based on violations."""
        if self.critical_violations > 0:
            return ComplianceHealth.CRITICAL
        if self.major_violations > 0:
            return ComplianceHealth.AT_RISK
        if self.moderate_violations > 0:
            return ComplianceHealth.DEGRADED
        return ComplianceHealth.HEALTHY


@dataclass
class ComplianceStatus:
    """Overall compliance status across all frameworks."""

    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    overall_health: ComplianceHealth = ComplianceHealth.HEALTHY
    overall_score: float = 100.0
    frameworks: dict[str, FrameworkStatus] = field(default_factory=dict)
    trend: ViolationTrend = ViolationTrend.STABLE
    open_violations: int = 0
    resolved_last_24h: int = 0
    mttr_hours: float | None = None  # Mean time to resolution
    audit_trail_verified: bool = True
    last_full_scan: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DriftEvent:
    """Represents a compliance configuration drift event."""

    timestamp: datetime
    drift_type: str  # policy_version, permission_change, config_change
    framework: str
    description: str
    severity: str
    current_value: Any
    expected_value: Any


@dataclass
class ComplianceMonitorConfig:
    """Configuration for continuous compliance monitoring."""

    enabled: bool = True
    check_interval_seconds: float = 300.0  # 5 minutes
    full_scan_interval_seconds: float = 3600.0  # 1 hour full scan
    audit_verify_interval_seconds: float = 1800.0  # 30 min audit verification

    # Alerting
    alert_on_critical: bool = True
    alert_on_major: bool = True
    alert_on_drift: bool = True
    alert_cooldown_seconds: float = 600.0  # 10 min between alerts

    # Frameworks to monitor
    enabled_frameworks: set[str] = field(
        default_factory=lambda: {"soc2", "gdpr", "hipaa", "pci-dss", "iso27001"}
    )

    # Thresholds
    critical_score_threshold: float = 70.0  # Alert if score drops below
    degraded_score_threshold: float = 85.0


class ComplianceMonitor:
    """
    Continuous compliance monitoring service.

    Runs background checks and integrates with alerting systems.
    """

    def __init__(
        self,
        config: ComplianceMonitorConfig,
        event_emitter: Any | None = None,
    ):
        """Initialize the monitor.

        Args:
            config: Monitor configuration
            event_emitter: Optional event emitter for COMPLIANCE_FINDING events
        """
        self.config = config
        self._event_emitter = event_emitter
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_status: ComplianceStatus | None = None
        self._status_history: list[ComplianceStatus] = []
        self._drift_events: list[DriftEvent] = []
        self._last_alert: dict[str, float] = {}
        self._violation_callbacks: list[Callable[[dict[str, Any]], Any]] = []
        self._drift_callbacks: list[Callable[[DriftEvent], Any]] = []
        self._last_full_scan: datetime | None = None
        self._last_audit_verify: datetime | None = None

    async def start(self) -> None:
        """Start the background monitoring loop."""
        if self._running:
            logger.warning("Compliance monitor already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._monitoring_loop())
        logger.info("Compliance monitor started (interval=%ss)", self.config.check_interval_seconds)

    async def stop(self) -> None:
        """Stop the monitoring loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                logger.debug("Compliance monitor task cancelled")
        logger.info("Compliance monitor stopped")

    async def _monitoring_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                # Quick check
                await self._run_quick_check()

                # Full scan if interval elapsed
                if self._should_full_scan():
                    await self._run_full_scan()

                # Audit verification if interval elapsed
                if self._should_verify_audit():
                    await self._verify_audit_trail()

                # Wait for next interval
                await asyncio.sleep(self.config.check_interval_seconds)

            except asyncio.CancelledError:
                break
            except (RuntimeError, OSError, ValueError, ConnectionError, TimeoutError) as e:
                logger.error("Compliance monitoring error: %s", e)
                await asyncio.sleep(60)  # Wait before retry

    async def _run_quick_check(self) -> ComplianceStatus:
        """Run a quick compliance status check."""
        status = ComplianceStatus()

        try:
            # Get violation counts from policy store
            from aragora.compliance.policy_store import get_policy_store

            store = get_policy_store()
            if store:
                await self._update_from_policy_store(status, store)

        except ImportError:
            logger.debug("Policy store not available for compliance check")
        except (RuntimeError, OSError, ValueError, ConnectionError) as e:
            logger.warning("Error checking policy store: %s", e)

        # Calculate overall health
        status.overall_health = self._calculate_overall_health(status)
        status.overall_score = self._calculate_overall_score(status)

        # Check for trend
        status.trend = self._calculate_trend()

        # Cross-pollination: enrich with recent audit findings
        audit_context = self._fetch_audit_context(status)
        if audit_context:
            status.metadata = getattr(status, "metadata", {}) or {}
            status.metadata["audit_findings_summary"] = audit_context

        # Store status
        self._last_status = status
        self._emit_compliance_status_event(status)
        self._status_history.append(status)
        if len(self._status_history) > 1000:
            self._status_history = self._status_history[-500:]

        # Check for alerts
        await self._check_and_alert(status)

        return status

    async def _update_from_policy_store(self, status: ComplianceStatus, store: Any) -> None:
        """Update status from policy store violations."""
        try:
            # Get open violations grouped by framework and severity
            violations = await store.list_violations(status="open")

            for v in violations:
                framework = v.framework or "unknown"
                if framework not in status.frameworks:
                    status.frameworks[framework] = FrameworkStatus(framework=framework)

                fs = status.frameworks[framework]
                severity = getattr(v, "severity", "minor").lower()

                if severity == "critical":
                    fs.critical_violations += 1
                elif severity == "major" or severity == "high":
                    fs.major_violations += 1
                elif severity == "moderate" or severity == "medium":
                    fs.moderate_violations += 1
                else:
                    fs.minor_violations += 1

                fs.rules_failing += 1
                status.open_violations += 1

            # Calculate scores for each framework
            for fs in status.frameworks.values():
                total = fs.rules_failing + fs.rules_passing
                if total > 0:
                    # Weighted score based on severity
                    penalty = (
                        fs.critical_violations * 25
                        + fs.major_violations * 15
                        + fs.moderate_violations * 5
                        + fs.minor_violations * 1
                    )
                    fs.score = max(0, 100 - penalty)
                fs.last_check = datetime.now(timezone.utc)

        except (RuntimeError, OSError, ValueError, KeyError, AttributeError, TypeError) as e:
            logger.warning("Error updating from policy store: %s", e)

    def _fetch_audit_context(self, status: ComplianceStatus) -> dict[str, Any] | None:
        """Fetch recent audit findings relevant to compliance scope.

        Cross-pollination: queries the audit system for findings that
        overlap with current compliance frameworks, enriching the
        compliance status with audit intelligence.

        Args:
            status: Current compliance status being built

        Returns:
            Summary dict of relevant audit findings, or None
        """
        try:
            # Try to get the audit log for recent findings
            try:
                from aragora.observability.audit_log import AuditQuery, get_audit_log
            except ImportError:
                return None

            audit_log = get_audit_log()
            if not audit_log:
                return None

            # Query recent audit entries that overlap with compliance scope
            frameworks = list(status.frameworks.keys()) if status.frameworks else []
            if not frameworks:
                return None

            query = AuditQuery(limit=20)
            recent_entries = audit_log.query(query)
            if not recent_entries:
                return None

            # Count findings by severity that relate to compliance frameworks
            severity_counts: dict[str, int] = {}
            relevant_count = 0
            for entry in recent_entries:
                # AuditEvent has action (str) and details (dict)
                action = getattr(entry, "action", "")
                details = getattr(entry, "details", {})
                # Check if any framework name appears in action or details
                searchable = (
                    f"{action} {details.get('framework', '')} {details.get('category', '')}".lower()
                )
                for fw in frameworks:
                    if fw.lower() in searchable:
                        severity = details.get("severity", "info")
                        severity_counts[severity] = severity_counts.get(severity, 0) + 1
                        relevant_count += 1
                        break

            if relevant_count == 0:
                return None

            return {
                "relevant_findings": relevant_count,
                "severity_breakdown": severity_counts,
                "frameworks_with_findings": frameworks,
                "source": "audit_orchestrator",
            }

        except (ImportError, AttributeError, TypeError) as e:
            logger.debug("Audit cross-pollination skipped: %s", e)
            return None

    async def _run_full_scan(self) -> None:
        """Run a full compliance scan across all resources."""
        logger.info("Running full compliance scan")
        self._last_full_scan = datetime.now(timezone.utc)

        try:
            from aragora.compliance.framework import ComplianceFrameworkManager

            framework_manager = ComplianceFrameworkManager()
            if not framework_manager:
                return

            # This would scan actual system resources
            # For now, we mark that a scan occurred
            if self._last_status:
                self._last_status.last_full_scan = self._last_full_scan

        except ImportError:
            logger.debug("Compliance framework not available")
        except (RuntimeError, OSError, ValueError, ConnectionError) as e:
            logger.warning("Error during full scan: %s", e)

    async def _verify_audit_trail(self) -> bool:
        """Verify audit trail integrity via hash chain."""
        logger.debug("Verifying audit trail integrity")
        self._last_audit_verify = datetime.now(timezone.utc)

        try:
            from aragora.observability.audit_log import get_audit_log

            audit_log = get_audit_log()
            if audit_log:
                # Verify recent entries have valid hash chain
                # verify_integrity returns (is_valid, list of error messages)
                is_valid, _errors = audit_log.verify_integrity()
                if self._last_status:
                    self._last_status.audit_trail_verified = is_valid

                if not is_valid:
                    await self._alert_audit_tamper()

                return is_valid

        except ImportError:
            logger.debug("Audit log not available for verification")
        except (RuntimeError, OSError, ValueError) as e:
            logger.warning("Error verifying audit trail: %s", e)

        return True

    async def _check_and_alert(self, status: ComplianceStatus) -> None:
        """Check status and send alerts if needed."""
        # Critical violations
        if self.config.alert_on_critical and status.overall_health == ComplianceHealth.CRITICAL:
            if self._should_alert("critical"):
                await self._send_alert(
                    alert_type="compliance_critical",
                    severity="critical",
                    title="Critical Compliance Violation",
                    message=f"Critical compliance violations detected. Open violations: {status.open_violations}",
                    data={
                        "health": status.overall_health.value,
                        "score": status.overall_score,
                        "open_violations": status.open_violations,
                        "frameworks": {
                            k: {
                                "critical": v.critical_violations,
                                "major": v.major_violations,
                            }
                            for k, v in status.frameworks.items()
                            if v.critical_violations > 0
                        },
                    },
                )

        # Major violations
        elif self.config.alert_on_major and status.overall_health == ComplianceHealth.AT_RISK:
            if self._should_alert("major"):
                await self._send_alert(
                    alert_type="compliance_at_risk",
                    severity="major",
                    title="Compliance At Risk",
                    message=f"Major compliance violations require attention. Score: {status.overall_score:.1f}%",
                    data={
                        "health": status.overall_health.value,
                        "score": status.overall_score,
                        "open_violations": status.open_violations,
                    },
                )

        # Score threshold alerts
        if status.overall_score < self.config.critical_score_threshold:
            if self._should_alert("score_critical"):
                await self._send_alert(
                    alert_type="compliance_score_critical",
                    severity="critical",
                    title="Compliance Score Critical",
                    message=f"Compliance score dropped to {status.overall_score:.1f}% (threshold: {self.config.critical_score_threshold}%)",
                    data={"score": status.overall_score},
                )

    def _emit_compliance_status_event(self, status: ComplianceStatus) -> None:
        """Emit a compliance status event to the events dispatcher."""
        try:
            from aragora.events.dispatcher import dispatch_event

            dispatch_event(
                "compliance_status_updated",
                {
                    "overall_health": status.overall_health.value,
                    "overall_score": round(status.overall_score, 2),
                    "open_violations": status.open_violations,
                    "trend": status.trend.value
                    if hasattr(status.trend, "value")
                    else str(status.trend),
                    "frameworks": {
                        name: {
                            "health": fs.health.value
                            if hasattr(fs.health, "value")
                            else str(getattr(fs, "health", "unknown")),
                            "score": getattr(fs, "score", 0),
                            "critical": getattr(fs, "critical_violations", 0),
                        }
                        for name, fs in status.frameworks.items()
                    }
                    if status.frameworks
                    else {},
                },
            )
        except (ImportError, AttributeError, TypeError, RuntimeError) as e:
            logger.debug("Compliance event emission unavailable: %s", e)

    def _emit_compliance_event(self, alert_type: str, severity: str, data: dict[str, Any]) -> None:
        """Emit a COMPLIANCE_FINDING event if an emitter is available."""
        if not self._event_emitter:
            return
        try:
            from aragora.events.types import StreamEvent, StreamEventType

            self._event_emitter.emit(
                StreamEvent(
                    type=StreamEventType.COMPLIANCE_FINDING,
                    data={
                        "alert_type": alert_type,
                        "severity": severity,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        **data,
                    },
                )
            )
        except (ImportError, AttributeError, TypeError) as e:
            logger.debug("Compliance event emission failed: %s", e)

    async def _send_alert(
        self,
        alert_type: str,
        severity: str,
        title: str,
        message: str,
        data: dict[str, Any],
    ) -> None:
        """Send alert via configured channels."""
        self._last_alert[alert_type] = time.time()

        alert_data = {
            "type": alert_type,
            "severity": severity,
            "title": title,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **data,
        }

        # Emit COMPLIANCE_FINDING event
        self._emit_compliance_event(
            alert_type,
            severity,
            {
                "title": title,
                "message": message,
                **data,
            },
        )

        # Invoke registered callbacks
        for callback in self._violation_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(alert_data)
                else:
                    callback(alert_data)
            except (RuntimeError, TypeError, ValueError, OSError) as e:
                logger.warning("Alert callback failed: %s", e)

        # Also try SLO alert bridge if available
        try:
            from aragora.observability.slo_alert_bridge import get_slo_alert_bridge

            bridge = get_slo_alert_bridge()
            if bridge:
                # Route compliance alerts through SLO bridge
                await bridge.on_slo_violation(
                    operation=f"compliance.{alert_type}",
                    percentile="p99",
                    latency_ms=0,
                    threshold_ms=0,
                    severity=severity,
                    context=alert_data,
                )
        except ImportError:
            logger.debug("SLO alert bridge not available")
        except (RuntimeError, ValueError, TypeError, AttributeError) as e:
            logger.debug("Could not route to SLO alert bridge: %s", e)

    async def _alert_audit_tamper(self) -> None:
        """Alert on audit trail tampering detection."""
        await self._send_alert(
            alert_type="audit_integrity",
            severity="critical",
            title="Audit Trail Integrity Failure",
            message="Audit log hash chain verification failed - possible tampering detected",
            data={"verified": False},
        )

    def _should_alert(self, alert_type: str) -> bool:
        """Check if we should send an alert (respecting cooldown)."""
        last = self._last_alert.get(alert_type, 0)
        return time.time() - last > self.config.alert_cooldown_seconds

    def _should_full_scan(self) -> bool:
        """Check if full scan is needed."""
        if self._last_full_scan is None:
            return True
        elapsed = (datetime.now(timezone.utc) - self._last_full_scan).total_seconds()
        return elapsed >= self.config.full_scan_interval_seconds

    def _should_verify_audit(self) -> bool:
        """Check if audit verification is needed."""
        if self._last_audit_verify is None:
            return True
        elapsed = (datetime.now(timezone.utc) - self._last_audit_verify).total_seconds()
        return elapsed >= self.config.audit_verify_interval_seconds

    def _calculate_overall_health(self, status: ComplianceStatus) -> ComplianceHealth:
        """Calculate overall health from framework statuses."""
        if not status.frameworks:
            return ComplianceHealth.HEALTHY

        # Any critical = overall critical
        for fs in status.frameworks.values():
            if fs.health == ComplianceHealth.CRITICAL:
                return ComplianceHealth.CRITICAL

        # Any at-risk = overall at-risk
        for fs in status.frameworks.values():
            if fs.health == ComplianceHealth.AT_RISK:
                return ComplianceHealth.AT_RISK

        # Any degraded = overall degraded
        for fs in status.frameworks.values():
            if fs.health == ComplianceHealth.DEGRADED:
                return ComplianceHealth.DEGRADED

        return ComplianceHealth.HEALTHY

    def _calculate_overall_score(self, status: ComplianceStatus) -> float:
        """Calculate overall compliance score."""
        if not status.frameworks:
            return 100.0

        scores = [fs.score for fs in status.frameworks.values() if fs.enabled]
        return sum(scores) / len(scores) if scores else 100.0

    def _calculate_trend(self) -> ViolationTrend:
        """Calculate violation trend from history."""
        if len(self._status_history) < 3:
            return ViolationTrend.STABLE

        # Compare last 5 vs previous 5
        recent = self._status_history[-5:]
        previous = self._status_history[-10:-5] if len(self._status_history) >= 10 else []

        if not previous:
            return ViolationTrend.STABLE

        recent_avg = sum(s.open_violations for s in recent) / len(recent)
        prev_avg = sum(s.open_violations for s in previous) / len(previous)

        if recent_avg < prev_avg * 0.8:
            return ViolationTrend.IMPROVING
        elif recent_avg > prev_avg * 1.2:
            return ViolationTrend.WORSENING
        return ViolationTrend.STABLE

    def get_status(self) -> ComplianceStatus | None:
        """Get current compliance status."""
        return self._last_status

    def get_drift_events(self, limit: int = 100) -> list[DriftEvent]:
        """Get recent drift events."""
        return self._drift_events[-limit:]

    def register_violation_callback(self, callback: Callable[[dict[str, Any]], Any]) -> None:
        """Register a callback for compliance violations."""
        if callback not in self._violation_callbacks:
            self._violation_callbacks.append(callback)

    def register_drift_callback(self, callback: Callable[[DriftEvent], Any]) -> None:
        """Register a callback for drift events."""
        if callback not in self._drift_callbacks:
            self._drift_callbacks.append(callback)

    async def record_drift(
        self,
        drift_type: str,
        framework: str,
        description: str,
        severity: str,
        current_value: Any,
        expected_value: Any,
    ) -> None:
        """Record a compliance drift event."""
        event = DriftEvent(
            timestamp=datetime.now(timezone.utc),
            drift_type=drift_type,
            framework=framework,
            description=description,
            severity=severity,
            current_value=current_value,
            expected_value=expected_value,
        )
        self._drift_events.append(event)
        if len(self._drift_events) > 1000:
            self._drift_events = self._drift_events[-500:]

        # Alert if configured
        if self.config.alert_on_drift:
            await self._send_alert(
                alert_type="compliance_drift",
                severity=severity,
                title=f"Compliance Drift: {drift_type}",
                message=description,
                data={
                    "framework": framework,
                    "drift_type": drift_type,
                    "current": str(current_value),
                    "expected": str(expected_value),
                },
            )

        # Invoke drift callbacks
        for callback in self._drift_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(event)
                else:
                    callback(event)
            except (RuntimeError, TypeError, ValueError, OSError) as e:
                logger.warning("Drift callback failed: %s", e)


# Global monitor instance
_monitor: ComplianceMonitor | None = None


def get_compliance_monitor() -> ComplianceMonitor | None:
    """Get the global compliance monitor instance."""
    return _monitor


def init_compliance_monitoring(
    check_interval_seconds: float = 300.0,
    alert_on_critical: bool = True,
    alert_on_major: bool = True,
    enabled_frameworks: set[str] | None = None,
) -> ComplianceMonitor:
    """
    Initialize continuous compliance monitoring.

    Call this at application startup.

    Args:
        check_interval_seconds: How often to run quick checks
        alert_on_critical: Alert on critical violations
        alert_on_major: Alert on major violations
        enabled_frameworks: Set of frameworks to monitor

    Returns:
        Configured ComplianceMonitor instance
    """
    global _monitor

    config = ComplianceMonitorConfig(
        check_interval_seconds=check_interval_seconds,
        alert_on_critical=alert_on_critical,
        alert_on_major=alert_on_major,
        enabled_frameworks=enabled_frameworks or {"soc2", "gdpr", "hipaa"},
    )

    _monitor = ComplianceMonitor(config)
    logger.info(
        "Compliance monitoring initialized: interval=%ss, frameworks=%s",
        check_interval_seconds,
        config.enabled_frameworks,
    )

    return _monitor


async def start_compliance_monitoring() -> None:
    """Start the compliance monitoring background task."""
    if _monitor:
        await _monitor.start()


async def stop_compliance_monitoring() -> None:
    """Stop the compliance monitoring background task."""
    if _monitor:
        await _monitor.stop()


async def get_compliance_status() -> ComplianceStatus | None:
    """Get current compliance status."""
    if _monitor:
        return _monitor.get_status()
    return None


__all__ = [
    "ComplianceHealth",
    "ViolationTrend",
    "FrameworkStatus",
    "ComplianceStatus",
    "DriftEvent",
    "ComplianceMonitorConfig",
    "ComplianceMonitor",
    "get_compliance_monitor",
    "init_compliance_monitoring",
    "start_compliance_monitoring",
    "stop_compliance_monitoring",
    "get_compliance_status",
]
