from __future__ import annotations

from itertools import product
import json
import math

import pytest

from aragora.evaluation.outcome_backed_analysis import (
    MIN_ABSOLUTE_BRIER_IMPROVEMENT,
    TIE_EPSILON,
    analyze_scored_conditions,
    exact_paired_sign_flip_p_value,
)
from aragora.evaluation.outcome_backed_scoring import SCORER_CONTRACT_VERSION


def _score(
    case_id: str,
    *,
    brier: float,
    accuracy: float = 1.0,
    crux_recall: float = 0.5,
    provenance: float = 0.5,
    receipt: float = 1.0,
) -> dict[str, float | int | str]:
    return {
        "case_id": case_id,
        "binary_brier": brier,
        "directional_accuracy": accuracy,
        "crux_recall": crux_recall,
        "provenance_completeness": provenance,
        "receipt_verification_rate": receipt,
        "latency_ms": 10.0,
        "model_calls": 1,
        "cost_usd": 0.01,
    }


def _analyze(
    team: list[dict[str, float | int | str]],
    baseline: list[dict[str, float | int | str]],
    **overrides: object,
):
    kwargs: dict[str, object] = {
        "team_condition_id": "aragora-team",
        "scorer_contract_version": SCORER_CONTRACT_VERSION,
        "holdout_case_ids": set(),
    }
    kwargs.update(overrides)
    return analyze_scored_conditions(
        {"aragora-team": team, "openai": baseline},
        **kwargs,  # type: ignore[arg-type]
    )


def _rows(count: int, *, team_brier: float, baseline_brier: float):
    team = [_score(f"dev-{index:02d}", brier=team_brier) for index in range(count)]
    baseline = [_score(f"dev-{index:02d}", brier=baseline_brier) for index in range(count)]
    return team, baseline


def test_report_is_byte_identical_across_repeated_calls() -> None:
    team, baseline = _rows(16, team_brier=0.2, baseline_brier=0.3)

    first = _analyze(team, baseline).to_dict()
    second = _analyze(list(reversed(team)), list(reversed(baseline))).to_dict()

    assert json.dumps(first, sort_keys=True, separators=(",", ":")) == json.dumps(
        second, sort_keys=True, separators=(",", ":")
    )


def test_hand_computed_three_case_summary_and_exact_p_value() -> None:
    baseline = [_score(f"dev-{index}", brier=0.5) for index in range(3)]
    team = [
        _score("dev-0", brier=0.4),
        _score("dev-1", brier=0.3),
        _score("dev-2", brier=0.2),
    ]

    report = _analyze(team, baseline)
    summary = report.per_baseline[0]

    assert summary.wins == 3
    assert summary.ties == 0
    assert summary.losses == 0
    assert summary.mean_composite_delta == pytest.approx(0.04)
    assert summary.mean_brier_improvement == pytest.approx(0.2)
    assert summary.exact_sign_flip_p_value == pytest.approx(0.25)
    assert report.verdict == "insufficient_data"


def test_tie_epsilon_classifies_small_delta_as_tie() -> None:
    baseline = [_score("dev-0", brier=0.5)]
    team = [_score("dev-0", brier=0.5 - (TIE_EPSILON * 5 / 2))]

    summary = _analyze(team, baseline).per_baseline[0]

    assert summary.wins == 0
    assert summary.ties == 1
    assert summary.losses == 0


def test_selects_strongest_baseline_with_lexicographic_exact_tiebreak() -> None:
    team, baseline = _rows(3, team_brier=0.2, baseline_brier=0.3)
    report = analyze_scored_conditions(
        {
            "aragora-team": team,
            "openai": baseline,
            "claude": list(reversed(baseline)),
        },
        team_condition_id="aragora-team",
        scorer_contract_version=SCORER_CONTRACT_VERSION,
        holdout_case_ids=set(),
    )

    assert report.strongest_baseline_id == "claude"


@pytest.mark.parametrize("defect", ["mismatch", "duplicate", "holdout"])
def test_rejects_case_identity_defects(defect: str) -> None:
    team, baseline = _rows(2, team_brier=0.2, baseline_brier=0.3)
    holdouts: set[str] = set()
    if defect == "mismatch":
        baseline[1] = _score("different-case", brier=0.3)
    elif defect == "duplicate":
        baseline[1] = _score("dev-00", brier=0.3)
    else:
        holdouts = {"dev-01"}

    with pytest.raises(
        ValueError,
        match={
            "mismatch": "case-id set",
            "duplicate": "duplicate case_id",
            "holdout": "holdout case IDs",
        }[defect],
    ):
        _analyze(team, baseline, holdout_case_ids=holdouts)


def test_rejects_scorer_contract_mismatch() -> None:
    team, baseline = _rows(2, team_brier=0.2, baseline_brier=0.3)

    with pytest.raises(ValueError, match="scorer contract mismatch"):
        _analyze(team, baseline, scorer_contract_version="outcome-decision-quality-scorer/1.0")


def test_rejects_non_finite_scored_metric() -> None:
    team, baseline = _rows(2, team_brier=0.2, baseline_brier=0.3)
    team[0]["crux_recall"] = math.nan

    with pytest.raises(ValueError, match="crux_recall must be a finite number"):
        _analyze(team, baseline)


def test_fewer_than_sixteen_pairs_is_insufficient_data() -> None:
    team, baseline = _rows(15, team_brier=0.2, baseline_brier=0.3)

    assert _analyze(team, baseline).verdict == "insufficient_data"


def test_exact_sign_flip_matches_independent_brute_force_for_eight_pairs() -> None:
    deltas = (0.07, -0.02, 0.11, 0.04, -0.03, 0.09, 0.01, 0.06)
    observed = abs(math.fsum(deltas) / len(deltas))
    permuted = [
        abs(math.fsum(sign * delta for sign, delta in zip(signs, deltas)) / len(deltas))
        for signs in product((-1.0, 1.0), repeat=len(deltas))
    ]
    expected = sum(value + 1e-15 >= observed for value in permuted) / len(permuted)

    assert exact_paired_sign_flip_p_value(deltas) == expected


@pytest.mark.parametrize(
    ("team_brier", "baseline_brier", "expected"),
    [
        (0.2, 0.2 + MIN_ABSOLUTE_BRIER_IMPROVEMENT, "team_outperforms"),
        (0.2 + MIN_ABSOLUTE_BRIER_IMPROVEMENT, 0.2, "baseline_outperforms"),
        (0.2, 0.2, "no_difference"),
    ],
)
def test_pre_registered_verdicts(
    team_brier: float,
    baseline_brier: float,
    expected: str,
) -> None:
    team, baseline = _rows(16, team_brier=team_brier, baseline_brier=baseline_brier)

    assert _analyze(team, baseline).verdict == expected
