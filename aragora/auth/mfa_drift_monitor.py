"""
MFA Policy Drift Monitor.

Periodic background job that scans all admin-role users and alerts
when any admin is found without MFA enabled (policy drift). Integrates
with the compliance monitor framework and emits structured log events
that feed into Prometheus/Grafana dashboards.

SOC 2 Control: CC5-01 - Enforce MFA for administrative access.
GitHub Issue: #510 - Admin MFA enforcement (Enterprise Assurance Closure)

Design:
- ``MFADriftMonitor`` is the background scanner (sync or async).
- ``MFADriftReport`` is the value object produced by each scan.
- ``MFADriftAlert`` represents a single non-compliant user finding.
- Alerting uses a callback pattern so callers can plug in Slack, PD, etc.

Usage:
    from aragora.auth.mfa_drift_monitor import MFADriftMonitor

    monitor = MFADriftMonitor(user_store=my_store, alert_threshold=0.9)

    # Run once (sync)
    report = monitor.scan()
    if report.has_violations:
        print(report.summary)

    # Run periodically in the background (async)
    await monitor.start(interval_seconds=3600)
    ...
    await monitor.stop()
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from aragora.auth.mfa_enforcement import DEFAULT_MFA_REQUIRED_ROLES

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass
class MFADriftAlert:
    """A single admin user found to be non-compliant with MFA policy.

    Attributes:
        user_id: The non-compliant user identifier.
        role: The admin role that triggers the MFA requirement.
        mfa_enabled: Whether MFA is enabled (expected: True; found: False).
        in_grace_period: Whether the user is still within the setup grace period.
        severity: "warning" (in grace period) or "critical" (grace expired/no record).
        detected_at: ISO-8601 timestamp of when the drift was detected.
    """

    user_id: str
    role: str
    mfa_enabled: bool
    in_grace_period: bool = False
    severity: str = "critical"
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for logging and API responses."""
        return {
            "user_id": self.user_id,
            "role": self.role,
            "mfa_enabled": self.mfa_enabled,
            "in_grace_period": self.in_grace_period,
            "severity": self.severity,
            "detected_at": self.detected_at,
        }


@dataclass
class MFADriftReport:
    """Full report produced by a single scan run.

    Attributes:
        scanned_at: ISO-8601 timestamp of scan start.
        total_admins: Number of admin-role users inspected.
        compliant: Number of admin users with MFA enabled.
        non_compliant: Number of admin users without MFA (grace + critical).
        in_grace_period: Subset of non_compliant still within grace window.
        compliance_rate: Fraction of admins with MFA enabled (0.0-1.0).
        alerts: Individual drift alerts per non-compliant user.
        policy_met: True when compliance_rate >= alert_threshold.
    """

    scanned_at: str
    total_admins: int
    compliant: int
    non_compliant: int
    in_grace_period: int
    compliance_rate: float
    alerts: list[MFADriftAlert]
    policy_met: bool

    @property
    def has_violations(self) -> bool:
        """Return True if any admin users lack MFA."""
        return self.non_compliant > 0

    @property
    def critical_violations(self) -> list[MFADriftAlert]:
        """Return only the critical (grace-period-expired) alerts."""
        return [a for a in self.alerts if a.severity == "critical"]

    @property
    def summary(self) -> str:
        """Human-readable one-line summary of the scan result."""
        if not self.has_violations:
            return (
                f"MFA compliance OK: {self.compliant}/{self.total_admins} "
                f"admin users have MFA enabled (rate={self.compliance_rate:.1%})"
            )
        return (
            f"MFA drift detected: {self.non_compliant}/{self.total_admins} "
            f"admin users lack MFA "
            f"({self.in_grace_period} in grace period, "
            f"{len(self.critical_violations)} critical). "
            f"Rate={self.compliance_rate:.1%}"
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for API and metric emission."""
        return {
            "scanned_at": self.scanned_at,
            "total_admins": self.total_admins,
            "compliant": self.compliant,
            "non_compliant": self.non_compliant,
            "in_grace_period": self.in_grace_period,
            "compliance_rate": round(self.compliance_rate, 4),
            "policy_met": self.policy_met,
            "alerts": [a.to_dict() for a in self.alerts],
        }


# ---------------------------------------------------------------------------
# MFADriftMonitor
# ---------------------------------------------------------------------------


class MFADriftMonitor:
    """
    Periodic MFA policy drift monitor for admin-role users.

    Scans the user store for admin accounts without MFA enabled and emits
    structured log events (and optional alert callbacks) for each violation.

    Args:
        user_store: Backend that provides ``list_users()`` or
                    ``get_all_users()`` and ``get_user_by_id()``.
        required_roles: Set of role names that require MFA.  Defaults to
                        :data:`~aragora.auth.mfa_enforcement.DEFAULT_MFA_REQUIRED_ROLES`.
        alert_threshold: Minimum acceptable MFA compliance rate (0.0-1.0).
                         Defaults to 1.0 (100% of admins must have MFA).
        on_violation: Optional callback invoked with the :class:`MFADriftReport`
                      when policy is not met.  Use to send Slack/PD alerts.
        on_critical: Optional callback invoked per :class:`MFADriftAlert` that
                     is critical (grace period expired).
    """

    def __init__(
        self,
        user_store: Any = None,
        required_roles: frozenset[str] | None = None,
        alert_threshold: float = 1.0,
        on_violation: Callable[[MFADriftReport], None] | None = None,
        on_critical: Callable[[MFADriftAlert], None] | None = None,
    ) -> None:
        self._user_store = user_store
        self._required_roles = required_roles or DEFAULT_MFA_REQUIRED_ROLES
        self._alert_threshold = max(0.0, min(1.0, alert_threshold))
        self._on_violation = on_violation
        self._on_critical = on_critical
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._last_report: MFADriftReport | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan(self) -> MFADriftReport:
        """
        Run a single synchronous MFA compliance scan.

        Returns:
            :class:`MFADriftReport` with scan results.  Also stores the
            result in :attr:`last_report`.
        """
        scanned_at = datetime.now(timezone.utc).isoformat()

        if self._user_store is None:
            logger.warning("MFADriftMonitor: no user_store configured; skipping scan")
            report = MFADriftReport(
                scanned_at=scanned_at,
                total_admins=0,
                compliant=0,
                non_compliant=0,
                in_grace_period=0,
                compliance_rate=1.0,
                alerts=[],
                policy_met=True,
            )
            self._last_report = report
            return report

        all_users = self._list_users()
        admin_users = [u for u in all_users if self._is_admin(u)]

        alerts: list[MFADriftAlert] = []
        compliant = 0
        grace_count = 0

        for user in admin_users:
            user_id = str(getattr(user, "id", getattr(user, "user_id", "unknown")))
            role = str(getattr(user, "role", "admin"))
            mfa_enabled = bool(getattr(user, "mfa_enabled", False))
            in_grace = bool(getattr(user, "mfa_grace_period_started_at", None))

            if mfa_enabled:
                compliant += 1
                continue

            # Non-compliant
            severity = "warning" if in_grace else "critical"
            if in_grace:
                grace_count += 1

            alert = MFADriftAlert(
                user_id=user_id,
                role=role,
                mfa_enabled=False,
                in_grace_period=in_grace,
                severity=severity,
                detected_at=scanned_at,
            )
            alerts.append(alert)

        total = len(admin_users)
        non_compliant = len(alerts)
        compliance_rate = (compliant / total) if total > 0 else 1.0
        policy_met = compliance_rate >= self._alert_threshold

        report = MFADriftReport(
            scanned_at=scanned_at,
            total_admins=total,
            compliant=compliant,
            non_compliant=non_compliant,
            in_grace_period=grace_count,
            compliance_rate=compliance_rate,
            alerts=alerts,
            policy_met=policy_met,
        )
        self._last_report = report
        self._emit(report)
        return report

    @property
    def last_report(self) -> MFADriftReport | None:
        """Return the most recent scan report, or None if no scan has run."""
        return self._last_report

    async def start(self, interval_seconds: int = 3600) -> None:
        """
        Start the periodic background scanner.

        Runs :meth:`scan` immediately, then every *interval_seconds* seconds.
        Safe to call multiple times; subsequent calls are no-ops if already running.

        Args:
            interval_seconds: Seconds between scans (default: 3600 = 1 hour).
        """
        if self._running:
            logger.debug("MFADriftMonitor: already running")
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(interval_seconds), name="mfa-drift-monitor")
        logger.info(
            "MFADriftMonitor started (interval=%ds, threshold=%.0f%%)",
            interval_seconds,
            self._alert_threshold * 100,
        )

    async def stop(self) -> None:
        """Stop the periodic background scanner."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("MFADriftMonitor stopped")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _loop(self, interval_seconds: int) -> None:
        """Background loop: scan, wait, repeat."""
        while self._running:
            try:
                self.scan()
            except Exception:  # noqa: BLE001 — broad catch intentional for background loop
                logger.exception("MFADriftMonitor: unexpected error during scan")
            try:
                await asyncio.sleep(interval_seconds)
            except asyncio.CancelledError:
                break

    def _list_users(self) -> list[Any]:
        """List users from the store; tries list_users then get_all_users."""
        list_fn = getattr(self._user_store, "list_users", None) or getattr(
            self._user_store, "get_all_users", None
        )
        if list_fn is None:
            logger.warning("MFADriftMonitor: user_store has no list_users / get_all_users method")
            return []
        try:
            return list(list_fn())
        except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
            logger.warning("MFADriftMonitor: failed to list users: %s", exc)
            return []

    def _is_admin(self, user: Any) -> bool:
        """Return True if the user holds at least one admin role."""
        role = getattr(user, "role", None)
        if role and str(role).lower() in self._required_roles:
            return True
        # Also check a roles set/list attribute
        roles = getattr(user, "roles", None)
        if roles:
            for r in roles:
                if str(r).lower() in self._required_roles:
                    return True
        return False

    def send_drift_alerts(self, report: MFADriftReport) -> None:
        """Send notifications for critical-level drift alerts.

        Sends a notification for each critical alert (grace period expired or
        admin without MFA) and an overall summary when policy is not met.
        Uses the notification service if available; logs warnings otherwise.
        """
        critical_alerts = report.critical_violations
        if not critical_alerts and report.policy_met:
            return

        try:
            from aragora.notifications.service import get_notification_service
            from aragora.notifications.models import (
                Notification,
                NotificationChannel,
                NotificationPriority,
            )

            service = get_notification_service()
        except ImportError:
            logger.warning(
                "MFADriftMonitor: notification service not available; skipping drift alert delivery"
            )
            return

        # Send per-user critical alerts
        for alert in critical_alerts:
            try:
                notification = Notification(
                    title="MFA Enforcement: Admin Without MFA",
                    message=(
                        f"Admin user {alert.user_id} (role={alert.role}) does not "
                        f"have MFA enabled and their grace period has expired. "
                        f"Immediate action required."
                    ),
                    severity="critical",
                    priority=NotificationPriority.URGENT,
                    resource_type="mfa_compliance",
                    resource_id=alert.user_id,
                )

                import asyncio

                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(
                        service.notify(
                            notification=notification,
                            channels=[NotificationChannel.SLACK, NotificationChannel.EMAIL],
                        )
                    )
                except RuntimeError:
                    # No running event loop — run synchronously
                    asyncio.run(
                        service.notify(
                            notification=notification,
                            channels=[NotificationChannel.SLACK, NotificationChannel.EMAIL],
                        )
                    )
            except Exception:  # noqa: BLE001 — notification delivery must not break the monitor
                logger.exception(
                    "MFADriftMonitor: failed to send drift alert for user %s",
                    alert.user_id,
                )

        # Send overall summary if policy is not met
        if not report.policy_met:
            try:
                summary_notification = Notification(
                    title="MFA Policy Non-Compliance Detected",
                    message=(
                        f"MFA compliance rate is {report.compliance_rate:.1%} "
                        f"({report.non_compliant}/{report.total_admins} admins non-compliant, "
                        f"{len(critical_alerts)} critical). "
                        f"Compliance threshold not met."
                    ),
                    severity="critical",
                    priority=NotificationPriority.URGENT,
                    resource_type="mfa_compliance",
                )

                import asyncio

                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(
                        service.notify(
                            notification=summary_notification,
                            channels=[NotificationChannel.SLACK, NotificationChannel.EMAIL],
                        )
                    )
                except RuntimeError:
                    asyncio.run(
                        service.notify(
                            notification=summary_notification,
                            channels=[NotificationChannel.SLACK, NotificationChannel.EMAIL],
                        )
                    )
            except Exception:  # noqa: BLE001 — notification delivery must not break the monitor
                logger.exception("MFADriftMonitor: failed to send policy summary notification")

    def _emit(self, report: MFADriftReport) -> None:
        """
        Emit the scan report as structured log events and invoke callbacks.

        Compliance rate and violation counts are logged at WARNING level when
        policy is not met, and at INFO level when compliant.  Also sends
        notifications for critical drift alerts.
        """
        if report.has_violations:
            logger.warning(
                "MFA policy drift: %s",
                report.summary,
                extra={
                    "event": "mfa_drift_detected",
                    "total_admins": report.total_admins,
                    "non_compliant": report.non_compliant,
                    "compliance_rate": report.compliance_rate,
                    "critical_count": len(report.critical_violations),
                    "grace_count": report.in_grace_period,
                },
            )
            for alert in report.critical_violations:
                logger.warning(
                    "MFA critical violation: admin user %s (role=%s) has no MFA and grace period has expired",
                    alert.user_id,
                    alert.role,
                    extra={
                        "event": "mfa_critical_violation",
                        "user_id": alert.user_id,
                        "role": alert.role,
                    },
                )
                if self._on_critical is not None:
                    try:
                        self._on_critical(alert)
                    except Exception:  # noqa: BLE001 — external callback
                        logger.exception("MFADriftMonitor: on_critical callback raised")

            if not report.policy_met and self._on_violation is not None:
                try:
                    self._on_violation(report)
                except Exception:  # noqa: BLE001 — external callback
                    logger.exception("MFADriftMonitor: on_violation callback raised")

            # Send notifications for critical drift
            self.send_drift_alerts(report)
        else:
            logger.info(
                "MFA compliance check passed: %s",
                report.summary,
                extra={
                    "event": "mfa_compliance_ok",
                    "total_admins": report.total_admins,
                    "compliant": report.compliant,
                    "compliance_rate": report.compliance_rate,
                },
            )


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

_default_monitor: MFADriftMonitor | None = None


def get_mfa_drift_monitor() -> MFADriftMonitor | None:
    """Return the default module-level MFA drift monitor, or None if uninitialised."""
    return _default_monitor


def init_mfa_drift_monitor(
    user_store: Any = None,
    required_roles: frozenset[str] | None = None,
    alert_threshold: float = 1.0,
    on_violation: Callable[[MFADriftReport], None] | None = None,
    on_critical: Callable[[MFADriftAlert], None] | None = None,
) -> MFADriftMonitor:
    """
    Create and register a module-level :class:`MFADriftMonitor`.

    Call once at server startup.  Subsequent calls return the same instance.

    Args:
        user_store: Backend providing ``list_users()`` / ``get_all_users()``.
        required_roles: Role names that require MFA.
        alert_threshold: Minimum acceptable compliance rate (default 1.0).
        on_violation: Callback when overall policy threshold not met.
        on_critical: Callback per critical (grace-expired) alert.

    Returns:
        The initialised :class:`MFADriftMonitor`.
    """
    global _default_monitor  # noqa: PLW0603
    if _default_monitor is None:
        _default_monitor = MFADriftMonitor(
            user_store=user_store,
            required_roles=required_roles,
            alert_threshold=alert_threshold,
            on_violation=on_violation,
            on_critical=on_critical,
        )
    return _default_monitor


__all__ = [
    "MFADriftAlert",
    "MFADriftMonitor",
    "MFADriftReport",
    "get_mfa_drift_monitor",
    "init_mfa_drift_monitor",
]
