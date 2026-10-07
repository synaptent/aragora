"""VIAH operator-truth status document generator (AGT-06 / #6067, SD-5).

Generates a Markdown status report mirroring ``docs/status/B0_BENCHMARK_TRUTH_STATUS.md``.
Gate: ``ARAGORA_VIAH_TREND_ENABLED``.

Out of scope: writing to disk (caller decides), historical persistence (SD-4 / PR #7133),
sidecar signals from AGT-05 (default 0 until wired).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from aragora.evaluation.viah import (
    VIAH_TREND_FLAG,
    ViahLedger,
    ViahLedgerEntry,
    compute_viah,
    rolling_viah_trend,
    viah_trend_enabled,
)

__all__ = ["generate_viah_status_report"]


def generate_viah_status_report(
    ledger: ViahLedger[ViahLedgerEntry],
    *,
    weeks: int = 4,
    now: Optional[datetime] = None,
) -> str:
    """Generate a Markdown VIAH status report.

    Raises RuntimeError when ARAGORA_VIAH_TREND_ENABLED is not set.
    """
    if not viah_trend_enabled():
        raise RuntimeError(f"VIAH status surface is disabled; set {VIAH_TREND_FLAG}=1 to enable")
    ref = (now or datetime.now(UTC)).astimezone(UTC)
    trend = rolling_viah_trend(ledger=ledger, weeks=weeks, now=ref)
    report = compute_viah(ledger=ledger, window_hours=168.0, now=ref)
    ts = ref.strftime("%Y-%m-%dT%H:%M:%SZ")
    viah_str = f"{report.viah:.4f}" if report.viah is not None else "N/A (no agent-hours)"
    coef = report.coefficients

    lines: list[str] = [
        "# VIAH Status",
        "",
        f"Last updated: {ts}",
        "",
        "Operator-truth surface for Verifiable Improvements per Agent-Hour (VIAH). "
        "See `docs/plans/AGENT_CIVILIZATION_SUBSTRATE.md` §4 and "
        "issue [#6067](https://github.com/synaptent/aragora/issues/6067).",
        "",
        "## Summary",
        "",
        f"- **Current window VIAH (7 d):** {viah_str}",
        f"- **Rolling trend ({trend.weeks_requested} w):** {trend.trend_direction}",
        f"- **Agent-hours in window:** {report.agent_hours:.2f} h",
        f"- **Merged autonomous PRs (7 d):** {report.merged_autonomous_prs}",
        f"- **Rescues required (7 d):** {report.rescues_required}",
        "",
        "## Rolling Trend",
        "",
        "| Week | Window start | Window end | VIAH | PRs merged | Agent-hours |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for pt in trend.points:
        vc = f"{pt.viah:.4f}" if pt.viah is not None else "—"
        label = (
            f"W{pt.week_index} (current)"
            if pt.week_index == trend.weeks_requested - 1
            else f"W{pt.week_index}"
        )
        lines.append(
            f"| {label} | {pt.window_start[:10]} | {pt.window_end[:10]}"
            f" | {vc} | {pt.merged_autonomous_prs} | {pt.agent_hours:.2f} h |"
        )
    lines += [
        "",
        "## Signal Breakdown (Most Recent 7-Day Window)",
        "",
        "| Signal | Count | Weight | Contribution |",
        "| --- | --- | --- | --- |",
        f"| Merged autonomous PRs | {report.merged_autonomous_prs} | +{coef.merged_pr_weight} | {coef.merged_pr_weight * report.merged_autonomous_prs:+.2f} |",
        f"| Cruxes correctly detected \\* | {report.cruxes_correctly_detected} | +{coef.crux_weight} | {coef.crux_weight * report.cruxes_correctly_detected:+.2f} |",
        f"| Predictions above Brier threshold \\* | {report.predictions_above_brier_threshold} | +{coef.prediction_weight} | {coef.prediction_weight * report.predictions_above_brier_threshold:+.2f} |",
        f"| Rescues required | {report.rescues_required} | -{coef.rescue_weight} | {-coef.rescue_weight * report.rescues_required:+.2f} |",
        f"| Failed claims promoted without repair | {report.failed_claims_promoted_without_repair} | -{coef.failed_claim_weight} | {-coef.failed_claim_weight * report.failed_claims_promoted_without_repair:+.2f} |",
        "",
        "_\\* Sidecar signal: defaults to 0 until AGT-05 settlement is live._",
        "",
        "## Caveats",
        "",
        "- VIAH **supplements** (does not replace) the TW-02 no-rescue success rate.",
        "- Crux-correctness and prediction-Brier sidecar signals are wired by AGT-05 "
        "and default to 0 until that path is live.",
        "- Historical trend persistence requires AGT-06 SD-4 "
        "(PR [#7133](https://github.com/synaptent/aragora/pull/7133)); "
        "trend is computed on-the-fly from live ShiftLedger entries.",
        f"- Gate: `{VIAH_TREND_FLAG}=1` required; default OFF.",
        "- No live queue effect; report-only.",
        "",
    ]
    return "\n".join(lines)
