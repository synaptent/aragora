"""Deterministic final reporting for outcome-backed decision quality.

This contract is intentionally frozen before benchmark inference begins.  It
maps the pre-registered development and holdout analysis results, paid-call
budget custody, and holdout exposure custody to exactly one public verdict:
``go``, ``conditional_go``, or ``no_go``.

Malformed or version-mismatched inputs raise ``ValueError``.  Valid negative
evidence does not: a baseline win, budget breach, unsettled reservation, or
holdout custody violation deterministically worsens the result to ``no_go``.
That distinction keeps data-integrity failures fail-closed while preserving an
honest benchmark outcome.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
import math
import re

from aragora.evaluation.outcome_backed_analysis import (
    ANALYSIS_CONTRACT_VERSION,
    AnalysisPhase,
    classify_analysis_verdict,
)
from aragora.evaluation.outcome_backed_budget import (
    BUDGET_LEDGER_SCHEMA,
    DAILY_BUDGET_CAP_USD,
)
from aragora.evaluation.outcome_backed_corpus import BENCHMARK_ID, SPLIT_COUNTS
from aragora.evaluation.outcome_backed_holdout import (
    HOLDOUT_CONTRACT_VERSION,
    MAX_HOLDOUT_EXPOSURES,
)
from aragora.evaluation.outcome_backed_scoring import SCORER_CONTRACT_VERSION


REPORT_CONTRACT_VERSION = "outcome-backed-decision-quality-report/1.0"
MIN_REQUIRED_HOLDOUT_EXPOSURES = 2

_ANALYSIS_VERDICTS = frozenset(
    {"team_outperforms", "baseline_outperforms", "no_difference", "insufficient_data"}
)
_FINAL_VERDICTS = frozenset({"go", "conditional_go", "no_go"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field} must be an integer >= {minimum}")
    return value


def _finite_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be a finite number")
    return number


def _money(value: object, field: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite non-negative USD amount")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{field} must be a finite non-negative USD amount") from None
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"{field} must be a finite non-negative USD amount")
    return amount


def _money_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _normalized_summary_number(summary: Mapping[str, object], field: str) -> float:
    return _finite_number(summary.get(field), f"normalized_summary.{field}")


def _analysis_report(
    report: Mapping[str, object],
    *,
    phase: AnalysisPhase,
    expected_count: int,
) -> dict[str, object]:
    if not isinstance(report, Mapping):
        raise ValueError(f"{phase}_report must be an object")
    if report.get("analysis_contract_version") != ANALYSIS_CONTRACT_VERSION:
        raise ValueError(f"{phase}_report analysis contract version mismatch")
    if report.get("scorer_contract_version") != SCORER_CONTRACT_VERSION:
        raise ValueError(f"{phase}_report scorer contract version mismatch")
    if report.get("phase") != phase:
        raise ValueError(f"{phase}_report phase mismatch")

    n = _integer(report.get("n"), f"{phase}_report.n", minimum=1)
    if n != expected_count:
        raise ValueError(f"{phase}_report.n must equal {expected_count}")
    team_condition_id = _required_text(
        report.get("team_condition_id"), f"{phase}_report.team_condition_id"
    )
    strongest_baseline_id = _required_text(
        report.get("strongest_baseline_id"), f"{phase}_report.strongest_baseline_id"
    )
    verdict = report.get("verdict")
    if verdict not in _ANALYSIS_VERDICTS:
        raise ValueError(f"{phase}_report.verdict is not recognized")

    raw_summaries = report.get("per_baseline")
    if (
        isinstance(raw_summaries, (str, bytes))
        or not isinstance(raw_summaries, Sequence)
        or not raw_summaries
    ):
        raise ValueError(f"{phase}_report.per_baseline must be a non-empty array")
    summaries: list[dict[str, object]] = []
    condition_ids: set[str] = set()
    for index, raw_summary in enumerate(raw_summaries):
        if not isinstance(raw_summary, Mapping):
            raise ValueError(f"{phase}_report.per_baseline[{index}] must be an object")
        prefix = f"{phase}_report.per_baseline[{index}]"
        condition_id = _required_text(raw_summary.get("condition_id"), f"{prefix}.condition_id")
        if condition_id in condition_ids:
            raise ValueError(f"{phase}_report has duplicate baseline {condition_id!r}")
        condition_ids.add(condition_id)
        p_value = _finite_number(
            raw_summary.get("exact_sign_flip_p_value"),
            f"{prefix}.exact_sign_flip_p_value",
        )
        team_mean = _finite_number(
            raw_summary.get("team_mean_composite_score"),
            f"{prefix}.team_mean_composite_score",
        )
        baseline_mean = _finite_number(
            raw_summary.get("baseline_mean_composite_score"),
            f"{prefix}.baseline_mean_composite_score",
        )
        mean_delta = _finite_number(
            raw_summary.get("mean_composite_delta"), f"{prefix}.mean_composite_delta"
        )
        if not math.isclose(team_mean - baseline_mean, mean_delta, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError(f"{prefix}.mean_composite_delta does not match the reported means")
        summary = {
            "condition_id": condition_id,
            "team_mean_composite_score": team_mean,
            "baseline_mean_composite_score": baseline_mean,
            "mean_composite_delta": mean_delta,
            "mean_brier_improvement": _finite_number(
                raw_summary.get("mean_brier_improvement"),
                f"{prefix}.mean_brier_improvement",
            ),
            "exact_sign_flip_p_value": p_value,
        }
        if not 0.0 <= p_value <= 1.0:
            raise ValueError(f"{prefix}.exact_sign_flip_p_value must be between 0 and 1")
        summaries.append(summary)
    if strongest_baseline_id not in condition_ids:
        raise ValueError(f"{phase}_report strongest baseline is missing from per_baseline")

    computed_strongest = min(
        summaries,
        key=lambda summary: (
            -_normalized_summary_number(summary, "baseline_mean_composite_score"),
            str(summary["condition_id"]),
        ),
    )
    if strongest_baseline_id != computed_strongest["condition_id"]:
        raise ValueError(f"{phase}_report strongest baseline does not match its metrics")
    computed_verdict = classify_analysis_verdict(
        phase=phase,
        n=n,
        mean_composite_delta=_normalized_summary_number(computed_strongest, "mean_composite_delta"),
        mean_brier_improvement=_normalized_summary_number(
            computed_strongest, "mean_brier_improvement"
        ),
        exact_sign_flip_p_value=_normalized_summary_number(
            computed_strongest, "exact_sign_flip_p_value"
        ),
    )
    if verdict != computed_verdict:
        raise ValueError(f"{phase}_report verdict does not match its strongest-baseline metrics")

    return {
        "phase": phase,
        "n": n,
        "team_condition_id": team_condition_id,
        "strongest_baseline_id": strongest_baseline_id,
        "verdict": verdict,
        "per_baseline": sorted(summaries, key=lambda item: str(item["condition_id"])),
    }


def _budget_documents(
    snapshots: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    if isinstance(snapshots, (str, bytes)) or not isinstance(snapshots, Sequence):
        raise ValueError("budget_snapshots must be an array")
    if not snapshots:
        raise ValueError("budget_snapshots must contain at least one UTC day")

    documents: list[dict[str, object]] = []
    seen_dates: set[str] = set()
    for index, snapshot in enumerate(snapshots):
        if not isinstance(snapshot, Mapping):
            raise ValueError(f"budget_snapshots[{index}] must be an object")
        prefix = f"budget_snapshots[{index}]"
        utc_date = _required_text(snapshot.get("utc_date"), f"{prefix}.utc_date")
        try:
            date.fromisoformat(utc_date)
        except ValueError:
            raise ValueError(f"{prefix}.utc_date must be YYYY-MM-DD") from None
        if utc_date in seen_dates:
            raise ValueError(f"budget_snapshots has duplicate UTC date {utc_date}")
        seen_dates.add(utc_date)

        cap = _money(snapshot.get("cap_usd"), f"{prefix}.cap_usd")
        if cap != DAILY_BUDGET_CAP_USD:
            raise ValueError(
                f"{prefix}.cap_usd must equal the frozen ${_money_text(DAILY_BUDGET_CAP_USD)} cap"
            )
        settled = _money(snapshot.get("settled_usd"), f"{prefix}.settled_usd")
        reserved = _money(snapshot.get("reserved_usd"), f"{prefix}.reserved_usd")
        committed = _money(snapshot.get("committed_usd"), f"{prefix}.committed_usd")
        remaining = _money(snapshot.get("remaining_usd"), f"{prefix}.remaining_usd")
        if committed != settled + reserved:
            raise ValueError(f"{prefix}.committed_usd does not equal settled plus reserved")
        if remaining != max(Decimal("0"), cap - committed):
            raise ValueError(f"{prefix}.remaining_usd is inconsistent with committed spend")
        open_reservations = _integer(
            snapshot.get("open_reservations"), f"{prefix}.open_reservations"
        )
        event_count = _integer(snapshot.get("event_count"), f"{prefix}.event_count")
        exceeded = snapshot.get("exceeded")
        if not isinstance(exceeded, bool):
            raise ValueError(f"{prefix}.exceeded must be a boolean")
        if exceeded != (committed > cap):
            raise ValueError(f"{prefix}.exceeded is inconsistent with committed spend")
        documents.append(
            {
                "utc_date": utc_date,
                "cap_usd": _money_text(cap),
                "settled_usd": _money_text(settled),
                "reserved_usd": _money_text(reserved),
                "committed_usd": _money_text(committed),
                "remaining_usd": _money_text(remaining),
                "open_reservations": open_reservations,
                "event_count": event_count,
                "exceeded": exceeded,
            }
        )
    return tuple(sorted(documents, key=lambda item: str(item["utc_date"])))


def _holdout_document(snapshot: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(snapshot, Mapping):
        raise ValueError("holdout_snapshot must be an object")
    if snapshot.get("holdout_contract_version") != HOLDOUT_CONTRACT_VERSION:
        raise ValueError("holdout_snapshot contract version mismatch")
    max_exposures = _integer(
        snapshot.get("max_exposures_per_registry"),
        "holdout_snapshot.max_exposures_per_registry",
        minimum=1,
    )
    if max_exposures != MAX_HOLDOUT_EXPOSURES:
        raise ValueError("holdout_snapshot exposure limit mismatch")
    event_count = _integer(snapshot.get("event_count"), "holdout_snapshot.event_count")
    raw_registries = snapshot.get("registries")
    if (
        isinstance(raw_registries, (str, bytes))
        or not isinstance(raw_registries, Sequence)
        or len(raw_registries) != 1
    ):
        raise ValueError("holdout_snapshot must contain exactly one frozen registry")

    raw_registry = raw_registries[0]
    if not isinstance(raw_registry, Mapping):
        raise ValueError("holdout_snapshot.registries[0] must be an object")
    registry_hash = raw_registry.get("registry_hash")
    if not isinstance(registry_hash, str) or not _SHA256_RE.fullmatch(registry_hash):
        raise ValueError("holdout_snapshot registry hash must be lowercase SHA-256")
    exposure_count = _integer(raw_registry.get("exposure_count"), "holdout_snapshot.exposure_count")
    remaining_exposures = _integer(
        raw_registry.get("remaining_exposures"), "holdout_snapshot.remaining_exposures"
    )
    expected_remaining = max(0, max_exposures - exposure_count)
    if remaining_exposures != expected_remaining:
        raise ValueError("holdout_snapshot remaining exposures are inconsistent")
    raw_labels = raw_registry.get("run_labels")
    if isinstance(raw_labels, (str, bytes)) or not isinstance(raw_labels, Sequence):
        raise ValueError("holdout_snapshot run_labels must be an array")
    run_labels = tuple(
        _required_text(label, f"holdout_snapshot.run_labels[{index}]")
        for index, label in enumerate(raw_labels)
    )
    if len(run_labels) != exposure_count or len(set(run_labels)) != len(run_labels):
        raise ValueError("holdout_snapshot run_labels must uniquely match exposure_count")
    if event_count != exposure_count:
        raise ValueError(
            "holdout_snapshot event_count must match the frozen registry exposure count"
        )
    return {
        "holdout_contract_version": HOLDOUT_CONTRACT_VERSION,
        "max_exposures_per_registry": max_exposures,
        "event_count": event_count,
        "registries": [
            {
                "registry_hash": registry_hash,
                "exposure_count": exposure_count,
                "remaining_exposures": remaining_exposures,
                "run_labels": sorted(run_labels),
            }
        ],
    }


def _budget_is_clean(snapshots: Sequence[Mapping[str, object]]) -> bool:
    for index, snapshot in enumerate(snapshots):
        open_reservations = _integer(
            snapshot.get("open_reservations"), f"budget_snapshots[{index}].open_reservations"
        )
        committed = _money(
            snapshot.get("committed_usd"), f"budget_snapshots[{index}].committed_usd"
        )
        if bool(snapshot.get("exceeded")) or committed > DAILY_BUDGET_CAP_USD:
            return False
        if open_reservations:
            return False
    return True


def _single_registry(snapshot: Mapping[str, object]) -> Mapping[str, object]:
    registries = snapshot.get("registries")
    if not isinstance(registries, list) or len(registries) != 1:
        raise ValueError("normalized holdout snapshot must contain one registry")
    registry = registries[0]
    if not isinstance(registry, Mapping):
        raise ValueError("normalized holdout registry must be an object")
    return registry


def _holdout_custody_is_clean(snapshot: Mapping[str, object]) -> bool:
    registry = _single_registry(snapshot)
    exposure_count = _integer(registry.get("exposure_count"), "holdout_snapshot.exposure_count")
    return MIN_REQUIRED_HOLDOUT_EXPOSURES <= exposure_count <= MAX_HOLDOUT_EXPOSURES


def _validated_inputs(
    development_report: Mapping[str, object],
    holdout_report: Mapping[str, object],
    budget_snapshots: Sequence[Mapping[str, object]],
    holdout_snapshot: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, object], tuple[dict[str, object], ...], dict[str, object]]:
    development = _analysis_report(
        development_report,
        phase="development",
        expected_count=SPLIT_COUNTS["development"],
    )
    holdout = _analysis_report(
        holdout_report,
        phase="holdout",
        expected_count=SPLIT_COUNTS["holdout"],
    )
    budgets = _budget_documents(budget_snapshots)
    custody = _holdout_document(holdout_snapshot)
    return development, holdout, budgets, custody


def final_verdict(
    development_report: Mapping[str, object],
    holdout_report: Mapping[str, object],
    budget_snapshots: Sequence[Mapping[str, object]],
    holdout_snapshot: Mapping[str, object],
) -> str:
    """Return the frozen final benchmark verdict.

    ``go`` requires the team to outperform in both the complete development
    and holdout analyses with settled, under-cap budget custody and two or
    three recorded holdout exposures.  ``conditional_go`` requires a
    development win and a complete but statistically unconfirmed holdout
    result (``no_difference``) under the same custody gates.  Every baseline
    win, inconclusive development result, budget
    violation, or holdout custody violation returns ``no_go``.

    Missing, malformed, or version-mismatched inputs raise ``ValueError``.
    """

    development, holdout, budgets, custody = _validated_inputs(
        development_report,
        holdout_report,
        budget_snapshots,
        holdout_snapshot,
    )
    if not _budget_is_clean(budgets) or not _holdout_custody_is_clean(custody):
        return "no_go"
    if development["verdict"] != "team_outperforms":
        return "no_go"
    if holdout["verdict"] == "team_outperforms":
        return "go"
    if holdout["verdict"] == "no_difference":
        return "conditional_go"
    return "no_go"


def _strongest_summary(report: Mapping[str, object]) -> Mapping[str, object]:
    strongest = report["strongest_baseline_id"]
    summaries = report.get("per_baseline")
    if not isinstance(summaries, list):
        raise ValueError("normalized analysis report must contain baseline summaries")
    for summary in summaries:
        if isinstance(summary, Mapping) and summary.get("condition_id") == strongest:
            return summary
    raise ValueError("normalized analysis report is missing its strongest baseline")


def _format_metric(value: object) -> str:
    return format(_finite_number(value, "report metric"), ".6f")


def _verdict_reasons(
    development: Mapping[str, object],
    holdout: Mapping[str, object],
    budgets: Sequence[Mapping[str, object]],
    custody: Mapping[str, object],
) -> tuple[str, ...]:
    reasons = [
        f"Development analysis: `{development['verdict']}`.",
        f"Holdout analysis: `{holdout['verdict']}`.",
        "Budget custody: `clean`." if _budget_is_clean(budgets) else "Budget custody: `violated`.",
        (
            "Holdout custody: `clean`."
            if _holdout_custody_is_clean(custody)
            else "Holdout custody: `violated or incomplete`."
        ),
    ]
    return tuple(reasons)


def render_report(
    development_report: Mapping[str, object],
    holdout_report: Mapping[str, object],
    budget_snapshots: Sequence[Mapping[str, object]],
    holdout_snapshot: Mapping[str, object],
) -> str:
    """Render byte-deterministic Markdown for the final benchmark report."""

    development, holdout, budgets, custody = _validated_inputs(
        development_report,
        holdout_report,
        budget_snapshots,
        holdout_snapshot,
    )
    verdict = final_verdict(development_report, holdout_report, budget_snapshots, holdout_snapshot)
    if verdict not in _FINAL_VERDICTS:  # pragma: no cover - defensive contract assertion
        raise ValueError("final verdict is not recognized")
    development_summary = _strongest_summary(development)
    holdout_summary = _strongest_summary(holdout)
    registry = _single_registry(custody)
    run_labels = registry.get("run_labels")
    if not isinstance(run_labels, list):
        raise ValueError("normalized holdout registry must contain run labels")

    lines = [
        "# Decision Quality Delta Benchmark Report",
        "",
        "## 1. Benchmark Contract",
        "",
        f"- Benchmark ID: `{BENCHMARK_ID}`",
        f"- Report contract: `{REPORT_CONTRACT_VERSION}`",
        f"- Analysis contract: `{ANALYSIS_CONTRACT_VERSION}`",
        f"- Scorer contract: `{SCORER_CONTRACT_VERSION}`",
        f"- Budget ledger schema: `{BUDGET_LEDGER_SCHEMA}`",
        f"- Holdout contract: `{HOLDOUT_CONTRACT_VERSION}`",
        "",
        "## 2. Benchmark Statement",
        "",
        "Same frozen cases and evidence compare fixed single-model baselines with the "
        "Aragora team; outcomes are scored without result-dependent threshold changes.",
        "",
        "## 3. Condition Summary",
        "",
        "| Phase | Cases | Team condition | Strongest single baseline | Analysis verdict |",
        "|---|---:|---|---|---|",
        (
            f"| Development | {development['n']} | `{development['team_condition_id']}` | "
            f"`{development['strongest_baseline_id']}` | `{development['verdict']}` |"
        ),
        (
            f"| Holdout | {holdout['n']} | `{holdout['team_condition_id']}` | "
            f"`{holdout['strongest_baseline_id']}` | `{holdout['verdict']}` |"
        ),
        "",
        "## 4. Primary Metrics",
        "",
        "| Phase | Team composite | Best-single composite | Composite delta | "
        "Brier improvement | Exact p-value |",
        "|---|---:|---:|---:|---:|---:|",
        (
            f"| Development | {_format_metric(development_summary['team_mean_composite_score'])} | "
            f"{_format_metric(development_summary['baseline_mean_composite_score'])} | "
            f"{_format_metric(development_summary['mean_composite_delta'])} | "
            f"{_format_metric(development_summary['mean_brier_improvement'])} | "
            f"{_format_metric(development_summary['exact_sign_flip_p_value'])} |"
        ),
        (
            f"| Holdout | {_format_metric(holdout_summary['team_mean_composite_score'])} | "
            f"{_format_metric(holdout_summary['baseline_mean_composite_score'])} | "
            f"{_format_metric(holdout_summary['mean_composite_delta'])} | "
            f"{_format_metric(holdout_summary['mean_brier_improvement'])} | "
            f"{_format_metric(holdout_summary['exact_sign_flip_p_value'])} |"
        ),
        "",
        "The frozen absolute Brier-improvement target is `>= 0.05`; uncertainty is "
        "descriptive and this corpus does not justify a broad significance claim.",
        "",
        "## 5. Cost and Custody",
        "",
        "| UTC date | Settled USD | Reserved USD | Committed USD | Cap USD | Open reservations | Status |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for snapshot in budgets:
        status = "violation" if snapshot["exceeded"] or snapshot["open_reservations"] else "clean"
        lines.append(
            f"| {snapshot['utc_date']} | {snapshot['settled_usd']} | {snapshot['reserved_usd']} | "
            f"{snapshot['committed_usd']} | {snapshot['cap_usd']} | "
            f"{snapshot['open_reservations']} | {status} |"
        )
    lines.extend(
        [
            "",
            "| Holdout registry | Exposures | Remaining | Run labels | Custody |",
            "|---|---:|---:|---|---|",
            (
                f"| `{registry['registry_hash']}` | {registry['exposure_count']} | "
                f"{registry['remaining_exposures']} | "
                f"{', '.join(f'`{label}`' for label in run_labels)} | "
                f"{'clean' if _holdout_custody_is_clean(custody) else 'violation or incomplete'} |"
            ),
            "",
            "## 6. Interpretation",
            "",
        ]
    )
    lines.extend(
        f"- {reason}" for reason in _verdict_reasons(development, holdout, budgets, custody)
    )
    lines.extend(
        [
            "",
            "## 7. Gate Decision",
            "",
            f"`{verdict}`",
            "",
            "This verdict is produced mechanically from the frozen contracts above. "
            "It is not a claim of statistical significance and does not erase recorded failures.",
            "",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "MIN_REQUIRED_HOLDOUT_EXPOSURES",
    "REPORT_CONTRACT_VERSION",
    "final_verdict",
    "render_report",
]
