"""Characterization of ``_validate_extensions`` (ODR optional-content walker).

Pins the walker's observable contract against both the bundled ODR schema and
small synthetic schemas: which values each JSON-Schema type accepts, the exact
error strings, error accumulation order, the paths that are walked or skipped,
``$ref`` resolution, and the exceptions raised for malformed schemas. Written
against the original implementation; must keep passing unchanged afterwards.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from aragora.gauntlet.odr_export import load_odr_schema
from aragora.gauntlet.odr_verify import _validate_extensions

ROOT = Path(__file__).resolve().parents[2]


def _errors(doc: Any, schema: dict[str, Any] | None = None) -> list[str]:
    errors: list[str] = []
    result = _validate_extensions(errors, doc, schema if schema is not None else load_odr_schema())
    assert result is None
    return errors


def _leaf_schema(leaf: dict[str, Any], defs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Minimal schema defining every walked path, with ``subject.repository`` as ``leaf``."""
    return {
        "$defs": defs or {},
        "properties": {
            "adjudication": {"type": "object"},
            "subject": {"properties": {"repository": leaf}},
            "reasoning": {"oneOf": [{"properties": {}}, {"$ref": "#/$defs/absent"}]},
            "quorum": {"properties": {"dissent": {"properties": {}}}},
            "attestation": {"properties": {"mechanism": {"properties": {}}}},
        },
    }


def _leaf_errors(value: Any, leaf: dict[str, Any], defs: dict[str, Any] | None = None) -> list[str]:
    return _errors({"subject": {"repository": value}}, _leaf_schema(leaf, defs))


def _mechanism(**members: Any) -> dict[str, Any]:
    return {"attestation": {"mechanism": {"type": "signature", **members}}}


# ---------------------------------------------------------------------------
# Valid inputs against the bundled schema
# ---------------------------------------------------------------------------


def test_legacy_example_document_has_no_extension_errors() -> None:
    doc = json.loads((ROOT / "docs/specs/examples/example-approved-clean.odr.json").read_text())
    assert _errors(doc) == []


@pytest.mark.parametrize(
    "doc",
    [
        {},
        {"subject": {}, "reasoning": {}, "quorum": {}, "attestation": {}},
        {"subject": {"claim_id": "x", "title": "unrelated members are ignored"}},
        {"subject": {"repository": "o/r", "pr_number": 1, "head_sha": "a" * 40, "base_sha": "b"}},
        {"subject": {"pr_number": 7.0}},
        {"reasoning": {"observations": []}},
        {"reasoning": {"observations": [{"kind": "timeout", "family": "grok", "detail": "d"}]}},
        {"reasoning": {"observations": [{}, {"kind": "rerun"}]}},
        {"quorum": {"verdicts": []}},
        {
            "quorum": {
                "verdicts": [
                    {
                        "issuer": "claude",
                        "role": "reviewer",
                        "verdict": "approve",
                        "model_family": "claude",
                        "model_id": "m",
                        "head_sha": "a",
                        "posted_at": "t",
                        "grounded": True,
                        "counted": False,
                        "severity_max": "P3",
                        "blocking": False,
                    }
                ]
            }
        },
        {"quorum": {"rule": {}}},
        {
            "quorum": {
                "rule": {
                    "required_signals": 2,
                    "requires_western_frontier": True,
                    "western_only_counted": False,
                    "counted_families": ["claude", "gpt"],
                }
            }
        },
        {"quorum": {"dissent": {"findings": [], "severity_max": "P0", "blocking": True}}},
        {
            "quorum": {
                "dissent": {
                    "findings": [
                        {
                            "issuer": "i",
                            "severity": "P2",
                            "blocking": False,
                            "location": "f.py:1",
                            "text": "t",
                        }
                    ]
                }
            }
        },
        {"adjudication": {}},
        {
            "adjudication": {
                "status": "present",
                "kind": "review_adjudication.v1",
                "verdict": "settle",
                "reason": "r",
                "policy": {"anything": ["goes", 1, None]},
                "assessments": [{"free": "form"}, {}],
                "blocking_findings": ["a"],
                "escalated_findings": [],
                "settled_findings": ["b", "c"],
            }
        },
        {"adjudication": {"status": "absent", "verdict": "block"}},
        _mechanism(policy_version=3, tier=None),
        _mechanism(policy_version=3.0, tier=2, tiered_gate=True, severity_gated=False),
        _mechanism(action="merge", action_reason="ok", record_ref="ref"),
        _mechanism(context="ctx", ref="unwalked members are ignored", unknown=object()),
    ],
    ids=[
        "empty-doc",
        "empty-parents",
        "unwalked-subject-members",
        "subject-full",
        "subject-integral-float",
        "observations-empty",
        "observations-full",
        "observations-partial",
        "verdicts-empty",
        "verdicts-full",
        "rule-empty",
        "rule-full",
        "dissent-scalars",
        "dissent-findings-full",
        "adjudication-empty",
        "adjudication-full",
        "adjudication-absent-status-still-walked",
        "mechanism-null-tier",
        "mechanism-integral-floats",
        "mechanism-strings",
        "mechanism-unwalked-members",
    ],
)
def test_valid_documents_produce_no_errors(doc: dict[str, Any]) -> None:
    assert _errors(doc) == []


# ---------------------------------------------------------------------------
# Skipped parents: absent markers and non-object parents
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "doc",
    [
        {"reasoning": {"status": "absent", "reason": "r", "observations": 42}},
        {"quorum": {"status": "absent", "reason": "r", "verdicts": 42, "rule": "x"}},
        {"quorum": {"dissent": {"status": "absent", "findings": 42, "blocking": "no"}}},
        {"subject": {"status": "absent", "pr_number": "not-an-int"}},
        {"attestation": {"mechanism": {"status": "absent", "tier": "x"}}},
        {"status": "absent", "adjudication": 42},
        {"subject": 42},
        {"subject": ["repository"]},
        {"subject": None},
        {"reasoning": "text"},
        {"quorum": [], "attestation": "x"},
        {"attestation": {"mechanism": []}},
        {"attestation": {"mechanism": None}},
        {"quorum": {"dissent": 42}},
        {"quorum": {"dissent": None}},
        {"quorum": 42, "attestation": 42, "reasoning": 42, "subject": 42},
    ],
    ids=[
        "reasoning-absent",
        "quorum-absent-skips-verdicts-and-rule",
        "dissent-absent",
        "subject-absent",
        "mechanism-absent",
        "root-absent-skips-adjudication",
        "subject-int",
        "subject-list",
        "subject-none",
        "reasoning-str",
        "quorum-list-attestation-str",
        "mechanism-list",
        "mechanism-none",
        "dissent-int",
        "dissent-none",
        "all-parents-non-dict",
    ],
)
def test_absent_or_non_object_parents_are_skipped(doc: dict[str, Any]) -> None:
    assert _errors(doc) == []


def test_quorum_absent_does_not_skip_a_present_dissent_block() -> None:
    doc = {"quorum": {"status": "absent", "verdicts": 42, "dissent": {"blocking": "no"}}}
    assert _errors(doc) == ["quorum.dissent.blocking: must have type ['boolean']"]


def test_non_dict_document_is_skipped_entirely() -> None:
    assert _errors(42) == []
    assert _errors(["adjudication"]) == []


# ---------------------------------------------------------------------------
# Distinguished invalid classes against the bundled schema
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("doc", "expected"),
    [
        ({"adjudication": 42}, ["adjudication: must have type ['object']"]),
        ({"adjudication": []}, ["adjudication: must have type ['object']"]),
        ({"adjudication": None}, ["adjudication: must have type ['object']"]),
        ({"adjudication": {"status": "pending"}}, ["adjudication.status: invalid value"]),
        ({"adjudication": {"kind": "other"}}, ["adjudication.kind: invalid value"]),
        ({"adjudication": {"kind": None}}, ["adjudication.kind: invalid value"]),
        ({"adjudication": {"verdict": "approve"}}, ["adjudication.verdict: invalid value"]),
        ({"adjudication": {"reason": 1}}, ["adjudication.reason: must have type ['string']"]),
        ({"adjudication": {"policy": []}}, ["adjudication.policy: must have type ['object']"]),
        (
            {"adjudication": {"assessments": {"a": 1}}},
            ["adjudication.assessments: must have type ['array']"],
        ),
        (
            {"adjudication": {"assessments": [{}, "s"]}},
            ["adjudication.assessments[1]: must have type ['object']"],
        ),
        (
            {"adjudication": {"blocking_findings": [1]}},
            ["adjudication.blocking_findings[0]: must have type ['string']"],
        ),
        (
            {"adjudication": {"escalated_findings": "x"}},
            ["adjudication.escalated_findings: must have type ['array']"],
        ),
        (
            {"adjudication": {"settled_findings": [None]}},
            ["adjudication.settled_findings[0]: must have type ['string']"],
        ),
        ({"adjudication": {"extra": True}}, ["adjudication.extra: unknown member"]),
        ({"subject": {"repository": 5}}, ["subject.repository: must have type ['string']"]),
        ({"subject": {"pr_number": 1.5}}, ["subject.pr_number: must have type ['integer']"]),
        ({"subject": {"pr_number": True}}, ["subject.pr_number: must have type ['integer']"]),
        ({"subject": {"pr_number": "1"}}, ["subject.pr_number: must have type ['integer']"]),
        ({"subject": {"pr_number": None}}, ["subject.pr_number: must have type ['integer']"]),
        ({"subject": {"head_sha": ["a"]}}, ["subject.head_sha: must have type ['string']"]),
        ({"subject": {"base_sha": {}}}, ["subject.base_sha: must have type ['string']"]),
        (
            {"reasoning": {"observations": {"kind": "timeout"}}},
            ["reasoning.observations: must have type ['array']"],
        ),
        (
            {"reasoning": {"observations": ["timeout"]}},
            ["reasoning.observations[0]: must have type ['object']"],
        ),
        (
            {"reasoning": {"observations": [{"kind": "crash"}]}},
            ["reasoning.observations[0].kind: invalid value"],
        ),
        (
            {"reasoning": {"observations": [{"family": 1}]}},
            ["reasoning.observations[0].family: must have type ['string']"],
        ),
        (
            {"reasoning": {"observations": [{"detail": None}]}},
            ["reasoning.observations[0].detail: must have type ['string']"],
        ),
        (
            {"reasoning": {"observations": [{"kind": "timeout", "extra": 1}]}},
            ["reasoning.observations[0].extra: unknown member"],
        ),
        ({"quorum": {"verdicts": {}}}, ["quorum.verdicts: must have type ['array']"]),
        ({"quorum": {"verdicts": [1]}}, ["quorum.verdicts[0]: must have type ['object']"]),
        (
            {"quorum": {"verdicts": [{"issuer": 1}]}},
            ["quorum.verdicts[0].issuer: must have type ['string']"],
        ),
        (
            {"quorum": {"verdicts": [{"grounded": "yes"}]}},
            ["quorum.verdicts[0].grounded: must have type ['boolean']"],
        ),
        (
            {"quorum": {"verdicts": [{"counted": 1}]}},
            ["quorum.verdicts[0].counted: must have type ['boolean']"],
        ),
        (
            {"quorum": {"verdicts": [{"severity_max": "P5"}]}},
            ["quorum.verdicts[0].severity_max: invalid value"],
        ),
        (
            {"quorum": {"verdicts": [{"severity_max": 1}]}},
            ["quorum.verdicts[0].severity_max: invalid value"],
        ),
        (
            {"quorum": {"verdicts": [{"unexpected": True}]}},
            ["quorum.verdicts[0].unexpected: unknown member"],
        ),
        ({"quorum": {"rule": []}}, ["quorum.rule: must have type ['object']"]),
        (
            {"quorum": {"rule": {"required_signals": "2"}}},
            ["quorum.rule.required_signals: must have type ['integer']"],
        ),
        (
            {"quorum": {"rule": {"required_signals": 2.5}}},
            ["quorum.rule.required_signals: must have type ['integer']"],
        ),
        (
            {"quorum": {"rule": {"requires_western_frontier": 1}}},
            ["quorum.rule.requires_western_frontier: must have type ['boolean']"],
        ),
        (
            {"quorum": {"rule": {"counted_families": "claude"}}},
            ["quorum.rule.counted_families: must have type ['array']"],
        ),
        (
            {"quorum": {"rule": {"counted_families": ["claude", 2]}}},
            ["quorum.rule.counted_families[1]: must have type ['string']"],
        ),
        ({"quorum": {"rule": {"extra": 1}}}, ["quorum.rule.extra: unknown member"]),
        (
            {"quorum": {"dissent": {"findings": {}}}},
            ["quorum.dissent.findings: must have type ['array']"],
        ),
        (
            {"quorum": {"dissent": {"findings": [["x"]]}}},
            ["quorum.dissent.findings[0]: must have type ['object']"],
        ),
        (
            {"quorum": {"dissent": {"findings": [{"severity": "P7"}]}}},
            ["quorum.dissent.findings[0].severity: invalid value"],
        ),
        (
            {"quorum": {"dissent": {"findings": [{"blocking": "true"}]}}},
            ["quorum.dissent.findings[0].blocking: must have type ['boolean']"],
        ),
        (
            {"quorum": {"dissent": {"findings": [{"location": 1}]}}},
            ["quorum.dissent.findings[0].location: must have type ['string']"],
        ),
        (
            {"quorum": {"dissent": {"findings": [{"text": 1}]}}},
            ["quorum.dissent.findings[0].text: must have type ['string']"],
        ),
        (
            {"quorum": {"dissent": {"findings": [{"extra": 1}]}}},
            ["quorum.dissent.findings[0].extra: unknown member"],
        ),
        (
            {"quorum": {"dissent": {"severity_max": "P9"}}},
            ["quorum.dissent.severity_max: invalid value"],
        ),
        (
            {"quorum": {"dissent": {"severity_max": None}}},
            ["quorum.dissent.severity_max: invalid value"],
        ),
        (
            {"quorum": {"dissent": {"blocking": 1}}},
            ["quorum.dissent.blocking: must have type ['boolean']"],
        ),
        (
            {"quorum": {"dissent": {"blocking": None}}},
            ["quorum.dissent.blocking: must have type ['boolean']"],
        ),
        (
            _mechanism(policy_version=True),
            ["attestation.mechanism.policy_version: must have type ['integer']"],
        ),
        (
            _mechanism(policy_version=1.5),
            ["attestation.mechanism.policy_version: must have type ['integer']"],
        ),
        (
            _mechanism(tier="3"),
            ["attestation.mechanism.tier: must have type ['integer', 'null']"],
        ),
        (
            _mechanism(tier=False),
            ["attestation.mechanism.tier: must have type ['integer', 'null']"],
        ),
        (
            _mechanism(tier=2.5),
            ["attestation.mechanism.tier: must have type ['integer', 'null']"],
        ),
        (
            _mechanism(tiered_gate="yes"),
            ["attestation.mechanism.tiered_gate: must have type ['boolean']"],
        ),
        (
            _mechanism(severity_gated=0),
            ["attestation.mechanism.severity_gated: must have type ['boolean']"],
        ),
        (
            _mechanism(action=1),
            ["attestation.mechanism.action: must have type ['string']"],
        ),
        (
            _mechanism(action_reason=[]),
            ["attestation.mechanism.action_reason: must have type ['string']"],
        ),
        (
            _mechanism(record_ref=None),
            ["attestation.mechanism.record_ref: must have type ['string']"],
        ),
    ],
)
def test_invalid_extension_produces_exact_error(doc: dict[str, Any], expected: list[str]) -> None:
    assert _errors(doc) == expected


# ---------------------------------------------------------------------------
# Ordering and accumulation
# ---------------------------------------------------------------------------


def test_errors_accumulate_in_walk_order_across_paths() -> None:
    doc = {
        "attestation": {"mechanism": {"tier": "x"}},
        "quorum": {
            "dissent": {"blocking": "no", "findings": "x"},
            "rule": [],
            "verdicts": [{"counted": "x"}],
        },
        "reasoning": {"observations": "x"},
        "subject": {"base_sha": 1, "head_sha": 2, "pr_number": "3", "repository": 4},
        "adjudication": {"kind": "x"},
    }
    assert _errors(doc) == [
        "adjudication.kind: invalid value",
        "subject.repository: must have type ['string']",
        "subject.pr_number: must have type ['integer']",
        "subject.head_sha: must have type ['string']",
        "subject.base_sha: must have type ['string']",
        "reasoning.observations: must have type ['array']",
        "quorum.verdicts[0].counted: must have type ['boolean']",
        "quorum.rule: must have type ['object']",
        "quorum.dissent.findings: must have type ['array']",
        "quorum.dissent.blocking: must have type ['boolean']",
        "attestation.mechanism.tier: must have type ['integer', 'null']",
    ]


def test_object_members_are_reported_in_document_insertion_order() -> None:
    doc = {"adjudication": {"zzz": 1, "kind": "bad", "aaa": 2, "verdict": "bad", "reason": 3}}
    assert _errors(doc) == [
        "adjudication.zzz: unknown member",
        "adjudication.kind: invalid value",
        "adjudication.aaa: unknown member",
        "adjudication.verdict: invalid value",
        "adjudication.reason: must have type ['string']",
    ]


def test_array_items_are_reported_by_index_and_depth_first() -> None:
    doc = {
        "quorum": {
            "verdicts": [
                {"issuer": 1, "counted": "x"},
                "not-an-object",
                {"severity_max": "P9", "extra": 1},
            ]
        }
    }
    assert _errors(doc) == [
        "quorum.verdicts[0].issuer: must have type ['string']",
        "quorum.verdicts[0].counted: must have type ['boolean']",
        "quorum.verdicts[1]: must have type ['object']",
        "quorum.verdicts[2].severity_max: invalid value",
        "quorum.verdicts[2].extra: unknown member",
    ]


def test_type_mismatch_stops_descent_into_that_member() -> None:
    doc = {"adjudication": ["kind", "bad", {"extra": 1}]}
    assert _errors(doc) == ["adjudication: must have type ['object']"]
    doc = {"quorum": {"rule": "not-an-object-with-extra"}}
    assert _errors(doc) == ["quorum.rule: must have type ['object']"]


def test_existing_errors_are_preserved_and_the_same_list_is_appended() -> None:
    errors = ["pre-existing"]
    result = _validate_extensions(errors, {"subject": {"pr_number": "x"}}, load_odr_schema())
    assert result is None
    assert errors == ["pre-existing", "subject.pr_number: must have type ['integer']"]


def test_document_and_schema_are_not_mutated() -> None:
    doc = {
        "adjudication": {"kind": "bad", "extra": 1},
        "subject": {"pr_number": 1.5},
        "quorum": {"verdicts": [{"severity_max": "P9"}]},
    }
    schema = load_odr_schema()
    doc_snapshot, schema_snapshot = copy.deepcopy(doc), copy.deepcopy(schema)
    _errors(doc, schema)
    assert doc == doc_snapshot
    assert schema == schema_snapshot


def test_repeated_calls_are_deterministic() -> None:
    doc = {"adjudication": {"kind": "bad"}, "subject": {"pr_number": "x"}}
    assert _errors(doc) == _errors(doc) == _errors(copy.deepcopy(doc))


# ---------------------------------------------------------------------------
# Type table and generic mechanics against synthetic schemas
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("type_name", "accepted", "rejected"),
    [
        ("string", ["", "s"], [1, 1.0, True, None, [], {}]),
        ("boolean", [True, False], [1, 0, 1.0, "true", None, [], {}]),
        (
            "integer",
            [0, 1, -3, 10**30, 1.0, -2.0, 0.0],
            [1.5, -0.5, True, False, "1", None, [], {}, float("inf"), float("nan")],
        ),
        (
            "number",
            [0, 1, -3, 1.5, 0.0, float("inf"), float("-inf"), float("nan")],
            [True, False, "1", None, [], {}],
        ),
        ("null", [None], [0, False, "", [], {}, "null"]),
        ("object", [{}, {"a": 1}], [[], "s", 1, None, True]),
        ("array", [[], [1, "x", None]], [{}, "s", 1, None, True, ("a",)]),
    ],
)
def test_type_table_accepts_and_rejects(
    type_name: str, accepted: list[Any], rejected: list[Any]
) -> None:
    leaf = {"type": type_name}
    for value in accepted:
        assert _leaf_errors(value, leaf) == [], repr(value)
    for value in rejected:
        assert _leaf_errors(value, leaf) == [
            f"subject.repository: must have type ['{type_name}']"
        ], repr(value)


def test_type_union_accepts_any_listed_type_and_echoes_the_list() -> None:
    leaf = {"type": ["integer", "null", "boolean"]}
    for value in (1, 2.0, None, True, False):
        assert _leaf_errors(value, leaf) == []
    for value in ("1", 1.5, [], {}):
        assert _leaf_errors(value, leaf) == [
            "subject.repository: must have type ['integer', 'null', 'boolean']"
        ]


def test_missing_type_accepts_any_value() -> None:
    for value in (None, 1, 1.5, True, "s", [], {}, object()):
        assert _leaf_errors(value, {}) == []
        assert _leaf_errors(value, {"description": "typeless"}) == []


def test_empty_type_list_accepts_any_value() -> None:
    for value in (None, 1, "s", [], {}):
        assert _leaf_errors(value, {"type": []}) == []


@pytest.mark.parametrize(
    ("leaf", "value", "expected"),
    [
        ({"enum": ["a", "b"]}, "a", []),
        ({"enum": ["a", "b"]}, "c", ["subject.repository: invalid value"]),
        ({"enum": ["a", "b"]}, None, ["subject.repository: invalid value"]),
        ({"enum": [1, 2]}, True, []),
        ({"enum": [1.0]}, 1, []),
        ({"enum": []}, "a", ["subject.repository: invalid value"]),
        ({"const": "x"}, "x", []),
        ({"const": "x"}, "y", ["subject.repository: invalid value"]),
        ({"const": 1}, True, []),
        ({"const": 0}, False, []),
        ({"const": None}, None, []),
        ({"const": None}, 0, ["subject.repository: invalid value"]),
        ({"enum": ["a"], "const": "a"}, "a", []),
        ({"enum": ["a"], "const": "b"}, "a", ["subject.repository: invalid value"]),
        ({"enum": ["b"], "const": "a"}, "a", ["subject.repository: invalid value"]),
        ({"enum": ["b"], "const": "b"}, "a", ["subject.repository: invalid value"]),
        ({"type": "string", "enum": ["a"]}, "a", []),
        ({"type": "string", "enum": ["a"]}, "b", ["subject.repository: invalid value"]),
        ({"type": "string", "enum": ["a"]}, 1, ["subject.repository: must have type ['string']"]),
        ({"type": "integer", "const": 1}, 1.0, []),
        ({"type": "integer", "const": 1}, 2, ["subject.repository: invalid value"]),
        ({"type": "integer", "const": 1}, 1.5, ["subject.repository: must have type ['integer']"]),
    ],
)
def test_enum_and_const_use_python_equality_after_the_type_check(
    leaf: dict[str, Any], value: Any, expected: list[str]
) -> None:
    assert _leaf_errors(value, leaf) == expected


def test_enum_mismatch_does_not_stop_descent() -> None:
    leaf = {"type": "object", "enum": [{"a": 1}], "properties": {"a": {"type": "integer"}}}
    assert _leaf_errors({"a": "x"}, leaf) == [
        "subject.repository: invalid value",
        "subject.repository.a: must have type ['integer']",
    ]
    leaf = {"type": "array", "const": [1], "items": {"type": "integer"}}
    assert _leaf_errors(["x"], leaf) == [
        "subject.repository: invalid value",
        "subject.repository[0]: must have type ['integer']",
    ]


def test_nested_arrays_and_objects_build_paths() -> None:
    leaf = {
        "type": "array",
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "inner": {"type": "object", "properties": {"leaf": {"type": "boolean"}}}
                },
                "additionalProperties": False,
            },
        },
    }
    value = [[{"inner": {"leaf": True}}], [{"inner": {"leaf": 1, "other": 2}}, {"bad": 1}], "x"]
    assert _leaf_errors(value, leaf) == [
        "subject.repository[1][0].inner.leaf: must have type ['boolean']",
        "subject.repository[1][1].bad: unknown member",
        "subject.repository[2]: must have type ['array']",
    ]


def test_array_without_items_and_object_without_properties_are_not_descended() -> None:
    assert _leaf_errors([1, "x", None, {}], {"type": "array"}) == []
    assert _leaf_errors({"a": 1, "b": None}, {"type": "object"}) == []
    assert _leaf_errors({"a": 1}, {"type": "object", "additionalProperties": False}) == []


@pytest.mark.parametrize(
    ("additional", "expected"),
    [
        (False, ["subject.repository.extra: unknown member"]),
        (True, []),
        ({}, []),
        ({"type": "string"}, []),
        (None, []),
        (0, []),
        ("absent", []),
    ],
)
def test_unknown_members_only_flagged_when_additional_properties_is_false(
    additional: Any, expected: list[str]
) -> None:
    leaf: dict[str, Any] = {"type": "object", "properties": {"known": {"type": "integer"}}}
    if additional != "absent":
        leaf["additionalProperties"] = additional
    assert _leaf_errors({"known": 1, "extra": 1}, leaf) == expected


def test_known_and_unknown_members_follow_document_order() -> None:
    leaf = {
        "type": "object",
        "properties": {"a": {"type": "integer"}, "b": {"type": "string"}},
        "additionalProperties": False,
    }
    assert _leaf_errors({"x": 1, "b": 1, "y": 2, "a": "s"}, leaf) == [
        "subject.repository.x: unknown member",
        "subject.repository.b: must have type ['string']",
        "subject.repository.y: unknown member",
        "subject.repository.a: must have type ['integer']",
    ]


def test_ref_resolves_against_top_level_defs_by_last_segment() -> None:
    defs = {"severity": {"enum": ["P0"]}, "flag": {"type": "boolean"}}
    assert _leaf_errors("P0", {"$ref": "#/$defs/severity"}, defs) == []
    assert _leaf_errors("P1", {"$ref": "#/$defs/severity"}, defs) == [
        "subject.repository: invalid value"
    ]
    assert _leaf_errors("P0", {"$ref": "anything/severity"}, defs) == []
    assert _leaf_errors(1, {"$ref": "#/$defs/flag"}, defs) == [
        "subject.repository: must have type ['boolean']"
    ]


def test_ref_replaces_the_local_spec_entirely() -> None:
    defs = {"flag": {"type": "boolean"}}
    leaf = {"$ref": "#/$defs/flag", "type": "string", "enum": ["ignored"]}
    assert _leaf_errors(True, leaf, defs) == []
    assert _leaf_errors("ignored", leaf, defs) == ["subject.repository: must have type ['boolean']"]


def test_ref_inside_items_and_properties() -> None:
    defs = {"severity": {"enum": ["P0", "P1"]}}
    leaf = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"severity": {"$ref": "#/$defs/severity"}},
        },
    }
    assert _leaf_errors([{"severity": "P1"}, {"severity": "P9"}], leaf, defs) == [
        "subject.repository[1].severity: invalid value"
    ]


def test_nested_ref_is_resolved_only_one_level() -> None:
    defs = {"outer": {"$ref": "#/$defs/inner"}, "inner": {"type": "boolean"}}
    assert _leaf_errors("not-a-bool", {"$ref": "#/$defs/outer"}, defs) == []


def test_unknown_ref_raises_key_error() -> None:
    with pytest.raises(KeyError):
        _leaf_errors("x", {"$ref": "#/$defs/missing"}, {"severity": {}})
    with pytest.raises(KeyError):
        _leaf_errors("x", {"$ref": "#/$defs/severity"}, None)


def test_unknown_type_name_raises_key_error_only_when_reached() -> None:
    with pytest.raises(KeyError):
        _leaf_errors("x", {"type": "float"})
    with pytest.raises(KeyError):
        _leaf_errors(1, {"type": ["string", "float"]})
    # Type candidates are tried in order and the first match short-circuits.
    assert _leaf_errors("x", {"type": ["string", "float"]}) == []


def test_schema_must_define_every_walked_path() -> None:
    schema = _leaf_schema({"type": "string"})
    del schema["properties"]["attestation"]
    with pytest.raises(KeyError):
        _errors({}, schema)
    schema = _leaf_schema({"type": "string"})
    del schema["properties"]["quorum"]["properties"]["dissent"]
    with pytest.raises(KeyError):
        _errors({}, schema)


def test_one_of_uses_the_first_branch_for_walked_parents() -> None:
    schema = _leaf_schema({"type": "string"})
    schema["properties"]["reasoning"] = {
        "oneOf": [
            {"properties": {"observations": {"type": "integer"}}},
            {"properties": {"observations": {"type": "string"}}},
        ]
    }
    assert _errors({"reasoning": {"observations": 1}}, schema) == []
    assert _errors({"reasoning": {"observations": "s"}}, schema) == [
        "reasoning.observations: must have type ['integer']"
    ]


def test_one_of_is_not_consulted_below_walked_parents() -> None:
    leaf = {"oneOf": [{"type": "integer"}, {"type": "string"}]}
    for value in (1, "s", None, []):
        assert _leaf_errors(value, leaf) == []


def test_root_adjudication_path_has_no_leading_dot() -> None:
    schema = _leaf_schema({"type": "string"})
    schema["properties"]["adjudication"] = {
        "type": "object",
        "properties": {"a": {"type": "array", "items": {"type": "string"}}},
    }
    assert _errors({"adjudication": {"a": [1]}}, schema) == [
        "adjudication.a[0]: must have type ['string']"
    ]
    assert _errors({"adjudication": 1}, schema) == ["adjudication: must have type ['object']"]


def test_only_declared_extension_keys_are_walked() -> None:
    schema = _leaf_schema({"type": "string"})
    schema["properties"]["subject"]["properties"]["claim_id"] = {"type": "integer"}
    schema["properties"]["quorum"]["properties"]["method"] = {"type": "integer"}
    doc = {"subject": {"claim_id": "s", "repository": "ok"}, "quorum": {"method": "s"}}
    assert _errors(doc, schema) == []
