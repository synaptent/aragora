"""
Tests for SLO Alert Bridge module.

Tests alert routing (PagerDuty, Slack, webhooks), incident deduplication,
cooldown handling, business hours calculations, webhook URL validation,
error handling, and edge cases.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.observability.slo_alert_bridge import (
    ActiveViolation,
    AlertChannel,
    AlertSeverity,
    SLOAlertBridge,
    SLOAlertConfig,
    get_slo_alert_bridge,
    init_slo_alerting,
    register_channel_alert_sink,
    register_pagerduty_alert_sink,
    shutdown_slo_alerting,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def _register_external_alert_sinks():
    """Register concrete adapters before constructing bridge fixtures."""
    from aragora.connectors.devops.slo_alert_sink import (
        register_slo_alert_sink as register_pagerduty_sink,
    )
    from aragora.control_plane.slo_alert_sink import (
        register_slo_alert_sink as register_channel_sink,
    )

    register_pagerduty_sink()
    register_channel_sink()
    yield
    register_pagerduty_alert_sink(None)
    register_channel_alert_sink(None)


@pytest.fixture
def default_config() -> SLOAlertConfig:
    """Create a default config with all channels disabled."""
    return SLOAlertConfig()


@pytest.fixture
def pagerduty_config() -> SLOAlertConfig:
    """Create a config with PagerDuty enabled."""
    return SLOAlertConfig(
        pagerduty_enabled=True,
        pagerduty_api_key="test-pd-api-key",
        pagerduty_service_id="PSERVICE01",
        pagerduty_email="slo@test.dev",
        pagerduty_min_severity=AlertSeverity.MAJOR,
    )


@pytest.fixture
def slack_config() -> SLOAlertConfig:
    """Create a config with Slack enabled."""
    return SLOAlertConfig(
        slack_enabled=True,
        slack_webhook_url="https://hooks.slack.com/services/T00/B00/xxx",
        slack_channel="#slo-alerts",
        slack_min_severity=AlertSeverity.MINOR,
    )


@pytest.fixture
def all_channels_config() -> SLOAlertConfig:
    """Create a config with all channels enabled."""
    return SLOAlertConfig(
        pagerduty_enabled=True,
        pagerduty_api_key="test-pd-api-key",
        pagerduty_service_id="PSERVICE01",
        pagerduty_email="slo@test.dev",
        pagerduty_min_severity=AlertSeverity.MAJOR,
        slack_enabled=True,
        slack_webhook_url="https://hooks.slack.com/services/T00/B00/xxx",
        slack_channel="#slo-alerts",
        slack_min_severity=AlertSeverity.MINOR,
        teams_enabled=True,
        teams_webhook_url="https://outlook.office.com/webhook/xxx",
        teams_min_severity=AlertSeverity.MINOR,
        cooldown_seconds=60.0,
        dedup_window_seconds=300.0,
        auto_resolve_on_recovery=True,
        include_runbook_links=True,
    )


@pytest.fixture
def bridge(default_config: SLOAlertConfig) -> SLOAlertBridge:
    """Create a bridge with default config."""
    return SLOAlertBridge(default_config)


@pytest.fixture
def pd_bridge(pagerduty_config: SLOAlertConfig) -> SLOAlertBridge:
    """Create a bridge with PagerDuty enabled."""
    return SLOAlertBridge(pagerduty_config)


@pytest.fixture
def slack_bridge(slack_config: SLOAlertConfig) -> SLOAlertBridge:
    """Create a bridge with Slack enabled."""
    return SLOAlertBridge(slack_config)


@pytest.fixture
def full_bridge(all_channels_config: SLOAlertConfig) -> SLOAlertBridge:
    """Create a bridge with all channels enabled."""
    return SLOAlertBridge(all_channels_config)


@pytest.fixture
def mock_pagerduty_connector():
    """Mock PagerDuty connector module."""
    mock_incident = MagicMock()
    mock_incident.id = "PD-INC-001"

    mock_connector = AsyncMock()
    mock_connector.create_incident = AsyncMock(return_value=mock_incident)
    mock_connector.resolve_incident = AsyncMock()
    mock_connector.__aenter__ = AsyncMock(return_value=mock_connector)
    mock_connector.__aexit__ = AsyncMock(return_value=None)

    mock_credentials_cls = MagicMock()
    mock_connector_cls = MagicMock(return_value=mock_connector)

    mock_request_cls = MagicMock()
    mock_urgency_cls = MagicMock()
    mock_urgency_cls.HIGH = "high"
    mock_urgency_cls.LOW = "low"

    return {
        "connector": mock_connector,
        "connector_cls": mock_connector_cls,
        "credentials_cls": mock_credentials_cls,
        "request_cls": mock_request_cls,
        "urgency_cls": mock_urgency_cls,
        "incident": mock_incident,
    }


@pytest.fixture
def mock_notification_manager():
    """Mock notification manager."""
    mock_manager = AsyncMock()
    mock_manager.add_channel = MagicMock()
    mock_manager.notify = AsyncMock()

    mock_event_type = MagicMock()
    mock_event_type.SLA_VIOLATION = "sla_violation"
    mock_event_type.TASK_COMPLETED = "task_completed"

    mock_priority = MagicMock()
    mock_priority.CRITICAL = "critical"
    mock_priority.URGENT = "urgent"
    mock_priority.HIGH = "high"
    mock_priority.NORMAL = "normal"
    mock_priority.LOW = "low"

    return {
        "manager": mock_manager,
        "event_type": mock_event_type,
        "priority": mock_priority,
    }


# =============================================================================
# Test Enums and Dataclasses
# =============================================================================


class TestAlertSeverity:
    """Tests for AlertSeverity enum."""

    def test_severity_values(self):
        """All severity levels have correct string values."""
        assert AlertSeverity.CRITICAL.value == "critical"
        assert AlertSeverity.MAJOR.value == "major"
        assert AlertSeverity.MODERATE.value == "moderate"
        assert AlertSeverity.MINOR.value == "minor"

    def test_severity_count(self):
        """Exactly 4 severity levels exist."""
        assert len(AlertSeverity) == 4


class TestAlertChannel:
    """Tests for AlertChannel enum."""

    def test_channel_values(self):
        """All channels have correct string values."""
        assert AlertChannel.PAGERDUTY.value == "pagerduty"
        assert AlertChannel.SLACK.value == "slack"
        assert AlertChannel.TEAMS.value == "teams"
        assert AlertChannel.EMAIL.value == "email"
        assert AlertChannel.WEBHOOK.value == "webhook"

    def test_channel_count(self):
        """Exactly 5 channels exist."""
        assert len(AlertChannel) == 5


class TestSLOAlertConfig:
    """Tests for SLOAlertConfig dataclass."""

    def test_default_config(self):
        """Default config has all channels disabled."""
        config = SLOAlertConfig()
        assert config.pagerduty_enabled is False
        assert config.slack_enabled is False
        assert config.teams_enabled is False
        assert config.cooldown_seconds == 60.0
        assert config.dedup_window_seconds == 300.0
        assert config.auto_resolve_on_recovery is True
        assert config.include_runbook_links is True

    def test_config_with_pagerduty(self):
        """Config with PagerDuty settings."""
        config = SLOAlertConfig(
            pagerduty_enabled=True,
            pagerduty_api_key="key",
            pagerduty_service_id="svc",
        )
        assert config.pagerduty_enabled is True
        assert config.pagerduty_api_key == "key"
        assert config.pagerduty_service_id == "svc"
        assert config.pagerduty_min_severity == AlertSeverity.MAJOR

    def test_config_defaults_email(self):
        """Default PagerDuty email is set."""
        config = SLOAlertConfig()
        assert config.pagerduty_email == "slo-alerts@aragora.dev"

    def test_config_custom_cooldown(self):
        """Custom cooldown value is accepted."""
        config = SLOAlertConfig(cooldown_seconds=120.0)
        assert config.cooldown_seconds == 120.0


class TestActiveViolation:
    """Tests for ActiveViolation dataclass."""

    def test_default_fields(self):
        """Default fields are set correctly."""
        v = ActiveViolation(
            operation="debate",
            percentile="p99",
            severity="critical",
            first_seen=1000.0,
            last_seen=1000.0,
        )
        assert v.count == 1
        assert v.incident_key is None
        assert v.pagerduty_incident_id is None
        assert v.notified_channels == set()

    def test_custom_fields(self):
        """Custom fields are set correctly."""
        v = ActiveViolation(
            operation="search",
            percentile="p95",
            severity="major",
            first_seen=1000.0,
            last_seen=1005.0,
            count=5,
            incident_key="abc123",
            pagerduty_incident_id="PD-001",
            notified_channels={"slack", "pagerduty"},
        )
        assert v.count == 5
        assert v.incident_key == "abc123"
        assert "slack" in v.notified_channels
        assert "pagerduty" in v.notified_channels


# =============================================================================
# Test Incident Key Generation
# =============================================================================


class TestMakeIncidentKey:
    """Tests for _make_incident_key."""

    def test_deterministic_key(self, bridge: SLOAlertBridge):
        """Same inputs produce same key."""
        key1 = bridge._make_incident_key("debate", "p99")
        key2 = bridge._make_incident_key("debate", "p99")
        assert key1 == key2

    def test_different_operations_produce_different_keys(self, bridge: SLOAlertBridge):
        """Different operations produce different keys."""
        key1 = bridge._make_incident_key("debate", "p99")
        key2 = bridge._make_incident_key("search", "p99")
        assert key1 != key2

    def test_different_percentiles_produce_different_keys(self, bridge: SLOAlertBridge):
        """Different percentiles produce different keys."""
        key1 = bridge._make_incident_key("debate", "p99")
        key2 = bridge._make_incident_key("debate", "p50")
        assert key1 != key2

    def test_key_is_16_chars(self, bridge: SLOAlertBridge):
        """Incident key is 16 hex characters (truncated SHA256)."""
        key = bridge._make_incident_key("debate", "p99")
        assert len(key) == 16
        # Verify it's valid hex
        int(key, 16)

    def test_key_matches_expected_sha256(self, bridge: SLOAlertBridge):
        """Key matches manually computed SHA256 prefix."""
        raw = "slo-debate-p99"
        expected = hashlib.sha256(raw.encode()).hexdigest()[:16]
        actual = bridge._make_incident_key("debate", "p99")
        assert actual == expected

    def test_special_characters_in_operation(self, bridge: SLOAlertBridge):
        """Special characters in operation name produce valid key."""
        key = bridge._make_incident_key("debate/v2/fast", "p99.5")
        assert len(key) == 16
        int(key, 16)  # valid hex

    def test_empty_strings(self, bridge: SLOAlertBridge):
        """Empty strings produce valid key."""
        key = bridge._make_incident_key("", "")
        assert len(key) == 16

    def test_unicode_in_operation(self, bridge: SLOAlertBridge):
        """Unicode characters in operation produce valid key."""
        key = bridge._make_incident_key("debat\u00e9", "p99")
        assert len(key) == 16


# =============================================================================
# Test Severity Mapping
# =============================================================================


class TestMapSeverity:
    """Tests for _map_severity."""

    def test_critical_maps(self, bridge: SLOAlertBridge):
        assert bridge._map_severity("critical") == AlertSeverity.CRITICAL

    def test_major_maps(self, bridge: SLOAlertBridge):
        assert bridge._map_severity("major") == AlertSeverity.MAJOR

    def test_moderate_maps(self, bridge: SLOAlertBridge):
        assert bridge._map_severity("moderate") == AlertSeverity.MODERATE

    def test_minor_maps(self, bridge: SLOAlertBridge):
        assert bridge._map_severity("minor") == AlertSeverity.MINOR

    def test_case_insensitive(self, bridge: SLOAlertBridge):
        """Mapping is case-insensitive."""
        assert bridge._map_severity("CRITICAL") == AlertSeverity.CRITICAL
        assert bridge._map_severity("Critical") == AlertSeverity.CRITICAL
        assert bridge._map_severity("MAJOR") == AlertSeverity.MAJOR

    def test_unknown_severity_defaults_to_minor(self, bridge: SLOAlertBridge):
        """Unknown severity strings default to MINOR."""
        assert bridge._map_severity("unknown") == AlertSeverity.MINOR
        assert bridge._map_severity("warning") == AlertSeverity.MINOR
        assert bridge._map_severity("") == AlertSeverity.MINOR


# =============================================================================
# Test Should Alert Logic
# =============================================================================


class TestShouldAlert:
    """Tests for _should_alert severity and cooldown filtering."""

    def test_pagerduty_blocks_minor_severity(self, pd_bridge: SLOAlertBridge):
        """PagerDuty with min_severity=MAJOR blocks MINOR alerts."""
        result = pd_bridge._should_alert(AlertChannel.PAGERDUTY, AlertSeverity.MINOR, "key1")
        assert result is False

    def test_pagerduty_blocks_moderate_severity(self, pd_bridge: SLOAlertBridge):
        """PagerDuty with min_severity=MAJOR blocks MODERATE alerts."""
        result = pd_bridge._should_alert(AlertChannel.PAGERDUTY, AlertSeverity.MODERATE, "key1")
        assert result is False

    def test_pagerduty_allows_major_severity(self, pd_bridge: SLOAlertBridge):
        """PagerDuty with min_severity=MAJOR allows MAJOR alerts."""
        result = pd_bridge._should_alert(AlertChannel.PAGERDUTY, AlertSeverity.MAJOR, "key1")
        assert result is True

    def test_pagerduty_allows_critical_severity(self, pd_bridge: SLOAlertBridge):
        """PagerDuty with min_severity=MAJOR allows CRITICAL alerts."""
        result = pd_bridge._should_alert(AlertChannel.PAGERDUTY, AlertSeverity.CRITICAL, "key1")
        assert result is True

    def test_slack_allows_all_severities(self, slack_bridge: SLOAlertBridge):
        """Slack with min_severity=MINOR allows all severities."""
        for severity in AlertSeverity:
            result = slack_bridge._should_alert(AlertChannel.SLACK, severity, "key1")
            assert result is True, f"Slack should allow {severity}"

    def test_cooldown_blocks_duplicate(self, slack_bridge: SLOAlertBridge):
        """Recent notification within cooldown blocks repeat."""
        cache_key = "slack:key1"
        slack_bridge._last_notification[cache_key] = time.time()

        result = slack_bridge._should_alert(AlertChannel.SLACK, AlertSeverity.CRITICAL, "key1")
        assert result is False

    def test_expired_cooldown_allows_alert(self, slack_bridge: SLOAlertBridge):
        """Notification after cooldown expires is allowed."""
        cache_key = "slack:key1"
        slack_bridge._last_notification[cache_key] = (
            time.time() - slack_bridge.config.cooldown_seconds - 1
        )

        result = slack_bridge._should_alert(AlertChannel.SLACK, AlertSeverity.CRITICAL, "key1")
        assert result is True

    def test_different_keys_independent_cooldown(self, slack_bridge: SLOAlertBridge):
        """Different incident keys have independent cooldowns."""
        slack_bridge._last_notification["slack:key1"] = time.time()

        # key2 should not be affected by key1's cooldown
        result = slack_bridge._should_alert(AlertChannel.SLACK, AlertSeverity.CRITICAL, "key2")
        assert result is True

    def test_different_channels_independent_cooldown(self, full_bridge: SLOAlertBridge):
        """Different channels have independent cooldowns for same key."""
        full_bridge._last_notification["slack:key1"] = time.time()

        # PagerDuty should not be affected by Slack's cooldown
        result = full_bridge._should_alert(AlertChannel.PAGERDUTY, AlertSeverity.CRITICAL, "key1")
        assert result is True

    def test_unknown_channel_defaults_to_minor_threshold(self, bridge: SLOAlertBridge):
        """Unknown channel defaults to MINOR minimum severity."""
        result = bridge._should_alert(AlertChannel.WEBHOOK, AlertSeverity.MINOR, "key1")
        assert result is True

    def test_zero_cooldown_always_allows(self):
        """Zero cooldown always allows alerts."""
        config = SLOAlertConfig(
            slack_enabled=True,
            slack_webhook_url="https://hooks.slack.com/services/T/B/x",
            cooldown_seconds=0.0,
        )
        b = SLOAlertBridge(config)
        b._last_notification["slack:key1"] = time.time()

        result = b._should_alert(AlertChannel.SLACK, AlertSeverity.MINOR, "key1")
        assert result is True


# =============================================================================
# Test Cooldown Handling
# =============================================================================


class TestCooldownHandling:
    """Tests for cooldown timing edge cases."""

    def test_cooldown_exactly_at_boundary(self, slack_bridge: SLOAlertBridge):
        """Alert at exact cooldown boundary is blocked (uses strict <)."""
        slack_bridge._last_notification["slack:key1"] = (
            time.time() - slack_bridge.config.cooldown_seconds
        )
        # time.time() - last_time == cooldown_seconds exactly,
        # which is NOT < cooldown_seconds, so alert is allowed
        result = slack_bridge._should_alert(AlertChannel.SLACK, AlertSeverity.CRITICAL, "key1")
        assert result is True

    def test_very_short_cooldown(self):
        """Very short cooldown works correctly."""
        config = SLOAlertConfig(
            slack_enabled=True,
            slack_webhook_url="https://hooks.slack.com/services/T/B/x",
            cooldown_seconds=0.001,
        )
        b = SLOAlertBridge(config)
        b._last_notification["slack:key1"] = time.time() - 0.01
        result = b._should_alert(AlertChannel.SLACK, AlertSeverity.MINOR, "key1")
        assert result is True

    def test_large_cooldown(self):
        """Large cooldown blocks alerts for a long time."""
        config = SLOAlertConfig(
            slack_enabled=True,
            slack_webhook_url="https://hooks.slack.com/services/T/B/x",
            cooldown_seconds=86400.0,  # 24 hours
        )
        b = SLOAlertBridge(config)
        b._last_notification["slack:key1"] = time.time() - 3600  # 1 hour ago
        result = b._should_alert(AlertChannel.SLACK, AlertSeverity.MINOR, "key1")
        assert result is False


# =============================================================================
# Test PagerDuty Alert Sending
# =============================================================================


class TestSendPagerDutyAlert:
    """Tests for _send_pagerduty_alert."""

    @pytest.mark.asyncio
    async def test_disabled_returns_none(self, bridge: SLOAlertBridge):
        """PagerDuty alert with disabled config returns None."""
        violation = ActiveViolation(
            operation="debate",
            percentile="p99",
            severity="critical",
            first_seen=time.time(),
            last_seen=time.time(),
        )
        result = await bridge._send_pagerduty_alert(violation, {})
        assert result is None

    @pytest.mark.asyncio
    async def test_registered_sink_factory_handles_incident_creation(
        self, pagerduty_config: SLOAlertConfig
    ):
        """PagerDuty delivery uses the connector-owned registered sink."""
        sink = AsyncMock()
        sink.create_incident = AsyncMock(return_value="PD-REGISTERED")
        register_pagerduty_alert_sink(lambda config: sink)
        try:
            registered_bridge = SLOAlertBridge(pagerduty_config)
            violation = ActiveViolation(
                operation="debate",
                percentile="p99",
                severity="critical",
                first_seen=time.time(),
                last_seen=time.time(),
                incident_key="registered-key",
            )

            result = await registered_bridge._send_pagerduty_alert(
                violation,
                {"latency_ms": 500, "threshold_ms": 200},
            )

            assert result == "PD-REGISTERED"
            sink.create_incident.assert_awaited_once()
        finally:
            register_pagerduty_alert_sink(None)

    @pytest.mark.asyncio
    async def test_sink_registered_after_bridge_creation_is_used(
        self, pagerduty_config: SLOAlertConfig
    ):
        """Direct bridges follow late registration, replacement, and removal."""
        register_pagerduty_alert_sink(None)
        registered_bridge = SLOAlertBridge(pagerduty_config)
        first_sink = AsyncMock()
        first_sink.create_incident = AsyncMock(return_value="PD-LATE")
        second_sink = AsyncMock()
        second_sink.create_incident = AsyncMock(return_value="PD-REPLACED")
        register_pagerduty_alert_sink(lambda config: first_sink)
        try:
            violation = ActiveViolation(
                operation="debate",
                percentile="p99",
                severity="critical",
                first_seen=time.time(),
                last_seen=time.time(),
                incident_key="late-key",
            )

            assert (
                await registered_bridge._send_pagerduty_alert(
                    violation,
                    {"latency_ms": 500, "threshold_ms": 200},
                )
                == "PD-LATE"
            )
            register_pagerduty_alert_sink(lambda config: second_sink)
            assert (
                await registered_bridge._send_pagerduty_alert(
                    violation,
                    {"latency_ms": 500, "threshold_ms": 200},
                )
                == "PD-REPLACED"
            )
            register_pagerduty_alert_sink(None)
            assert await registered_bridge._send_pagerduty_alert(violation, {}) is None
        finally:
            register_pagerduty_alert_sink(None)

        first_sink.create_incident.assert_awaited_once()
        second_sink.create_incident.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_failed_factory_replacement_clears_prior_sink(
        self, pagerduty_config: SLOAlertConfig
    ):
        """A failed explicit replacement cannot retain stale PagerDuty credentials."""
        old_sink = AsyncMock()
        old_sink.create_incident = AsyncMock(return_value="PD-OLD")
        register_pagerduty_alert_sink(lambda config: old_sink)
        bridge = SLOAlertBridge(pagerduty_config)
        factory_calls = 0

        def failing_factory(config):
            nonlocal factory_calls
            factory_calls += 1
            raise ValueError("invalid replacement")

        register_pagerduty_alert_sink(failing_factory)
        try:
            violation = ActiveViolation(
                operation="debate",
                percentile="p99",
                severity="critical",
                first_seen=time.time(),
                last_seen=time.time(),
            )
            assert await bridge._send_pagerduty_alert(violation, {}) is None
            assert await bridge._send_pagerduty_alert(violation, {}) is None
        finally:
            register_pagerduty_alert_sink(None)

        old_sink.create_incident.assert_not_awaited()
        assert factory_calls == 2

    @pytest.mark.asyncio
    async def test_connector_sink_constructs_real_incident_request(
        self, pagerduty_config: SLOAlertConfig
    ):
        """The concrete adapter maps primitive urgency into the connector enum."""
        from aragora.connectors.devops.pagerduty import IncidentUrgency
        from aragora.connectors.devops.slo_alert_sink import PagerDutySLOAlertSink

        incident = MagicMock(id="PD-REAL")
        connector = AsyncMock()
        connector.create_incident = AsyncMock(return_value=incident)
        sink = PagerDutySLOAlertSink(pagerduty_config)
        sink._connector = connector

        assert (
            await sink.create_incident(
                title="SLO violation",
                service_id="service-id",
                urgency="high",
                description="latency exceeded",
                incident_key="dedup-key",
            )
            == "PD-REAL"
        )
        request = connector.create_incident.call_args.args[0]
        assert request.urgency is IncidentUrgency.HIGH
        assert request.incident_key == "dedup-key"

    @pytest.mark.asyncio
    async def test_connector_sink_manages_real_connector_context(
        self, pagerduty_config: SLOAlertConfig
    ):
        """The concrete adapter enters and closes connectors it constructs."""
        from aragora.connectors.devops.slo_alert_sink import PagerDutySLOAlertSink

        incident = MagicMock(id="PD-CONTEXT")
        initialized = AsyncMock()
        initialized.create_incident = AsyncMock(return_value=incident)
        connector = MagicMock()
        connector.__aenter__ = AsyncMock(return_value=initialized)
        connector.__aexit__ = AsyncMock(return_value=None)
        sink = PagerDutySLOAlertSink(pagerduty_config)

        with patch(
            "aragora.connectors.devops.pagerduty.PagerDutyConnector",
            return_value=connector,
        ):
            assert (
                await sink.create_incident(
                    title="SLO violation",
                    service_id="service-id",
                    urgency="high",
                    description="latency exceeded",
                    incident_key="dedup-key",
                )
                == "PD-CONTEXT"
            )

        connector.__aenter__.assert_awaited_once()
        connector.__aexit__.assert_awaited_once()
        initialized.create_incident.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connector_sink_reports_resolution_failure(
        self, pagerduty_config: SLOAlertConfig
    ):
        """Connector exceptions produce an explicit failed resolution result."""
        from aragora.connectors.devops.slo_alert_sink import PagerDutySLOAlertSink

        sink = PagerDutySLOAlertSink(pagerduty_config)
        sink._connector = AsyncMock()
        sink._connector.resolve_incident = AsyncMock(side_effect=ConnectionError("down"))

        assert await sink.resolve_incident("PD-1", "recovered") is False

    @pytest.mark.asyncio
    async def test_import_error_returns_none(self, pd_bridge: SLOAlertBridge):
        """Import error for PagerDuty connector returns None gracefully."""
        violation = ActiveViolation(
            operation="debate",
            percentile="p99",
            severity="critical",
            first_seen=time.time(),
            last_seen=time.time(),
        )
        with patch.dict("sys.modules", {"aragora.connectors.devops.pagerduty": None}):
            result = await pd_bridge._send_pagerduty_alert(violation, {})
            assert result is None

    @pytest.mark.asyncio
    async def test_successful_incident_creation(
        self, pd_bridge: SLOAlertBridge, mock_pagerduty_connector
    ):
        """Successful PagerDuty incident creation returns incident ID."""
        violation = ActiveViolation(
            operation="debate",
            percentile="p99",
            severity="critical",
            first_seen=time.time(),
            last_seen=time.time(),
            incident_key="testkey123",
        )

        mock_module = MagicMock()
        mock_module.PagerDutyConnector = mock_pagerduty_connector["connector_cls"]
        mock_module.PagerDutyCredentials = mock_pagerduty_connector["credentials_cls"]
        mock_module.IncidentCreateRequest = mock_pagerduty_connector["request_cls"]
        mock_module.IncidentUrgency = mock_pagerduty_connector["urgency_cls"]

        # Make the connector class return our mock connector
        mock_pagerduty_connector["connector_cls"].return_value = mock_pagerduty_connector[
            "connector"
        ]

        with patch.dict(
            "sys.modules",
            {"aragora.connectors.devops.pagerduty": mock_module},
        ):
            result = await pd_bridge._send_pagerduty_alert(
                violation, {"latency_ms": 500, "threshold_ms": 200}
            )
            assert result == "PD-INC-001"

    @pytest.mark.asyncio
    async def test_incident_creation_failure(
        self, pd_bridge: SLOAlertBridge, mock_pagerduty_connector
    ):
        """Failed PagerDuty API call returns None."""
        violation = ActiveViolation(
            operation="debate",
            percentile="p99",
            severity="critical",
            first_seen=time.time(),
            last_seen=time.time(),
        )

        mock_pagerduty_connector["connector"].create_incident = AsyncMock(
            side_effect=ConnectionError("API Error")
        )
        mock_pagerduty_connector["connector_cls"].return_value = mock_pagerduty_connector[
            "connector"
        ]

        mock_module = MagicMock()
        mock_module.PagerDutyConnector = mock_pagerduty_connector["connector_cls"]
        mock_module.PagerDutyCredentials = mock_pagerduty_connector["credentials_cls"]
        mock_module.IncidentCreateRequest = mock_pagerduty_connector["request_cls"]
        mock_module.IncidentUrgency = mock_pagerduty_connector["urgency_cls"]

        with patch.dict(
            "sys.modules",
            {"aragora.connectors.devops.pagerduty": mock_module},
        ):
            result = await pd_bridge._send_pagerduty_alert(violation, {})
            assert result is None

    @pytest.mark.asyncio
    async def test_runbook_link_included_when_enabled(
        self, pd_bridge: SLOAlertBridge, mock_pagerduty_connector
    ):
        """Runbook link is included in description when enabled."""
        pd_bridge.config.include_runbook_links = True
        violation = ActiveViolation(
            operation="debate",
            percentile="p99",
            severity="critical",
            first_seen=time.time(),
            last_seen=time.time(),
            incident_key="testkey",
        )

        captured_request = None
        original_request_cls = mock_pagerduty_connector["request_cls"]

        def capture_request(*args, **kwargs):
            nonlocal captured_request
            captured_request = kwargs
            return original_request_cls(*args, **kwargs)

        mock_module = MagicMock()
        mock_module.PagerDutyConnector = mock_pagerduty_connector["connector_cls"]
        mock_module.PagerDutyCredentials = mock_pagerduty_connector["credentials_cls"]
        mock_module.IncidentCreateRequest = capture_request
        mock_module.IncidentUrgency = mock_pagerduty_connector["urgency_cls"]

        mock_pagerduty_connector["connector_cls"].return_value = mock_pagerduty_connector[
            "connector"
        ]

        with patch.dict(
            "sys.modules",
            {"aragora.connectors.devops.pagerduty": mock_module},
        ):
            await pd_bridge._send_pagerduty_alert(violation, {"latency_ms": 500})
            assert captured_request is not None
            assert "Runbook:" in captured_request["description"]

    @pytest.mark.asyncio
    async def test_runbook_link_excluded_when_disabled(
        self, pd_bridge: SLOAlertBridge, mock_pagerduty_connector
    ):
        """Runbook link is excluded when include_runbook_links is False."""
        pd_bridge.config.include_runbook_links = False
        violation = ActiveViolation(
            operation="debate",
            percentile="p99",
            severity="critical",
            first_seen=time.time(),
            last_seen=time.time(),
            incident_key="testkey",
        )

        captured_request = None
        original_request_cls = mock_pagerduty_connector["request_cls"]

        def capture_request(*args, **kwargs):
            nonlocal captured_request
            captured_request = kwargs
            return original_request_cls(*args, **kwargs)

        mock_module = MagicMock()
        mock_module.PagerDutyConnector = mock_pagerduty_connector["connector_cls"]
        mock_module.PagerDutyCredentials = mock_pagerduty_connector["credentials_cls"]
        mock_module.IncidentCreateRequest = capture_request
        mock_module.IncidentUrgency = mock_pagerduty_connector["urgency_cls"]

        mock_pagerduty_connector["connector_cls"].return_value = mock_pagerduty_connector[
            "connector"
        ]

        with patch.dict(
            "sys.modules",
            {"aragora.connectors.devops.pagerduty": mock_module},
        ):
            await pd_bridge._send_pagerduty_alert(violation, {"latency_ms": 500})
            assert captured_request is not None
            assert "Runbook:" not in captured_request["description"]


# =============================================================================
# Test Slack Alert Sending
# =============================================================================


class TestSendSlackAlert:
    """Tests for _send_slack_alert."""

    @pytest.mark.asyncio
    async def test_disabled_returns_false(self, bridge: SLOAlertBridge):
        """Slack alert with disabled config returns False."""
        violation = ActiveViolation(
            operation="debate",
            percentile="p99",
            severity="critical",
            first_seen=time.time(),
            last_seen=time.time(),
        )
        result = await bridge._send_slack_alert(violation, {})
        assert result is False

    @pytest.mark.asyncio
    async def test_registered_channel_sink_handles_notification(self, slack_config: SLOAlertConfig):
        """Slack delivery uses the control-plane-owned registered sink."""
        sink = AsyncMock()
        sink.notify = AsyncMock()
        register_channel_alert_sink(lambda config: sink)
        try:
            registered_bridge = SLOAlertBridge(slack_config)
            violation = ActiveViolation(
                operation="debate",
                percentile="p99",
                severity="critical",
                first_seen=time.time(),
                last_seen=time.time(),
            )

            assert await registered_bridge._send_slack_alert(violation, {}) is True
            sink.notify.assert_awaited_once()
        finally:
            register_channel_alert_sink(None)

    @pytest.mark.asyncio
    async def test_channel_sink_replacement_and_removal(self, slack_config: SLOAlertConfig):
        """Direct bridges stop using stale channel sinks after registration changes."""
        first_sink = AsyncMock()
        first_sink.notify = AsyncMock()
        second_sink = AsyncMock()
        second_sink.notify = AsyncMock()
        register_channel_alert_sink(lambda config: first_sink)
        registered_bridge = SLOAlertBridge(slack_config)
        violation = ActiveViolation(
            operation="debate",
            percentile="p99",
            severity="critical",
            first_seen=time.time(),
            last_seen=time.time(),
        )

        try:
            assert await registered_bridge._send_slack_alert(violation, {}) is True
            register_channel_alert_sink(lambda config: second_sink)
            assert await registered_bridge._send_slack_alert(violation, {}) is True
            register_channel_alert_sink(None)
            assert await registered_bridge._send_slack_alert(violation, {}) is False
        finally:
            register_channel_alert_sink(None)

        first_sink.notify.assert_awaited_once()
        second_sink.notify.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_failed_channel_factory_retries_without_stale_sink(
        self, slack_config: SLOAlertConfig
    ):
        """Transient channel factory failures are retried without using the old sink."""
        old_sink = AsyncMock()
        old_sink.notify = AsyncMock()
        register_channel_alert_sink(lambda config: old_sink)
        bridge = SLOAlertBridge(slack_config)
        factory_calls = 0

        def failing_factory(config):
            nonlocal factory_calls
            factory_calls += 1
            raise ValueError("invalid replacement")

        register_channel_alert_sink(failing_factory)
        violation = ActiveViolation(
            operation="debate",
            percentile="p99",
            severity="critical",
            first_seen=time.time(),
            last_seen=time.time(),
        )
        try:
            assert await bridge._send_slack_alert(violation, {}) is False
            assert await bridge._send_slack_alert(violation, {}) is False
        finally:
            register_channel_alert_sink(None)

        old_sink.notify.assert_not_awaited()
        assert factory_calls == 2

    @pytest.mark.asyncio
    async def test_no_webhook_url_returns_false(self):
        """Slack enabled but no webhook URL returns False."""
        config = SLOAlertConfig(slack_enabled=True, slack_webhook_url=None)
        b = SLOAlertBridge(config)
        violation = ActiveViolation(
            operation="debate",
            percentile="p99",
            severity="critical",
            first_seen=time.time(),
            last_seen=time.time(),
        )
        result = await b._send_slack_alert(violation, {})
        assert result is False

    @pytest.mark.asyncio
    async def test_import_error_returns_false(self, slack_bridge: SLOAlertBridge):
        """Import error for notification manager returns False."""
        violation = ActiveViolation(
            operation="debate",
            percentile="p99",
            severity="critical",
            first_seen=time.time(),
            last_seen=time.time(),
        )
        with patch.dict("sys.modules", {"aragora.control_plane.channels": None}):
            result = await slack_bridge._send_slack_alert(violation, {})
            assert result is False

    @pytest.mark.asyncio
    async def test_successful_slack_notification(
        self, slack_bridge: SLOAlertBridge, mock_notification_manager
    ):
        """Successful Slack notification returns True."""
        violation = ActiveViolation(
            operation="debate",
            percentile="p99",
            severity="critical",
            first_seen=time.time(),
            last_seen=time.time(),
        )

        mock_module = MagicMock()
        mock_module.NotificationManager = MagicMock(
            return_value=mock_notification_manager["manager"]
        )
        mock_module.NotificationEventType = mock_notification_manager["event_type"]
        mock_module.NotificationPriority = mock_notification_manager["priority"]

        with patch.dict(
            "sys.modules",
            {"aragora.control_plane.channels": mock_module},
        ):
            result = await slack_bridge._send_slack_alert(
                violation, {"latency_ms": 500, "threshold_ms": 200}
            )
            assert result is True
            mock_notification_manager["manager"].notify.assert_called_once()

    @pytest.mark.asyncio
    async def test_slack_notification_failure(
        self, slack_bridge: SLOAlertBridge, mock_notification_manager
    ):
        """Failed Slack notification returns False."""
        violation = ActiveViolation(
            operation="debate",
            percentile="p99",
            severity="critical",
            first_seen=time.time(),
            last_seen=time.time(),
        )

        mock_notification_manager["manager"].notify = AsyncMock(
            side_effect=ConnectionError("Slack API error")
        )

        mock_module = MagicMock()
        mock_module.NotificationManager = MagicMock(
            return_value=mock_notification_manager["manager"]
        )
        mock_module.NotificationEventType = mock_notification_manager["event_type"]
        mock_module.NotificationPriority = mock_notification_manager["priority"]

        with patch.dict(
            "sys.modules",
            {"aragora.control_plane.channels": mock_module},
        ):
            result = await slack_bridge._send_slack_alert(violation, {})
            assert result is False

    @pytest.mark.asyncio
    async def test_slack_message_contains_blocks(
        self, slack_bridge: SLOAlertBridge, mock_notification_manager
    ):
        """Slack message metadata contains block-kit blocks."""
        violation = ActiveViolation(
            operation="debate",
            percentile="p99",
            severity="critical",
            first_seen=time.time(),
            last_seen=time.time(),
        )

        mock_module = MagicMock()
        mock_module.NotificationManager = MagicMock(
            return_value=mock_notification_manager["manager"]
        )
        mock_module.NotificationEventType = mock_notification_manager["event_type"]
        mock_module.NotificationPriority = mock_notification_manager["priority"]

        with patch.dict(
            "sys.modules",
            {"aragora.control_plane.channels": mock_module},
        ):
            await slack_bridge._send_slack_alert(
                violation, {"latency_ms": 500, "threshold_ms": 200}
            )

            call_kwargs = mock_notification_manager["manager"].notify.call_args
            metadata = call_kwargs.kwargs.get("metadata", {})
            blocks = metadata.get("blocks", [])
            assert len(blocks) == 3  # header, section, context
            assert blocks[0]["type"] == "header"
            assert blocks[1]["type"] == "section"
            assert blocks[2]["type"] == "context"


# =============================================================================
# Test on_slo_violation
# =============================================================================


class TestOnSLOViolation:
    """Tests for on_slo_violation handler."""

    @pytest.mark.asyncio
    async def test_creates_new_violation(self, bridge: SLOAlertBridge):
        """New violation creates an active violation entry."""
        await bridge.on_slo_violation(
            operation="debate",
            percentile="p99",
            latency_ms=500,
            threshold_ms=200,
            severity="critical",
        )

        violations = bridge.get_active_violations()
        assert len(violations) == 1
        assert violations[0]["operation"] == "debate"
        assert violations[0]["percentile"] == "p99"
        assert violations[0]["severity"] == "critical"
        assert violations[0]["count"] == 1

    @pytest.mark.asyncio
    async def test_updates_existing_violation_count(self, bridge: SLOAlertBridge):
        """Repeated violation increments count."""
        for _ in range(3):
            await bridge.on_slo_violation(
                operation="debate",
                percentile="p99",
                latency_ms=500,
                threshold_ms=200,
                severity="critical",
            )

        violations = bridge.get_active_violations()
        assert len(violations) == 1
        assert violations[0]["count"] == 3

    @pytest.mark.asyncio
    async def test_severity_upgrade(self, bridge: SLOAlertBridge):
        """Severity is upgraded when a worse violation arrives."""
        await bridge.on_slo_violation(
            operation="debate",
            percentile="p99",
            latency_ms=300,
            threshold_ms=200,
            severity="minor",
        )
        await bridge.on_slo_violation(
            operation="debate",
            percentile="p99",
            latency_ms=500,
            threshold_ms=200,
            severity="critical",
        )

        violations = bridge.get_active_violations()
        assert violations[0]["severity"] == "critical"

    @pytest.mark.asyncio
    async def test_severity_not_downgraded(self, bridge: SLOAlertBridge):
        """Severity is NOT downgraded when a less severe violation arrives."""
        await bridge.on_slo_violation(
            operation="debate",
            percentile="p99",
            latency_ms=500,
            threshold_ms=200,
            severity="critical",
        )
        await bridge.on_slo_violation(
            operation="debate",
            percentile="p99",
            latency_ms=250,
            threshold_ms=200,
            severity="minor",
        )

        violations = bridge.get_active_violations()
        assert violations[0]["severity"] == "critical"

    @pytest.mark.asyncio
    async def test_context_passed_through(self, bridge: SLOAlertBridge):
        """Context is enriched with latency and threshold."""
        # Just ensure no exception with custom context
        await bridge.on_slo_violation(
            operation="debate",
            percentile="p99",
            latency_ms=500,
            threshold_ms=200,
            severity="critical",
            context={"env": "production", "region": "us-east-1"},
        )

        violations = bridge.get_active_violations()
        assert len(violations) == 1

    @pytest.mark.asyncio
    async def test_none_context_handled(self, bridge: SLOAlertBridge):
        """None context is handled gracefully (defaults to {})."""
        await bridge.on_slo_violation(
            operation="debate",
            percentile="p99",
            latency_ms=500,
            threshold_ms=200,
            severity="critical",
            context=None,
        )
        violations = bridge.get_active_violations()
        assert len(violations) == 1

    @pytest.mark.asyncio
    async def test_multiple_distinct_violations_tracked(self, bridge: SLOAlertBridge):
        """Different operation/percentile pairs are tracked separately."""
        await bridge.on_slo_violation(
            operation="debate",
            percentile="p99",
            latency_ms=500,
            threshold_ms=200,
            severity="critical",
        )
        await bridge.on_slo_violation(
            operation="search",
            percentile="p95",
            latency_ms=300,
            threshold_ms=100,
            severity="major",
        )

        violations = bridge.get_active_violations()
        assert len(violations) == 2
        ops = {v["operation"] for v in violations}
        assert ops == {"debate", "search"}


# =============================================================================
# Test Incident Deduplication
# =============================================================================


class TestIncidentDeduplication:
    """Tests for incident deduplication behavior."""

    @pytest.mark.asyncio
    async def test_same_operation_percentile_deduplicates(self, bridge: SLOAlertBridge):
        """Same operation+percentile maps to same active violation (deduplication)."""
        await bridge.on_slo_violation(
            operation="debate",
            percentile="p99",
            latency_ms=500,
            threshold_ms=200,
            severity="major",
        )
        await bridge.on_slo_violation(
            operation="debate",
            percentile="p99",
            latency_ms=600,
            threshold_ms=200,
            severity="major",
        )

        assert len(bridge._active_violations) == 1
        key = bridge._make_incident_key("debate", "p99")
        assert bridge._active_violations[key].count == 2

    @pytest.mark.asyncio
    async def test_different_operation_not_deduped(self, bridge: SLOAlertBridge):
        """Different operations are NOT deduped."""
        await bridge.on_slo_violation(
            operation="debate",
            percentile="p99",
            latency_ms=500,
            threshold_ms=200,
            severity="major",
        )
        await bridge.on_slo_violation(
            operation="search",
            percentile="p99",
            latency_ms=500,
            threshold_ms=200,
            severity="major",
        )

        assert len(bridge._active_violations) == 2

    @pytest.mark.asyncio
    async def test_different_percentile_not_deduped(self, bridge: SLOAlertBridge):
        """Different percentiles for same operation are NOT deduped."""
        await bridge.on_slo_violation(
            operation="debate",
            percentile="p99",
            latency_ms=500,
            threshold_ms=200,
            severity="major",
        )
        await bridge.on_slo_violation(
            operation="debate",
            percentile="p50",
            latency_ms=200,
            threshold_ms=100,
            severity="minor",
        )

        assert len(bridge._active_violations) == 2

    @pytest.mark.asyncio
    async def test_last_seen_updated_on_dedup(self, bridge: SLOAlertBridge):
        """last_seen is updated when a duplicate violation arrives."""
        await bridge.on_slo_violation(
            operation="debate",
            percentile="p99",
            latency_ms=500,
            threshold_ms=200,
            severity="major",
        )

        key = bridge._make_incident_key("debate", "p99")
        first_last_seen = bridge._active_violations[key].last_seen

        # Small delay to ensure time difference
        await asyncio.sleep(0.01)

        await bridge.on_slo_violation(
            operation="debate",
            percentile="p99",
            latency_ms=600,
            threshold_ms=200,
            severity="major",
        )

        assert bridge._active_violations[key].last_seen >= first_last_seen


# =============================================================================
# Test on_slo_recovery
# =============================================================================


class TestOnSLORecovery:
    """Tests for on_slo_recovery handler."""

    @pytest.mark.asyncio
    async def test_recovery_removes_active_violation(self, bridge: SLOAlertBridge):
        """Recovery removes the violation from active tracking."""
        await bridge.on_slo_violation(
            operation="debate",
            percentile="p99",
            latency_ms=500,
            threshold_ms=200,
            severity="critical",
        )
        assert len(bridge.get_active_violations()) == 1

        await bridge.on_slo_recovery(
            operation="debate",
            percentile="p99",
        )
        assert len(bridge.get_active_violations()) == 0

    @pytest.mark.asyncio
    async def test_recovery_no_active_violation_is_noop(self, bridge: SLOAlertBridge):
        """Recovery with no matching active violation does nothing."""
        await bridge.on_slo_recovery(
            operation="nonexistent",
            percentile="p99",
        )
        assert len(bridge.get_active_violations()) == 0

    @pytest.mark.asyncio
    async def test_recovery_resolves_pagerduty_incident(self, pd_bridge: SLOAlertBridge):
        """Recovery auto-resolves PagerDuty incident when configured."""
        mock_client = AsyncMock()
        mock_client.resolve_incident = AsyncMock()

        pd_bridge._pagerduty_client = mock_client

        # Create a violation with PagerDuty incident
        key = pd_bridge._make_incident_key("debate", "p99")
        pd_bridge._active_violations[key] = ActiveViolation(
            operation="debate",
            percentile="p99",
            severity="critical",
            first_seen=time.time() - 60,
            last_seen=time.time(),
            incident_key=key,
            pagerduty_incident_id="PD-INC-001",
            notified_channels={"pagerduty"},
        )

        await pd_bridge.on_slo_recovery(operation="debate", percentile="p99")

        mock_client.resolve_incident.assert_called_once()
        call_args = mock_client.resolve_incident.call_args
        assert call_args.args[0] == "PD-INC-001"
        assert "recovered" in call_args.kwargs.get("resolution", "").lower()

    @pytest.mark.asyncio
    async def test_recovery_refreshes_replaced_and_removed_sinks(self):
        """Recovery never uses alert sinks invalidated by registration changes."""
        config = SLOAlertConfig(
            pagerduty_enabled=True,
            pagerduty_api_key="key",
            pagerduty_service_id="svc",
            slack_enabled=True,
            slack_webhook_url="https://hooks.slack.com/test",
        )
        first_pagerduty = AsyncMock()
        first_pagerduty.resolve_incident = AsyncMock(return_value=True)
        second_pagerduty = AsyncMock()
        second_pagerduty.resolve_incident = AsyncMock(return_value=True)
        first_channel = AsyncMock()
        first_channel.notify = AsyncMock()
        second_channel = AsyncMock()
        second_channel.notify = AsyncMock()
        register_pagerduty_alert_sink(lambda alert_config: first_pagerduty)
        register_channel_alert_sink(lambda alert_config: first_channel)
        bridge = SLOAlertBridge(config)

        try:
            register_pagerduty_alert_sink(lambda alert_config: second_pagerduty)
            register_channel_alert_sink(lambda alert_config: second_channel)
            key = bridge._make_incident_key("debate", "p99")
            bridge._active_violations[key] = ActiveViolation(
                operation="debate",
                percentile="p99",
                severity="critical",
                first_seen=time.time() - 60,
                last_seen=time.time(),
                incident_key=key,
                pagerduty_incident_id="PD-REPLACED",
                notified_channels={"pagerduty", "slack"},
            )

            await bridge.on_slo_recovery(operation="debate", percentile="p99")

            first_pagerduty.resolve_incident.assert_not_awaited()
            first_channel.notify.assert_not_awaited()
            second_pagerduty.resolve_incident.assert_awaited_once()
            second_channel.notify.assert_awaited_once()

            register_pagerduty_alert_sink(None)
            register_channel_alert_sink(None)
            bridge._active_violations[key] = ActiveViolation(
                operation="debate",
                percentile="p99",
                severity="critical",
                first_seen=time.time() - 60,
                last_seen=time.time(),
                incident_key=key,
                pagerduty_incident_id="PD-REMOVED",
                notified_channels={"pagerduty", "slack"},
            )
            await bridge.on_slo_recovery(operation="debate", percentile="p99")
        finally:
            register_pagerduty_alert_sink(None)
            register_channel_alert_sink(None)

        second_pagerduty.resolve_incident.assert_awaited_once()
        second_channel.notify.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_recovery_skips_resolve_when_disabled(self):
        """Recovery does not resolve PagerDuty when auto_resolve is off."""
        config = SLOAlertConfig(
            pagerduty_enabled=True,
            pagerduty_api_key="key",
            pagerduty_service_id="svc",
            auto_resolve_on_recovery=False,
        )
        b = SLOAlertBridge(config)
        mock_client = AsyncMock()
        b._pagerduty_client = mock_client

        key = b._make_incident_key("debate", "p99")
        b._active_violations[key] = ActiveViolation(
            operation="debate",
            percentile="p99",
            severity="critical",
            first_seen=time.time() - 60,
            last_seen=time.time(),
            incident_key=key,
            pagerduty_incident_id="PD-INC-001",
            notified_channels={"pagerduty"},
        )

        await b.on_slo_recovery(operation="debate", percentile="p99")

        mock_client.resolve_incident.assert_not_called()

    @pytest.mark.asyncio
    async def test_recovery_sends_slack_notification(
        self, slack_bridge: SLOAlertBridge, mock_notification_manager
    ):
        """Recovery sends Slack recovery notification when channel was notified."""
        slack_bridge._notification_manager = mock_notification_manager["manager"]

        key = slack_bridge._make_incident_key("debate", "p99")
        slack_bridge._active_violations[key] = ActiveViolation(
            operation="debate",
            percentile="p99",
            severity="critical",
            first_seen=time.time() - 60,
            last_seen=time.time(),
            incident_key=key,
            notified_channels={"slack"},
        )

        mock_module = MagicMock()
        mock_module.NotificationEventType = mock_notification_manager["event_type"]
        mock_module.NotificationPriority = mock_notification_manager["priority"]

        with patch.dict(
            "sys.modules",
            {"aragora.control_plane.channels": mock_module},
        ):
            await slack_bridge.on_slo_recovery(operation="debate", percentile="p99")

        mock_notification_manager["manager"].notify.assert_called_once()
        call_kwargs = mock_notification_manager["manager"].notify.call_args.kwargs
        assert "Recovered" in call_kwargs.get("title", "")

    @pytest.mark.asyncio
    async def test_recovery_skips_slack_if_not_notified(self, slack_bridge: SLOAlertBridge):
        """Recovery does not send Slack if channel was not originally notified."""
        key = slack_bridge._make_incident_key("debate", "p99")
        slack_bridge._active_violations[key] = ActiveViolation(
            operation="debate",
            percentile="p99",
            severity="critical",
            first_seen=time.time() - 60,
            last_seen=time.time(),
            incident_key=key,
            notified_channels=set(),  # Slack was NOT notified
        )

        # If _notification_manager were called, it would raise
        slack_bridge._notification_manager = None

        await slack_bridge.on_slo_recovery(operation="debate", percentile="p99")
        assert len(slack_bridge.get_active_violations()) == 0

    @pytest.mark.asyncio
    async def test_recovery_pagerduty_resolve_failure_logged(self, pd_bridge: SLOAlertBridge):
        """PagerDuty resolve failure is handled gracefully."""
        mock_client = AsyncMock()
        mock_client.resolve_incident = AsyncMock(side_effect=ConnectionError("PD API down"))
        pd_bridge._pagerduty_client = mock_client

        key = pd_bridge._make_incident_key("debate", "p99")
        pd_bridge._active_violations[key] = ActiveViolation(
            operation="debate",
            percentile="p99",
            severity="critical",
            first_seen=time.time() - 60,
            last_seen=time.time(),
            incident_key=key,
            pagerduty_incident_id="PD-INC-001",
            notified_channels={"pagerduty"},
        )

        # Should not raise
        await pd_bridge.on_slo_recovery(operation="debate", percentile="p99")
        # Violation still cleaned up despite resolve failure
        assert len(pd_bridge.get_active_violations()) == 0

    @pytest.mark.asyncio
    async def test_recovery_slack_notification_failure_logged(
        self, slack_bridge: SLOAlertBridge, mock_notification_manager
    ):
        """Slack recovery notification failure is handled gracefully."""
        mock_notification_manager["manager"].notify = AsyncMock(
            side_effect=RuntimeError("Slack API error")
        )
        slack_bridge._notification_manager = mock_notification_manager["manager"]

        key = slack_bridge._make_incident_key("debate", "p99")
        slack_bridge._active_violations[key] = ActiveViolation(
            operation="debate",
            percentile="p99",
            severity="critical",
            first_seen=time.time() - 60,
            last_seen=time.time(),
            incident_key=key,
            notified_channels={"slack"},
        )

        mock_module = MagicMock()
        mock_module.NotificationEventType = mock_notification_manager["event_type"]
        mock_module.NotificationPriority = mock_notification_manager["priority"]

        with patch.dict(
            "sys.modules",
            {"aragora.control_plane.channels": mock_module},
        ):
            # Should not raise
            await slack_bridge.on_slo_recovery(operation="debate", percentile="p99")

        # Violation still cleaned up
        assert len(slack_bridge.get_active_violations()) == 0


# =============================================================================
# Test get_active_violations
# =============================================================================


class TestGetActiveViolations:
    """Tests for get_active_violations."""

    def test_empty_by_default(self, bridge: SLOAlertBridge):
        """No violations by default."""
        assert bridge.get_active_violations() == []

    @pytest.mark.asyncio
    async def test_returns_correct_structure(self, bridge: SLOAlertBridge):
        """Returns correctly structured violation dictionaries."""
        await bridge.on_slo_violation(
            operation="debate",
            percentile="p99",
            latency_ms=500,
            threshold_ms=200,
            severity="critical",
        )

        violations = bridge.get_active_violations()
        assert len(violations) == 1
        v = violations[0]

        # Check all expected keys
        expected_keys = {
            "operation",
            "percentile",
            "severity",
            "first_seen",
            "last_seen",
            "count",
            "incident_key",
            "pagerduty_incident_id",
            "notified_channels",
        }
        assert set(v.keys()) == expected_keys

    @pytest.mark.asyncio
    async def test_timestamps_are_iso_format(self, bridge: SLOAlertBridge):
        """Timestamps are returned in ISO format."""
        await bridge.on_slo_violation(
            operation="debate",
            percentile="p99",
            latency_ms=500,
            threshold_ms=200,
            severity="critical",
        )

        violations = bridge.get_active_violations()
        # Verify ISO format by parsing
        datetime.fromisoformat(violations[0]["first_seen"])
        datetime.fromisoformat(violations[0]["last_seen"])

    @pytest.mark.asyncio
    async def test_notified_channels_as_list(self, bridge: SLOAlertBridge):
        """notified_channels is returned as a list (not set)."""
        await bridge.on_slo_violation(
            operation="debate",
            percentile="p99",
            latency_ms=500,
            threshold_ms=200,
            severity="critical",
        )

        violations = bridge.get_active_violations()
        assert isinstance(violations[0]["notified_channels"], list)


# =============================================================================
# Test cleanup_stale_violations
# =============================================================================


class TestCleanupStaleViolations:
    """Tests for cleanup_stale_violations."""

    def test_no_violations_returns_zero(self, bridge: SLOAlertBridge):
        """No violations returns 0 cleaned."""
        assert bridge.cleanup_stale_violations() == 0

    def test_fresh_violations_not_cleaned(self, bridge: SLOAlertBridge):
        """Recent violations are not cleaned up."""
        key = bridge._make_incident_key("debate", "p99")
        bridge._active_violations[key] = ActiveViolation(
            operation="debate",
            percentile="p99",
            severity="critical",
            first_seen=time.time(),
            last_seen=time.time(),
        )

        cleaned = bridge.cleanup_stale_violations(max_age_seconds=3600)
        assert cleaned == 0
        assert len(bridge._active_violations) == 1

    def test_stale_violations_cleaned(self, bridge: SLOAlertBridge):
        """Old violations are cleaned up."""
        key = bridge._make_incident_key("debate", "p99")
        bridge._active_violations[key] = ActiveViolation(
            operation="debate",
            percentile="p99",
            severity="critical",
            first_seen=time.time() - 7200,
            last_seen=time.time() - 7200,  # 2 hours old
        )

        cleaned = bridge.cleanup_stale_violations(max_age_seconds=3600)
        assert cleaned == 1
        assert len(bridge._active_violations) == 0

    def test_mixed_fresh_and_stale(self, bridge: SLOAlertBridge):
        """Only stale violations are cleaned, fresh ones remain."""
        now = time.time()

        key_fresh = bridge._make_incident_key("debate", "p99")
        bridge._active_violations[key_fresh] = ActiveViolation(
            operation="debate",
            percentile="p99",
            severity="critical",
            first_seen=now,
            last_seen=now,
        )

        key_stale = bridge._make_incident_key("search", "p95")
        bridge._active_violations[key_stale] = ActiveViolation(
            operation="search",
            percentile="p95",
            severity="major",
            first_seen=now - 7200,
            last_seen=now - 7200,
        )

        cleaned = bridge.cleanup_stale_violations(max_age_seconds=3600)
        assert cleaned == 1
        assert len(bridge._active_violations) == 1
        assert key_fresh in bridge._active_violations

    def test_custom_max_age(self, bridge: SLOAlertBridge):
        """Custom max_age_seconds is respected."""
        key = bridge._make_incident_key("debate", "p99")
        bridge._active_violations[key] = ActiveViolation(
            operation="debate",
            percentile="p99",
            severity="critical",
            first_seen=time.time() - 120,
            last_seen=time.time() - 120,
        )

        # 60 seconds max age should clean 120-second-old violation
        cleaned = bridge.cleanup_stale_violations(max_age_seconds=60)
        assert cleaned == 1

        # But 300 seconds max age should keep it
        bridge._active_violations[key] = ActiveViolation(
            operation="debate",
            percentile="p99",
            severity="critical",
            first_seen=time.time() - 120,
            last_seen=time.time() - 120,
        )
        cleaned = bridge.cleanup_stale_violations(max_age_seconds=300)
        assert cleaned == 0

    def test_stale_check_uses_last_seen_not_first_seen(self, bridge: SLOAlertBridge):
        """Staleness is based on last_seen, not first_seen."""
        key = bridge._make_incident_key("debate", "p99")
        bridge._active_violations[key] = ActiveViolation(
            operation="debate",
            percentile="p99",
            severity="critical",
            first_seen=time.time() - 7200,  # first_seen 2 hours ago
            last_seen=time.time(),  # but last_seen is now
        )

        cleaned = bridge.cleanup_stale_violations(max_age_seconds=3600)
        assert cleaned == 0  # Not stale because last_seen is recent


# =============================================================================
# Test Full Alert Routing Flow
# =============================================================================


class TestFullAlertRouting:
    """Integration-style tests for the complete alert routing flow."""

    @pytest.mark.asyncio
    async def test_pagerduty_routing_for_critical(
        self, pd_bridge: SLOAlertBridge, mock_pagerduty_connector
    ):
        """Critical violation routes to PagerDuty and sets incident ID."""
        mock_module = MagicMock()
        mock_module.PagerDutyConnector = mock_pagerduty_connector["connector_cls"]
        mock_module.PagerDutyCredentials = mock_pagerduty_connector["credentials_cls"]
        mock_module.IncidentCreateRequest = mock_pagerduty_connector["request_cls"]
        mock_module.IncidentUrgency = mock_pagerduty_connector["urgency_cls"]

        mock_pagerduty_connector["connector_cls"].return_value = mock_pagerduty_connector[
            "connector"
        ]

        with patch.dict(
            "sys.modules",
            {"aragora.connectors.devops.pagerduty": mock_module},
        ):
            await pd_bridge.on_slo_violation(
                operation="debate",
                percentile="p99",
                latency_ms=500,
                threshold_ms=200,
                severity="critical",
            )

        violations = pd_bridge.get_active_violations()
        assert len(violations) == 1
        assert violations[0]["pagerduty_incident_id"] == "PD-INC-001"
        assert "pagerduty" in violations[0]["notified_channels"]

    @pytest.mark.asyncio
    async def test_minor_violation_skips_pagerduty(self, pd_bridge: SLOAlertBridge):
        """Minor violation does NOT route to PagerDuty (min_severity=MAJOR)."""
        await pd_bridge.on_slo_violation(
            operation="debate",
            percentile="p99",
            latency_ms=250,
            threshold_ms=200,
            severity="minor",
        )

        violations = pd_bridge.get_active_violations()
        assert len(violations) == 1
        assert violations[0]["pagerduty_incident_id"] is None
        assert "pagerduty" not in violations[0]["notified_channels"]

    @pytest.mark.asyncio
    async def test_cooldown_prevents_duplicate_notifications(
        self, slack_bridge: SLOAlertBridge, mock_notification_manager
    ):
        """Cooldown prevents duplicate notifications for the same violation."""
        mock_module = MagicMock()
        mock_module.NotificationManager = MagicMock(
            return_value=mock_notification_manager["manager"]
        )
        mock_module.NotificationEventType = mock_notification_manager["event_type"]
        mock_module.NotificationPriority = mock_notification_manager["priority"]

        with patch.dict(
            "sys.modules",
            {"aragora.control_plane.channels": mock_module},
        ):
            # First violation triggers notification
            await slack_bridge.on_slo_violation(
                operation="debate",
                percentile="p99",
                latency_ms=500,
                threshold_ms=200,
                severity="critical",
            )
            assert mock_notification_manager["manager"].notify.call_count == 1

            # Second within cooldown does NOT trigger
            await slack_bridge.on_slo_violation(
                operation="debate",
                percentile="p99",
                latency_ms=600,
                threshold_ms=200,
                severity="critical",
            )
            assert mock_notification_manager["manager"].notify.call_count == 1

    @pytest.mark.asyncio
    async def test_full_lifecycle_violation_then_recovery(
        self, pd_bridge: SLOAlertBridge, mock_pagerduty_connector
    ):
        """Full lifecycle: violation -> PagerDuty incident -> recovery -> resolve."""
        mock_module = MagicMock()
        mock_module.PagerDutyConnector = mock_pagerduty_connector["connector_cls"]
        mock_module.PagerDutyCredentials = mock_pagerduty_connector["credentials_cls"]
        mock_module.IncidentCreateRequest = mock_pagerduty_connector["request_cls"]
        mock_module.IncidentUrgency = mock_pagerduty_connector["urgency_cls"]

        mock_pagerduty_connector["connector_cls"].return_value = mock_pagerduty_connector[
            "connector"
        ]

        with patch.dict(
            "sys.modules",
            {"aragora.connectors.devops.pagerduty": mock_module},
        ):
            # Trigger violation
            await pd_bridge.on_slo_violation(
                operation="debate",
                percentile="p99",
                latency_ms=500,
                threshold_ms=200,
                severity="critical",
            )
            assert len(pd_bridge.get_active_violations()) == 1

        # Recovery resolves
        await pd_bridge.on_slo_recovery(operation="debate", percentile="p99")
        assert len(pd_bridge.get_active_violations()) == 0
        mock_pagerduty_connector["connector"].resolve_incident.assert_called_once()


# =============================================================================
# Test Concurrency Safety
# =============================================================================


class TestConcurrencySafety:
    """Tests for concurrent access protection via asyncio Lock."""

    @pytest.mark.asyncio
    async def test_concurrent_violations_do_not_corrupt_state(self, bridge: SLOAlertBridge):
        """Concurrent violations for different operations are all tracked."""
        tasks = []
        for i in range(20):
            tasks.append(
                bridge.on_slo_violation(
                    operation=f"op-{i}",
                    percentile="p99",
                    latency_ms=500,
                    threshold_ms=200,
                    severity="critical",
                )
            )
        await asyncio.gather(*tasks)

        violations = bridge.get_active_violations()
        assert len(violations) == 20

    @pytest.mark.asyncio
    async def test_concurrent_violation_and_recovery(self, bridge: SLOAlertBridge):
        """Concurrent violation + recovery do not corrupt state."""
        # First create a violation
        await bridge.on_slo_violation(
            operation="debate",
            percentile="p99",
            latency_ms=500,
            threshold_ms=200,
            severity="critical",
        )

        # Then concurrently add more and recover one
        tasks = [
            bridge.on_slo_violation(
                operation="search",
                percentile="p95",
                latency_ms=300,
                threshold_ms=100,
                severity="major",
            ),
            bridge.on_slo_recovery(operation="debate", percentile="p99"),
        ]
        await asyncio.gather(*tasks)

        violations = bridge.get_active_violations()
        ops = {v["operation"] for v in violations}
        assert "debate" not in ops
        assert "search" in ops


# =============================================================================
# Test init_slo_alerting and shutdown_slo_alerting
# =============================================================================


class TestInitSLOAlerting:
    """Tests for init_slo_alerting factory function."""

    def _reset_global_bridge(self):
        """Reset the global bridge state."""
        import aragora.observability.slo_alert_bridge as module

        module._bridge = None

    def test_returns_bridge_instance(self):
        """init_slo_alerting returns an SLOAlertBridge instance."""
        self._reset_global_bridge()
        with patch.dict("sys.modules", {"aragora.observability.metrics.slo": None}):
            bridge = init_slo_alerting()
            assert isinstance(bridge, SLOAlertBridge)
            self._reset_global_bridge()

    def test_pagerduty_enabled_when_both_keys_provided(self):
        """PagerDuty is enabled when both API key and service ID are provided."""
        self._reset_global_bridge()
        with patch.dict("sys.modules", {"aragora.observability.metrics.slo": None}):
            bridge = init_slo_alerting(
                pagerduty_api_key="key",
                pagerduty_service_id="svc",
            )
            assert bridge.config.pagerduty_enabled is True
            self._reset_global_bridge()

    def test_late_registration_retrofits_global_bridge(self):
        """Startup composition can register adapters after bridge initialization."""
        register_pagerduty_alert_sink(None)
        bridge = init_slo_alerting(
            pagerduty_api_key="key",
            pagerduty_service_id="svc",
        )
        sink = AsyncMock()

        try:
            assert bridge._pagerduty_client is None
            register_pagerduty_alert_sink(lambda config: sink)
            assert bridge._pagerduty_client is sink
        finally:
            shutdown_slo_alerting()
            register_pagerduty_alert_sink(None)

    def test_pagerduty_disabled_when_key_missing(self):
        """PagerDuty is disabled when API key is missing."""
        self._reset_global_bridge()
        with patch.dict("sys.modules", {"aragora.observability.metrics.slo": None}):
            bridge = init_slo_alerting(
                pagerduty_service_id="svc",
            )
            assert bridge.config.pagerduty_enabled is False
            self._reset_global_bridge()

    def test_pagerduty_disabled_when_service_id_missing(self):
        """PagerDuty is disabled when service ID is missing."""
        self._reset_global_bridge()
        with patch.dict("sys.modules", {"aragora.observability.metrics.slo": None}):
            bridge = init_slo_alerting(
                pagerduty_api_key="key",
            )
            assert bridge.config.pagerduty_enabled is False
            self._reset_global_bridge()

    def test_slack_enabled_when_webhook_provided(self):
        """Slack is enabled when webhook URL is provided."""
        self._reset_global_bridge()
        with patch.dict("sys.modules", {"aragora.observability.metrics.slo": None}):
            bridge = init_slo_alerting(
                slack_webhook_url="https://hooks.slack.com/services/T/B/x",
            )
            assert bridge.config.slack_enabled is True
            self._reset_global_bridge()

    def test_slack_disabled_when_no_webhook(self):
        """Slack is disabled when no webhook URL."""
        self._reset_global_bridge()
        with patch.dict("sys.modules", {"aragora.observability.metrics.slo": None}):
            bridge = init_slo_alerting()
            assert bridge.config.slack_enabled is False
            self._reset_global_bridge()

    def test_teams_enabled_when_webhook_provided(self):
        """Teams is enabled when webhook URL is provided."""
        self._reset_global_bridge()
        with patch.dict("sys.modules", {"aragora.observability.metrics.slo": None}):
            bridge = init_slo_alerting(
                teams_webhook_url="https://outlook.office.com/webhook/xxx",
            )
            assert bridge.config.teams_enabled is True
            self._reset_global_bridge()

    def test_custom_cooldown_passed(self):
        """Custom cooldown is passed through to config."""
        self._reset_global_bridge()
        with patch.dict("sys.modules", {"aragora.observability.metrics.slo": None}):
            bridge = init_slo_alerting(cooldown_seconds=120.0)
            assert bridge.config.cooldown_seconds == 120.0
            self._reset_global_bridge()

    def test_auto_resolve_passed(self):
        """auto_resolve_on_recovery is passed through to config."""
        self._reset_global_bridge()
        with patch.dict("sys.modules", {"aragora.observability.metrics.slo": None}):
            bridge = init_slo_alerting(auto_resolve_on_recovery=False)
            assert bridge.config.auto_resolve_on_recovery is False
            self._reset_global_bridge()

    def test_sets_global_bridge(self):
        """init_slo_alerting sets the global _bridge variable."""
        self._reset_global_bridge()
        with patch.dict("sys.modules", {"aragora.observability.metrics.slo": None}):
            bridge = init_slo_alerting()
            assert get_slo_alert_bridge() is bridge
            self._reset_global_bridge()

    def test_registers_callbacks_when_slo_module_available(self):
        """Registers violation and recovery callbacks when SLO module is available."""
        self._reset_global_bridge()

        mock_register_violation = MagicMock()
        mock_register_recovery = MagicMock()

        mock_slo_module = MagicMock()
        mock_slo_module.register_violation_callback = mock_register_violation
        mock_slo_module.register_recovery_callback = mock_register_recovery

        with patch.dict(
            "sys.modules",
            {"aragora.observability.metrics.slo": mock_slo_module},
        ):
            init_slo_alerting()
            mock_register_violation.assert_called_once()
            mock_register_recovery.assert_called_once()
            self._reset_global_bridge()

    def test_handles_import_error_gracefully(self):
        """Handles missing SLO module gracefully."""
        self._reset_global_bridge()
        with patch.dict("sys.modules", {"aragora.observability.metrics.slo": None}):
            bridge = init_slo_alerting()
            assert bridge is not None
            self._reset_global_bridge()


class TestGetSLOAlertBridge:
    """Tests for get_slo_alert_bridge."""

    def test_returns_none_when_not_initialized(self):
        """Returns None when no bridge has been initialized."""
        import aragora.observability.slo_alert_bridge as module

        original = module._bridge
        module._bridge = None
        try:
            assert get_slo_alert_bridge() is None
        finally:
            module._bridge = original

    def test_returns_bridge_when_initialized(self):
        """Returns the bridge after initialization."""
        import aragora.observability.slo_alert_bridge as module

        original = module._bridge
        config = SLOAlertConfig()
        bridge = SLOAlertBridge(config)
        module._bridge = bridge
        try:
            assert get_slo_alert_bridge() is bridge
        finally:
            module._bridge = original


class TestShutdownSLOAlerting:
    """Tests for shutdown_slo_alerting."""

    def test_shutdown_clears_global_bridge(self):
        """Shutdown sets global bridge to None."""
        import aragora.observability.slo_alert_bridge as module

        original = module._bridge

        module._bridge = SLOAlertBridge(SLOAlertConfig())
        with patch.dict("sys.modules", {"aragora.observability.metrics.slo": None}):
            shutdown_slo_alerting()
            assert module._bridge is None

        module._bridge = original

    def test_shutdown_when_not_initialized_is_noop(self):
        """Shutdown with no bridge is a no-op."""
        import aragora.observability.slo_alert_bridge as module

        original = module._bridge

        module._bridge = None
        shutdown_slo_alerting()
        assert module._bridge is None

        module._bridge = original

    def test_shutdown_unregisters_only_bridge_callbacks(self):
        """Shutdown unregisters the callbacks owned by the bridge."""
        import aragora.observability.slo_alert_bridge as module

        original = module._bridge
        original_violation = module._registered_violation_callback
        original_recovery = module._registered_recovery_callback

        module._bridge = SLOAlertBridge(SLOAlertConfig())
        violation_callback = MagicMock()
        recovery_callback = MagicMock()
        module._registered_violation_callback = violation_callback
        module._registered_recovery_callback = recovery_callback

        mock_slo_module = MagicMock()
        mock_slo_module.unregister_violation_callback = MagicMock()
        mock_slo_module.unregister_recovery_callback = MagicMock()

        with patch.dict(
            "sys.modules",
            {"aragora.observability.metrics.slo": mock_slo_module},
        ):
            shutdown_slo_alerting()
            mock_slo_module.unregister_violation_callback.assert_called_once_with(
                violation_callback
            )
            mock_slo_module.unregister_recovery_callback.assert_called_once_with(recovery_callback)

        module._bridge = original
        module._registered_violation_callback = original_violation
        module._registered_recovery_callback = original_recovery

    def test_shutdown_handles_import_error(self):
        """Shutdown handles missing SLO module gracefully."""
        import aragora.observability.slo_alert_bridge as module

        original = module._bridge

        module._bridge = SLOAlertBridge(SLOAlertConfig())
        with patch.dict("sys.modules", {"aragora.observability.metrics.slo": None}):
            shutdown_slo_alerting()
            assert module._bridge is None

        module._bridge = original


# =============================================================================
# Test Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_very_long_operation_name(self, bridge: SLOAlertBridge):
        """Very long operation names are handled gracefully."""
        long_op = "x" * 10000
        await bridge.on_slo_violation(
            operation=long_op,
            percentile="p99",
            latency_ms=500,
            threshold_ms=200,
            severity="critical",
        )
        violations = bridge.get_active_violations()
        assert len(violations) == 1
        assert violations[0]["operation"] == long_op

    @pytest.mark.asyncio
    async def test_special_characters_in_operation(self, bridge: SLOAlertBridge):
        """Operations with special characters are handled."""
        await bridge.on_slo_violation(
            operation="api/v2/debate?format=json&limit=10",
            percentile="p99.9",
            latency_ms=500,
            threshold_ms=200,
            severity="critical",
        )
        violations = bridge.get_active_violations()
        assert len(violations) == 1

    @pytest.mark.asyncio
    async def test_zero_latency_and_threshold(self, bridge: SLOAlertBridge):
        """Zero latency and threshold values are handled."""
        await bridge.on_slo_violation(
            operation="debate",
            percentile="p99",
            latency_ms=0,
            threshold_ms=0,
            severity="minor",
        )
        violations = bridge.get_active_violations()
        assert len(violations) == 1

    @pytest.mark.asyncio
    async def test_negative_latency(self, bridge: SLOAlertBridge):
        """Negative latency values don't crash."""
        await bridge.on_slo_violation(
            operation="debate",
            percentile="p99",
            latency_ms=-1,
            threshold_ms=200,
            severity="minor",
        )
        violations = bridge.get_active_violations()
        assert len(violations) == 1

    @pytest.mark.asyncio
    async def test_empty_operation_and_percentile(self, bridge: SLOAlertBridge):
        """Empty operation and percentile strings are handled."""
        await bridge.on_slo_violation(
            operation="",
            percentile="",
            latency_ms=500,
            threshold_ms=200,
            severity="critical",
        )
        violations = bridge.get_active_violations()
        assert len(violations) == 1

    def test_violation_timestamps_are_utc(self, bridge: SLOAlertBridge):
        """Violation timestamps in get_active_violations are UTC."""
        key = bridge._make_incident_key("debate", "p99")
        bridge._active_violations[key] = ActiveViolation(
            operation="debate",
            percentile="p99",
            severity="critical",
            first_seen=0.0,  # Unix epoch
            last_seen=0.0,
        )

        violations = bridge.get_active_violations()
        first_seen = datetime.fromisoformat(violations[0]["first_seen"])
        assert first_seen.tzinfo is not None
        assert first_seen.year == 1970

    @pytest.mark.asyncio
    async def test_many_violations_tracked(self, bridge: SLOAlertBridge):
        """Large number of distinct violations tracked correctly."""
        for i in range(100):
            await bridge.on_slo_violation(
                operation=f"op-{i}",
                percentile="p99",
                latency_ms=500 + i,
                threshold_ms=200,
                severity="minor",
            )

        violations = bridge.get_active_violations()
        assert len(violations) == 100

    def test_cleanup_many_stale_violations(self, bridge: SLOAlertBridge):
        """Cleanup handles large number of stale violations."""
        now = time.time()
        for i in range(200):
            key = bridge._make_incident_key(f"op-{i}", "p99")
            bridge._active_violations[key] = ActiveViolation(
                operation=f"op-{i}",
                percentile="p99",
                severity="minor",
                first_seen=now - 7200,
                last_seen=now - 7200,
            )

        cleaned = bridge.cleanup_stale_violations(max_age_seconds=3600)
        assert cleaned == 200
        assert len(bridge._active_violations) == 0

    @pytest.mark.asyncio
    async def test_violation_with_large_count(self, bridge: SLOAlertBridge):
        """Violation with many occurrences maintains correct count."""
        for _ in range(50):
            await bridge.on_slo_violation(
                operation="debate",
                percentile="p99",
                latency_ms=500,
                threshold_ms=200,
                severity="critical",
            )

        violations = bridge.get_active_violations()
        assert violations[0]["count"] == 50

    @pytest.mark.asyncio
    async def test_severity_escalation_path(self, bridge: SLOAlertBridge):
        """Full severity escalation path works correctly."""
        severities = ["minor", "moderate", "major", "critical"]
        for sev in severities:
            await bridge.on_slo_violation(
                operation="debate",
                percentile="p99",
                latency_ms=500,
                threshold_ms=200,
                severity=sev,
            )

        violations = bridge.get_active_violations()
        assert violations[0]["severity"] == "critical"
        assert violations[0]["count"] == 4

    @pytest.mark.asyncio
    async def test_hash_collision_resilience(self, bridge: SLOAlertBridge):
        """Different operation/percentile pairs produce different incident keys.

        While SHA256 collisions are theoretically possible, in practice
        different inputs should yield different 16-char hex prefixes.
        This test verifies many pairs are distinct.
        """
        keys = set()
        for i in range(100):
            key = bridge._make_incident_key(f"op-{i}", f"p{i}")
            keys.add(key)

        # All 100 different inputs should produce unique keys
        assert len(keys) == 100
