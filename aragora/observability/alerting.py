"""
Production Alerting Rules Module for Aragora.

Provides a comprehensive alerting system with:
- AlertRule dataclass for defining alert conditions
- AlertManager for evaluating rules and triggering notifications
- Critical alert rules for production monitoring
- Integration with Slack, Email, and Prometheus AlertManager

Usage:
    from aragora.observability.alerting import (
        AlertManager,
        AlertRule,
        AlertSeverity,
        get_alert_manager,
        init_alerting,
    )

    # Initialize at startup
    manager = init_alerting(
        slack_webhook_url="https://hooks.slack.com/...",
        smtp_host="smtp.example.com",
    )

    # Add custom rule
    manager.add_rule(AlertRule(
        name="custom_rule",
        condition=lambda metrics: metrics.get("custom_value", 0) > 100,
        severity=AlertSeverity.WARNING,
        notification_channels=["slack"],
        description="Custom value exceeded threshold",
    ))

    # Start monitoring
    await manager.start_monitoring()

Environment Variables:
    ALERTING_ENABLED: Enable/disable alerting (default: true)
    ALERTING_CHECK_INTERVAL_SECONDS: How often to evaluate rules (default: 30)
    ALERTING_COOLDOWN_SECONDS: Min time between same alerts (default: 300)
    SLACK_WEBHOOK_URL: Slack incoming webhook URL
    ALERT_EMAIL_RECIPIENTS: Comma-separated email addresses
    PROMETHEUS_ALERTMANAGER_URL: AlertManager endpoint

See docs/ALERTING.md for full configuration reference.
"""

from __future__ import annotations

import asyncio
import logging
import os
import smtplib
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from enum import Enum
from typing import Any
from collections.abc import Callable

logger = logging.getLogger(__name__)


# =============================================================================
# Enums and Constants
# =============================================================================


class AlertSeverity(str, Enum):
    """Alert severity levels."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class AlertState(str, Enum):
    """Alert lifecycle states."""

    PENDING = "pending"
    FIRING = "firing"
    RESOLVED = "resolved"


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class AlertRule:
    """
    Definition of an alert rule.

    Attributes:
        name: Unique identifier for the rule
        condition: Callable that takes metrics dict and returns True if alert should fire
        severity: Alert severity level
        notification_channels: List of channels to notify (slack, email, prometheus)
        description: Human-readable description of what the alert means
        runbook_url: Optional link to runbook for remediation
        labels: Additional labels for categorization
        cooldown_seconds: Override default cooldown for this rule
        for_duration_seconds: Condition must be true for this duration before firing
    """

    name: str
    condition: Callable[[dict[str, Any]], bool]
    severity: AlertSeverity
    notification_channels: list[str] = field(default_factory=lambda: ["slack"])
    description: str = ""
    runbook_url: str | None = None
    labels: dict[str, str] = field(default_factory=dict)
    cooldown_seconds: float | None = None
    for_duration_seconds: float = 0.0

    def __hash__(self) -> int:
        """Make AlertRule hashable by name."""
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        """Compare rules by name."""
        if isinstance(other, AlertRule):
            return self.name == other.name
        return False


@dataclass
class Alert:
    """
    An active or historical alert instance.

    Attributes:
        rule_name: Name of the rule that triggered this alert
        severity: Alert severity
        state: Current state (pending, firing, resolved)
        message: Alert message
        first_triggered: When the alert condition first became true
        last_triggered: Most recent evaluation where condition was true
        resolved_at: When the alert was resolved (if resolved)
        labels: Labels from the rule plus any dynamic labels
        annotations: Additional context about the alert
        notification_count: Number of notifications sent for this alert
    """

    rule_name: str
    severity: AlertSeverity
    state: AlertState
    message: str
    first_triggered: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_triggered: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: datetime | None = None
    labels: dict[str, str] = field(default_factory=dict)
    annotations: dict[str, Any] = field(default_factory=dict)
    notification_count: int = 0
    id: str = field(default_factory=lambda: f"alert-{int(time.time() * 1000)}")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "rule_name": self.rule_name,
            "severity": self.severity.value,
            "state": self.state.value,
            "message": self.message,
            "first_triggered": self.first_triggered.isoformat(),
            "last_triggered": self.last_triggered.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "labels": self.labels,
            "annotations": self.annotations,
            "notification_count": self.notification_count,
        }


@dataclass
class MetricsSnapshot:
    """
    Snapshot of system metrics for alert evaluation.

    Populated by collecting data from various observability sources.
    """

    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Agent metrics
    agent_failures: dict[str, int] = field(default_factory=dict)
    agent_failure_timestamps: dict[str, list[float]] = field(default_factory=dict)
    circuit_breaker_states: dict[str, str] = field(default_factory=dict)

    # Debate metrics
    active_debates: int = 0
    debate_phase_durations: dict[str, float] = field(default_factory=dict)
    stalled_debates: list[str] = field(default_factory=list)
    consensus_failures_hourly: int = 0
    total_debates_hourly: int = 0

    # Queue metrics
    queue_size: int = 0
    queue_capacity: int = 1000

    # Memory metrics
    memory_eviction_rate: float = 0.0

    # Rate limit metrics
    rate_limited_tenants: list[str] = field(default_factory=list)

    # API latency metrics
    api_latency_p99: float = 0.0
    api_latency_baseline: float = 0.1

    # Custom metrics
    custom: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Notification Channels
# =============================================================================


class NotificationChannel(ABC):
    """Base class for notification channels."""

    @abstractmethod
    async def send(self, alert: Alert, rule: AlertRule) -> bool:
        """Send notification for an alert."""
        pass

    @abstractmethod
    def get_name(self) -> str:
        """Get the channel name."""
        pass


class SlackNotificationChannel(NotificationChannel):
    """Slack webhook notification channel."""

    def __init__(self, webhook_url: str, channel: str | None = None):
        self.webhook_url = webhook_url
        self.channel = channel

    def get_name(self) -> str:
        return "slack"

    async def send(self, alert: Alert, rule: AlertRule) -> bool:
        """Send alert to Slack."""
        try:
            # Build Slack message
            color = self._get_severity_color(alert.severity)
            blocks = self._build_slack_blocks(alert, rule)

            payload: dict[str, Any] = {
                "attachments": [
                    {
                        "color": color,
                        "blocks": blocks,
                    }
                ]
            }

            if self.channel:
                payload["channel"] = self.channel

            # Send via HTTP
            await self._post_webhook(payload)
            logger.info("Slack notification sent for alert %s", alert.rule_name)
            return True

        except (OSError, ConnectionError, ValueError) as e:
            logger.error("Failed to send Slack notification: %s", e)
            return False

    def _get_severity_color(self, severity: AlertSeverity) -> str:
        """Map severity to Slack attachment color."""
        return {
            AlertSeverity.INFO: "#36a64f",
            AlertSeverity.WARNING: "#ffa500",
            AlertSeverity.CRITICAL: "#ff0000",
            AlertSeverity.EMERGENCY: "#8b0000",
        }.get(severity, "#808080")

    def _build_slack_blocks(self, alert: Alert, rule: AlertRule) -> list[dict[str, Any]]:
        """Build Slack Block Kit message."""
        blocks: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"[{alert.severity.value.upper()}] {alert.rule_name}",
                },
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": alert.message},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*State:*\n{alert.state.value}"},
                    {
                        "type": "mrkdwn",
                        "text": f"*First Seen:*\n{alert.first_triggered.strftime('%H:%M:%S UTC')}",
                    },
                ],
            },
        ]

        if rule.description:
            blocks.append(
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": rule.description}],
                }
            )

        if rule.runbook_url:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"<{rule.runbook_url}|View Runbook>",
                    },
                }
            )

        return blocks

    async def _post_webhook(self, payload: dict[str, Any]) -> None:
        """Post payload to Slack webhook."""
        try:
            from aragora.observability.http_client_pool import get_http_pool

            pool = get_http_pool()
            async with pool.get_session("slack-alerts") as client:
                response = await client.post(self.webhook_url, json=payload, timeout=10.0)
                response.raise_for_status()
        except ImportError:
            # Fallback to aiohttp if http_client_pool not available
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.webhook_url, json=payload, timeout=aiohttp.ClientTimeout(10)
                ) as response:
                    response.raise_for_status()


class EmailNotificationChannel(NotificationChannel):
    """Email notification channel via SMTP."""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int = 587,
        smtp_user: str | None = None,
        smtp_password: str | None = None,
        from_address: str = "alerts@aragora.dev",
        recipients: list[str] | None = None,
        use_tls: bool = True,
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.from_address = from_address
        self.recipients = recipients or []
        self.use_tls = use_tls

    def get_name(self) -> str:
        return "email"

    async def send(self, alert: Alert, rule: AlertRule) -> bool:
        """Send alert via email."""
        if not self.recipients:
            logger.warning("No email recipients configured, skipping email notification")
            return False

        try:
            # Run SMTP in thread pool to avoid blocking
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._send_email_sync, alert, rule)
            logger.info(
                "Email notification sent for alert %s to %s recipients",
                alert.rule_name,
                len(self.recipients),
            )
            return True
        except (OSError, smtplib.SMTPException, ConnectionError) as e:
            logger.error("Failed to send email notification: %s", e)
            return False

    def _send_email_sync(self, alert: Alert, rule: AlertRule) -> None:
        """Synchronously send email."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[{alert.severity.value.upper()}] Aragora Alert: {alert.rule_name}"
        msg["From"] = self.from_address
        msg["To"] = ", ".join(self.recipients)

        # Plain text version
        text_content = self._build_text_content(alert, rule)
        msg.attach(MIMEText(text_content, "plain"))

        # HTML version
        html_content = self._build_html_content(alert, rule)
        msg.attach(MIMEText(html_content, "html"))

        # Send email
        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            if self.use_tls:
                server.starttls()
            if self.smtp_user and self.smtp_password:
                server.login(self.smtp_user, self.smtp_password)
            server.sendmail(self.from_address, self.recipients, msg.as_string())

    def _build_text_content(self, alert: Alert, rule: AlertRule) -> str:
        """Build plain text email content."""
        lines = [
            f"Alert: {alert.rule_name}",
            f"Severity: {alert.severity.value.upper()}",
            f"State: {alert.state.value}",
            "",
            alert.message,
            "",
            f"First Triggered: {alert.first_triggered.isoformat()}",
            f"Last Triggered: {alert.last_triggered.isoformat()}",
        ]

        if rule.description:
            lines.extend(["", "Description:", rule.description])

        if rule.runbook_url:
            lines.extend(["", f"Runbook: {rule.runbook_url}"])

        return "\n".join(lines)

    def _build_html_content(self, alert: Alert, rule: AlertRule) -> str:
        """Build HTML email content."""
        severity_color = {
            AlertSeverity.INFO: "#36a64f",
            AlertSeverity.WARNING: "#ffa500",
            AlertSeverity.CRITICAL: "#ff0000",
            AlertSeverity.EMERGENCY: "#8b0000",
        }.get(alert.severity, "#808080")

        return f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <div style="border-left: 4px solid {severity_color}; padding-left: 15px;">
                <h2 style="margin: 0 0 10px 0; color: {severity_color};">
                    [{alert.severity.value.upper()}] {alert.rule_name}
                </h2>
                <p style="margin: 5px 0;"><strong>State:</strong> {alert.state.value}</p>
                <p style="margin: 15px 0;">{alert.message}</p>
                <p style="margin: 5px 0; color: #666; font-size: 0.9em;">
                    First Triggered: {alert.first_triggered.strftime("%Y-%m-%d %H:%M:%S UTC")}
                </p>
            </div>
            {f'<p style="margin-top: 15px;"><em>{rule.description}</em></p>' if rule.description else ""}
            {f'<p><a href="{rule.runbook_url}">View Runbook</a></p>' if rule.runbook_url else ""}
        </body>
        </html>
        """


class PrometheusAlertManagerChannel(NotificationChannel):
    """Prometheus AlertManager compatible notification channel."""

    def __init__(self, alertmanager_url: str):
        self.alertmanager_url = alertmanager_url.rstrip("/")

    def get_name(self) -> str:
        return "prometheus"

    async def send(self, alert: Alert, rule: AlertRule) -> bool:
        """Send alert to Prometheus AlertManager."""
        try:
            payload = self._build_alertmanager_payload(alert, rule)
            await self._post_alert(payload)
            logger.info("Prometheus AlertManager notification sent for %s", alert.rule_name)
            return True
        except (OSError, ConnectionError, ValueError) as e:
            logger.error("Failed to send AlertManager notification: %s", e)
            return False

    def _build_alertmanager_payload(self, alert: Alert, rule: AlertRule) -> list[dict[str, Any]]:
        """Build AlertManager API payload."""
        labels = {
            "alertname": alert.rule_name,
            "severity": alert.severity.value,
            **rule.labels,
            **alert.labels,
        }

        annotations = {
            "summary": alert.message,
            "description": rule.description,
            **alert.annotations,
        }

        if rule.runbook_url:
            annotations["runbook_url"] = rule.runbook_url

        return [
            {
                "labels": labels,
                "annotations": annotations,
                "startsAt": alert.first_triggered.isoformat(),
                "endsAt": (alert.resolved_at.isoformat() if alert.resolved_at else ""),
                "generatorURL": "https://aragora.dev/alerts",
            }
        ]

    async def _post_alert(self, payload: list[dict[str, Any]]) -> None:
        """Post alert to AlertManager API."""
        url = f"{self.alertmanager_url}/api/v2/alerts"

        try:
            from aragora.observability.http_client_pool import get_http_pool

            pool = get_http_pool()
            async with pool.get_session("alertmanager") as client:
                response = await client.post(url, json=payload, timeout=10.0)
                response.raise_for_status()
        except ImportError:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=payload, timeout=aiohttp.ClientTimeout(10)
                ) as response:
                    response.raise_for_status()


# =============================================================================
# Metrics Collector
# =============================================================================


class MetricsCollector:
    """
    Collects metrics from various observability sources for alert evaluation.

    This class integrates with the existing Prometheus metrics and
    other observability systems to gather data.
    """

    def __init__(self) -> None:
        self._agent_failure_window: dict[str, deque[float]] = {}
        self._window_seconds = 300.0  # 5-minute window for failure tracking

    async def collect(self) -> MetricsSnapshot:
        """Collect current metrics snapshot."""
        snapshot = MetricsSnapshot()

        try:
            await self._collect_agent_metrics(snapshot)
        except Exception as e:  # noqa: BLE001 - observability must not crash app
            logger.debug("Error collecting agent metrics: %s", e)

        try:
            await self._collect_debate_metrics(snapshot)
        except Exception as e:  # noqa: BLE001 - observability must not crash app
            logger.debug("Error collecting debate metrics: %s", e)

        try:
            await self._collect_queue_metrics(snapshot)
        except Exception as e:  # noqa: BLE001 - observability must not crash app
            logger.debug("Error collecting queue metrics: %s", e)

        try:
            await self._collect_memory_metrics(snapshot)
        except Exception as e:  # noqa: BLE001 - observability must not crash app
            logger.debug("Error collecting memory metrics: %s", e)

        try:
            await self._collect_api_metrics(snapshot)
        except Exception as e:  # noqa: BLE001 - observability must not crash app
            logger.debug("Error collecting API metrics: %s", e)

        return snapshot

    def record_agent_failure(self, agent_name: str) -> None:
        """Record an agent failure for cascade detection."""
        now = time.time()
        if agent_name not in self._agent_failure_window:
            self._agent_failure_window[agent_name] = deque()

        self._agent_failure_window[agent_name].append(now)
        self._prune_old_failures(agent_name)

    def record_circuit_breaker_state(self, provider: str, state: str) -> None:
        """Record circuit breaker state change."""
        # This will be reflected in the next metrics collection
        pass

    def _prune_old_failures(self, agent_name: str) -> None:
        """Remove failures outside the window."""
        now = time.time()
        cutoff = now - self._window_seconds
        window = self._agent_failure_window.get(agent_name, deque())

        while window and window[0] < cutoff:
            window.popleft()

    async def _collect_agent_metrics(self, snapshot: MetricsSnapshot) -> None:
        """Collect agent-related metrics."""
        # Prune and collect failure counts
        for agent_name, window in self._agent_failure_window.items():
            self._prune_old_failures(agent_name)
            snapshot.agent_failures[agent_name] = len(window)
            snapshot.agent_failure_timestamps[agent_name] = list(window)

        # Try to get circuit breaker states
        try:
            from aragora.resilience import get_circuit_breakers

            breakers = get_circuit_breakers()
            if breakers:
                for name, breaker in breakers.items():
                    snapshot.circuit_breaker_states[name] = breaker.state
        except (ImportError, AttributeError):
            pass

    async def _collect_debate_metrics(self, snapshot: MetricsSnapshot) -> None:
        """Collect debate-related metrics."""
        try:
            from aragora.observability.server_metrics import ACTIVE_DEBATES

            snapshot.active_debates = int(ACTIVE_DEBATES.get())
        except (ImportError, AttributeError):
            pass

        # Detect stalled debates (would need integration with debate tracking)
        # This is a placeholder - actual implementation would query active debates

    async def _collect_queue_metrics(self, snapshot: MetricsSnapshot) -> None:
        """Collect queue-related metrics."""
        try:
            from aragora.observability.metrics.task_queue import TASK_QUEUE_SIZE

            if TASK_QUEUE_SIZE is not None:
                # Sum pending, ready, running queue sizes
                total = 0
                for status in ("pending", "ready", "running"):
                    try:
                        total += int(TASK_QUEUE_SIZE.labels(status=status)._value.get())
                    except (AttributeError, KeyError) as e:
                        logger.debug("Failed to parse numeric value: %s", e)
                snapshot.queue_size = total
        except (ImportError, AttributeError):
            # Use defaults
            pass

    async def _collect_memory_metrics(self, snapshot: MetricsSnapshot) -> None:
        """Collect memory-related metrics."""
        # Memory eviction rate is not currently tracked via metrics.
        # The snapshot uses the default value (0.0) from MetricsSnapshot.
        pass

    async def _collect_api_metrics(self, snapshot: MetricsSnapshot) -> None:
        """Collect API latency metrics."""
        try:
            from aragora.observability.metrics.request import REQUEST_LATENCY

            if REQUEST_LATENCY is not None:
                # This would need histogram quantile calculation
                # For now, use placeholder
                pass
        except (ImportError, AttributeError):
            pass


# =============================================================================
# Alert Manager
# =============================================================================


class AlertManager:
    """
    Central alert management system.

    Evaluates alert rules against metrics and triggers notifications
    through configured channels.
    """

    def __init__(
        self,
        check_interval_seconds: float = 30.0,
        default_cooldown_seconds: float = 300.0,
    ) -> None:
        """
        Initialize the alert manager.

        Args:
            check_interval_seconds: How often to evaluate alert rules
            default_cooldown_seconds: Default time between repeated notifications
        """
        self.check_interval = check_interval_seconds
        self.default_cooldown = default_cooldown_seconds

        self._rules: dict[str, AlertRule] = {}
        self._channels: dict[str, NotificationChannel] = {}
        self._active_alerts: dict[str, Alert] = {}
        self._last_notification: dict[str, float] = {}
        self._pending_since: dict[str, float] = {}

        self._collector = MetricsCollector()
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    # =========================================================================
    # Rule Management
    # =========================================================================

    def add_rule(self, rule: AlertRule) -> None:
        """Add an alert rule."""
        self._rules[rule.name] = rule
        logger.info("Added alert rule: %s", rule.name)

    def remove_rule(self, rule_name: str) -> bool:
        """Remove an alert rule. Returns True if rule existed."""
        if rule_name in self._rules:
            del self._rules[rule_name]
            logger.info("Removed alert rule: %s", rule_name)
            return True
        return False

    def get_rules(self) -> list[AlertRule]:
        """Get all registered rules."""
        return list(self._rules.values())

    # =========================================================================
    # Channel Management
    # =========================================================================

    def add_channel(self, channel: NotificationChannel) -> None:
        """Add a notification channel."""
        self._channels[channel.get_name()] = channel
        logger.info("Added notification channel: %s", channel.get_name())

    def remove_channel(self, channel_name: str) -> bool:
        """Remove a notification channel."""
        if channel_name in self._channels:
            del self._channels[channel_name]
            return True
        return False

    # =========================================================================
    # Alert State
    # =========================================================================

    def get_active_alerts(self) -> list[Alert]:
        """Get currently firing alerts."""
        return [a for a in self._active_alerts.values() if a.state == AlertState.FIRING]

    def get_all_alerts(self) -> list[Alert]:
        """Get all alerts (active and pending)."""
        return list(self._active_alerts.values())

    def acknowledge_alert(self, alert_id: str) -> bool:
        """Acknowledge an alert (stops notifications but doesn't resolve)."""
        for alert in self._active_alerts.values():
            if alert.id == alert_id:
                # Set a high notification count to effectively silence
                alert.notification_count = 999999
                logger.info("Alert %s acknowledged", alert_id)
                return True
        return False

    def resolve_alert(self, rule_name: str) -> bool:
        """Manually resolve an alert."""
        if rule_name in self._active_alerts:
            alert = self._active_alerts[rule_name]
            alert.state = AlertState.RESOLVED
            alert.resolved_at = datetime.now(timezone.utc)
            del self._active_alerts[rule_name]
            logger.info("Alert %s manually resolved", rule_name)
            return True
        return False

    # =========================================================================
    # Metrics Collector Access
    # =========================================================================

    def get_collector(self) -> MetricsCollector:
        """Get the metrics collector for external event recording."""
        return self._collector

    # =========================================================================
    # Monitoring Loop
    # =========================================================================

    async def start_monitoring(self) -> None:
        """Start the background monitoring loop."""
        if self._running:
            logger.warning("Alert monitoring already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info(
            "Alert monitoring started (interval: %ss, rules: %s, channels: %s)",
            self.check_interval,
            len(self._rules),
            len(self._channels),
        )

    async def stop_monitoring(self) -> None:
        """Stop the background monitoring loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Alert monitoring stopped")

    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                await self.evaluate_rules()
            except Exception as e:  # noqa: BLE001 - observability must not crash app
                logger.error("Error in alert monitoring loop: %s", e)

            await asyncio.sleep(self.check_interval)

    async def evaluate_rules(self) -> list[Alert]:
        """Evaluate all rules and return newly fired alerts."""
        async with self._lock:
            # Collect current metrics
            metrics = await self._collector.collect()
            metrics_dict = self._metrics_to_dict(metrics)

            fired_alerts: list[Alert] = []
            now = time.time()

            for rule_name, rule in self._rules.items():
                try:
                    condition_met = rule.condition(metrics_dict)
                except Exception as e:  # noqa: BLE001 - observability must not crash app
                    logger.error("Error evaluating rule %s: %s", rule_name, e)
                    continue

                if condition_met:
                    alert = await self._handle_condition_met(rule, metrics_dict, now)
                    if alert and alert.state == AlertState.FIRING:
                        fired_alerts.append(alert)
                else:
                    await self._handle_condition_resolved(rule_name)

            return fired_alerts

    def _metrics_to_dict(self, metrics: MetricsSnapshot) -> dict[str, Any]:
        """Convert MetricsSnapshot to dictionary for rule evaluation."""
        return {
            "timestamp": metrics.timestamp,
            "agent_failures": metrics.agent_failures,
            "agent_failure_timestamps": metrics.agent_failure_timestamps,
            "circuit_breaker_states": metrics.circuit_breaker_states,
            "active_debates": metrics.active_debates,
            "debate_phase_durations": metrics.debate_phase_durations,
            "stalled_debates": metrics.stalled_debates,
            "consensus_failures_hourly": metrics.consensus_failures_hourly,
            "total_debates_hourly": metrics.total_debates_hourly,
            "queue_size": metrics.queue_size,
            "queue_capacity": metrics.queue_capacity,
            "queue_saturation": (
                metrics.queue_size / metrics.queue_capacity if metrics.queue_capacity > 0 else 0.0
            ),
            "memory_eviction_rate": metrics.memory_eviction_rate,
            "rate_limited_tenants": metrics.rate_limited_tenants,
            "api_latency_p99": metrics.api_latency_p99,
            "api_latency_baseline": metrics.api_latency_baseline,
            **metrics.custom,
        }

    async def _handle_condition_met(
        self,
        rule: AlertRule,
        metrics: dict[str, Any],
        now: float,
    ) -> Alert | None:
        """Handle when a rule condition is met."""
        rule_name = rule.name

        # Check if this is a new condition or continuation
        if rule_name not in self._pending_since:
            self._pending_since[rule_name] = now

        time_in_condition = now - self._pending_since[rule_name]

        # Check if we've met the for_duration requirement
        if time_in_condition < rule.for_duration_seconds:
            # Still pending, not yet firing
            if rule_name not in self._active_alerts:
                self._active_alerts[rule_name] = Alert(
                    rule_name=rule_name,
                    severity=rule.severity,
                    state=AlertState.PENDING,
                    message=self._build_alert_message(rule, metrics),
                    labels=rule.labels.copy(),
                )
            return self._active_alerts.get(rule_name)

        # Condition met for required duration
        if rule_name in self._active_alerts:
            alert = self._active_alerts[rule_name]
            alert.last_triggered = datetime.now(timezone.utc)
            alert.state = AlertState.FIRING
        else:
            alert = Alert(
                rule_name=rule_name,
                severity=rule.severity,
                state=AlertState.FIRING,
                message=self._build_alert_message(rule, metrics),
                labels=rule.labels.copy(),
            )
            self._active_alerts[rule_name] = alert

        # Send notifications if cooldown allows
        await self._maybe_notify(alert, rule)

        return alert

    async def _handle_condition_resolved(self, rule_name: str) -> None:
        """Handle when a rule condition is no longer met."""
        # Clear pending state
        if rule_name in self._pending_since:
            del self._pending_since[rule_name]

        # Resolve active alert if exists
        if rule_name in self._active_alerts:
            alert = self._active_alerts[rule_name]
            if alert.state == AlertState.FIRING:
                alert.state = AlertState.RESOLVED
                alert.resolved_at = datetime.now(timezone.utc)

                # Send resolution notification
                rule = self._rules.get(rule_name)
                if rule:
                    await self._send_notifications(alert, rule, is_resolution=True)

            del self._active_alerts[rule_name]

    def _build_alert_message(self, rule: AlertRule, metrics: dict[str, Any]) -> str:
        """Build alert message with context."""
        base_message = rule.description or f"Alert condition triggered: {rule.name}"

        # Add relevant metrics context
        context_parts = []

        if rule.name.startswith("agent_cascade"):
            failures = metrics.get("agent_failures", {})
            if failures:
                context_parts.append(
                    f"Failed agents: {', '.join(f'{k}({v})' for k, v in failures.items())}"
                )

        if rule.name.startswith("queue_"):
            saturation = metrics.get("queue_saturation", 0) * 100
            context_parts.append(f"Queue saturation: {saturation:.1f}%")

        if context_parts:
            return f"{base_message}\n{chr(10).join(context_parts)}"

        return base_message

    async def _maybe_notify(self, alert: Alert, rule: AlertRule) -> None:
        """Send notifications if cooldown allows."""
        now = time.time()
        last_notified = self._last_notification.get(rule.name, 0)
        cooldown = rule.cooldown_seconds or self.default_cooldown

        if now - last_notified < cooldown:
            return

        await self._send_notifications(alert, rule)
        self._last_notification[rule.name] = now
        alert.notification_count += 1

    async def _send_notifications(
        self,
        alert: Alert,
        rule: AlertRule,
        is_resolution: bool = False,
    ) -> None:
        """Send notifications to all configured channels."""
        for channel_name in rule.notification_channels:
            channel = self._channels.get(channel_name)
            if not channel:
                logger.warning(
                    "Notification channel '%s' not configured for alert %s", channel_name, rule.name
                )
                continue

            try:
                # Modify message for resolution
                if is_resolution:
                    original_message = alert.message
                    alert.message = f"[RESOLVED] {original_message}"

                await channel.send(alert, rule)

                # Restore original message
                if is_resolution:
                    alert.message = original_message

            except (OSError, ConnectionError, RuntimeError, ValueError) as e:
                logger.error(
                    "Failed to send notification via %s for alert %s: %s",
                    channel_name,
                    rule.name,
                    e,
                )


# =============================================================================
# Built-in Alert Rules
# =============================================================================


def create_critical_alert_rules() -> list[AlertRule]:
    """
    Create the 8 critical alert rules for production monitoring.

    Returns:
        List of pre-configured AlertRule instances
    """
    rules = []

    # 1. Agent cascade failure - 2+ providers fail within 5 minutes
    rules.append(
        AlertRule(
            name="agent_cascade_failure",
            condition=lambda m: sum(
                1 for count in m.get("agent_failures", {}).values() if count >= 1
            )
            >= 2,
            severity=AlertSeverity.CRITICAL,
            notification_channels=["slack", "email", "prometheus"],
            description="Multiple agent providers have failed within 5 minutes. "
            "This indicates a potential infrastructure issue or API outage.",
            runbook_url="https://docs.aragora.dev/runbooks/agent-cascade-failure",
            labels={"category": "agents", "team": "platform"},
            for_duration_seconds=0,  # Immediate alert
        )
    )

    # 2. Debate stalling - >5min without phase transition
    rules.append(
        AlertRule(
            name="debate_stalling",
            condition=lambda m: len(m.get("stalled_debates", [])) > 0,
            severity=AlertSeverity.WARNING,
            notification_channels=["slack", "prometheus"],
            description="One or more debates have stalled without phase transitions "
            "for over 5 minutes. This may indicate agent timeouts or processing issues.",
            runbook_url="https://docs.aragora.dev/runbooks/debate-stalling",
            labels={"category": "debates", "team": "core"},
            for_duration_seconds=300,  # 5 minutes
        )
    )

    # 3. Queue saturation - >90% capacity
    rules.append(
        AlertRule(
            name="queue_saturation_critical",
            condition=lambda m: m.get("queue_saturation", 0) > 0.9,
            severity=AlertSeverity.CRITICAL,
            notification_channels=["slack", "email", "prometheus"],
            description="Task queue is over 90% capacity. New tasks may be rejected "
            "or severely delayed. Scale workers or investigate processing backlog.",
            runbook_url="https://docs.aragora.dev/runbooks/queue-saturation",
            labels={"category": "infrastructure", "team": "platform"},
            for_duration_seconds=60,  # 1 minute sustained
        )
    )

    # 4. Consensus failure pattern - >10% failure rate in rolling hour
    rules.append(
        AlertRule(
            name="consensus_failure_pattern",
            condition=lambda m: (
                m.get("total_debates_hourly", 0) > 10
                and m.get("consensus_failures_hourly", 0) / max(m.get("total_debates_hourly", 1), 1)
                > 0.1
            ),
            severity=AlertSeverity.WARNING,
            notification_channels=["slack", "prometheus"],
            description="Consensus failure rate exceeds 10% in the past hour. "
            "This may indicate model degradation or problematic debate configurations.",
            runbook_url="https://docs.aragora.dev/runbooks/consensus-failures",
            labels={"category": "debates", "team": "ml"},
            for_duration_seconds=0,
        )
    )

    # 5. Memory pressure - eviction rate >5%
    rules.append(
        AlertRule(
            name="memory_pressure_warning",
            condition=lambda m: m.get("memory_eviction_rate", 0) > 0.05,
            severity=AlertSeverity.WARNING,
            notification_channels=["slack", "prometheus"],
            description="Memory eviction rate exceeds 5%. Cache efficiency is degraded. "
            "Consider increasing memory allocation or reviewing cache policies.",
            runbook_url="https://docs.aragora.dev/runbooks/memory-pressure",
            labels={"category": "infrastructure", "team": "platform"},
            for_duration_seconds=120,  # 2 minutes sustained
        )
    )

    # 6. Rate limit exceeded - tenant hitting limits
    rules.append(
        AlertRule(
            name="rate_limit_exceeded",
            condition=lambda m: len(m.get("rate_limited_tenants", [])) > 0,
            severity=AlertSeverity.INFO,
            notification_channels=["prometheus"],  # Info-level, just metrics
            description="One or more tenants are hitting rate limits. "
            "Review tenant usage patterns and consider quota adjustments.",
            labels={"category": "tenants", "team": "billing"},
            for_duration_seconds=0,
        )
    )

    # 7. Circuit breaker open - any provider circuit opens
    rules.append(
        AlertRule(
            name="circuit_breaker_open",
            condition=lambda m: any(
                state == "open" for state in m.get("circuit_breaker_states", {}).values()
            ),
            severity=AlertSeverity.WARNING,
            notification_channels=["slack", "prometheus"],
            description="A circuit breaker has opened due to repeated failures. "
            "The affected provider will be unavailable until recovery.",
            runbook_url="https://docs.aragora.dev/runbooks/circuit-breaker",
            labels={"category": "agents", "team": "platform"},
            for_duration_seconds=0,  # Immediate alert
        )
    )

    # 8. API latency spike - p99 > 2x baseline
    rules.append(
        AlertRule(
            name="api_latency_spike",
            condition=lambda m: (
                m.get("api_latency_p99", 0) > 0
                and m.get("api_latency_baseline", 0) > 0
                and m.get("api_latency_p99", 0) > 2 * m.get("api_latency_baseline", 1)
            ),
            severity=AlertSeverity.WARNING,
            notification_channels=["slack", "prometheus"],
            description="API p99 latency has spiked to more than 2x the baseline. "
            "Investigate slow queries, external service degradation, or resource constraints.",
            runbook_url="https://docs.aragora.dev/runbooks/latency-spike",
            labels={"category": "performance", "team": "platform"},
            for_duration_seconds=60,  # 1 minute sustained
        )
    )

    return rules


# =============================================================================
# Global Instance and Initialization
# =============================================================================

_global_manager: AlertManager | None = None


def get_alert_manager() -> AlertManager | None:
    """Get the global alert manager instance."""
    return _global_manager


def init_alerting(
    slack_webhook_url: str | None = None,
    smtp_host: str | None = None,
    smtp_port: int = 587,
    smtp_user: str | None = None,
    smtp_password: str | None = None,
    email_from: str = "alerts@aragora.dev",
    email_recipients: list[str] | None = None,
    prometheus_alertmanager_url: str | None = None,
    check_interval_seconds: float = 30.0,
    cooldown_seconds: float = 300.0,
    include_critical_rules: bool = True,
) -> AlertManager:
    """
    Initialize the alerting system.

    Reads configuration from environment variables and parameters.
    Environment variables (override parameters):
        - ALERTING_ENABLED
        - ALERTING_CHECK_INTERVAL_SECONDS
        - ALERTING_COOLDOWN_SECONDS
        - SLACK_WEBHOOK_URL
        - SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD
        - ALERT_EMAIL_RECIPIENTS (comma-separated)
        - PROMETHEUS_ALERTMANAGER_URL

    Args:
        slack_webhook_url: Slack incoming webhook URL
        smtp_host: SMTP server hostname
        smtp_port: SMTP server port
        smtp_user: SMTP authentication username
        smtp_password: SMTP authentication password
        email_from: From address for alert emails
        email_recipients: List of email recipients
        prometheus_alertmanager_url: Prometheus AlertManager URL
        check_interval_seconds: How often to evaluate rules
        cooldown_seconds: Default cooldown between notifications
        include_critical_rules: Whether to include built-in critical rules

    Returns:
        Configured AlertManager instance
    """
    global _global_manager

    # Check if alerting is enabled
    enabled = os.getenv("ALERTING_ENABLED", "true").lower() in ("true", "1", "yes")
    if not enabled:
        logger.info("Alerting is disabled via ALERTING_ENABLED")
        _global_manager = AlertManager()  # Empty manager
        return _global_manager

    # Get config from environment with parameter fallbacks
    check_interval = float(
        os.getenv("ALERTING_CHECK_INTERVAL_SECONDS", str(check_interval_seconds))
    )
    cooldown = float(os.getenv("ALERTING_COOLDOWN_SECONDS", str(cooldown_seconds)))

    # Create manager
    _global_manager = AlertManager(
        check_interval_seconds=check_interval,
        default_cooldown_seconds=cooldown,
    )

    # Configure Slack channel
    slack_url = os.getenv("SLACK_WEBHOOK_URL") or slack_webhook_url
    if slack_url:
        _global_manager.add_channel(SlackNotificationChannel(slack_url))

    # Configure Email channel
    email_host = os.getenv("SMTP_HOST") or smtp_host
    if email_host:
        recipients = email_recipients or []
        env_recipients = os.getenv("ALERT_EMAIL_RECIPIENTS", "")
        if env_recipients:
            recipients = [r.strip() for r in env_recipients.split(",") if r.strip()]

        _global_manager.add_channel(
            EmailNotificationChannel(
                smtp_host=email_host,
                smtp_port=int(os.getenv("SMTP_PORT", str(smtp_port))),
                smtp_user=os.getenv("SMTP_USER") or smtp_user,
                smtp_password=os.getenv("SMTP_PASSWORD") or smtp_password,
                from_address=email_from,
                recipients=recipients,
            )
        )

    # Configure Prometheus AlertManager channel
    alertmanager_url = os.getenv("PROMETHEUS_ALERTMANAGER_URL") or prometheus_alertmanager_url
    if alertmanager_url:
        _global_manager.add_channel(PrometheusAlertManagerChannel(alertmanager_url))

    # Add built-in critical rules
    if include_critical_rules:
        for rule in create_critical_alert_rules():
            _global_manager.add_rule(rule)

    logger.info(
        "Alerting initialized: rules=%s, channels=%s",
        len(_global_manager.get_rules()),
        list(_global_manager._channels.keys()),
    )

    return _global_manager


def shutdown_alerting() -> None:
    """Shutdown the alerting system."""
    global _global_manager

    if _global_manager:
        # Stop monitoring synchronously by setting flag
        _global_manager._running = False
        logger.info("Alerting shutdown initiated")

    _global_manager = None


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Enums
    "AlertSeverity",
    "AlertState",
    # Data Classes
    "AlertRule",
    "Alert",
    "MetricsSnapshot",
    # Notification Channels
    "NotificationChannel",
    "SlackNotificationChannel",
    "EmailNotificationChannel",
    "PrometheusAlertManagerChannel",
    # Core Classes
    "MetricsCollector",
    "AlertManager",
    # Factory Functions
    "create_critical_alert_rules",
    # Global Functions
    "get_alert_manager",
    "init_alerting",
    "shutdown_alerting",
]
