"""Tests for DebateChannelSLAMonitor."""

import pytest
from datetime import datetime, timezone, timedelta

from aragora.services.debate_sla_monitor import (
    DebateChannelSLAMonitor,
    DebateSLAConfig,
    DebateSLAViolation,
)


@pytest.fixture
def monitor():
    """Create a fresh debate SLA monitor with default config."""
    return DebateChannelSLAMonitor()


@pytest.fixture
def strict_monitor():
    """Create a debate SLA monitor with tight SLA windows."""
    return DebateChannelSLAMonitor(
        config=DebateSLAConfig(
            response_sla_minutes=5,
            resolution_sla_minutes=30,
        )
    )


class TestDebateSLAConfig:
    """Tests for DebateSLAConfig defaults and fields."""

    def test_defaults(self):
        cfg = DebateSLAConfig()
        assert cfg.response_sla_minutes == 15
        assert cfg.resolution_sla_minutes == 60
        assert cfg.escalation_rules == []

    def test_custom_values(self):
        cfg = DebateSLAConfig(
            response_sla_minutes=10,
            resolution_sla_minutes=120,
            escalation_rules=[{"level": 1, "action": "notify"}],
        )
        assert cfg.response_sla_minutes == 10
        assert cfg.resolution_sla_minutes == 120
        assert len(cfg.escalation_rules) == 1


class TestDebateSLAViolation:
    """Tests for DebateSLAViolation data class."""

    def test_to_dict(self):
        v = DebateSLAViolation(
            debate_id="d-1",
            violation_type="RESPONSE",
            sla_minutes=15,
            actual_minutes=20.5,
            breached_at="2026-03-05T12:00:00+00:00",
        )
        d = v.to_dict()
        assert d["debate_id"] == "d-1"
        assert d["violation_type"] == "RESPONSE"
        assert d["sla_minutes"] == 15
        assert d["actual_minutes"] == 20.5
        assert "2026-03-05" in d["breached_at"]


class TestCheckDebateSLA:
    """Tests for check_debate_sla method."""

    def test_no_violation_when_within_response_sla(self, monitor):
        created = datetime.now(timezone.utc) - timedelta(minutes=10)
        result = monitor.check_debate_sla("d-1", created)
        assert result is None

    def test_response_violation_when_exceeded(self, monitor):
        created = datetime.now(timezone.utc) - timedelta(minutes=20)
        result = monitor.check_debate_sla("d-1", created)
        assert result is not None
        assert result.violation_type == "RESPONSE"
        assert result.sla_minutes == 15
        assert result.actual_minutes >= 20

    def test_resolution_violation_when_completed_late(self, monitor):
        created = datetime.now(timezone.utc) - timedelta(minutes=120)
        completed = datetime.now(timezone.utc)
        result = monitor.check_debate_sla("d-1", created, completed_at=completed)
        assert result is not None
        assert result.violation_type == "RESOLUTION"
        assert result.sla_minutes == 60
        assert result.actual_minutes >= 120

    def test_no_resolution_violation_when_on_time(self, monitor):
        created = datetime.now(timezone.utc) - timedelta(minutes=30)
        completed = datetime.now(timezone.utc)
        result = monitor.check_debate_sla("d-1", created, completed_at=completed)
        assert result is None

    def test_handles_naive_datetimes(self, monitor):
        # Naive datetimes should be treated as UTC
        created = datetime.utcnow() - timedelta(minutes=20)  # noqa: DTZ003
        result = monitor.check_debate_sla("d-1", created)
        assert result is not None
        assert result.violation_type == "RESPONSE"

    def test_uses_custom_config(self, strict_monitor):
        created = datetime.now(timezone.utc) - timedelta(minutes=6)
        result = strict_monitor.check_debate_sla("d-1", created)
        assert result is not None
        assert result.sla_minutes == 5

    def test_breached_at_is_iso_string(self, monitor):
        created = datetime.now(timezone.utc) - timedelta(minutes=20)
        result = monitor.check_debate_sla("d-1", created)
        assert result is not None
        # Should be parseable back
        parsed = datetime.fromisoformat(result.breached_at)
        assert parsed.tzinfo is not None


class TestGetAtRiskDebates:
    """Tests for get_at_risk_debates method."""

    def test_identifies_at_risk_debate(self, monitor):
        # Created 12 minutes ago with 15-minute SLA -> 3 minutes remaining
        debates = [
            {
                "id": "d-1",
                "created_at": (datetime.now(timezone.utc) - timedelta(minutes=12)).isoformat(),
            },
        ]
        result = monitor.get_at_risk_debates(debates, threshold_minutes=5)
        assert len(result) == 1
        assert result[0]["id"] == "d-1"
        assert "minutes_remaining" in result[0]

    def test_excludes_safe_debates(self, monitor):
        # Created 5 minutes ago with 15-minute SLA -> 10 minutes remaining
        debates = [
            {
                "id": "d-1",
                "created_at": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
            },
        ]
        result = monitor.get_at_risk_debates(debates, threshold_minutes=5)
        assert len(result) == 0

    def test_excludes_completed_debates(self, monitor):
        debates = [
            {
                "id": "d-1",
                "created_at": (datetime.now(timezone.utc) - timedelta(minutes=14)).isoformat(),
                "completed_at": datetime.now(timezone.utc).isoformat(),
            },
        ]
        result = monitor.get_at_risk_debates(debates, threshold_minutes=5)
        assert len(result) == 0

    def test_excludes_already_breached(self, monitor):
        # Created 20 minutes ago -> already breached, remaining < 0
        debates = [
            {
                "id": "d-1",
                "created_at": (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat(),
            },
        ]
        result = monitor.get_at_risk_debates(debates, threshold_minutes=5)
        assert len(result) == 0

    def test_sorts_by_urgency(self, monitor):
        now = datetime.now(timezone.utc)
        debates = [
            {
                "id": "d-less-urgent",
                "created_at": (now - timedelta(minutes=11)).isoformat(),
            },
            {
                "id": "d-more-urgent",
                "created_at": (now - timedelta(minutes=13)).isoformat(),
            },
        ]
        result = monitor.get_at_risk_debates(debates, threshold_minutes=5)
        assert len(result) == 2
        assert result[0]["id"] == "d-more-urgent"

    def test_handles_missing_created_at(self, monitor):
        debates = [{"id": "d-1"}]
        result = monitor.get_at_risk_debates(debates, threshold_minutes=5)
        assert len(result) == 0

    def test_handles_datetime_objects(self, monitor):
        debates = [
            {
                "id": "d-1",
                "created_at": datetime.now(timezone.utc) - timedelta(minutes=13),
            },
        ]
        result = monitor.get_at_risk_debates(debates, threshold_minutes=5)
        assert len(result) == 1


class TestViolationHandler:
    """Tests for violation handler registration and dispatch."""

    def test_register_and_invoke_handler(self, monitor):
        violations_seen: list[DebateSLAViolation] = []
        monitor.register_violation_handler(violations_seen.append)

        created = datetime.now(timezone.utc) - timedelta(minutes=20)
        result = monitor.check_debate_sla("d-1", created)
        assert result is not None
        assert len(violations_seen) == 1
        assert violations_seen[0].debate_id == "d-1"

    def test_multiple_handlers_invoked(self, monitor):
        calls_a: list[str] = []
        calls_b: list[str] = []
        monitor.register_violation_handler(lambda v: calls_a.append(v.debate_id))
        monitor.register_violation_handler(lambda v: calls_b.append(v.debate_id))

        created = datetime.now(timezone.utc) - timedelta(minutes=20)
        monitor.check_debate_sla("d-1", created)
        assert calls_a == ["d-1"]
        assert calls_b == ["d-1"]

    def test_handler_error_does_not_propagate(self, monitor):
        def bad_handler(v: DebateSLAViolation) -> None:
            raise RuntimeError("boom")

        monitor.register_violation_handler(bad_handler)
        created = datetime.now(timezone.utc) - timedelta(minutes=20)
        # Should not raise
        result = monitor.check_debate_sla("d-1", created)
        assert result is not None

    def test_no_handler_called_when_no_violation(self, monitor):
        called = []
        monitor.register_violation_handler(lambda v: called.append(v))
        created = datetime.now(timezone.utc) - timedelta(minutes=5)
        result = monitor.check_debate_sla("d-1", created)
        assert result is None
        assert called == []
