from __future__ import annotations

import math
from typing import Any

import pytest

from aragora.evaluation.outcome_backed_scoring import (
    MAX_PREDICTED_CRUX_CHARS,
    crux_recall,
    score_case_result,
)


def _case() -> dict[str, object]:
    return {
        "case_id": "software-development-001",
        "forecast_option_id": "ship",
        "options": [
            {"option_id": "ship", "label": "Ship"},
            {"option_id": "wait", "label": "Wait"},
        ],
        "sources": [
            {"source_id": "release-notes"},
            {"source_id": "incident-log"},
        ],
    }


def _outcome() -> dict[str, object]:
    return {
        "case_id": "software-development-001",
        "correct_option_id": "ship",
        "cruxes": [
            {
                "crux_id": "compatibility",
                "description": "backward compatibility remains intact",
                "aliases": ["no breaking API change"],
            },
            {
                "crux_id": "reliability",
                "description": "error rate remains below the release threshold",
                "aliases": ["low production error rate"],
            },
            {
                "crux_id": "rollback",
                "description": "rollback procedure is tested and available",
                "aliases": ["tested rollback path"],
            },
        ],
    }


def _output() -> dict[str, object]:
    return {
        "selected_option_id": "ship",
        "forecast_probability": 0.8,
        "cruxes": [
            "No breaking API change was observed.",
            "The production error rate is low.",
            "A tested rollback path is available.",
        ],
        "source_ids": ["release-notes", "incident-log"],
    }


def _score(**overrides: object) -> dict[str, float | int | str]:
    kwargs: dict[str, object] = {
        "receipt_verification": "verified",
        "latency_ms": 1250,
        "model_calls": 3,
        "cost_usd": 0.42,
    }
    kwargs.update(overrides)
    return score_case_result(_case(), _outcome(), _output(), **kwargs)  # type: ignore[arg-type]


def test_scores_complete_case_deterministically() -> None:
    expected = {
        "case_id": "software-development-001",
        "binary_brier": pytest.approx(0.04),
        "directional_accuracy": 1.0,
        "crux_recall": 1.0,
        "provenance_completeness": 1.0,
        "receipt_verification_rate": 1.0,
        "latency_ms": 1250.0,
        "model_calls": 3,
        "cost_usd": 0.42,
    }

    assert _score() == expected
    assert _score() == expected


def test_scores_incorrect_forecast_direction_and_partial_provenance() -> None:
    outcome = _outcome()
    outcome["correct_option_id"] = "wait"
    output = _output()
    output["selected_option_id"] = "ship"
    output["source_ids"] = ["release-notes"]

    score = score_case_result(
        _case(),
        outcome,
        output,
        receipt_verification="failed",
        latency_ms=10,
        model_calls=1,
        cost_usd=0,
    )

    assert score["binary_brier"] == pytest.approx(0.64)
    assert score["directional_accuracy"] == 0.0
    assert score["provenance_completeness"] == 0.5
    assert score["receipt_verification_rate"] == 0.0


@pytest.mark.parametrize("probability", [-0.01, 1.01, math.nan, math.inf, True, "0.8"])
def test_rejects_invalid_forecast_probability(probability: object) -> None:
    output = _output()
    output["forecast_probability"] = probability

    with pytest.raises(ValueError, match="forecast_probability"):
        score_case_result(
            _case(),
            _outcome(),
            output,
            receipt_verification="verified",
            latency_ms=1,
            model_calls=1,
            cost_usd=0,
        )


@pytest.mark.parametrize(
    "cruxes",
    [
        ["one", "two"],
        ["one", "two", "three", "four", "five", "six"],
        ["one", "two", ""],
        ["same", "SAME", "different"],
        ["one", "two", "!?!"],
        ["one", "two", "x" * (MAX_PREDICTED_CRUX_CHARS + 1)],
    ],
)
def test_rejects_unbounded_or_malformed_predicted_cruxes(cruxes: list[str]) -> None:
    output = _output()
    output["cruxes"] = cruxes

    with pytest.raises(ValueError, match="output.cruxes"):
        score_case_result(
            _case(),
            _outcome(),
            output,
            receipt_verification="verified",
            latency_ms=1,
            model_calls=1,
            cost_usd=0,
        )


def test_one_predicted_crux_cannot_satisfy_multiple_expected_cruxes() -> None:
    expected = [
        {"description": "database migration rollback", "aliases": []},
        {"description": "database migration verification", "aliases": []},
        {"description": "customer notification delivery", "aliases": []},
    ]
    predicted = [
        "database migration rollback verification",
        "unrelated capacity planning",
        "unrelated support staffing",
    ]

    assert crux_recall(predicted, expected) == pytest.approx(1 / 3)


@pytest.mark.parametrize(
    ("source_ids", "message"),
    [
        (["release-notes", "release-notes"], "duplicates"),
        (["unknown"], "unknown IDs"),
        ("release-notes", "array of strings"),
    ],
)
def test_rejects_invalid_source_identity(source_ids: object, message: str) -> None:
    output = _output()
    output["source_ids"] = source_ids

    with pytest.raises(ValueError, match=message):
        score_case_result(
            _case(),
            _outcome(),
            output,
            receipt_verification="verified",
            latency_ms=1,
            model_calls=1,
            cost_usd=0,
        )


def test_allows_empty_citations_as_zero_completeness() -> None:
    output = _output()
    output["source_ids"] = []

    score = score_case_result(
        _case(),
        _outcome(),
        output,
        receipt_verification="missing",
        latency_ms=1,
        model_calls=1,
        cost_usd=0,
    )

    assert score["provenance_completeness"] == 0.0
    assert score["receipt_verification_rate"] == 0.0


def test_rejects_case_outcome_identity_mismatch() -> None:
    outcome = _outcome()
    outcome["case_id"] = "different-case"

    with pytest.raises(ValueError, match="identities must match"):
        score_case_result(
            _case(),
            outcome,
            _output(),
            receipt_verification="verified",
            latency_ms=1,
            model_calls=1,
            cost_usd=0,
        )


def test_rejects_non_object_result_input() -> None:
    invalid_output: Any = []
    with pytest.raises(ValueError, match="output must be an object"):
        score_case_result(
            _case(),
            _outcome(),
            invalid_output,
            receipt_verification="verified",
            latency_ms=1,
            model_calls=1,
            cost_usd=0,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("receipt_verification", "unknown", "receipt_verification"),
        ("latency_ms", -1, "latency_ms"),
        ("latency_ms", math.inf, "latency_ms"),
        ("model_calls", -1, "model_calls"),
        ("model_calls", True, "model_calls"),
        ("cost_usd", -0.01, "cost_usd"),
        ("cost_usd", math.nan, "cost_usd"),
    ],
)
def test_rejects_invalid_execution_metrics(field: str, value: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _score(**{field: value})
