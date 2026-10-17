"""Tests for aragora.evaluation.cp5_evaluator — AGT-06 CP-5 verdict from a VIAH trend."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aragora.evaluation.capability_checkpoint import (
    CheckpointCode,
    CheckpointRecord,
    CheckpointRegistryError,
    CheckpointStatus,
    build_default_registry,
)
from aragora.evaluation.cp5_evaluator import (
    DEFAULT_RESCUE_SPIKE_THRESHOLD,
    Cp5Evaluation,
    evaluate_cp5,
    record_cp5,
    rescue_spike_weeks,
)
from aragora.evaluation.viah import VIAH_TREND_FLAG, ViahTrend, ViahTrendPoint, rolling_viah_trend

FLAG = "ARAGORA_CAPABILITY_CHECKPOINTS_ENABLED"


def _point(idx: int, viah: float | None, rescues: int = 0) -> ViahTrendPoint:
    return ViahTrendPoint(
        week_index=idx,
        window_start=f"2026-09-{1 + idx * 7:02d}T00:00:00Z",
        window_end=f"2026-09-{8 + idx * 7:02d}T00:00:00Z",
        viah=viah,
        merged_autonomous_prs=0,
        agent_hours=0.0 if viah is None else 10.0,
        rescues_required=rescues,
    )


def _trend(
    scores: list[float | None], rescues: list[int] | None = None, direction: str = "positive"
) -> ViahTrend:
    rescues = rescues or [0] * len(scores)
    points = [_point(i, s, r) for i, (s, r) in enumerate(zip(scores, rescues, strict=True))]
    return ViahTrend(weeks_requested=len(scores), points=points, trend_direction=direction)


@pytest.fixture
def enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(FLAG, "1")


# ---------------------------------------------------------------------------
# Gating
# ---------------------------------------------------------------------------


def test_evaluate_raises_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(FLAG, raising=False)
    with pytest.raises(CheckpointRegistryError, match="disabled"):
        evaluate_cp5(_trend([0.1, 0.2, 0.3, 0.4]))


def test_record_raises_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(FLAG, raising=False)
    registry = build_default_registry()
    with pytest.raises(CheckpointRegistryError, match="disabled"):
        record_cp5(registry, _trend([0.1, 0.2, 0.3, 0.4]))
    assert registry.latest_record(CheckpointCode.CP5) is None


# ---------------------------------------------------------------------------
# Rescue spikes
# ---------------------------------------------------------------------------


def test_rescue_spike_weeks_uses_strict_threshold_and_ignores_unscored() -> None:
    trend = _trend([0.1, None, 0.3, 0.4], rescues=[3, 9, 4, 0])
    assert rescue_spike_weeks(trend) == [2]  # week 0 == threshold, week 1 unscored
    assert rescue_spike_weeks(trend, threshold=0) == [0, 2]


def test_rescue_spike_weeks_rejects_negative_threshold() -> None:
    with pytest.raises(ValueError):
        rescue_spike_weeks(_trend([0.1]), threshold=-1)


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------


def test_pass_when_positive_and_no_spike(enabled: None) -> None:
    ev = evaluate_cp5(_trend([0.1, 0.2, 0.3, 0.4]))
    assert ev.status is CheckpointStatus.PASS
    assert ev.scored_weeks == 4
    assert ev.spike_weeks == ()
    assert ev.rescue_spike_threshold == DEFAULT_RESCUE_SPIKE_THRESHOLD


@pytest.mark.parametrize("direction", ["flat", "negative"])
def test_fail_when_trend_not_positive(enabled: None, direction: str) -> None:
    ev = evaluate_cp5(_trend([0.2, 0.2, 0.2, 0.2], direction=direction))
    assert ev.status is CheckpointStatus.FAIL
    assert direction in ev.notes


def test_fail_when_positive_but_rescue_spike(enabled: None) -> None:
    ev = evaluate_cp5(_trend([0.1, 0.2, 0.3, 0.4], rescues=[0, 0, 5, 0]))
    assert ev.status is CheckpointStatus.FAIL
    assert ev.spike_weeks == (2,)
    assert "rescue spike" in ev.notes


def test_fail_notes_list_both_reasons(enabled: None) -> None:
    ev = evaluate_cp5(_trend([0.4, 0.3, 0.2, 0.1], rescues=[0, 4, 0, 0], direction="negative"))
    assert ev.status is CheckpointStatus.FAIL
    assert "negative" in ev.notes and "week(s) [1]" in ev.notes


def test_pending_when_insufficient_data_direction(enabled: None) -> None:
    ev = evaluate_cp5(_trend([0.1, None, None, None], direction="insufficient_data"))
    assert ev.status is CheckpointStatus.PENDING
    assert ev.scored_weeks == 1


def test_pending_when_fewer_scored_weeks_than_required(enabled: None) -> None:
    # Direction is positive from 3 scored weeks, but the default requires all 4.
    ev = evaluate_cp5(_trend([0.1, 0.2, None, 0.4]))
    assert ev.status is CheckpointStatus.PENDING
    assert "3/4" in ev.notes


def test_min_scored_weeks_relaxes_pending(enabled: None) -> None:
    ev = evaluate_cp5(_trend([0.1, 0.2, None, 0.4]), min_scored_weeks=3)
    assert ev.status is CheckpointStatus.PASS
    assert ev.min_scored_weeks == 3


@pytest.mark.parametrize("bad", [0, 5])
def test_min_scored_weeks_out_of_range(enabled: None, bad: int) -> None:
    with pytest.raises(ValueError):
        evaluate_cp5(_trend([0.1, 0.2, 0.3, 0.4]), min_scored_weeks=bad)


def test_negative_threshold_rejected(enabled: None) -> None:
    with pytest.raises(ValueError):
        evaluate_cp5(_trend([0.1, 0.2, 0.3, 0.4]), rescue_spike_threshold=-1)


# ---------------------------------------------------------------------------
# Serialization / record
# ---------------------------------------------------------------------------


def test_to_dict_and_to_record_round_trip(enabled: None) -> None:
    ev = evaluate_cp5(_trend([0.1, 0.2, 0.3, 0.4], rescues=[0, 0, 7, 0]))
    payload = ev.to_dict()
    assert payload["status"] == "fail"
    assert payload["spike_weeks"] == [2]
    json.dumps(payload)  # must be JSON-serializable
    rec = ev.to_record()
    assert isinstance(rec, CheckpointRecord)
    assert rec.checkpoint_code is CheckpointCode.CP5
    assert rec.status is CheckpointStatus.FAIL
    assert rec.evidence == payload
    assert rec.evaluator == "cp5_evaluator"


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


def _pass_cp4(registry) -> None:
    registry.record(
        CheckpointRecord.create(
            checkpoint_code=CheckpointCode.CP4, status=CheckpointStatus.PASS, evaluator="t"
        )
    )


def test_record_skips_when_cp4_not_passed(enabled: None) -> None:
    registry = build_default_registry()
    rec = record_cp5(registry, _trend([0.1, 0.2, 0.3, 0.4]))
    assert rec.status is CheckpointStatus.SKIPPED
    assert rec.evidence == {"depends_on": "CP-4", "dependency_status": "pending"}
    assert registry.status_of(CheckpointCode.CP5) is CheckpointStatus.SKIPPED


def test_record_writes_verdict_when_cp4_passed(enabled: None) -> None:
    registry = build_default_registry()
    _pass_cp4(registry)
    rec = record_cp5(registry, _trend([0.1, 0.2, 0.3, 0.4]), evaluator="weekly-job")
    assert rec.status is CheckpointStatus.PASS
    assert rec.evaluator == "weekly-job"
    assert registry.latest_record(CheckpointCode.CP5) is rec


def test_record_passes_through_thresholds(enabled: None) -> None:
    registry = build_default_registry()
    _pass_cp4(registry)
    rec = record_cp5(
        registry, _trend([0.1, 0.2, 0.3, 0.4], rescues=[0, 2, 0, 0]), rescue_spike_threshold=1
    )
    assert rec.status is CheckpointStatus.FAIL
    assert rec.evidence["spike_weeks"] == [1]


# ---------------------------------------------------------------------------
# End-to-end: ledger → rolling trend → rescues_required populated
# ---------------------------------------------------------------------------


def test_rolling_trend_carries_weekly_rescues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    from aragora.swarm.shift_ledger import ShiftLedger

    monkeypatch.setenv(VIAH_TREND_FLAG, "1")
    now = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    week = timedelta(hours=168)

    def ts(at: datetime) -> str:
        return at.strftime("%Y-%m-%dT%H:%M:%SZ")

    entries: list[dict] = []
    # Two weeks of activity; the most recent week has a rescue spike.
    for weeks_ago, rescues in ((1, 1), (0, 5)):
        start = now - week * weeks_ago - timedelta(hours=10)
        entries.append(
            {
                "entry_type": "shift_start",
                "timestamp": ts(start),
                "payload": {"shift_id": f"s{weeks_ago}"},
            }
        )
        entries.append(
            {
                "entry_type": "cycle_tick",
                "timestamp": ts(start + timedelta(hours=1)),
                "payload": {"rescue_count": rescues},
            }
        )
        entries.append(
            {"entry_type": "pr_merged", "timestamp": ts(start + timedelta(hours=2)), "payload": {}}
        )
        entries.append(
            {
                "entry_type": "shift_stop",
                "timestamp": ts(start + timedelta(hours=5)),
                "payload": {"shift_id": f"s{weeks_ago}"},
            }
        )
    path = tmp_path / "shift_ledger.jsonl"
    path.write_text(
        "".join(json.dumps(e, sort_keys=True) + "\n" for e in entries), encoding="utf-8"
    )

    trend = rolling_viah_trend(ledger=ShiftLedger(path=path), weeks=2, now=now)
    assert [p.rescues_required for p in trend.points] == [1, 5]
    assert trend.to_dict()["points"][1]["rescues_required"] == 5

    ev = evaluate_cp5(trend)
    assert isinstance(ev, Cp5Evaluation)
    assert ev.spike_weeks == (1,)
    assert ev.status is CheckpointStatus.FAIL
