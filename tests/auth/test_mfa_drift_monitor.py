"""
Tests for MFA policy drift monitor (GitHub issue #510).

Tests cover:
- Scan with no user store configured (safe no-op)
- Scan with all-compliant admin users
- Scan with mixed compliant / non-compliant admins
- Grace-period users classified as warnings, not critical
- Critical alerts raised for admins past grace period
- Compliance rate calculation
- policy_met threshold logic
- on_violation callback invocation
- on_critical callback invocation per critical alert
- has_violations and critical_violations properties
- summary string generation
- to_dict serialization for MFADriftReport and MFADriftAlert
- _is_admin detection via role and roles attributes
- list_users fallback to get_all_users
- Async start / stop (cancel) lifecycle
- init_mfa_drift_monitor singleton guard
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest

from aragora.auth.mfa_drift_monitor import (
    MFADriftAlert,
    MFADriftMonitor,
    MFADriftReport,
    get_mfa_drift_monitor,
    init_mfa_drift_monitor,
)


# ---------------------------------------------------------------------------
# Fake user objects
# ---------------------------------------------------------------------------


@dataclass
class _AdminUser:
    """Minimal admin user fixture."""

    id: str = "admin-1"
    role: str = "admin"
    mfa_enabled: bool = False
    mfa_grace_period_started_at: str | None = None


@dataclass
class _RegularUser:
    """Non-admin user fixture."""

    id: str = "user-1"
    role: str = "member"
    mfa_enabled: bool = False


@dataclass
class _MultiRoleUser:
    """User with a roles set instead of single role."""

    id: str = "u-99"
    roles: set[str] = field(default_factory=lambda: {"admin", "member"})
    mfa_enabled: bool = False
    mfa_grace_period_started_at: str | None = None

    # No `role` attribute -- detection must use `roles`


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _store(*users: object) -> MagicMock:
    """Return a mock user store that yields *users*."""
    store = MagicMock(spec=["list_users"])
    store.list_users.return_value = list(users)
    return store


# ---------------------------------------------------------------------------
# Scan without user store
# ---------------------------------------------------------------------------


class TestScanNoStore:
    def test_returns_ok_report(self):
        monitor = MFADriftMonitor()
        report = monitor.scan()
        assert report.total_admins == 0
        assert not report.has_violations
        assert report.policy_met
        assert report.compliance_rate == 1.0

    def test_report_stored_as_last(self):
        monitor = MFADriftMonitor()
        assert monitor.last_report is None
        monitor.scan()
        assert monitor.last_report is not None


# ---------------------------------------------------------------------------
# All-compliant scan
# ---------------------------------------------------------------------------


class TestFullyCompliant:
    def test_all_mfa_enabled_policy_met(self):
        user = _AdminUser(id="a-1", mfa_enabled=True)
        monitor = MFADriftMonitor(user_store=_store(user))
        report = monitor.scan()
        assert report.total_admins == 1
        assert report.compliant == 1
        assert report.non_compliant == 0
        assert report.has_violations is False
        assert report.policy_met

    def test_non_admin_users_excluded(self):
        admin = _AdminUser(id="a-1", mfa_enabled=True)
        regular = _RegularUser(id="u-1")
        monitor = MFADriftMonitor(user_store=_store(admin, regular))
        report = monitor.scan()
        assert report.total_admins == 1  # regular excluded

    def test_compliance_rate_one_when_all_compliant(self):
        users = [_AdminUser(id=f"a-{i}", mfa_enabled=True) for i in range(5)]
        monitor = MFADriftMonitor(user_store=_store(*users))
        report = monitor.scan()
        assert report.compliance_rate == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Mixed compliant / non-compliant
# ---------------------------------------------------------------------------


class TestMixedCompliance:
    def test_non_compliant_count(self):
        compliant = _AdminUser(id="a-1", mfa_enabled=True)
        bad1 = _AdminUser(id="a-2", mfa_enabled=False)
        bad2 = _AdminUser(id="a-3", mfa_enabled=False)
        monitor = MFADriftMonitor(user_store=_store(compliant, bad1, bad2))
        report = monitor.scan()
        assert report.total_admins == 3
        assert report.compliant == 1
        assert report.non_compliant == 2
        assert report.has_violations is True

    def test_compliance_rate_calculation(self):
        users = [_AdminUser(id=f"a-{i}", mfa_enabled=(i < 3)) for i in range(5)]
        monitor = MFADriftMonitor(user_store=_store(*users))
        report = monitor.scan()
        assert report.compliance_rate == pytest.approx(3 / 5)

    def test_alerts_list_populated(self):
        bad = _AdminUser(id="a-1", mfa_enabled=False)
        monitor = MFADriftMonitor(user_store=_store(bad))
        report = monitor.scan()
        assert len(report.alerts) == 1
        assert report.alerts[0].user_id == "a-1"


# ---------------------------------------------------------------------------
# Severity: grace period vs critical
# ---------------------------------------------------------------------------


class TestSeverityClassification:
    def test_grace_period_alert_severity_is_warning(self):
        user = _AdminUser(
            id="a-1",
            mfa_enabled=False,
            mfa_grace_period_started_at="2026-03-01T00:00:00+00:00",
        )
        monitor = MFADriftMonitor(user_store=_store(user))
        report = monitor.scan()
        assert report.alerts[0].severity == "warning"
        assert report.alerts[0].in_grace_period is True
        assert report.in_grace_period == 1

    def test_no_grace_period_alert_severity_is_critical(self):
        user = _AdminUser(id="a-1", mfa_enabled=False, mfa_grace_period_started_at=None)
        monitor = MFADriftMonitor(user_store=_store(user))
        report = monitor.scan()
        assert report.alerts[0].severity == "critical"
        assert report.alerts[0].in_grace_period is False

    def test_critical_violations_filtered(self):
        grace_user = _AdminUser(
            id="a-1", mfa_enabled=False, mfa_grace_period_started_at="2026-03-01T00:00:00+00:00"
        )
        crit_user = _AdminUser(id="a-2", mfa_enabled=False)
        monitor = MFADriftMonitor(user_store=_store(grace_user, crit_user))
        report = monitor.scan()
        assert len(report.critical_violations) == 1
        assert report.critical_violations[0].user_id == "a-2"


# ---------------------------------------------------------------------------
# Policy threshold
# ---------------------------------------------------------------------------


class TestPolicyThreshold:
    def test_policy_met_at_100_percent_threshold(self):
        user = _AdminUser(id="a-1", mfa_enabled=False)
        monitor = MFADriftMonitor(user_store=_store(user), alert_threshold=1.0)
        report = monitor.scan()
        assert not report.policy_met

    def test_policy_met_at_80_percent_threshold_when_enough_compliant(self):
        users = [_AdminUser(id=f"a-{i}", mfa_enabled=(i < 4)) for i in range(5)]
        monitor = MFADriftMonitor(user_store=_store(*users), alert_threshold=0.8)
        report = monitor.scan()
        assert report.policy_met  # 4/5 = 80%

    def test_policy_not_met_below_threshold(self):
        users = [_AdminUser(id=f"a-{i}", mfa_enabled=(i < 3)) for i in range(5)]
        monitor = MFADriftMonitor(user_store=_store(*users), alert_threshold=0.9)
        report = monitor.scan()
        assert not report.policy_met  # 3/5 = 60% < 90%


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------


class TestCallbacks:
    def test_on_violation_called_when_threshold_not_met(self):
        callback = MagicMock()
        user = _AdminUser(id="a-1", mfa_enabled=False)
        monitor = MFADriftMonitor(
            user_store=_store(user), alert_threshold=1.0, on_violation=callback
        )
        monitor.scan()
        callback.assert_called_once()
        args = callback.call_args[0]
        assert isinstance(args[0], MFADriftReport)

    def test_on_violation_not_called_when_policy_met(self):
        callback = MagicMock()
        user = _AdminUser(id="a-1", mfa_enabled=True)
        monitor = MFADriftMonitor(
            user_store=_store(user), alert_threshold=1.0, on_violation=callback
        )
        monitor.scan()
        callback.assert_not_called()

    def test_on_critical_called_per_critical_alert(self):
        callback = MagicMock()
        crit1 = _AdminUser(id="a-1", mfa_enabled=False)
        crit2 = _AdminUser(id="a-2", mfa_enabled=False)
        monitor = MFADriftMonitor(user_store=_store(crit1, crit2), on_critical=callback)
        monitor.scan()
        assert callback.call_count == 2

    def test_on_critical_not_called_for_grace_period_alerts(self):
        callback = MagicMock()
        user = _AdminUser(
            id="a-1",
            mfa_enabled=False,
            mfa_grace_period_started_at="2026-03-01T00:00:00+00:00",
        )
        monitor = MFADriftMonitor(user_store=_store(user), on_critical=callback)
        monitor.scan()
        callback.assert_not_called()

    def test_failing_callback_does_not_crash_monitor(self):
        def bad_callback(report: MFADriftReport) -> None:
            raise RuntimeError("callback error")

        user = _AdminUser(id="a-1", mfa_enabled=False)
        monitor = MFADriftMonitor(
            user_store=_store(user), alert_threshold=1.0, on_violation=bad_callback
        )
        # Should not raise
        report = monitor.scan()
        assert report.has_violations


# ---------------------------------------------------------------------------
# Summary and serialization
# ---------------------------------------------------------------------------


class TestReportOutputs:
    def test_summary_ok(self):
        user = _AdminUser(id="a-1", mfa_enabled=True)
        monitor = MFADriftMonitor(user_store=_store(user))
        report = monitor.scan()
        assert (
            "OK" in report.summary or "passed" in report.summary.lower() or "100" in report.summary
        )

    def test_summary_violation(self):
        user = _AdminUser(id="a-1", mfa_enabled=False)
        monitor = MFADriftMonitor(user_store=_store(user))
        report = monitor.scan()
        assert "drift" in report.summary.lower() or "lack" in report.summary.lower()

    def test_to_dict_keys(self):
        user = _AdminUser(id="a-1", mfa_enabled=False)
        monitor = MFADriftMonitor(user_store=_store(user))
        report = monitor.scan()
        d = report.to_dict()
        assert "total_admins" in d
        assert "compliance_rate" in d
        assert "alerts" in d
        assert isinstance(d["alerts"], list)

    def test_alert_to_dict(self):
        alert = MFADriftAlert(user_id="u-1", role="admin", mfa_enabled=False)
        d = alert.to_dict()
        assert d["user_id"] == "u-1"
        assert d["mfa_enabled"] is False
        assert "severity" in d
        assert "detected_at" in d


# ---------------------------------------------------------------------------
# Admin detection via roles attribute
# ---------------------------------------------------------------------------


class TestAdminDetection:
    def test_detects_admin_via_single_role(self):
        user = _AdminUser(id="a-1", role="owner", mfa_enabled=False)
        monitor = MFADriftMonitor(user_store=_store(user))
        report = monitor.scan()
        assert report.total_admins == 1

    def test_detects_admin_via_roles_set(self):
        user = _MultiRoleUser(id="u-1", roles={"admin", "viewer"})
        monitor = MFADriftMonitor(user_store=_store(user))
        report = monitor.scan()
        assert report.total_admins == 1

    def test_non_admin_role_excluded(self):
        user = _RegularUser(id="u-1", role="viewer")
        monitor = MFADriftMonitor(user_store=_store(user))
        report = monitor.scan()
        assert report.total_admins == 0


# ---------------------------------------------------------------------------
# list_users fallback to get_all_users
# ---------------------------------------------------------------------------


class TestUserStoreFallback:
    def test_supports_list_all_users_tuple(self):
        store = MagicMock(spec=["list_all_users"])
        user = _AdminUser(id="a-1", mfa_enabled=True)
        store.list_all_users.return_value = ([user], 1)
        monitor = MFADriftMonitor(user_store=store)
        report = monitor.scan()
        assert report.total_admins == 1

    def test_falls_back_to_get_all_users(self):
        store = MagicMock(spec=[])  # no list_users
        user = _AdminUser(id="a-1", mfa_enabled=True)
        store.get_all_users = MagicMock(return_value=[user])
        monitor = MFADriftMonitor(user_store=store)
        report = monitor.scan()
        assert report.total_admins == 1

    def test_returns_empty_when_no_list_method(self):
        store = MagicMock(spec=[])  # neither list_users nor get_all_users
        monitor = MFADriftMonitor(user_store=store)
        report = monitor.scan()
        assert report.total_admins == 0
        assert report.policy_met

    def test_handles_list_users_exception_gracefully(self):
        store = MagicMock()
        store.list_users.side_effect = RuntimeError("db error")
        monitor = MFADriftMonitor(user_store=store)
        report = monitor.scan()
        assert report.total_admins == 0


# ---------------------------------------------------------------------------
# Async start / stop lifecycle
# ---------------------------------------------------------------------------


class TestAsyncLifecycle:
    def test_start_stop(self):
        monitor = MFADriftMonitor()

        async def run():
            await monitor.start(interval_seconds=3600)
            assert monitor._running
            await monitor.stop()
            assert not monitor._running

        asyncio.run(run())

    def test_double_start_is_noop(self):
        monitor = MFADriftMonitor()

        async def run():
            await monitor.start(interval_seconds=3600)
            task1 = monitor._task
            await monitor.start(interval_seconds=3600)  # second call
            task2 = monitor._task
            assert task1 is task2  # same task
            await monitor.stop()

        asyncio.run(run())

    def test_scan_runs_in_background(self):
        user = _AdminUser(id="a-1", mfa_enabled=True)
        monitor = MFADriftMonitor(user_store=_store(user))

        async def run():
            await monitor.start(interval_seconds=0)
            # Give the loop a tick to run the scan
            await asyncio.sleep(0.05)
            await monitor.stop()

        asyncio.run(run())
        assert monitor.last_report is not None
        assert monitor.last_report.total_admins == 1


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_get_before_init_returns_none(self):
        import aragora.auth.mfa_drift_monitor as mod

        original = mod._default_monitor
        mod._default_monitor = None
        assert get_mfa_drift_monitor() is None
        mod._default_monitor = original

    def test_init_creates_monitor(self):
        import aragora.auth.mfa_drift_monitor as mod

        original = mod._default_monitor
        mod._default_monitor = None
        m = init_mfa_drift_monitor()
        assert m is not None
        assert get_mfa_drift_monitor() is m
        mod._default_monitor = original

    def test_init_returns_existing_on_second_call(self):
        import aragora.auth.mfa_drift_monitor as mod

        original = mod._default_monitor
        mod._default_monitor = None
        m1 = init_mfa_drift_monitor()
        m2 = init_mfa_drift_monitor()
        assert m1 is m2
        mod._default_monitor = original
