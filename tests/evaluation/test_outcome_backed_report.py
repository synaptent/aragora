from __future__ import annotations

from copy import deepcopy

import pytest

from aragora.evaluation.outcome_backed_analysis import (
    ANALYSIS_CONTRACT_VERSION,
    analyze_scored_conditions,
)
from aragora.evaluation.outcome_backed_holdout import (
    HOLDOUT_CONTRACT_VERSION,
    MAX_HOLDOUT_EXPOSURES,
)
from aragora.evaluation.outcome_backed_report import (
    REPORT_CONTRACT_VERSION,
    final_verdict,
    render_report,
)
from aragora.evaluation.outcome_backed_scoring import SCORER_CONTRACT_VERSION


REGISTRY_HASH = "a" * 64


def _summary(condition_id: str, verdict: str) -> dict[str, object]:
    if verdict == "team_outperforms":
        team_score, baseline_score, delta, brier, p_value = 0.78, 0.68, 0.1, 0.08, 0.01
    elif verdict == "baseline_outperforms":
        team_score, baseline_score, delta, brier, p_value = 0.68, 0.78, -0.1, -0.08, 0.01
    else:
        team_score, baseline_score, delta, brier, p_value = 0.7, 0.7, 0.0, 0.0, 1.0
    return {
        "condition_id": condition_id,
        "team_mean_composite_score": team_score,
        "baseline_mean_composite_score": baseline_score,
        "mean_composite_delta": delta,
        "mean_brier_improvement": brier,
        "wins": 14,
        "ties": 1,
        "losses": 1,
        "exact_sign_flip_p_value": p_value,
        "case_deltas": [],
    }


def _analysis_report(
    phase: str,
    verdict: str,
    *,
    reverse_baselines: bool = False,
) -> dict[str, object]:
    summaries = [_summary("openai", verdict), _summary("claude", verdict)]
    if reverse_baselines:
        summaries.reverse()
    return {
        "analysis_contract_version": ANALYSIS_CONTRACT_VERSION,
        "scorer_contract_version": SCORER_CONTRACT_VERSION,
        "phase": phase,
        "team_condition_id": "aragora_team",
        "n": 16 if phase == "development" else 8,
        "strongest_baseline_id": "claude",
        "strongest_baseline_rule": "frozen rule",
        "thresholds": {},
        "per_baseline": summaries,
        "verdict": verdict,
    }


def _budget_snapshot(
    utc_date: str = "2026-08-30",
    *,
    settled: str = "4",
    reserved: str = "0",
    open_reservations: int = 0,
    exceeded: bool = False,
) -> dict[str, object]:
    committed = str(float(settled) + float(reserved)).rstrip("0").rstrip(".") or "0"
    remaining = str(max(0.0, 25.0 - float(committed))).rstrip("0").rstrip(".") or "0"
    return {
        "utc_date": utc_date,
        "cap_usd": "25",
        "settled_usd": settled,
        "reserved_usd": reserved,
        "committed_usd": committed,
        "remaining_usd": remaining,
        "open_reservations": open_reservations,
        "event_count": 2,
        "exceeded": exceeded,
    }


def _holdout_snapshot(exposure_count: int = 2) -> dict[str, object]:
    return {
        "holdout_contract_version": HOLDOUT_CONTRACT_VERSION,
        "max_exposures_per_registry": MAX_HOLDOUT_EXPOSURES,
        "event_count": exposure_count,
        "registries": [
            {
                "registry_hash": REGISTRY_HASH,
                "exposure_count": exposure_count,
                "remaining_exposures": max(0, MAX_HOLDOUT_EXPOSURES - exposure_count),
                "run_labels": [f"holdout-r{index}" for index in range(1, exposure_count + 1)],
            }
        ],
    }


def _verdict(
    development: str,
    holdout: str,
    *,
    budgets: list[dict[str, object]] | None = None,
    custody: dict[str, object] | None = None,
) -> str:
    return final_verdict(
        _analysis_report("development", development),
        _analysis_report("holdout", holdout),
        budgets or [_budget_snapshot()],
        custody or _holdout_snapshot(),
    )


def test_report_contract_version_is_frozen() -> None:
    assert REPORT_CONTRACT_VERSION == "outcome-backed-decision-quality-report/1.0"


@pytest.mark.parametrize(
    ("development", "holdout", "expected"),
    [
        ("team_outperforms", "team_outperforms", "go"),
        ("team_outperforms", "no_difference", "conditional_go"),
        ("team_outperforms", "baseline_outperforms", "no_go"),
        ("baseline_outperforms", "team_outperforms", "no_go"),
        ("no_difference", "team_outperforms", "no_go"),
    ],
)
def test_frozen_verdict_branches(development: str, holdout: str, expected: str) -> None:
    assert _verdict(development, holdout) == expected


@pytest.mark.parametrize(
    "budget",
    [
        _budget_snapshot(settled="26", exceeded=True),
        _budget_snapshot(reserved="1", open_reservations=1),
    ],
)
def test_budget_violation_forces_no_go_despite_team_wins(budget: dict[str, object]) -> None:
    assert _verdict("team_outperforms", "team_outperforms", budgets=[budget]) == "no_go"


@pytest.mark.parametrize("exposures", [1, MAX_HOLDOUT_EXPOSURES + 1])
def test_holdout_custody_violation_forces_no_go_despite_team_wins(exposures: int) -> None:
    assert (
        _verdict(
            "team_outperforms",
            "team_outperforms",
            custody=_holdout_snapshot(exposures),
        )
        == "no_go"
    )


@pytest.mark.parametrize(
    ("target", "field", "value", "message"),
    [
        ("development", "analysis_contract_version", "future-analysis", "analysis contract"),
        ("holdout", "scorer_contract_version", "future-scorer", "scorer contract"),
        ("development", "n", 15, r"n must equal 16"),
        ("holdout", "n", 7, r"n must equal 8"),
        ("development", "per_baseline", [], "non-empty array"),
    ],
)
def test_analysis_input_defects_fail_closed(
    target: str,
    field: str,
    value: object,
    message: str,
) -> None:
    development = _analysis_report("development", "team_outperforms")
    holdout = _analysis_report("holdout", "team_outperforms")
    report = development if target == "development" else holdout
    report[field] = value

    with pytest.raises(ValueError, match=message):
        final_verdict(development, holdout, [_budget_snapshot()], _holdout_snapshot())


def test_analysis_phase_and_claimed_verdict_must_match_metrics() -> None:
    development = _analysis_report("development", "team_outperforms")
    holdout = _analysis_report("holdout", "team_outperforms")
    holdout["phase"] = "development"
    with pytest.raises(ValueError, match="phase mismatch"):
        final_verdict(development, holdout, [_budget_snapshot()], _holdout_snapshot())

    holdout = _analysis_report("holdout", "team_outperforms")
    holdout["verdict"] = "no_difference"
    with pytest.raises(ValueError, match="verdict does not match"):
        final_verdict(development, holdout, [_budget_snapshot()], _holdout_snapshot())


def test_strongest_baseline_must_match_metrics() -> None:
    development = _analysis_report("development", "team_outperforms")
    holdout = _analysis_report("holdout", "team_outperforms")
    development["strongest_baseline_id"] = "openai"

    with pytest.raises(ValueError, match="strongest baseline does not match"):
        final_verdict(development, holdout, [_budget_snapshot()], _holdout_snapshot())


def test_summary_delta_must_match_reported_means() -> None:
    development = _analysis_report("development", "team_outperforms")
    holdout = _analysis_report("holdout", "team_outperforms")
    summaries = development["per_baseline"]
    assert isinstance(summaries, list)
    summaries[0]["mean_composite_delta"] = 0.2

    with pytest.raises(ValueError, match="mean_composite_delta does not match"):
        final_verdict(development, holdout, [_budget_snapshot()], _holdout_snapshot())


def test_complete_report_rejects_insufficient_data_claim() -> None:
    development = _analysis_report("development", "team_outperforms")
    holdout = _analysis_report("holdout", "no_difference")
    holdout["verdict"] = "insufficient_data"

    with pytest.raises(ValueError, match="verdict does not match"):
        final_verdict(development, holdout, [_budget_snapshot()], _holdout_snapshot())


def _scored_rows(prefix: str, count: int, *, brier: float) -> list[dict[str, object]]:
    return [
        {
            "case_id": f"{prefix}-{index:02d}",
            "binary_brier": brier,
            "directional_accuracy": 1.0,
            "crux_recall": 0.8,
            "provenance_completeness": 1.0,
            "receipt_verification_rate": 1.0,
        }
        for index in range(count)
    ]


def test_real_development_and_holdout_analysis_can_produce_go() -> None:
    development = analyze_scored_conditions(
        {
            "aragora_team": _scored_rows("dev", 16, brier=0.2),
            "openai": _scored_rows("dev", 16, brier=0.3),
        },
        team_condition_id="aragora_team",
        scorer_contract_version=SCORER_CONTRACT_VERSION,
        holdout_case_ids=set(),
    ).to_dict()
    holdout_ids = {f"holdout-{index:02d}" for index in range(8)}
    holdout = analyze_scored_conditions(
        {
            "aragora_team": _scored_rows("holdout", 8, brier=0.2),
            "openai": _scored_rows("holdout", 8, brier=0.3),
        },
        team_condition_id="aragora_team",
        scorer_contract_version=SCORER_CONTRACT_VERSION,
        holdout_case_ids=holdout_ids,
        phase="holdout",
    ).to_dict()

    assert (
        final_verdict(
            development,
            holdout,
            [_budget_snapshot()],
            _holdout_snapshot(),
        )
        == "go"
    )


def test_budget_shape_defect_fails_closed() -> None:
    budget = _budget_snapshot()
    budget["committed_usd"] = "5"

    with pytest.raises(ValueError, match="settled plus reserved"):
        _verdict("team_outperforms", "team_outperforms", budgets=[budget])


def test_holdout_shape_and_version_defects_fail_closed() -> None:
    wrong_version = _holdout_snapshot()
    wrong_version["holdout_contract_version"] = "future-holdout"
    with pytest.raises(ValueError, match="contract version mismatch"):
        _verdict("team_outperforms", "team_outperforms", custody=wrong_version)

    missing_registry = _holdout_snapshot()
    missing_registry["registries"] = []
    with pytest.raises(ValueError, match="exactly one frozen registry"):
        _verdict("team_outperforms", "team_outperforms", custody=missing_registry)


def test_render_report_is_byte_identical_and_stably_ordered() -> None:
    development = _analysis_report("development", "team_outperforms")
    holdout = _analysis_report("holdout", "no_difference")
    budgets = [_budget_snapshot("2026-08-31"), _budget_snapshot("2026-08-30")]

    first = render_report(development, holdout, budgets, _holdout_snapshot())
    second = render_report(
        _analysis_report("development", "team_outperforms", reverse_baselines=True),
        _analysis_report("holdout", "no_difference", reverse_baselines=True),
        list(reversed(deepcopy(budgets))),
        _holdout_snapshot(),
    )

    assert first == second
    assert first.index("2026-08-30") < first.index("2026-08-31")
    assert "## 3. Condition Summary" in first
    assert "## 4. Primary Metrics" in first
    assert "## 7. Gate Decision" in first
    assert "`conditional_go`" in first
    assert "not a claim of statistical significance" in first
