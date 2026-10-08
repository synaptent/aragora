from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCOREBOARD = REPO_ROOT / "docs" / "status" / "DATA_WINDOW_ARMING_SCOREBOARD.md"
REQUIRED_WINDOWS = {
    "adjudicator.step_2",
    "lease.strict",
    "executor.kill_switch_read",
    "issue_close_discipline",
    "cancelled_run_self_heal",
}
TIMESTAMP_RE = re.compile(r"2026-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


def _window_rows() -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in SCOREBOARD.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| `"):
            continue
        window = line.split("`", 2)[1]
        rows[window] = line
    return rows


def test_scoreboard_covers_every_required_data_window() -> None:
    rows = _window_rows()
    assert set(rows) == REQUIRED_WINDOWS


def test_every_window_has_decision_owner_and_last_checked() -> None:
    for window, row in _window_rows().items():
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        assert len(cells) == 6, window
        assert cells[3] in {"**ARM (data only)**", "**HOLD**"}, window
        assert cells[4], window
        assert TIMESTAMP_RE.fullmatch(cells[5]), window


def test_scoreboard_is_report_only_and_fails_closed() -> None:
    text = SCOREBOARD.read_text(encoding="utf-8")
    assert "this document cannot arm a mechanism" in text
    assert "fails closed to **HOLD**" in text
    assert "must not create `boss-ready` work" in text
    assert "Human re-arm remains a separate action" in text
