from __future__ import annotations

import math

import pytest

from aragora.evaluation.outcome_decision_quality import (
    PRIMARY_METRICS,
    SCORER_CONTRACT_VERSION,
    crux_recall,
    score_case_result,
)


def _case() -> dict[str, object]:
    return {
        "case_id": "case-1",
        "forecast_option_id": "ship",
        "options": [
            {"option_id": "ship", "label": "Ship"},
            {"option_id": "wait", "label": "Wait"},
        ],
        "sources": [
            {"source_id": "source-a"},
            {"source_id": "source-b"},
        ],
    }


def _outcome() -> dict[str, object]:
    return {
        "case_id": "case-1",
        "correct_option_id": "ship",
        "cruxes": [
            {
                "description": "Whether the published schedule remains credible",
                "aliases": ["schedule credibility"],
            },
            {
                "description": "Whether a replacement implementation is ready",
                "aliases": ["replacement readiness"],
            },
        ],
    }


def _output() -> dict[str, object]:
    return {
        "selected_option_id": "ship",
        "forecast_probability": 0.75,
        "cruxes": ["schedule credibility remains uncertain"],
        "source_ids": ["source-a"],
        "rationale": "Bounded rationale.",
    }


def test_scorer_contract_matches_all_frozen_primary_metrics() -> None:
    assert SCORER_CONTRACT_VERSION == "outcome-decision-quality-scorer/1.0"
    assert PRIMARY_METRICS == (
        "binary_brier",
        "directional_accuracy",
        "crux_recall",
        "provenance_completeness",
        "receipt_verification_rate",
        "latency",
        "model_calls",
        "cost",
    )


def test_score_case_result_is_deterministic_for_all_primary_metrics() -> None:
    first = score_case_result(
        _case(),
        _outcome(),
        _output(),
        receipt_verification="verified",
        latency_ms=125.0,
        model_calls=3,
        cost_usd=0.25,
    )
    second = score_case_result(
        _case(),
        _outcome(),
        _output(),
        receipt_verification="verified",
        latency_ms=125.0,
        model_calls=3,
        cost_usd=0.25,
    )

    assert first == second
    assert tuple(first) == PRIMARY_METRICS
    assert first == {
        "binary_brier": 0.0625,
        "directional_accuracy": 1.0,
        "crux_recall": 0.5,
        "provenance_completeness": 0.5,
        "receipt_verification_rate": 1.0,
        "latency": 125.0,
        "model_calls": 3,
        "cost": 0.25,
    }


def test_brier_target_tracks_the_declared_forecast_option() -> None:
    outcome = _outcome()
    outcome["correct_option_id"] = "wait"
    result = score_case_result(
        _case(),
        outcome,
        _output() | {"selected_option_id": "wait"},
        receipt_verification="failed",
        latency_ms=0,
        model_calls=1,
        cost_usd=0,
    )

    assert result["binary_brier"] == 0.75**2
    assert result["directional_accuracy"] == 1.0
    assert result["receipt_verification_rate"] == 0.0


def test_crux_recall_is_order_independent() -> None:
    expected = _outcome()["cruxes"]
    assert isinstance(expected, list)
    forward = crux_recall(["replacement readiness", "schedule credibility"], expected)
    reverse = crux_recall(["schedule credibility", "replacement readiness"], expected)
    assert forward == reverse == 1.0


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("forecast_probability", math.nan, "forecast_probability"),
        ("forecast_probability", math.inf, "forecast_probability"),
        ("forecast_probability", True, "forecast_probability"),
        ("selected_option_id", "unknown", "selected option"),
    ],
)
def test_score_case_result_rejects_invalid_output(field: str, value: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        score_case_result(
            _case(),
            _outcome(),
            _output() | {field: value},
            receipt_verification="verified",
            latency_ms=1,
            model_calls=1,
            cost_usd=0,
        )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"latency_ms": -1}, "latency_ms"),
        ({"latency_ms": math.inf}, "latency_ms"),
        ({"model_calls": True}, "model_calls"),
        ({"cost_usd": math.nan}, "cost_usd"),
    ],
)
def test_score_case_result_rejects_invalid_operational_metrics(
    kwargs: dict[str, object], message: str
) -> None:
    parameters: dict[str, object] = {
        "receipt_verification": "verified",
        "latency_ms": 1,
        "model_calls": 1,
        "cost_usd": 0,
    }
    parameters.update(kwargs)
    with pytest.raises(ValueError, match=message):
        score_case_result(_case(), _outcome(), _output(), **parameters)  # type: ignore[arg-type]
