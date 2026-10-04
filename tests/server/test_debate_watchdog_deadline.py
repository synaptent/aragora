"""The stuck-debate watchdog must respect each debate's recorded deadline.

Each test runs single watchdog passes (the second ``asyncio.sleep`` ends the
loop) and sets debate age through ``start_time``, so nothing waits in real time.
"""

from __future__ import annotations

import asyncio
import logging
import time

import pytest

import aragora.server.debate_utils as du
from aragora.server.state import get_state_manager, reset_state_manager

DEBATE_ID = "watchdog-deadline"
FULL_FORMAT_DEADLINE = 1800.0


@pytest.fixture(autouse=True)
def _isolated_state():
    reset_state_manager()
    yield
    reset_state_manager()


def _running_debate(age_seconds: float, **status_fields) -> None:
    manager = get_state_manager()
    manager.register_debate(debate_id=DEBATE_ID, task="Adopt a four-day week?", agents=["a", "b"])
    du.update_debate_status(DEBATE_ID, "running", **status_fields)
    manager.get_debate(DEBATE_ID).start_time = time.time() - age_seconds


def _one_watchdog_pass(monkeypatch) -> None:
    sleeps: list[float] = []

    async def _sleep(delay: float) -> None:
        if sleeps:
            raise asyncio.CancelledError
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _sleep)
    asyncio.run(du.watchdog_stuck_debates(check_interval=60.0))
    assert sleeps == [60.0]


def _state():
    return get_state_manager().get_debate(DEBATE_ID)


def test_debate_within_its_recorded_deadline_is_not_flagged_at_700s(monkeypatch):
    _running_debate(700, deadline_seconds=FULL_FORMAT_DEADLINE)

    _one_watchdog_pass(monkeypatch)

    assert _state().status == "running"
    assert "error" not in _state().metadata


def test_debate_is_flagged_after_deadline_plus_margin(monkeypatch, caplog):
    margin = du.STUCK_DEBATE_DEADLINE_MARGIN_SECONDS
    assert 60 <= margin <= 300
    _running_debate(FULL_FORMAT_DEADLINE + margin + 5, deadline_seconds=FULL_FORMAT_DEADLINE)

    with caplog.at_level(logging.WARNING, logger=du.logger.name):
        _one_watchdog_pass(monkeypatch)

    assert _state().status == "timeout"
    assert _state().metadata["error"].startswith("Debate timed out after")
    assert f"timeout: {FULL_FORMAT_DEADLINE + margin:.0f}s" in caplog.text


@pytest.mark.parametrize(
    "stored",
    [None, 0, -5, float("nan"), float("inf"), "1800", True, 60.0],
    ids=["missing", "zero", "negative", "nan", "inf", "string", "bool", "short-valid"],
)
def test_600s_limit_applies_without_a_longer_valid_deadline(monkeypatch, caplog, stored):
    _running_debate(595, **({} if stored is None else {"deadline_seconds": stored}))
    _one_watchdog_pass(monkeypatch)
    assert _state().status == "running"

    _state().start_time = time.time() - 605
    with caplog.at_level(logging.WARNING, logger=du.logger.name):
        _one_watchdog_pass(monkeypatch)

    assert du.STUCK_DEBATE_TIMEOUT_SECONDS == 600
    assert _state().status == "timeout"
    assert "timeout: 600s" in caplog.text


def test_debate_completing_after_watchdog_flag_keeps_no_stale_error(monkeypatch):
    _running_debate(605)
    _one_watchdog_pass(monkeypatch)
    assert _state().status == "timeout"

    du.update_debate_status(DEBATE_ID, "completed", result={"final_answer": "Yes"})

    assert _state().status == "completed"
    assert "error" not in _state().metadata
