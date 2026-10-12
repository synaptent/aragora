"""Characterization tests for the skip-and-warn paths of ``ReputationStore.load_from_file``.

Each parametrized line first proves which exception the real parse path
(``json.loads`` plus the ``from_json`` classmethod) raises for it, then
checks that loading a ledger containing that line skips only that line,
keeps the valid records around it and logs one warning naming the line.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from aragora.reputation.store import ReputationStore
from aragora.reputation.types import (
    DOMAIN_PREDICTION_MARKET,
    ReputationDelta,
    ReputationDeltaReversed,
)

_STORE_LOGGER = "aragora.reputation.store"
_MISSING = object()

_DELTA: dict[str, Any] = {
    "delta_id": "d-a",
    "agent_id": "alice",
    "domain": DOMAIN_PREDICTION_MARKET,
    "claim_id": "c-1",
    "resolution_id": "mkt-1",
    "delta": 0.5,
    "scoring_rule": "brier_proper",
    "applied_at": "2026-10-12T00:00:00Z",
    "decay_half_life_days": None,
    "reason": {},
}

_REVERSAL: dict[str, Any] = {
    "reversal_id": "rev-a",
    "original_delta_id": "d-a",
    "agent_id": "alice",
    "domain": DOMAIN_PREDICTION_MARKET,
    "counter_delta": -0.5,
    "reversed_at": "2026-10-12T01:00:00Z",
    "reason": {},
}


def _line(base: dict[str, Any], **changes: Any) -> str:
    data = dict(base)
    for key, value in changes.items():
        if value is _MISSING:
            data.pop(key)
        else:
            data[key] = value
    return json.dumps(data)


_SHARED_BAD_LINES = [
    pytest.param("{bad", json.JSONDecodeError, id="malformed-json"),
    pytest.param("1" * 5000, ValueError, id="integer-digit-limit"),
    pytest.param("[" * 100_000, RecursionError, id="deep-nesting"),
    pytest.param("[]", TypeError, id="array-payload"),
    pytest.param('"text"', TypeError, id="string-payload"),
    pytest.param("null", TypeError, id="null-payload"),
]

_DELTA_BAD_LINES = [
    *_SHARED_BAD_LINES,
    pytest.param(_line(_DELTA, agent_id=_MISSING), KeyError, id="missing-key"),
    pytest.param(_line(_DELTA, delta=None), TypeError, id="null-delta"),
    pytest.param(_line(_DELTA, delta="abc"), ValueError, id="non-numeric-delta"),
    pytest.param(_line(_DELTA, delta=10**400), OverflowError, id="huge-integer-delta"),
    pytest.param(
        _line(_DELTA, decay_half_life_days=10**400),
        OverflowError,
        id="huge-integer-half-life",
    ),
    pytest.param(_line(_DELTA, reason=5), TypeError, id="integer-reason"),
    pytest.param(_line(_DELTA, reason="ab"), ValueError, id="string-reason"),
]

_REVERSAL_BAD_LINES = [
    *_SHARED_BAD_LINES,
    pytest.param(_line(_REVERSAL, original_delta_id=_MISSING), KeyError, id="missing-key"),
    pytest.param(_line(_REVERSAL, counter_delta=[1]), TypeError, id="array-counter-delta"),
    pytest.param(_line(_REVERSAL, counter_delta="abc"), ValueError, id="non-numeric-delta"),
    pytest.param(
        _line(_REVERSAL, counter_delta=-(10**400)), OverflowError, id="huge-integer-delta"
    ),
    pytest.param(_line(_REVERSAL, reason=[[[1], 2]]), TypeError, id="unhashable-reason-key"),
    pytest.param(_line(_REVERSAL, reason=["abc"]), ValueError, id="bad-reason-pair"),
]


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == _STORE_LOGGER and record.levelno == logging.WARNING
    ]


def _write(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.mark.parametrize(("bad_line", "expected_exc"), _DELTA_BAD_LINES)
def test_invalid_delta_line_is_skipped_with_one_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    bad_line: str,
    expected_exc: type[BaseException],
) -> None:
    with pytest.raises(expected_exc) as excinfo:
        ReputationDelta.from_json(json.loads(bad_line))
    assert excinfo.type is expected_exc

    ledger = tmp_path / "ledger.jsonl"
    _write(
        ledger,
        [
            _line(_DELTA, delta_id="d-a"),
            bad_line,
            _line(_DELTA, delta_id="d-b", agent_id="bob", delta=-0.25),
        ],
    )

    with caplog.at_level(logging.WARNING, logger=_STORE_LOGGER):
        store = ReputationStore.load_from_file(ledger)

    assert len(store) == 2
    assert [d.delta_id for d in store.deltas_for("alice")] == ["d-a"]
    assert [d.delta_id for d in store.deltas_for("bob")] == ["d-b"]
    warnings = _warnings(caplog)
    assert len(warnings) == 1
    assert warnings[0].startswith(f"ReputationStore: skipping invalid line 2 in {ledger}: ")


@pytest.mark.parametrize(("bad_line", "expected_exc"), _REVERSAL_BAD_LINES)
def test_invalid_reversal_line_is_skipped_with_one_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    bad_line: str,
    expected_exc: type[BaseException],
) -> None:
    with pytest.raises(expected_exc) as excinfo:
        ReputationDeltaReversed.from_json(json.loads(bad_line))
    assert excinfo.type is expected_exc

    ledger = tmp_path / "ledger.jsonl"
    _write(ledger, [_line(_DELTA, delta_id="d-a"), _line(_DELTA, delta_id="d-b")])
    reversal_path = tmp_path / "ledger.reversals.jsonl"
    _write(reversal_path, [bad_line, _line(_REVERSAL, original_delta_id="d-a")])

    with caplog.at_level(logging.WARNING, logger=_STORE_LOGGER):
        store = ReputationStore.load_from_file(ledger)

    assert [r.original_delta_id for r in store.reversals_for("alice")] == ["d-a"]
    assert store.get_score("alice", apply_decay=False) == pytest.approx(0.5)
    warnings = _warnings(caplog)
    assert len(warnings) == 1
    assert warnings[0].startswith(
        f"ReputationStore: skipping invalid reversal line 1 in {reversal_path}: "
    )
