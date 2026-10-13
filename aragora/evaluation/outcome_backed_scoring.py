"""Deterministic scoring for the outcome-backed decision-quality benchmark.

This module is deliberately transport- and runner-independent. It scores one
already-recorded result against one validated corpus case and its outcome
sidecar without performing I/O or model calls.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
import re
from typing import Any

from aragora.evaluation.manifold_brier import brier_score


SCORER_CONTRACT_VERSION = "outcome-backed-decision-quality-scorer/1.0"
MIN_PREDICTED_CRUXES = 3
MAX_PREDICTED_CRUXES = 5
MAX_PREDICTED_CRUX_CHARS = 500
CRUX_TOKEN_RECALL_THRESHOLD = 0.6
RECEIPT_VERIFICATION_STATES = frozenset({"verified", "failed", "missing"})

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def _finite_number(
    value: Any,
    field: str,
    *,
    minimum: float = 0.0,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise ValueError(f"{field} must be a finite number >= {minimum}")
    if maximum is not None and result > maximum:
        raise ValueError(f"{field} must be a finite number <= {maximum}")
    return result


def _string_ids(value: Any, field: str, *, allow_empty: bool) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array of strings")
    if not allow_empty and not value:
        raise ValueError(f"{field} must not be empty")
    items: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise ValueError(f"{field}[{index}] must be a non-empty string")
        items.append(item)
    if len(set(items)) != len(items):
        raise ValueError(f"{field} must not contain duplicates")
    return tuple(items)


def _predicted_cruxes(value: Any) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError("output.cruxes must be an array of strings")
    if not MIN_PREDICTED_CRUXES <= len(value) <= MAX_PREDICTED_CRUXES:
        raise ValueError(
            f"output.cruxes must contain {MIN_PREDICTED_CRUXES} to {MAX_PREDICTED_CRUXES} items"
        )
    items: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"output.cruxes[{index}] must be a non-empty string")
        normalized = item.strip()
        if len(normalized) > MAX_PREDICTED_CRUX_CHARS:
            raise ValueError(
                f"output.cruxes[{index}] exceeds {MAX_PREDICTED_CRUX_CHARS} characters"
            )
        if not _TOKEN_PATTERN.search(normalized.lower()):
            raise ValueError(f"output.cruxes[{index}] must contain a word or number")
        items.append(normalized)
    if len({item.casefold() for item in items}) != len(items):
        raise ValueError("output.cruxes must not contain duplicates")
    return tuple(items)


def _normalize_tokens(value: str) -> frozenset[str]:
    return frozenset(_TOKEN_PATTERN.findall(value.lower()))


def _expected_crux_candidates(
    expected: Sequence[Mapping[str, Any]],
) -> tuple[tuple[frozenset[str], ...], ...]:
    if not MIN_PREDICTED_CRUXES <= len(expected) <= MAX_PREDICTED_CRUXES:
        raise ValueError(
            f"outcome.cruxes must contain {MIN_PREDICTED_CRUXES} to {MAX_PREDICTED_CRUXES} items"
        )
    result: list[tuple[frozenset[str], ...]] = []
    for index, crux in enumerate(expected):
        if not isinstance(crux, Mapping):
            raise ValueError(f"outcome.cruxes[{index}] must be an object")
        description = crux.get("description")
        aliases = crux.get("aliases")
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f"outcome.cruxes[{index}].description must be non-empty")
        if not isinstance(aliases, list) or any(
            not isinstance(alias, str) or not alias.strip() for alias in aliases
        ):
            raise ValueError(f"outcome.cruxes[{index}].aliases must be an array of strings")
        candidates = tuple(
            tokens for text in (description, *aliases) if (tokens := _normalize_tokens(text))
        )
        if not candidates:
            raise ValueError(f"outcome.cruxes[{index}] has no scoreable text")
        result.append(candidates)
    return tuple(result)


def _maximum_matching(edges: Sequence[Sequence[int]], expected_count: int) -> int:
    """Return maximum one-to-one matches between predicted and expected cruxes."""

    matched_prediction_by_expected = [-1] * expected_count

    def assign(prediction_index: int, seen: set[int]) -> bool:
        for expected_index in edges[prediction_index]:
            if expected_index in seen:
                continue
            seen.add(expected_index)
            previous = matched_prediction_by_expected[expected_index]
            if previous == -1 or assign(previous, seen):
                matched_prediction_by_expected[expected_index] = prediction_index
                return True
        return False

    return sum(assign(index, set()) for index in range(len(edges)))


def crux_recall(predicted: Sequence[str], expected: Sequence[Mapping[str, Any]]) -> float:
    """Score preregistered crux recall with deterministic one-to-one matching.

    A predicted crux matches an expected crux when it covers at least 60% of
    the normalized tokens in the expected description or one declared alias.
    One predicted item can satisfy at most one expected crux.
    """

    predicted_items = _predicted_cruxes(predicted)
    expected_candidates = _expected_crux_candidates(expected)
    predicted_tokens = tuple(_normalize_tokens(item) for item in predicted_items)
    edges: list[list[int]] = []
    for observed in predicted_tokens:
        matches: list[int] = []
        for expected_index, candidates in enumerate(expected_candidates):
            if any(
                len(candidate & observed) / len(candidate) >= CRUX_TOKEN_RECALL_THRESHOLD
                for candidate in candidates
            ):
                matches.append(expected_index)
        edges.append(matches)
    return _maximum_matching(edges, len(expected_candidates)) / len(expected_candidates)


def _option_ids(case: Mapping[str, Any]) -> tuple[str, str]:
    options = case.get("options")
    if not isinstance(options, list) or len(options) != 2:
        raise ValueError("case.options must contain exactly two options")
    ids: list[str] = []
    for index, item in enumerate(options):
        option_id = item.get("option_id") if isinstance(item, Mapping) else None
        if not isinstance(option_id, str) or not option_id:
            raise ValueError(f"case.options[{index}].option_id must be a non-empty string")
        ids.append(option_id)
    if len(set(ids)) != 2:
        raise ValueError("case option IDs must be unique")
    return ids[0], ids[1]


def _available_source_ids(case: Mapping[str, Any]) -> tuple[str, ...]:
    sources = case.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("case.sources must be a non-empty array")
    ids: list[str] = []
    for index, source in enumerate(sources):
        source_id = source.get("source_id") if isinstance(source, Mapping) else None
        if not isinstance(source_id, str) or not source_id:
            raise ValueError(f"case.sources[{index}].source_id must be a non-empty string")
        ids.append(source_id)
    if len(set(ids)) != len(ids):
        raise ValueError("case source IDs must be unique")
    return tuple(ids)


def score_case_result(
    case: Mapping[str, Any],
    outcome: Mapping[str, Any],
    output: Mapping[str, Any],
    *,
    receipt_verification: str,
    latency_ms: float,
    model_calls: int,
    cost_usd: float,
) -> dict[str, float | int | str]:
    """Score one completed benchmark result against its frozen ground truth."""

    for field, value in (("case", case), ("outcome", outcome), ("output", output)):
        if not isinstance(value, Mapping):
            raise ValueError(f"{field} must be an object")

    case_id = case.get("case_id")
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("case.case_id must be a non-empty string")
    if outcome.get("case_id") != case_id:
        raise ValueError("case and outcome identities must match")

    option_ids = _option_ids(case)
    forecast_option_id = case.get("forecast_option_id")
    correct_option_id = outcome.get("correct_option_id")
    selected_option_id = output.get("selected_option_id")
    if forecast_option_id not in option_ids:
        raise ValueError("case.forecast_option_id must reference a case option")
    if correct_option_id not in option_ids:
        raise ValueError("outcome.correct_option_id must reference a case option")
    if selected_option_id not in option_ids:
        raise ValueError("output.selected_option_id must reference a case option")

    probability = _finite_number(
        output.get("forecast_probability"),
        "output.forecast_probability",
        maximum=1.0,
    )
    predicted_cruxes = _predicted_cruxes(output.get("cruxes"))
    expected_cruxes = outcome.get("cruxes")
    if not isinstance(expected_cruxes, list):
        raise ValueError("outcome.cruxes must be an array")

    cited_source_ids = _string_ids(output.get("source_ids"), "output.source_ids", allow_empty=True)
    available_source_ids = _available_source_ids(case)
    unknown_sources = sorted(set(cited_source_ids) - set(available_source_ids))
    if unknown_sources:
        raise ValueError(f"output.source_ids contains unknown IDs: {', '.join(unknown_sources)}")

    if receipt_verification not in RECEIPT_VERIFICATION_STATES:
        raise ValueError(
            "receipt_verification must be one of " + ", ".join(sorted(RECEIPT_VERIFICATION_STATES))
        )
    if isinstance(model_calls, bool) or not isinstance(model_calls, int) or model_calls < 0:
        raise ValueError("model_calls must be a non-negative integer")
    latency = _finite_number(latency_ms, "latency_ms")
    cost = _finite_number(cost_usd, "cost_usd")

    target = int(correct_option_id == forecast_option_id)
    return {
        "case_id": case_id,
        "binary_brier": brier_score(probability, target),
        "directional_accuracy": float(selected_option_id == correct_option_id),
        "crux_recall": crux_recall(predicted_cruxes, expected_cruxes),
        "provenance_completeness": len(cited_source_ids) / len(available_source_ids),
        "receipt_verification_rate": float(receipt_verification == "verified"),
        "latency_ms": latency,
        "model_calls": model_calls,
        "cost_usd": cost,
    }


__all__ = [
    "CRUX_TOKEN_RECALL_THRESHOLD",
    "MAX_PREDICTED_CRUXES",
    "MAX_PREDICTED_CRUX_CHARS",
    "MIN_PREDICTED_CRUXES",
    "RECEIPT_VERIFICATION_STATES",
    "SCORER_CONTRACT_VERSION",
    "crux_recall",
    "score_case_result",
]
