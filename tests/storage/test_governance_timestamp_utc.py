"""Timestamp UTC-consistency regression tests for GovernanceStore.

Python-side timestamps must be UTC to match SQLite's ``datetime('now')``.

``cleanup_old_records`` ages ``governance_approvals.requested_at`` and
``governance_verifications.timestamp`` with UTC ``datetime('now', '-N days')``
comparisons, so naive local-time stamps skew retention by the machine's UTC
offset (same bug family as PRs #9316/#9318; see
tests/memory/test_continuum_timestamp_utc.py).

Tests pin far-from-UTC, DST-free timezones via time.tzset() so the skew is
deterministic on any runner.
"""

import os
import time

import pytest

from aragora.storage.governance.store import GovernanceStore

# Freshly written stamps must agree with SQLite's UTC clock within this many
# seconds. Any local-time stamp would be off by whole hours (>= 3600s).
MAX_SKEW_SECONDS = 300


def _pin_timezone(tz: str):
    """Force a specific process-local timezone; restores the old one after."""
    if not hasattr(time, "tzset"):
        pytest.skip("requires time.tzset (POSIX)")
    old_tz = os.environ.get("TZ")
    os.environ["TZ"] = tz
    time.tzset()
    try:
        yield
    finally:
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        time.tzset()


@pytest.fixture
def positive_offset_timezone():
    """UTC+14, no DST: local stamps would lead datetime('now') by 14h."""
    yield from _pin_timezone("Pacific/Kiritimati")


@pytest.fixture
def negative_offset_timezone():
    """UTC-12, no DST: local stamps would trail datetime('now') by 12h."""
    yield from _pin_timezone("Etc/GMT+12")


@pytest.fixture
def store(tmp_path):
    gov = GovernanceStore(db_path=str(tmp_path / "governance_tz.db"))
    yield gov
    gov.close()


def _age_seconds(store: GovernanceStore, table: str, column: str) -> float:
    """Age of the single row's timestamp as SQLite's UTC clock sees it."""
    assert (table, column) in {
        ("governance_approvals", "requested_at"),
        ("governance_approvals", "approved_at"),
        ("governance_verifications", "timestamp"),
        ("governance_decisions", "timestamp"),
    }
    row = store._backend.fetch_one(
        f"SELECT (julianday('now') - julianday({column})) * 86400.0 FROM {table}"  # noqa: S608
    )
    assert row is not None and row[0] is not None
    return row[0]


class TestGovernanceTimestampUTCConsistency:
    """Fresh governance rows must not appear hours old/new to datetime('now')."""

    def _save_approval(self, store: GovernanceStore) -> None:
        store.save_approval(
            approval_id="apr-tz",
            title="tz check",
            description="",
            risk_level="low",
            status="pending",
            requested_by="tester",
            changes=[],
        )

    def test_save_approval_stamps_utc(self, store, positive_offset_timezone):
        self._save_approval(store)
        age = _age_seconds(store, "governance_approvals", "requested_at")
        assert abs(age) < MAX_SKEW_SECONDS, f"requested_at skewed by {age:.0f}s vs UTC"

    def test_update_approval_status_stamps_utc(self, store, negative_offset_timezone):
        self._save_approval(store)
        store.update_approval_status("apr-tz", status="approved", approved_by="tester")
        age = _age_seconds(store, "governance_approvals", "approved_at")
        assert abs(age) < MAX_SKEW_SECONDS, f"approved_at skewed by {age:.0f}s vs UTC"

    def test_save_verification_stamps_utc(self, store, positive_offset_timezone):
        store.save_verification(
            verification_id="ver-tz",
            claim="claim",
            context="ctx",
            result={"ok": True},
        )
        age = _age_seconds(store, "governance_verifications", "timestamp")
        assert abs(age) < MAX_SKEW_SECONDS, f"timestamp skewed by {age:.0f}s vs UTC"

    def test_save_decision_stamps_utc(self, store, negative_offset_timezone):
        store.save_decision(
            decision_id="dec-tz",
            debate_id="deb-tz",
            conclusion="fine",
            consensus_reached=True,
            confidence=0.9,
        )
        age = _age_seconds(store, "governance_decisions", "timestamp")
        assert abs(age) < MAX_SKEW_SECONDS, f"timestamp skewed by {age:.0f}s vs UTC"

    def test_fresh_rows_survive_cleanup(self, store, positive_offset_timezone):
        # Under local stamps at UTC+14 a fresh approval looked 14h in the
        # future; at UTC-12 old rows aged out 12h early. Fresh completed rows
        # must survive a 0-day retention boundary only by their true age.
        self._save_approval(store)
        store.update_approval_status("apr-tz", status="approved", approved_by="tester")
        counts = store.cleanup_old_records(approvals_days=1, verifications_days=1)
        assert counts["approvals"] == 0
