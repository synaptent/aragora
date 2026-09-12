"""Pure deterministic scoring for the outcome-backed decision-quality benchmark.

The benchmark runner and transport policy are intentionally outside this module.
This surface converts one already-recorded case result into the eight metrics
frozen by the benchmark manifest without performing I/O or model calls.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from aragora.evaluation.manifold_brier import brier_score

SCORER_CONTRACT_VERSION = "outcome-decision-quality-scorer/1.0"
PRIMARY_METRICS = (
    "binary_brier",
    "directional_accuracy",
    "crux_recall",
    "provenance_completeness",
    "receipt_verification_rate",
    "latency",
    "model_calls",
    "cost",
)

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def _finite_nonnegative(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite non-negative number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{field} must be a finite non-negative number")
    return result


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be an array of strings")
    return value


def _normalize_tokens(value: str) -> set[str]:
    return set(_TOKEN_PATTERN.findall(value.lower()))


def crux_recall(predicted: Sequence[str], expected: Sequence[Mapping[str, Any]]) -> float:
    """Return the fraction of preregistered cruxes covered by predicted text.

    A crux is covered when one predicted item overlaps at least 60 percent of
    the normalized tokens in its description or one of its declared aliases.
    """
    if not expected:
        return 0.0
    predicted_tokens = [_normalize_tokens(item) for item in predicted]
    hits = 0
    for index, crux in enumerate(expected):
        description = crux.get("description")
        aliases = crux.get("aliases", [])
        if (
            not isinstance(description, str)
            or not isinstance(aliases, list)
            or any(not isinstance(alias, str) for alias in aliases)
        ):
            raise ValueError(f"expected_cruxes[{index}] has invalid description or aliases")
        candidates = [description, *aliases]
        matched = False
        for candidate in candidates:
            expected_tokens = _normalize_tokens(candidate)
            if not expected_tokens:
                continue
            for observed in predicted_tokens:
                if len(expected_tokens & observed) / len(expected_tokens) >= 0.6:
                    matched = True
                    break
            if matched:
                break
        hits += int(matched)
    return hits / len(expected)


def score_case_result(
    case: Mapping[str, Any],
    outcome: Mapping[str, Any],
    output: Mapping[str, Any],
    *,
    receipt_verification: str,
    latency_ms: float,
    model_calls: int,
    cost_usd: float,
) -> dict[str, float | int]:
    """Score one result against its frozen case and outcome sidecar."""
    case_id = case.get("case_id")
    if not isinstance(case_id, str) or outcome.get("case_id") != case_id:
        raise ValueError("case and outcome identities must match")

    options = case.get("options")
    if not isinstance(options, list):
        raise ValueError("case.options must be an array")
    option_ids: list[str] = []
    for item in options:
        option_id = item.get("option_id") if isinstance(item, dict) else None
        if not isinstance(option_id, str):
            raise ValueError("every case option must have a string option_id")
        option_ids.append(option_id)
    if len(option_ids) != 2 or len(set(option_ids)) != 2:
        raise ValueError("case must define exactly two unique option IDs")

    forecast_option_id = case.get("forecast_option_id")
    correct_option_id = outcome.get("correct_option_id")
    selected_option_id = output.get("selected_option_id")
    if forecast_option_id not in option_ids or correct_option_id not in option_ids:
        raise ValueError("forecast and correct option IDs must reference case options")
    if selected_option_id not in option_ids:
        raise ValueError("selected option ID must reference a case option")

    probability = output.get("forecast_probability")
    if isinstance(probability, bool) or not isinstance(probability, (int, float)):
        raise ValueError("forecast_probability must be a finite number in [0, 1]")
    probability_value = float(probability)
    if not math.isfinite(probability_value):
        raise ValueError("forecast_probability must be a finite number in [0, 1]")

    predicted_cruxes = _string_list(output.get("cruxes"), "output.cruxes")
    expected_cruxes = outcome.get("cruxes")
    if not isinstance(expected_cruxes, list) or any(
        not isinstance(item, dict) for item in expected_cruxes
    ):
        raise ValueError("outcome.cruxes must be an array of objects")

    cited_source_ids = set(_string_list(output.get("source_ids"), "output.source_ids"))
    sources = case.get("sources")
    if not isinstance(sources, list) or any(not isinstance(item, dict) for item in sources):
        raise ValueError("case.sources must be an array of objects")
    available_source_ids: set[str] = set()
    for item in sources:
        source_id = item.get("source_id")
        if not isinstance(source_id, str):
            raise ValueError("every case source must have a string source_id")
        available_source_ids.add(source_id)
    provenance = (
        len(cited_source_ids & available_source_ids) / len(available_source_ids)
        if available_source_ids
        else 1.0
    )

    if isinstance(model_calls, bool) or not isinstance(model_calls, int) or model_calls < 0:
        raise ValueError("model_calls must be a non-negative integer")
    latency = _finite_nonnegative(latency_ms, "latency_ms")
    cost = _finite_nonnegative(cost_usd, "cost_usd")
    target = int(correct_option_id == forecast_option_id)

    return {
        "binary_brier": brier_score(probability_value, target),
        "directional_accuracy": float(selected_option_id == correct_option_id),
        "crux_recall": crux_recall(predicted_cruxes, expected_cruxes),
        "provenance_completeness": provenance,
        "receipt_verification_rate": float(receipt_verification == "verified"),
        "latency": latency,
        "model_calls": model_calls,
        "cost": cost,
    }


__all__ = [
    "PRIMARY_METRICS",
    "SCORER_CONTRACT_VERSION",
    "crux_recall",
    "score_case_result",
]
