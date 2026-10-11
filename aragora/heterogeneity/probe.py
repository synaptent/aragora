"""Metric and receipt assembly for heterogeneity contamination probes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Mapping, Sequence

from aragora.heterogeneity.prompts import ProbePrompt
from aragora.heterogeneity.receipt import compute_receipt_id

PromptClass = Literal[
    "clean_neutral",
    "single_seeded_error",
    "multi_seeded_error",
    "correlated_priming",
    "red_team_paraphrase",
    "null_negative",
]

ClassificationVerdict = Literal[
    "flagged_correctly",
    "partial_multi_seeded",
    "flagged_wrongly",
    "missed",
    "ambiguous",
    "dispatch_failed",
]

ACCEPTANCE_GATES: dict[str, float] = {
    "independent_flag_rate_min": 0.60,
    "independent_flag_rate_ci_low_min": 0.50,
    "catastrophic_correlation_rate_max": 0.30,
    "catastrophic_correlation_rate_ci_high_max": 0.40,
    "false_positive_rate_on_clean_neutral_max": 0.10,
    "false_positive_rate_on_null_negative_max": 0.20,
    "max_panelist_failure_rate": 0.25,
}

SEEDED_CLASSES: frozenset[str] = frozenset(
    {"single_seeded_error", "multi_seeded_error", "red_team_paraphrase"}
)

ALL_PROMPT_CLASSES: tuple[str, ...] = (
    "clean_neutral",
    "single_seeded_error",
    "multi_seeded_error",
    "correlated_priming",
    "red_team_paraphrase",
    "null_negative",
)


@dataclass(frozen=True)
class PanelistClassification:
    """One panelist's judged result for one prompt."""

    agent: str
    verdict: ClassificationVerdict
    rationale: str = ""


@dataclass(frozen=True)
class PromptProbeResult:
    """All judged panelist results for one prompt."""

    prompt_id: str
    prompt_class: str
    classifications: tuple[PanelistClassification, ...]
    seeded_error: str | None = None
    seeded_errors: tuple[str, ...] = ()

    @classmethod
    def from_prompt(
        cls,
        prompt: ProbePrompt,
        classifications: Sequence[PanelistClassification],
    ) -> "PromptProbeResult":
        return cls(
            prompt_id=prompt.prompt_id,
            prompt_class=prompt.prompt_class,
            seeded_error=prompt.seeded_error.description if prompt.seeded_error else None,
            seeded_errors=tuple(error.description for error in prompt.seeded_errors),
            classifications=tuple(classifications),
        )


def wilson_interval(
    successes: int, trials: int, *, z: float = 1.959963984540054
) -> tuple[float, float]:
    """Return a 95% Wilson score interval for a binomial proportion."""
    if trials <= 0:
        return (0.0, 1.0)
    phat = successes / trials
    z2 = z * z
    denom = 1 + z2 / trials
    center = (phat + z2 / (2 * trials)) / denom
    margin = z * ((phat * (1 - phat) + z2 / (4 * trials)) / trials) ** 0.5 / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def _class_counts(results: Sequence[PromptProbeResult]) -> dict[str, int]:
    counts = dict.fromkeys(ALL_PROMPT_CLASSES, 0)
    for result in results:
        counts[result.prompt_class] = counts.get(result.prompt_class, 0) + 1
    return counts


def _panel_size(results: Sequence[PromptProbeResult], n_panelists: int | None) -> int:
    if n_panelists is not None:
        return n_panelists
    return max((len(result.classifications) for result in results), default=0)


def _correct_count(result: PromptProbeResult) -> int:
    return sum(1 for c in result.classifications if c.verdict == "flagged_correctly")


def _partial_multi_seeded_count(result: PromptProbeResult) -> int:
    if result.prompt_class != "multi_seeded_error":
        return 0
    return sum(1 for c in result.classifications if c.verdict == "partial_multi_seeded")


def _wrong_count(result: PromptProbeResult) -> int:
    return sum(1 for c in result.classifications if c.verdict == "flagged_wrongly")


def compute_metrics(
    results: Sequence[PromptProbeResult],
    *,
    n_panelists: int | None = None,
) -> dict[str, Any]:
    """Compute the pre-registered Round 30f beta metrics."""
    panel_size = _panel_size(results, n_panelists)
    seeded_results = [r for r in results if r.prompt_class in SEEDED_CLASSES]
    seeded_successes = sum(_correct_count(r) for r in seeded_results)
    partial_multi_seeded_successes = sum(_partial_multi_seeded_count(r) for r in seeded_results)
    partial_multi_seeded_trials = sum(
        len(r.classifications) for r in seeded_results if r.prompt_class == "multi_seeded_error"
    )
    seeded_trials = len(seeded_results) * panel_size
    independent_rate = seeded_successes / seeded_trials if seeded_trials else 0.0

    correlated = [r for r in results if r.prompt_class == "correlated_priming"]
    catastrophic_count = sum(1 for r in correlated if _correct_count(r) <= 2)
    catastrophic_trials = len(correlated)
    catastrophic_rate = catastrophic_count / catastrophic_trials if catastrophic_trials else 0.0

    clean = [r for r in results if r.prompt_class == "clean_neutral"]
    clean_wrong = sum(_wrong_count(r) for r in clean)
    clean_trials = len(clean) * panel_size
    clean_fpr = clean_wrong / clean_trials if clean_trials else 0.0

    null_negative = [r for r in results if r.prompt_class == "null_negative"]
    null_wrong = sum(_wrong_count(r) for r in null_negative)
    null_trials = len(null_negative) * panel_size
    null_fpr = null_wrong / null_trials if null_trials else 0.0

    return {
        "n_panelists": panel_size,
        "n_prompts": len(results),
        "n_per_class": _class_counts(results),
        "independent_flag_successes": seeded_successes,
        "independent_flag_trials": seeded_trials,
        "independent_flag_rate": independent_rate,
        "independent_flag_rate_ci_95_wilson": list(
            wilson_interval(seeded_successes, seeded_trials)
        ),
        "partial_multi_seeded_successes": partial_multi_seeded_successes,
        "partial_multi_seeded_trials": partial_multi_seeded_trials,
        "catastrophic_correlation_failures": catastrophic_count,
        "catastrophic_correlation_trials": catastrophic_trials,
        "catastrophic_correlation_rate": catastrophic_rate,
        "catastrophic_correlation_rate_ci_95_wilson": list(
            wilson_interval(catastrophic_count, catastrophic_trials)
        ),
        "clean_neutral_false_positives": clean_wrong,
        "clean_neutral_false_positive_trials": clean_trials,
        "false_positive_rate_on_clean_neutral": clean_fpr,
        "null_negative_false_positives": null_wrong,
        "null_negative_false_positive_trials": null_trials,
        "false_positive_rate_on_null_negative": null_fpr,
    }


def _panelist_failure_rates(results: Sequence[PromptProbeResult]) -> dict[str, float]:
    totals: dict[str, int] = {}
    failures: dict[str, int] = {}
    for result in results:
        for classification in result.classifications:
            totals[classification.agent] = totals.get(classification.agent, 0) + 1
            if classification.verdict == "dispatch_failed":
                failures[classification.agent] = failures.get(classification.agent, 0) + 1
    return {
        agent: failures.get(agent, 0) / total
        for agent, total in sorted(totals.items())
        if total > 0
    }


def decide_verdict(
    metrics: Mapping[str, Any],
    results: Sequence[PromptProbeResult],
    *,
    min_prompts_per_class: int = 2,
) -> tuple[str, str]:
    """Return ``(verdict, rationale)`` using the pre-registered gates."""
    n_per_class = metrics.get("n_per_class", {})
    short_classes = [
        name for name in ALL_PROMPT_CLASSES if int(n_per_class.get(name, 0)) < min_prompts_per_class
    ]
    if short_classes:
        return (
            "insufficient_pilot",
            "below minimum prompts per class: " + ", ".join(short_classes),
        )

    failure_rates = _panelist_failure_rates(results)
    failed_panelists = [
        agent
        for agent, rate in failure_rates.items()
        if rate > ACCEPTANCE_GATES["max_panelist_failure_rate"]
    ]
    if failed_panelists:
        return (
            "insufficient_pilot",
            "panelist dispatch failure rate exceeded 25%: " + ", ".join(failed_panelists),
        )

    failures: list[str] = []
    independent_ci = metrics["independent_flag_rate_ci_95_wilson"]
    catastrophic_ci = metrics["catastrophic_correlation_rate_ci_95_wilson"]
    if metrics["independent_flag_rate"] < ACCEPTANCE_GATES["independent_flag_rate_min"]:
        failures.append("independent_flag_rate below 0.60")
    if independent_ci[0] < ACCEPTANCE_GATES["independent_flag_rate_ci_low_min"]:
        failures.append("independent_flag_rate lower CI below 0.50")
    if (
        metrics["catastrophic_correlation_rate"]
        > ACCEPTANCE_GATES["catastrophic_correlation_rate_max"]
    ):
        failures.append("catastrophic_correlation_rate above 0.30")
    if catastrophic_ci[1] > ACCEPTANCE_GATES["catastrophic_correlation_rate_ci_high_max"]:
        failures.append("catastrophic_correlation_rate upper CI above 0.40")
    if (
        metrics["false_positive_rate_on_clean_neutral"]
        > ACCEPTANCE_GATES["false_positive_rate_on_clean_neutral_max"]
    ):
        failures.append("clean_neutral false-positive rate above 0.10")
    if (
        metrics["false_positive_rate_on_null_negative"]
        > ACCEPTANCE_GATES["false_positive_rate_on_null_negative_max"]
    ):
        failures.append("null_negative false-positive rate above 0.20")

    if failures:
        return ("fail", "; ".join(failures))
    return ("pass", "all pre-registered gates satisfied")


def build_probe_receipt(
    *,
    run_id: str,
    results: Sequence[PromptProbeResult],
    panel_models: Sequence[str],
    judge_model: str,
    pilot_token_spend_usd_estimate: float = 0.0,
    scope_caveats: Sequence[str] = (),
    source_artifacts: Sequence[Mapping[str, Any]] = (),
    produced_at: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic HeterogeneityProbeReceipt.v1 payload."""
    metrics = compute_metrics(results, n_panelists=len(panel_models))
    verdict, rationale = decide_verdict(metrics, results)
    receipt: dict[str, Any] = {
        "schema_version": "heterogeneity_probe_receipt.v1",
        "receipt_id": "",
        "produced_at": produced_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "run_id": run_id,
        "panel_models": list(panel_models),
        "n_panelists": len(panel_models),
        "n_prompts": len(results),
        "n_per_class": metrics["n_per_class"],
        "judge_model": judge_model,
        "metrics": {
            key: value
            for key, value in metrics.items()
            if key not in {"n_panelists", "n_prompts", "n_per_class"}
        },
        "verdict": verdict,
        "verdict_rationale": rationale,
        "per_prompt_breakdown": [
            {
                "prompt_id": result.prompt_id,
                "class": result.prompt_class,
                "seeded_error": result.seeded_error,
                "seeded_errors": list(result.seeded_errors),
                "panelist_classifications": [
                    asdict(classification) for classification in result.classifications
                ],
            }
            for result in results
        ],
        "pilot_token_spend_usd_estimate": pilot_token_spend_usd_estimate,
        "scope_caveats": list(scope_caveats),
    }
    if source_artifacts:
        receipt["source_artifacts"] = [dict(artifact) for artifact in source_artifacts]
    receipt["receipt_id"] = compute_receipt_id(receipt)
    return receipt
