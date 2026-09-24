"""Characterization of ``_validate_inspection_fields`` (receipt inspect display guard).

These tests pin the observable contract of the validator: which inputs it
accepts, the exact ``ValueError`` message for every invalid class it
distinguishes, the order in which fields are checked (first error wins), and
the absence of side effects. They were written against the original
implementation and must keep passing unchanged after any restructuring.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from aragora.cli.commands.receipt import _validate_inspection_fields, cmd_receipt_inspect


def _full_valid_receipt() -> dict[str, Any]:
    return {
        "receipt_id": "r-1",
        "verdict": "APPROVED",
        "confidence": 0.75,
        "robustness_score": 1,
        "risk_summary": {
            "critical": 0,
            "high": 1.0,
            "medium": "2",
            "low": " 3 ",
            "total": "1e400",
            "unchecked": object(),
        },
        "consensus_proof": {
            "reached": True,
            "method": "majority",
            "supporting_agents": ["a", "b"],
            "dissenting_agents": [],
        },
        "agent_responses": [
            {"agent_name": "a", "content": "hello"},
            {"agent_name": "b"},
        ],
        "cost_summary": {"total_usd": 0.1},
        "config_used": {
            "rounds": 3,
            "critique_summaries": [
                {"critic": "a", "issues": ["x"]},
                {"critic": "b"},
            ],
        },
        "dissenting_views": ["view", 1, None],
    }


def _expect(data: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError) as excinfo:
        _validate_inspection_fields(data)
    assert str(excinfo.value) == message


# ---------------------------------------------------------------------------
# Valid inputs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "data",
    [
        {},
        _full_valid_receipt(),
        {"verdict": "REJECTED", "confidence": 0, "robustness_score": 0.0},
        {"confidence": -1, "robustness_score": 1e306},
        {"risk_summary": None, "consensus_proof": None, "agent_responses": None},
        {"cost_summary": None, "dissenting_views": None},
        {"risk_summary": {}, "consensus_proof": {}, "config_used": {}},
        {"consensus_proof": {"supporting_agents": None, "dissenting_agents": None}},
        {"consensus_proof": {"reached": None}},
        {"config_used": {"critique_summaries": None}},
        {"config_used": {"critique_summaries": []}},
        {"config_used": {"critique_summaries": [{}]}},
        {"agent_responses": []},
        {"agent_responses": [{}]},
        {"dissenting_views": []},
        {"dissenting_views": [1, {"nested": True}]},
        {"unknown_top_level": object()},
    ],
    ids=[
        "empty",
        "full",
        "zero-scores",
        "negative-and-large-scores",
        "nullable-dicts-and-lists",
        "nullable-cost-and-views",
        "empty-containers-skip-inner-checks",
        "nullable-agent-lists",
        "reached-none",
        "critiques-none",
        "critiques-empty",
        "critique-without-issues",
        "responses-empty",
        "response-without-content",
        "views-empty",
        "views-elements-unchecked",
        "unknown-keys-ignored",
    ],
)
def test_valid_inputs_return_none(data: dict[str, Any]) -> None:
    assert _validate_inspection_fields(data) is None


@pytest.mark.parametrize(
    "value",
    [0, 1, -7, 10**30, 2.5, 0.0, -1.5, "0", "3", "-2", "2.5", " 4 ", "\n\t2\r", "1e400", "1E5"],
)
def test_risk_count_accepts_ints_finite_floats_and_numeric_strings(value: Any) -> None:
    for field in ("critical", "high", "medium", "low", "total"):
        assert _validate_inspection_fields({"risk_summary": {field: value}}) is None


@pytest.mark.parametrize("value", [True, False, 1, 0, 2, -1, 1.5, "true", "0", "YES", " off ", ""])
def test_consensus_reached_accepts_recognized_booleans(value: Any) -> None:
    assert _validate_inspection_fields({"consensus_proof": {"reached": value}}) is None


# ---------------------------------------------------------------------------
# Distinguished invalid classes and their exact messages
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, 1, 1.0, True, ["APPROVED"], {"verdict": "x"}, b"x"])
def test_verdict_must_be_str(value: Any) -> None:
    _expect({"verdict": value}, "verdict must be str")


@pytest.mark.parametrize("field", ["confidence", "robustness_score"])
@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        "0.5",
        "",
        [],
        {},
        Decimal("0.5"),
        float("inf"),
        float("-inf"),
        float("nan"),
        10**400,
    ],
    ids=[
        "none",
        "true",
        "false",
        "numeric-string",
        "empty-string",
        "list",
        "dict",
        "decimal",
        "inf",
        "-inf",
        "nan",
        "int-too-large-for-float",
    ],
)
def test_scores_must_be_finite_numbers(field: str, value: Any) -> None:
    _expect({field: value}, f"{field} must be a finite number")


@pytest.mark.parametrize("field", ["confidence", "robustness_score"])
@pytest.mark.parametrize("value", [1e307, -1e307, 1.7e308])
def test_scores_must_survive_percentage_scaling(field: str, value: Any) -> None:
    assert math.isfinite(value)
    _expect({field: value}, f"{field} cannot be displayed as a finite percentage")


@pytest.mark.parametrize("value", [1, "x", [], [("high", 1)], True, 0.5])
def test_risk_summary_must_be_dict(value: Any) -> None:
    _expect({"risk_summary": value}, "risk_summary must be dict")


@pytest.mark.parametrize("field", ["critical", "high", "medium", "low", "total"])
@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        float("inf"),
        float("-inf"),
        float("nan"),
        "",
        "abc",
        "nan",
        "inf",
        "-Infinity",
        "0x10",
        "1,000",
        [1],
        {"n": 1},
        Decimal("1"),
        b"1",
    ],
    ids=[
        "none",
        "true",
        "false",
        "inf",
        "-inf",
        "nan",
        "empty-string",
        "alpha-string",
        "nan-string",
        "inf-string",
        "-infinity-string",
        "hex-string",
        "comma-string",
        "list",
        "dict",
        "decimal",
        "bytes",
    ],
)
def test_risk_counts_must_be_finite_numbers(field: str, value: Any) -> None:
    _expect({"risk_summary": {field: value}}, f"risk_summary.{field} must be a finite number")


def test_risk_summary_unknown_keys_are_not_validated() -> None:
    assert _validate_inspection_fields({"risk_summary": {"other": "abc", "notes": None}}) is None


@pytest.mark.parametrize("value", [1, "x", [], True])
def test_consensus_proof_must_be_dict(value: Any) -> None:
    _expect({"consensus_proof": value}, "consensus_proof must be dict")


@pytest.mark.parametrize(
    "value",
    ["maybe", "2", [], {}, [True], float("nan"), float("inf"), object()],
    ids=["alpha", "numeric-string", "list", "dict", "list-bool", "nan", "inf", "object"],
)
def test_consensus_reached_rejects_unrecognized_booleans(value: Any) -> None:
    _expect(
        {"consensus_proof": {"reached": value}},
        "consensus_proof.reached is not a recognized boolean",
    )


@pytest.mark.parametrize("field", ["supporting_agents", "dissenting_agents"])
@pytest.mark.parametrize("value", ["a", 1, {"a": 1}, ("a",), True])
def test_agent_lists_must_be_list(field: str, value: Any) -> None:
    _expect({"consensus_proof": {field: value}}, f"consensus_proof.{field} must be list")


@pytest.mark.parametrize("field", ["supporting_agents", "dissenting_agents"])
@pytest.mark.parametrize("value", [None, 1, 1.0, True, [], {}, b"a"])
def test_agent_entries_must_be_str(field: str, value: Any) -> None:
    _expect(
        {"consensus_proof": {field: ["ok", value]}},
        f"consensus_proof.{field}[1] must be str",
    )


@pytest.mark.parametrize("value", ["a", 1, {"a": 1}, ({},), True])
def test_agent_responses_must_be_list(value: Any) -> None:
    _expect({"agent_responses": value}, "agent_responses must be list")


@pytest.mark.parametrize("value", [None, 1, "x", [], True])
def test_agent_response_entries_must_be_dict(value: Any) -> None:
    _expect({"agent_responses": [{}, {}, value]}, "agent_responses[2] must be dict")


@pytest.mark.parametrize("value", [None, 1, 1.0, True, [], {}, b"x"])
def test_agent_response_content_must_be_str(value: Any) -> None:
    _expect({"agent_responses": [{"content": value}]}, "agent_responses[0].content must be str")


@pytest.mark.parametrize("value", [1, "x", [], True, 0.0])
def test_cost_summary_must_be_dict(value: Any) -> None:
    _expect({"cost_summary": value}, "cost_summary must be dict")


@pytest.mark.parametrize("value", [None, 1, "x", [], True])
def test_config_used_is_not_nullable(value: Any) -> None:
    _expect({"config_used": value}, "config_used must be dict")


@pytest.mark.parametrize("value", ["a", 1, {"a": 1}, ({},), True])
def test_critique_summaries_must_be_list(value: Any) -> None:
    _expect(
        {"config_used": {"critique_summaries": value}},
        "config_used.critique_summaries must be list",
    )


@pytest.mark.parametrize("value", [None, 1, "x", [], True])
def test_critique_entries_must_be_dict(value: Any) -> None:
    _expect(
        {"config_used": {"critique_summaries": [{}, value]}},
        "config_used.critique_summaries[1] must be dict",
    )


@pytest.mark.parametrize("value", [None, 1, "x", {}, ("a",), True])
def test_critique_issues_must_be_list(value: Any) -> None:
    _expect(
        {"config_used": {"critique_summaries": [{"issues": value}]}},
        "config_used.critique_summaries[0].issues must be list",
    )


@pytest.mark.parametrize("value", ["a", 1, {"a": 1}, ("a",), True])
def test_dissenting_views_must_be_list(value: Any) -> None:
    _expect({"dissenting_views": value}, "dissenting_views must be list")


# ---------------------------------------------------------------------------
# Ordering: the first failing field in declaration order wins
# ---------------------------------------------------------------------------


_ORDERED_FAILURES: list[tuple[str, dict[str, Any], str]] = [
    ("verdict", {"verdict": None}, "verdict must be str"),
    ("confidence", {"confidence": "x"}, "confidence must be a finite number"),
    (
        "robustness_score",
        {"robustness_score": 1e307},
        "robustness_score cannot be displayed as a finite percentage",
    ),
    ("risk_summary", {"risk_summary": []}, "risk_summary must be dict"),
    (
        "risk_summary.critical",
        {"risk_summary": {"critical": "x"}},
        "risk_summary.critical must be a finite number",
    ),
    (
        "risk_summary.high",
        {"risk_summary": {"high": None}},
        "risk_summary.high must be a finite number",
    ),
    (
        "risk_summary.medium",
        {"risk_summary": {"medium": True}},
        "risk_summary.medium must be a finite number",
    ),
    (
        "risk_summary.low",
        {"risk_summary": {"low": "nan"}},
        "risk_summary.low must be a finite number",
    ),
    (
        "risk_summary.total",
        {"risk_summary": {"total": []}},
        "risk_summary.total must be a finite number",
    ),
    ("consensus_proof", {"consensus_proof": []}, "consensus_proof must be dict"),
    (
        "consensus_proof.reached",
        {"consensus_proof": {"reached": "maybe"}},
        "consensus_proof.reached is not a recognized boolean",
    ),
    (
        "consensus_proof.supporting_agents",
        {"consensus_proof": {"supporting_agents": "a"}},
        "consensus_proof.supporting_agents must be list",
    ),
    (
        "consensus_proof.supporting_agents[0]",
        {"consensus_proof": {"supporting_agents": [1]}},
        "consensus_proof.supporting_agents[0] must be str",
    ),
    (
        "consensus_proof.dissenting_agents",
        {"consensus_proof": {"dissenting_agents": "a"}},
        "consensus_proof.dissenting_agents must be list",
    ),
    (
        "consensus_proof.dissenting_agents[0]",
        {"consensus_proof": {"dissenting_agents": [1]}},
        "consensus_proof.dissenting_agents[0] must be str",
    ),
    ("agent_responses", {"agent_responses": "x"}, "agent_responses must be list"),
    ("agent_responses[0]", {"agent_responses": [1]}, "agent_responses[0] must be dict"),
    (
        "agent_responses[0].content",
        {"agent_responses": [{"content": 1}]},
        "agent_responses[0].content must be str",
    ),
    ("cost_summary", {"cost_summary": []}, "cost_summary must be dict"),
    ("config_used", {"config_used": None}, "config_used must be dict"),
    (
        "config_used.critique_summaries",
        {"config_used": {"critique_summaries": "x"}},
        "config_used.critique_summaries must be list",
    ),
    (
        "config_used.critique_summaries[0]",
        {"config_used": {"critique_summaries": [1]}},
        "config_used.critique_summaries[0] must be dict",
    ),
    (
        "config_used.critique_summaries[0].issues",
        {"config_used": {"critique_summaries": [{"issues": 1}]}},
        "config_used.critique_summaries[0].issues must be list",
    ),
    ("dissenting_views", {"dissenting_views": "x"}, "dissenting_views must be list"),
]


def _merge(*fragments: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for fragment in fragments:
        for key, value in fragment.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = copy.deepcopy(value)
    return merged


@pytest.mark.parametrize(
    "earlier", range(len(_ORDERED_FAILURES) - 1), ids=[f[0] for f in _ORDERED_FAILURES[:-1]]
)
def test_each_failure_precedes_every_later_failure(earlier: int) -> None:
    _, fragment, message = _ORDERED_FAILURES[earlier]
    checked = 0
    for _, later_fragment, _ in _ORDERED_FAILURES[earlier + 1 :]:
        combined = _merge(later_fragment, fragment)
        if combined != _merge(fragment, later_fragment):
            # Both fragments target the same key with incompatible shapes, so
            # only one of them can be present; that is not an ordering pair.
            continue
        _expect(combined, message)
        checked += 1
    assert checked >= 1


def test_every_failure_in_isolation_matches_its_message() -> None:
    for _, fragment, message in _ORDERED_FAILURES:
        _expect(copy.deepcopy(fragment), message)


def test_all_invalid_fields_at_once_reports_verdict_first() -> None:
    data = {
        "verdict": 1,
        "confidence": "x",
        "robustness_score": None,
        "risk_summary": "x",
        "consensus_proof": "x",
        "agent_responses": "x",
        "cost_summary": "x",
        "config_used": "x",
        "dissenting_views": "x",
    }
    _expect(data, "verdict must be str")


def test_risk_count_fields_are_checked_in_fixed_order_not_insertion_order() -> None:
    _expect(
        {"risk_summary": {"total": "x", "low": "y", "medium": "z"}},
        "risk_summary.medium must be a finite number",
    )


def test_agent_list_entries_are_reported_by_first_bad_index() -> None:
    _expect(
        {"consensus_proof": {"supporting_agents": ["a", "b", 3, 4]}},
        "consensus_proof.supporting_agents[2] must be str",
    )


def test_response_dict_check_precedes_its_content_check() -> None:
    _expect(
        {"agent_responses": [{"content": 1}, "x"]},
        "agent_responses[0].content must be str",
    )
    _expect(
        {"agent_responses": ["x", {"content": 1}]},
        "agent_responses[0] must be dict",
    )


def test_critique_dict_check_precedes_its_issues_check() -> None:
    _expect(
        {"config_used": {"critique_summaries": [{"issues": 1}, "x"]}},
        "config_used.critique_summaries[0].issues must be list",
    )
    _expect(
        {"config_used": {"critique_summaries": ["x", {"issues": 1}]}},
        "config_used.critique_summaries[0] must be dict",
    )


# ---------------------------------------------------------------------------
# Return value, side effects and error type
# ---------------------------------------------------------------------------


def test_valid_input_is_not_mutated_and_returns_none(
    capsys: pytest.CaptureFixture[str],
) -> None:
    data = _full_valid_receipt()
    del data["risk_summary"]["unchecked"]
    snapshot = copy.deepcopy(data)
    assert _validate_inspection_fields(data) is None
    assert data == snapshot
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_invalid_input_is_not_mutated_and_prints_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    data = {"verdict": "ok", "confidence": 0.5, "consensus_proof": {"supporting_agents": [1]}}
    snapshot = copy.deepcopy(data)
    with pytest.raises(ValueError):
        _validate_inspection_fields(data)
    assert data == snapshot
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_errors_are_plain_value_errors_without_cause() -> None:
    for fragment, message in (
        ({"verdict": None}, "verdict must be str"),
        ({"confidence": 10**400}, "confidence must be a finite number"),
        ({"risk_summary": {"high": "abc"}}, "risk_summary.high must be a finite number"),
        (
            {"consensus_proof": {"reached": "maybe"}},
            "consensus_proof.reached is not a recognized boolean",
        ),
    ):
        with pytest.raises(ValueError) as excinfo:
            _validate_inspection_fields(fragment)
        assert type(excinfo.value) is ValueError
        assert str(excinfo.value) == message
        assert excinfo.value.__cause__ is None


# ---------------------------------------------------------------------------
# Call-site contract: cmd_receipt_inspect surfaces the message and exits 1
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"verdict": None}, "verdict must be str"),
        ({"confidence": 1e307}, "confidence cannot be displayed as a finite percentage"),
        ({"risk_summary": {"low": "nan"}}, "risk_summary.low must be a finite number"),
        ({"config_used": None}, "config_used must be dict"),
    ],
)
def test_cmd_receipt_inspect_reports_validation_failure(
    data: dict[str, Any], message: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "receipt.json"
    source.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        cmd_receipt_inspect(argparse.Namespace(receipt=str(source)))
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"Error: Invalid receipt inspection field: {message}\n"


def test_cmd_receipt_inspect_accepts_full_valid_receipt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _full_valid_receipt()
    del data["risk_summary"]["unchecked"]
    source = tmp_path / "receipt.json"
    source.write_text(json.dumps(data), encoding="utf-8")
    cmd_receipt_inspect(argparse.Namespace(receipt=str(source)))
    captured = capsys.readouterr()
    assert "Decision Receipt" in captured.out
    assert "Invalid receipt inspection field" not in captured.err
