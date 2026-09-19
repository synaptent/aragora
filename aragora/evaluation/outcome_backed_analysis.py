"""Pre-registered analysis for the outcome-backed decision-quality benchmark.

The primary comparison is the Aragora team condition against the strongest
fixed single-model baseline.  Per-case quality is the equal-weight mean of
Brier skill (``1 - binary_brier``), directional accuracy, crux recall,
provenance completeness, and receipt verification.  The strongest baseline
has the highest mean composite score; exact ties use the lexicographically
smallest condition ID.

The exact paired sign-flip test is two-sided and fully enumerates every sign
assignment for at most 16 development cases.  A result is ``team_outperforms``
or ``baseline_outperforms`` only when all 16 development pairs are present,
the exact p-value is below 0.05, the mean composite delta has the matching
sign, and the absolute mean Brier improvement is at least 0.05 in that
direction.  Otherwise the verdict is ``no_difference``; fewer than 16 pairs
is ``insufficient_data``.  Holdout case IDs are rejected by this development
analysis contract.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from itertools import product
import math
from typing import Any

from aragora.evaluation.outcome_backed_scoring import SCORER_CONTRACT_VERSION


ANALYSIS_CONTRACT_VERSION = "outcome-backed-decision-quality-analysis/1.0"
DEVELOPMENT_CASE_COUNT = 16
MAX_EXACT_CASE_COUNT = 16
TIE_EPSILON = 1e-9
P_VALUE_THRESHOLD = 0.05
MIN_ABSOLUTE_BRIER_IMPROVEMENT = 0.05
STRONGEST_BASELINE_RULE = (
    "highest mean composite score; lexicographically smallest condition_id breaks exact ties"
)

_UNIT_INTERVAL_METRICS = (
    "binary_brier",
    "directional_accuracy",
    "crux_recall",
    "provenance_completeness",
    "receipt_verification_rate",
)


@dataclass(frozen=True)
class CaseDelta:
    """One paired team-minus-baseline composite result."""

    case_id: str
    team_composite_score: float
    baseline_composite_score: float
    composite_delta: float

    def to_dict(self) -> dict[str, float | str]:
        return {
            "case_id": self.case_id,
            "team_composite_score": self.team_composite_score,
            "baseline_composite_score": self.baseline_composite_score,
            "composite_delta": self.composite_delta,
        }


@dataclass(frozen=True)
class BaselineSummary:
    """Deterministic paired summary for one baseline condition."""

    condition_id: str
    team_mean_composite_score: float
    baseline_mean_composite_score: float
    mean_composite_delta: float
    mean_brier_improvement: float
    wins: int
    ties: int
    losses: int
    exact_sign_flip_p_value: float
    case_deltas: tuple[CaseDelta, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition_id": self.condition_id,
            "team_mean_composite_score": self.team_mean_composite_score,
            "baseline_mean_composite_score": self.baseline_mean_composite_score,
            "mean_composite_delta": self.mean_composite_delta,
            "mean_brier_improvement": self.mean_brier_improvement,
            "wins": self.wins,
            "ties": self.ties,
            "losses": self.losses,
            "exact_sign_flip_p_value": self.exact_sign_flip_p_value,
            "case_deltas": [delta.to_dict() for delta in self.case_deltas],
        }


@dataclass(frozen=True)
class AnalysisReport:
    """Serializable benchmark analysis bound to scorer and analysis contracts."""

    team_condition_id: str
    n: int
    strongest_baseline_id: str
    verdict: str
    per_baseline: tuple[BaselineSummary, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_contract_version": ANALYSIS_CONTRACT_VERSION,
            "scorer_contract_version": SCORER_CONTRACT_VERSION,
            "team_condition_id": self.team_condition_id,
            "n": self.n,
            "strongest_baseline_id": self.strongest_baseline_id,
            "strongest_baseline_rule": STRONGEST_BASELINE_RULE,
            "thresholds": {
                "development_case_count": DEVELOPMENT_CASE_COUNT,
                "tie_epsilon": TIE_EPSILON,
                "p_value": P_VALUE_THRESHOLD,
                "minimum_absolute_brier_improvement": MIN_ABSOLUTE_BRIER_IMPROVEMENT,
            },
            "per_baseline": [summary.to_dict() for summary in self.per_baseline],
            "verdict": self.verdict,
        }


def _finite_unit_interval(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number between 0 and 1")
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{field} must be a finite number between 0 and 1")
    return number


def _condition_rows(
    condition_id: str,
    rows: Sequence[Mapping[str, object]],
) -> dict[str, Mapping[str, object]]:
    if not isinstance(condition_id, str) or not condition_id:
        raise ValueError("condition IDs must be non-empty strings")
    if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence):
        raise ValueError(f"condition {condition_id!r} results must be an array")

    indexed: dict[str, Mapping[str, object]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ValueError(f"condition {condition_id!r} result {index} must be an object")
        case_id = row.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError(f"condition {condition_id!r} result {index}.case_id must be non-empty")
        if case_id in indexed:
            raise ValueError(f"condition {condition_id!r} has duplicate case_id {case_id!r}")
        for metric in _UNIT_INTERVAL_METRICS:
            _finite_unit_interval(row.get(metric), f"{condition_id}.{case_id}.{metric}")
        indexed[case_id] = row
    if not indexed:
        raise ValueError(f"condition {condition_id!r} must contain at least one result")
    return indexed


def composite_score(row: Mapping[str, object]) -> float:
    """Return the pre-registered equal-weight quality composite for one score row."""

    brier_skill = 1.0 - _finite_unit_interval(row.get("binary_brier"), "binary_brier")
    components = [brier_skill]
    components.extend(
        _finite_unit_interval(row.get(metric), metric)
        for metric in _UNIT_INTERVAL_METRICS
        if metric != "binary_brier"
    )
    return math.fsum(components) / len(components)


def exact_paired_sign_flip_p_value(deltas: Sequence[float]) -> float:
    """Return the exact two-sided paired sign-flip permutation p-value."""

    if not deltas:
        raise ValueError("at least one paired delta is required")
    if len(deltas) > MAX_EXACT_CASE_COUNT:
        raise ValueError(f"exact sign-flip analysis supports at most {MAX_EXACT_CASE_COUNT} cases")
    normalized: list[float] = []
    for index, delta in enumerate(deltas):
        if isinstance(delta, bool) or not isinstance(delta, (int, float)):
            raise ValueError(f"deltas[{index}] must be finite")
        number = float(delta)
        if not math.isfinite(number):
            raise ValueError(f"deltas[{index}] must be finite")
        normalized.append(number)

    observed = abs(math.fsum(normalized) / len(normalized))
    extreme = 0
    assignments = 0
    for signs in product((-1.0, 1.0), repeat=len(normalized)):
        permuted = abs(math.fsum(sign * delta for sign, delta in zip(signs, normalized)))
        permuted /= len(normalized)
        if permuted + 1e-15 >= observed:
            extreme += 1
        assignments += 1
    return extreme / assignments


def _mean(values: Sequence[float]) -> float:
    return math.fsum(values) / len(values)


def _summarize_baseline(
    condition_id: str,
    case_ids: Sequence[str],
    team_rows: Mapping[str, Mapping[str, object]],
    baseline_rows: Mapping[str, Mapping[str, object]],
) -> BaselineSummary:
    case_deltas: list[CaseDelta] = []
    brier_improvements: list[float] = []
    for case_id in case_ids:
        team_score = composite_score(team_rows[case_id])
        baseline_score = composite_score(baseline_rows[case_id])
        case_deltas.append(
            CaseDelta(
                case_id=case_id,
                team_composite_score=team_score,
                baseline_composite_score=baseline_score,
                composite_delta=team_score - baseline_score,
            )
        )
        team_brier = _finite_unit_interval(team_rows[case_id]["binary_brier"], "binary_brier")
        baseline_brier = _finite_unit_interval(
            baseline_rows[case_id]["binary_brier"], "binary_brier"
        )
        brier_improvements.append(baseline_brier - team_brier)

    deltas = tuple(delta.composite_delta for delta in case_deltas)
    wins = sum(delta > TIE_EPSILON for delta in deltas)
    losses = sum(delta < -TIE_EPSILON for delta in deltas)
    ties = len(deltas) - wins - losses
    team_scores = tuple(delta.team_composite_score for delta in case_deltas)
    baseline_scores = tuple(delta.baseline_composite_score for delta in case_deltas)
    return BaselineSummary(
        condition_id=condition_id,
        team_mean_composite_score=_mean(team_scores),
        baseline_mean_composite_score=_mean(baseline_scores),
        mean_composite_delta=_mean(deltas),
        mean_brier_improvement=_mean(brier_improvements),
        wins=wins,
        ties=ties,
        losses=losses,
        exact_sign_flip_p_value=exact_paired_sign_flip_p_value(deltas),
        case_deltas=tuple(case_deltas),
    )


def _verdict(strongest: BaselineSummary, n: int) -> str:
    if n < DEVELOPMENT_CASE_COUNT:
        return "insufficient_data"
    if (
        strongest.exact_sign_flip_p_value < P_VALUE_THRESHOLD
        and strongest.mean_composite_delta > TIE_EPSILON
        and strongest.mean_brier_improvement >= MIN_ABSOLUTE_BRIER_IMPROVEMENT - TIE_EPSILON
    ):
        return "team_outperforms"
    if (
        strongest.exact_sign_flip_p_value < P_VALUE_THRESHOLD
        and strongest.mean_composite_delta < -TIE_EPSILON
        and strongest.mean_brier_improvement <= -MIN_ABSOLUTE_BRIER_IMPROVEMENT + TIE_EPSILON
    ):
        return "baseline_outperforms"
    return "no_difference"


def analyze_scored_conditions(
    condition_results: Mapping[str, Sequence[Mapping[str, object]]],
    *,
    team_condition_id: str,
    scorer_contract_version: str,
    holdout_case_ids: Collection[str],
) -> AnalysisReport:
    """Analyze scored development results for team and fixed baseline conditions."""

    if scorer_contract_version != SCORER_CONTRACT_VERSION:
        raise ValueError(
            "scorer contract mismatch: "
            f"expected {SCORER_CONTRACT_VERSION!r}, got {scorer_contract_version!r}"
        )
    if not isinstance(condition_results, Mapping):
        raise ValueError("condition_results must be an object")
    if team_condition_id not in condition_results:
        raise ValueError("team_condition_id must reference a condition")
    if len(condition_results) < 2:
        raise ValueError("analysis requires one team and at least one baseline condition")

    indexed = {
        condition_id: _condition_rows(condition_id, rows)
        for condition_id, rows in condition_results.items()
    }
    team_case_ids = set(indexed[team_condition_id])
    if len(team_case_ids) > MAX_EXACT_CASE_COUNT:
        raise ValueError(f"analysis supports at most {MAX_EXACT_CASE_COUNT} development cases")
    for condition_id, rows in indexed.items():
        if set(rows) != team_case_ids:
            raise ValueError(
                f"condition {condition_id!r} case-id set does not match team condition"
            )

    if isinstance(holdout_case_ids, (str, bytes)) or any(
        not isinstance(case_id, str) or not case_id for case_id in holdout_case_ids
    ):
        raise ValueError("holdout_case_ids must contain non-empty strings")
    holdouts = set(holdout_case_ids)
    leaked_holdouts = sorted(team_case_ids & holdouts)
    if leaked_holdouts:
        raise ValueError("holdout case IDs are not allowed: " + ", ".join(leaked_holdouts))

    case_ids = tuple(sorted(team_case_ids))
    summaries = tuple(
        _summarize_baseline(
            condition_id,
            case_ids,
            indexed[team_condition_id],
            indexed[condition_id],
        )
        for condition_id in sorted(indexed)
        if condition_id != team_condition_id
    )
    strongest = min(
        summaries,
        key=lambda summary: (-summary.baseline_mean_composite_score, summary.condition_id),
    )
    return AnalysisReport(
        team_condition_id=team_condition_id,
        n=len(case_ids),
        strongest_baseline_id=strongest.condition_id,
        verdict=_verdict(strongest, len(case_ids)),
        per_baseline=summaries,
    )


__all__ = [
    "ANALYSIS_CONTRACT_VERSION",
    "AnalysisReport",
    "BaselineSummary",
    "CaseDelta",
    "DEVELOPMENT_CASE_COUNT",
    "MIN_ABSOLUTE_BRIER_IMPROVEMENT",
    "P_VALUE_THRESHOLD",
    "STRONGEST_BASELINE_RULE",
    "TIE_EPSILON",
    "analyze_scored_conditions",
    "composite_score",
    "exact_paired_sign_flip_p_value",
]
