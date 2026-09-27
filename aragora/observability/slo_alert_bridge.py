"""
SLO Alert Bridge - Connects SLO violations to alerting systems.

Provides automatic routing of SLO violations to:
- PagerDuty (critical/major violations create incidents)
- Slack/Teams (all violations posted to channels)
- Generic webhooks (for custom integrations)

Features:
- Severity-based routing (critical → P1, major → P2, etc.)
- Incident deduplication (same operation/percentile → same incident)
- Automatic recovery handling (resolves incidents when SLO recovers)
- Cooldown to prevent notification spam
- Business hour awareness for escalation

Usage:
    from aragora.observability.slo_alert_bridge import (
        SLOAlertBridge,
        init_slo_alerting,
    )

    # Register higher-layer adapters at the application composition root.
    from aragora.connectors.devops.slo_alert_sink import (
        register_slo_alert_sink as register_pagerduty_sink,
    )
    from aragora.control_plane.slo_alert_sink import (
        register_slo_alert_sink as register_channel_sink,
    )

    register_pagerduty_sink()
    register_channel_sink()

    # Initialize at startup
    bridge = init_slo_alerting(
        pagerduty_api_key="...",
        pagerduty_service_id="...",
        slack_webhook_url="...",
    )

    # Violations automatically routed via webhook callbacks
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Protocol

logger = logging.getLogger(__name__)


class AlertSeverity(Enum):
    """Alert severity levels mapped to PagerDuty priorities."""

    CRITICAL = "critical"  # P1 - Immediate response required
    MAJOR = "major"  # P2 - Urgent, within 1 hour
    MODERATE = "moderate"  # P3 - High priority, within 4 hours
    MINOR = "minor"  # P4 - Low priority, next business day


class AlertChannel(Enum):
    """Available alert channels."""

    PAGERDUTY = "pagerduty"
    SLACK = "slack"
    TEAMS = "teams"
    EMAIL = "email"
    WEBHOOK = "webhook"


@dataclass
class SLOAlertConfig:
    """Configuration for SLO alerting."""

    # PagerDuty configuration
    pagerduty_enabled: bool = False
    pagerduty_api_key: str | None = None
    pagerduty_service_id: str | None = None
    pagerduty_email: str = "slo-alerts@aragora.dev"  # Email for PagerDuty requests
    pagerduty_min_severity: AlertSeverity = AlertSeverity.MAJOR

    # Slack configuration
    slack_enabled: bool = False
    slack_webhook_url: str | None = None
    slack_channel: str | None = None
    slack_min_severity: AlertSeverity = AlertSeverity.MINOR

    # Teams configuration
    teams_enabled: bool = False
    teams_webhook_url: str | None = None
    teams_min_severity: AlertSeverity = AlertSeverity.MINOR

    # General settings
    cooldown_seconds: float = 60.0  # Min time between duplicate alerts
    dedup_window_seconds: float = 300.0  # Window for incident deduplication
    auto_resolve_on_recovery: bool = True
    include_runbook_links: bool = True


@dataclass
class ActiveViolation:
    """Tracks an active SLO violation for deduplication."""

    operation: str
    percentile: str
    severity: str
    first_seen: float
    last_seen: float
    count: int = 1
    incident_key: str | None = None
    pagerduty_incident_id: str | None = None
    notified_channels: set[str] = field(default_factory=set)


PagerDutyUrgency = Literal["high", "low"]


class PagerDutyAlertSink(Protocol):
    """Connector-owned PagerDuty delivery contract."""

    async def create_incident(
        self,
        *,
        title: str,
        service_id: str,
        urgency: PagerDutyUrgency,
        description: str,
        incident_key: str | None,
    ) -> str | None:
        """Create an incident and return its external identifier."""

    async def resolve_incident(self, incident_id: str, resolution: str) -> bool:
        """Resolve an existing incident."""


class ChannelAlertSink(Protocol):
    """Control-plane-owned notification delivery contract."""

    async def notify(
        self,
        *,
        event_type: str,
        title: str,
        body: str,
        priority: str,
        metadata: dict[str, Any],
    ) -> Any:
        """Deliver an alert notification."""


PagerDutyAlertSinkFactory = Callable[[SLOAlertConfig], PagerDutyAlertSink]
ChannelAlertSinkFactory = Callable[[SLOAlertConfig], ChannelAlertSink]

_pagerduty_alert_sink_factory: PagerDutyAlertSinkFactory | None = None
_channel_alert_sink_factory: ChannelAlertSinkFactory | None = None
_pagerduty_alert_sink_generation = 0
_channel_alert_sink_generation = 0


def register_pagerduty_alert_sink(factory: PagerDutyAlertSinkFactory | None) -> None:
    """Register the connector-side PagerDuty sink factory."""
    global _pagerduty_alert_sink_factory, _pagerduty_alert_sink_generation
    _pagerduty_alert_sink_factory = factory
    _pagerduty_alert_sink_generation += 1
    bridge = globals().get("_bridge")
    if isinstance(bridge, SLOAlertBridge):
        bridge._ensure_pagerduty_sink()


def register_channel_alert_sink(factory: ChannelAlertSinkFactory | None) -> None:
    """Register the control-plane channel sink factory."""
    global _channel_alert_sink_factory, _channel_alert_sink_generation
    _channel_alert_sink_factory = factory
    _channel_alert_sink_generation += 1
    bridge = globals().get("_bridge")
    if isinstance(bridge, SLOAlertBridge):
        bridge._ensure_channel_sink()


class SLOAlertBridge:
    """
    Bridges SLO violations to alerting systems.

    Receives SLO violation notifications and routes them to appropriate
    alert channels based on severity and configuration.
    """

    def __init__(self, config: SLOAlertConfig):
        """Initialize the bridge with configuration."""
        self.config = config
        self._active_violations: dict[str, ActiveViolation] = {}
        self._last_notification: dict[str, float] = {}
        self._pagerduty_client: Any | None = None
        self._notification_manager: Any | None = None
        self._pagerduty_sink_generation = -1
        self._channel_sink_generation = -1
        self._lock = asyncio.Lock()

        self._ensure_pagerduty_sink(warn_if_missing=True)
        self._ensure_channel_sink(warn_if_missing=True)

    def _ensure_pagerduty_sink(self, *, warn_if_missing: bool = False) -> None:
        """Attach the current PagerDuty adapter when one is registered."""
        if not self.config.pagerduty_enabled:
            return
        if self._pagerduty_sink_generation == _pagerduty_alert_sink_generation:
            return
        if _pagerduty_alert_sink_factory is None:
            self._pagerduty_client = None
            self._pagerduty_sink_generation = _pagerduty_alert_sink_generation
            if warn_if_missing:
                logger.warning(
                    "PagerDuty SLO alerting enabled without a registered sink; "
                    "register the connector adapter before creating the bridge"
                )
            return
        try:
            replacement = _pagerduty_alert_sink_factory(self.config)
        except (ImportError, OSError, RuntimeError, TypeError, ValueError) as e:
            logger.error("Failed to initialize PagerDuty alert sink: %s", e)
            self._pagerduty_client = None
            return

        self._pagerduty_client = replacement
        self._pagerduty_sink_generation = _pagerduty_alert_sink_generation

    def _ensure_channel_sink(self, *, warn_if_missing: bool = False) -> None:
        """Attach the current channel adapter when one is registered."""
        if not self.config.slack_enabled:
            return
        if self._channel_sink_generation == _channel_alert_sink_generation:
            return
        if _channel_alert_sink_factory is None:
            self._notification_manager = None
            self._channel_sink_generation = _channel_alert_sink_generation
            if warn_if_missing:
                logger.warning(
                    "Slack SLO alerting enabled without a registered sink; "
                    "register the control-plane adapter before creating the bridge"
                )
            return
        try:
            replacement = _channel_alert_sink_factory(self.config)
        except (ImportError, OSError, RuntimeError, TypeError, ValueError) as e:
            logger.error("Failed to initialize channel alert sink: %s", e)
            self._notification_manager = None
            return

        self._notification_manager = replacement
        self._channel_sink_generation = _channel_alert_sink_generation

    def _make_incident_key(self, operation: str, percentile: str) -> str:
        """Generate unique incident key for deduplication."""
        raw = f"slo-{operation}-{percentile}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _map_severity(self, slo_severity: str) -> AlertSeverity:
        """Map SLO severity string to AlertSeverity enum."""
        mapping = {
            "critical": AlertSeverity.CRITICAL,
            "major": AlertSeverity.MAJOR,
            "moderate": AlertSeverity.MODERATE,
            "minor": AlertSeverity.MINOR,
        }
        return mapping.get(slo_severity.lower(), AlertSeverity.MINOR)

    def _should_alert(
        self, channel: AlertChannel, severity: AlertSeverity, incident_key: str
    ) -> bool:
        """Check if we should send an alert to this channel."""
        # Check channel-specific minimum severity
        min_severity_map = {
            AlertChannel.PAGERDUTY: self.config.pagerduty_min_severity,
            AlertChannel.SLACK: self.config.slack_min_severity,
            AlertChannel.TEAMS: self.config.teams_min_severity,
        }

        min_severity = min_severity_map.get(channel, AlertSeverity.MINOR)
        severity_order = [
            AlertSeverity.MINOR,
            AlertSeverity.MODERATE,
            AlertSeverity.MAJOR,
            AlertSeverity.CRITICAL,
        ]

        if severity_order.index(severity) < severity_order.index(min_severity):
            return False

        # Check cooldown
        cache_key = f"{channel.value}:{incident_key}"
        last_time = self._last_notification.get(cache_key, 0)
        if time.time() - last_time < self.config.cooldown_seconds:
            return False

        return True

    async def _send_pagerduty_alert(
        self,
        violation: ActiveViolation,
        context: dict[str, Any],
    ) -> str | None:
        """Create or update a PagerDuty incident."""
        self._ensure_pagerduty_sink()
        if not self.config.pagerduty_enabled or self._pagerduty_client is None:
            return None

        try:
            urgency_map: dict[AlertSeverity, PagerDutyUrgency] = {
                AlertSeverity.CRITICAL: "high",
                AlertSeverity.MAJOR: "high",
                AlertSeverity.MODERATE: "low",
                AlertSeverity.MINOR: "low",
            }

            severity = self._map_severity(violation.severity)
            urgency: PagerDutyUrgency = urgency_map.get(severity, "low")

            # Build description with context
            description = (
                f"SLO Violation: {violation.operation} {violation.percentile}\n"
                f"Severity: {violation.severity}\n"
                f"Latency: {context.get('latency_ms', 'N/A')}ms "
                f"(threshold: {context.get('threshold_ms', 'N/A')}ms)\n"
                f"First seen: {datetime.fromtimestamp(violation.first_seen, tz=timezone.utc).isoformat()}\n"
                f"Occurrences: {violation.count}"
            )

            if self.config.include_runbook_links:
                description += "\n\nRunbook: https://docs.aragora.dev/runbooks/slo-violations"

            incident_id = await self._pagerduty_client.create_incident(
                title=f"[SLO] {violation.operation} {violation.percentile} violation ({violation.severity})",
                service_id=self.config.pagerduty_service_id or "",
                urgency=urgency,
                description=description,
                incident_key=violation.incident_key,
            )
            if incident_id:
                logger.info(
                    "Created PagerDuty incident %s for %s",
                    incident_id,
                    violation.operation,
                )
            return incident_id
        except (OSError, ConnectionError, RuntimeError, TypeError, ValueError) as e:
            logger.error("Failed to create PagerDuty incident: %s", e)

        return None

    async def _send_slack_alert(
        self,
        violation: ActiveViolation,
        context: dict[str, Any],
    ) -> bool:
        """Send alert to Slack."""
        self._ensure_channel_sink()
        if (
            not self.config.slack_enabled
            or not self.config.slack_webhook_url
            or self._notification_manager is None
        ):
            return False

        try:
            severity = self._map_severity(violation.severity)
            priority_map = {
                AlertSeverity.CRITICAL: "critical",
                AlertSeverity.MAJOR: "urgent",
                AlertSeverity.MODERATE: "high",
                AlertSeverity.MINOR: "normal",
            }

            # Build Slack message with blocks
            blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"SLO Violation: {violation.operation}",
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Severity:*\n{violation.severity.upper()}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Percentile:*\n{violation.percentile}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Latency:*\n{context.get('latency_ms', 'N/A')}ms",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Threshold:*\n{context.get('threshold_ms', 'N/A')}ms",
                        },
                    ],
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"Occurrences: {violation.count} | First seen: {datetime.fromtimestamp(violation.first_seen, tz=timezone.utc).strftime('%H:%M:%S UTC')}",
                        }
                    ],
                },
            ]

            await self._notification_manager.notify(
                event_type="sla_violation",
                title=f"SLO Violation: {violation.operation} {violation.percentile}",
                body=f"Severity: {violation.severity}, Latency: {context.get('latency_ms')}ms",
                priority=priority_map.get(severity, "normal"),
                metadata={
                    "operation": violation.operation,
                    "percentile": violation.percentile,
                    "severity": violation.severity,
                    "blocks": blocks,
                },
            )

            logger.info("Sent Slack alert for %s", violation.operation)
            return True

        except (ImportError, OSError, ConnectionError, RuntimeError, TypeError, ValueError) as e:
            logger.error("Failed to send Slack alert: %s", e)

        return False

    async def on_slo_violation(
        self,
        operation: str,
        percentile: str,
        latency_ms: float,
        threshold_ms: float,
        severity: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        """
        Handle an SLO violation event.

        Called by the SLO metrics system when a violation is detected.
        Routes to appropriate alert channels based on severity.
        """
        context = context or {}
        context.update(
            {
                "latency_ms": latency_ms,
                "threshold_ms": threshold_ms,
            }
        )

        incident_key = self._make_incident_key(operation, percentile)

        async with self._lock:
            # Check if this is a new or existing violation
            if incident_key in self._active_violations:
                violation = self._active_violations[incident_key]
                violation.last_seen = time.time()
                violation.count += 1

                # Update severity if it increased
                severity_order = ["minor", "moderate", "major", "critical"]
                if severity_order.index(severity) > severity_order.index(violation.severity):
                    violation.severity = severity
            else:
                violation = ActiveViolation(
                    operation=operation,
                    percentile=percentile,
                    severity=severity,
                    first_seen=time.time(),
                    last_seen=time.time(),
                    incident_key=incident_key,
                )
                self._active_violations[incident_key] = violation

            alert_severity = self._map_severity(severity)

            # Route to PagerDuty for critical/major violations
            if self.config.pagerduty_enabled and self._should_alert(
                AlertChannel.PAGERDUTY, alert_severity, incident_key
            ):
                incident_id = await self._send_pagerduty_alert(violation, context)
                if incident_id:
                    violation.pagerduty_incident_id = incident_id
                    violation.notified_channels.add("pagerduty")
                    self._last_notification[f"pagerduty:{incident_key}"] = time.time()

            # Route to Slack for all severities above threshold
            if self.config.slack_enabled and self._should_alert(
                AlertChannel.SLACK, alert_severity, incident_key
            ):
                if await self._send_slack_alert(violation, context):
                    violation.notified_channels.add("slack")
                    self._last_notification[f"slack:{incident_key}"] = time.time()

    async def on_slo_recovery(
        self,
        operation: str,
        percentile: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        """
        Handle an SLO recovery event.

        Called when an SLO returns to compliance after a violation.
        Resolves any open incidents and sends recovery notifications.
        """
        incident_key = self._make_incident_key(operation, percentile)
        self._ensure_pagerduty_sink()
        self._ensure_channel_sink()

        async with self._lock:
            if incident_key not in self._active_violations:
                return

            violation = self._active_violations[incident_key]

            # Auto-resolve PagerDuty incident
            if (
                self.config.auto_resolve_on_recovery
                and violation.pagerduty_incident_id
                and self._pagerduty_client
            ):
                try:
                    resolved = await self._pagerduty_client.resolve_incident(
                        violation.pagerduty_incident_id,
                        resolution=f"SLO {operation} {percentile} recovered. "
                        f"Duration: {time.time() - violation.first_seen:.0f}s, "
                        f"Occurrences: {violation.count}",
                    )
                    if resolved:
                        logger.info(
                            "Resolved PagerDuty incident %s",
                            violation.pagerduty_incident_id,
                        )
                    else:
                        logger.error(
                            "Failed to resolve PagerDuty incident %s",
                            violation.pagerduty_incident_id,
                        )
                except (OSError, ConnectionError, RuntimeError, TypeError, ValueError) as e:
                    logger.error("Failed to resolve PagerDuty incident: %s", e)

            # Send recovery notification to Slack
            if "slack" in violation.notified_channels and self._notification_manager:
                try:
                    await self._notification_manager.notify(
                        event_type="task_completed",
                        title=f"SLO Recovered: {operation} {percentile}",
                        body=f"Duration: {time.time() - violation.first_seen:.0f}s, Occurrences: {violation.count}",
                        priority="low",
                        metadata={
                            "operation": operation,
                            "percentile": percentile,
                            "duration_seconds": time.time() - violation.first_seen,
                            "occurrence_count": violation.count,
                        },
                    )
                except (
                    ImportError,
                    OSError,
                    ConnectionError,
                    RuntimeError,
                    TypeError,
                    ValueError,
                ) as e:
                    logger.error("Failed to send recovery notification: %s", e)

            # Clean up
            del self._active_violations[incident_key]

    def get_active_violations(self) -> list[dict[str, Any]]:
        """Get list of currently active violations."""
        return [
            {
                "operation": v.operation,
                "percentile": v.percentile,
                "severity": v.severity,
                "first_seen": datetime.fromtimestamp(v.first_seen, tz=timezone.utc).isoformat(),
                "last_seen": datetime.fromtimestamp(v.last_seen, tz=timezone.utc).isoformat(),
                "count": v.count,
                "incident_key": v.incident_key,
                "pagerduty_incident_id": v.pagerduty_incident_id,
                "notified_channels": list(v.notified_channels),
            }
            for v in self._active_violations.values()
        ]

    def cleanup_stale_violations(self, max_age_seconds: float = 3600) -> int:
        """Remove violations that haven't been seen recently."""
        now = time.time()
        stale_keys = [
            key for key, v in self._active_violations.items() if now - v.last_seen > max_age_seconds
        ]
        for key in stale_keys:
            del self._active_violations[key]
        return len(stale_keys)


# Global bridge instance
_bridge: SLOAlertBridge | None = None
_registered_violation_callback: Callable[[dict[str, Any]], Any] | None = None
_registered_recovery_callback: Callable[[dict[str, Any]], Any] | None = None


def get_slo_alert_bridge() -> SLOAlertBridge | None:
    """Get the global SLO alert bridge instance."""
    return _bridge


def init_slo_alerting(
    pagerduty_api_key: str | None = None,
    pagerduty_service_id: str | None = None,
    slack_webhook_url: str | None = None,
    slack_channel: str | None = None,
    teams_webhook_url: str | None = None,
    cooldown_seconds: float = 60.0,
    auto_resolve_on_recovery: bool = True,
) -> SLOAlertBridge:
    """
    Initialize the SLO alerting system.

    Call this at application startup to enable SLO → Alert routing.

    Args:
        pagerduty_api_key: PagerDuty API key for incident creation
        pagerduty_service_id: PagerDuty service ID to create incidents in
        slack_webhook_url: Slack webhook URL for notifications
        slack_channel: Slack channel override
        teams_webhook_url: Microsoft Teams webhook URL
        cooldown_seconds: Minimum time between duplicate alerts
        auto_resolve_on_recovery: Auto-resolve incidents when SLO recovers

    Returns:
        Configured SLOAlertBridge instance
    """
    global _bridge, _registered_violation_callback, _registered_recovery_callback

    _unregister_bridge_callbacks()

    config = SLOAlertConfig(
        pagerduty_enabled=bool(pagerduty_api_key and pagerduty_service_id),
        pagerduty_api_key=pagerduty_api_key,
        pagerduty_service_id=pagerduty_service_id,
        slack_enabled=bool(slack_webhook_url),
        slack_webhook_url=slack_webhook_url,
        slack_channel=slack_channel,
        teams_enabled=bool(teams_webhook_url),
        teams_webhook_url=teams_webhook_url,
        cooldown_seconds=cooldown_seconds,
        auto_resolve_on_recovery=auto_resolve_on_recovery,
    )

    _bridge = SLOAlertBridge(config)

    # Register callbacks with SLO metrics system
    try:
        from aragora.observability.metrics.slo import (
            register_violation_callback,
            register_recovery_callback,
        )

        async def violation_callback(data: dict[str, Any]) -> None:
            """Handle SLO violation events from the metrics system."""
            if _bridge:
                await _bridge.on_slo_violation(
                    operation=data.get("operation", "unknown"),
                    percentile=data.get("percentile", "p99"),
                    latency_ms=data.get("latency_ms", 0),
                    threshold_ms=data.get("threshold_ms", 0),
                    severity=data.get("severity", "minor"),
                    context=data.get("context", {}),
                )

        async def recovery_callback(data: dict[str, Any]) -> None:
            """Handle SLO recovery events from the metrics system."""
            if _bridge:
                await _bridge.on_slo_recovery(
                    operation=data.get("operation", "unknown"),
                    percentile=data.get("percentile", "p99"),
                    context=data.get("context", {}),
                )

        register_violation_callback(violation_callback)
        register_recovery_callback(recovery_callback)
        _registered_violation_callback = violation_callback
        _registered_recovery_callback = recovery_callback

        logger.info(
            "SLO alerting initialized: pagerduty=%s, slack=%s, teams=%s",
            config.pagerduty_enabled,
            config.slack_enabled,
            config.teams_enabled,
        )

    except ImportError:
        logger.warning("SLO metrics module not available - alerting callbacks not registered")

    return _bridge


def _unregister_bridge_callbacks() -> None:
    """Unregister callbacks owned by this bridge without disturbing other consumers."""
    global _registered_violation_callback, _registered_recovery_callback

    try:
        from aragora.observability.metrics.slo import (
            unregister_recovery_callback,
            unregister_violation_callback,
        )

        if _registered_violation_callback is not None:
            unregister_violation_callback(_registered_violation_callback)
        if _registered_recovery_callback is not None:
            unregister_recovery_callback(_registered_recovery_callback)
    except ImportError:
        pass

    _registered_violation_callback = None
    _registered_recovery_callback = None


def shutdown_slo_alerting() -> None:
    """Shutdown the SLO alerting system and unregister callbacks."""
    global _bridge

    _unregister_bridge_callbacks()
    _bridge = None
    logger.info("SLO alerting shutdown, callbacks unregistered")


__all__ = [
    "AlertSeverity",
    "AlertChannel",
    "SLOAlertConfig",
    "SLOAlertBridge",
    "ActiveViolation",
    "PagerDutyUrgency",
    "PagerDutyAlertSink",
    "ChannelAlertSink",
    "register_pagerduty_alert_sink",
    "register_channel_alert_sink",
    "get_slo_alert_bridge",
    "init_slo_alerting",
    "shutdown_slo_alerting",
]
