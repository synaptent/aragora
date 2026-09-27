"""Timestamp UTC-consistency regression tests for FlipDetector.

``FlipEvent.detected_at`` rows are aged with UTC ``datetime('now', '-1 day')``
in ``get_flip_summary`` (recent_24h window), so naive local-time stamps skew
the window by the machine's UTC offset (same bug family as PRs #9316/#9318;
see tests/memory/test_continuum_timestamp_utc.py).
"""

import os
import sqlite3
import time

import pytest

from aragora.insights.flip_detector import FlipDetector, FlipEvent

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


def _make_flip() -> FlipEvent:
    return FlipEvent(
        id="flip-tz",
        agent_name="claude",
        original_claim="a",
        new_claim="not a",
        original_confidence=0.9,
        new_confidence=0.9,
        original_debate_id="d1",
        new_debate_id="d2",
        original_position_id="p1",
        new_position_id="p2",
        similarity_score=0.9,
        flip_type="contradiction",
    )


class TestFlipDetectorTimestampUTCConsistency:
    def test_detected_at_stamps_utc(self, tmp_path, positive_offset_timezone):
        detector = FlipDetector(db_path=tmp_path / "flips_tz.db")
        detector._store_flip(_make_flip())

        with sqlite3.connect(detector.db_path) as conn:
            row = conn.execute(
                "SELECT (julianday('now') - julianday(detected_at)) * 86400.0 "
                "FROM detected_flips WHERE id = 'flip-tz'"
            ).fetchone()
        assert row is not None and row[0] is not None
        age = row[0]
        # At UTC+14 a local stamp would look ~14h in the future (age ~ -50400s)
        # and drop out of the recent_24h window early on the other side.
        assert abs(age) < MAX_SKEW_SECONDS, f"detected_at skewed by {age:.0f}s vs UTC"

    def test_fresh_flip_counts_in_recent_24h(self, tmp_path, positive_offset_timezone):
        detector = FlipDetector(db_path=tmp_path / "flips_tz2.db")
        detector._store_flip(_make_flip())
        summary = detector.get_flip_summary()
        assert summary["recent_24h"] >= 1
