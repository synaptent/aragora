"""Characterization of the ODR optional-content walker.

Pins the walker's observable contract against both the bundled ODR schema and
small synthetic schemas: which values each JSON-Schema type accepts, the exact
error strings, error accumulation order, the paths that are walked or skipped,
``$ref`` resolution, and the exceptions raised for malformed schemas.

``_validate_extensions`` runs two independent passes: the declared-path walk
(:func:`_validate_scoped_paths`) and the whole-document backstop
(:func:`_apply_schema_backstop`), which types every member the schema types so the
verdict does not depend on the optional ``jsonschema`` extra. Most cases below pin
the declared-path walk through ``_errors``; the backstop and the composition of the
two are pinned separately through ``_all_errors``, since a partial synthetic document
draws a ``missing required member`` line from the backstop for every block it omits.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from aragora.gauntlet.odr_export import load_odr_schema
from aragora.gauntlet.odr_verify import (
    _validate_extensions,
    _validate_scoped_paths,
    verify_odr_document,
)

ROOT = Path(__file__).resolve().parents[2]


def _errors(doc: Any, schema: dict[str, Any] | None = None) -> list[str]:
    """Findings from the declared-extension-path walk alone."""
    errors: list[str] = []
    result = _validate_scoped_paths(
        errors, doc, schema if schema is not None else load_odr_schema()
    )
    assert result is None
    return errors


def _all_errors(doc: Any, schema: dict[str, Any] | None = None) -> list[str]:
    """Findings from the whole walker: the declared-path walk then the schema backstop."""
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


# Each block below carries the members its schema requires, so a case pins the finding for
# the member it overrides instead of also restating what an incomplete fragment omits.


def _adjudication(**members: Any) -> dict[str, Any]:
    base = {"kind": "review_adjudication.v1", "verdict": "settle", "reason": "r"}
    return {"adjudication": {**base, **members}}


def _observation(**members: Any) -> dict[str, Any]:
    base = {"kind": "failure", "family": "grok", "detail": "d"}
    return {"reasoning": {"observations": [{**base, **members}]}}


def _verdict(**members: Any) -> dict[str, Any]:
    base = {"issuer": "claude", "verdict": "pass", "model_family": "claude", "model_id": "m"}
    return {"quorum": {"verdicts": [{**base, **members}]}}


def _rule(**members: Any) -> dict[str, Any]:
    base = {
        "required_signals": 1,
        "requires_western_frontier": False,
        "western_only_counted": False,
        "counted_families": ["claude"],
    }
    return {"quorum": {"rule": {**base, **members}}}


def _finding(**members: Any) -> dict[str, Any]:
    base = {"issuer": "claude", "severity": "P3", "blocking": False, "text": "t"}
    return {"quorum": {"dissent": {"findings": [{**base, **members}]}}}


def _independence(**members: Any) -> dict[str, Any]:
    base = {"disclosed": True, "model_families": [], "distinct_model_families": 2}
    return {"independence": {**base, **members}}


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
        {
            "adjudication": {
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
        "verdicts-empty",
        "verdicts-full",
        "rule-full",
        "dissent-scalars",
        "dissent-findings-full",
        "adjudication-full",
        "mechanism-null-tier",
        "mechanism-integral-floats",
        "mechanism-strings",
        "mechanism-unwalked-members",
    ],
)
def test_valid_documents_produce_no_errors(doc: dict[str, Any]) -> None:
    assert _errors(doc) == []


# ---------------------------------------------------------------------------
# Required sub-members and the adjudication shape (spec §4.10)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("doc", "expected"),
    [
        (
            {"reasoning": {"observations": [{}, {"kind": "rerun"}]}},
            [
                "reasoning.observations[0]: missing required member: kind",
                "reasoning.observations[0]: missing required member: family",
                "reasoning.observations[0]: missing required member: detail",
                "reasoning.observations[1]: missing required member: family",
                "reasoning.observations[1]: missing required member: detail",
            ],
        ),
        (
            {"quorum": {"rule": {}}},
            [
                "quorum.rule: missing required member: required_signals",
                "quorum.rule: missing required member: requires_western_frontier",
                "quorum.rule: missing required member: western_only_counted",
                "quorum.rule: missing required member: counted_families",
            ],
        ),
        (
            {"adjudication": {}},
            [
                "adjudication: missing required member: kind",
                "adjudication: missing required member: verdict",
                "adjudication: missing required member: reason",
            ],
        ),
        (
            {"adjudication": {"status": "present", "kind": "review_adjudication.v1"}},
            [
                "adjudication: missing required member: verdict",
                "adjudication: missing required member: reason",
                "adjudication.status: unknown member",
            ],
        ),
        (
            {"adjudication": {"status": "absent", "verdict": "block"}},
            [
                "adjudication: missing required member: kind",
                "adjudication: missing required member: reason",
                "adjudication.status: unknown member",
            ],
        ),
    ],
    ids=[
        "observations-partial",
        "rule-empty",
        "adjudication-empty",
        "adjudication-status-present",
        "adjudication-status-absent",
    ],
)
def test_incomplete_object_shapes_name_each_missing_member(
    doc: dict[str, Any], expected: list[str]
) -> None:
    # adjudication declares no ``status`` member at all, so a marker-style value there is
    # an unknown member rather than a skip: an adjudication block is present or omitted.
    assert _errors(doc) == expected


# ---------------------------------------------------------------------------
# Skipped parents: absent markers and non-object parents
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "doc",
    [
        {"reasoning": {"status": "absent", "reason": "r"}},
        {"quorum": {"status": "absent", "reason": "r"}},
        {"quorum": {"dissent": {"status": "absent", "reason": "r"}}},
        {"subject": {"status": "absent", "reason": "r"}},
        {"attestation": {"mechanism": {"status": "absent", "reason": "r"}}},
        {"status": "absent", "reason": "r"},
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
        "reasoning-strict-marker",
        "quorum-strict-marker",
        "dissent-strict-marker",
        "subject-strict-marker",
        "mechanism-strict-marker",
        "root-strict-marker",
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
def test_strict_absent_markers_and_non_object_parents_are_skipped(doc: dict[str, Any]) -> None:
    assert _errors(doc) == []


@pytest.mark.parametrize(
    ("doc", "expected"),
    [
        (
            {"reasoning": {"status": "absent", "reason": "r", "observations": 42}},
            ["reasoning.observations: must have type ['array']"],
        ),
        (
            {"quorum": {"status": "absent", "reason": "r", "verdicts": 42, "rule": "x"}},
            [
                "quorum.verdicts: must have type ['array']",
                "quorum.rule: must have type ['object']",
            ],
        ),
        (
            {"quorum": {"dissent": {"status": "absent", "findings": 42, "blocking": "no"}}},
            [
                "quorum.dissent.findings: must have type ['array']",
                "quorum.dissent.blocking: must have type ['boolean']",
            ],
        ),
        (
            {"subject": {"status": "absent", "pr_number": "not-an-int"}},
            ["subject.pr_number: must have type ['integer']"],
        ),
        (
            {"attestation": {"mechanism": {"status": "absent", "tier": "x"}}},
            ["attestation.mechanism.tier: must have type ['integer', 'null']"],
        ),
        ({"status": "absent", "adjudication": 42}, ["adjudication: must have type ['object']"]),
    ],
    ids=[
        "reasoning-marker-with-observations",
        "quorum-marker-with-verdicts-and-rule",
        "dissent-marker-with-findings",
        "subject-marker-with-pr-number",
        "mechanism-marker-with-tier",
        "root-marker-with-adjudication",
    ],
)
def test_absent_marker_carrying_members_is_walked_like_a_present_block(
    doc: dict[str, Any], expected: list[str]
) -> None:
    # A marker with extra members satisfies neither branch of its oneOf, so the members are
    # checked rather than waved through; only a bare ``status``/``reason`` marker skips.
    assert _errors(doc) == expected


def test_quorum_absent_does_not_skip_a_present_dissent_block() -> None:
    doc = {"quorum": {"status": "absent", "verdicts": 42, "dissent": {"blocking": "no"}}}
    assert _errors(doc) == [
        # The quorum marker carries members, so its own verdicts are checked as well.
        "quorum.verdicts: must have type ['array']",
        "quorum.dissent.blocking: must have type ['boolean']",
    ]


def test_non_dict_document_is_rejected_before_the_walker_runs() -> None:
    # The walker reads the document's ``odr_version`` to scope membership, so a non-dict
    # document no longer reaches it; both entry points reject one with a single finding.
    for doc in (42, ["adjudication"]):
        with pytest.raises(AttributeError):
            _errors(doc)
        result = verify_odr_document(doc)
        assert not result.ok
        assert result.checks[0].detail == "receipt: top-level value must be a JSON object"


# ---------------------------------------------------------------------------
# Distinguished invalid classes against the bundled schema
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("doc", "expected"),
    [
        ({"adjudication": 42}, ["adjudication: must have type ['object']"]),
        ({"adjudication": []}, ["adjudication: must have type ['object']"]),
        ({"adjudication": None}, ["adjudication: must have type ['object']"]),
        # v0.2 drops ``status`` from adjudication's properties: a block is present or omitted.
        (_adjudication(status="pending"), ["adjudication.status: unknown member"]),
        (_adjudication(kind="other"), ["adjudication.kind: invalid value"]),
        (_adjudication(kind=None), ["adjudication.kind: invalid value"]),
        (_adjudication(verdict="approve"), ["adjudication.verdict: invalid value"]),
        (_adjudication(reason=1), ["adjudication.reason: must have type ['string']"]),
        (_adjudication(policy=[]), ["adjudication.policy: must have type ['object']"]),
        (
            _adjudication(assessments={"a": 1}),
            ["adjudication.assessments: must have type ['array']"],
        ),
        (
            _adjudication(assessments=[{}, "s"]),
            ["adjudication.assessments[1]: must have type ['object']"],
        ),
        (
            _adjudication(blocking_findings=[1]),
            ["adjudication.blocking_findings[0]: must have type ['string']"],
        ),
        (
            _adjudication(escalated_findings="x"),
            ["adjudication.escalated_findings: must have type ['array']"],
        ),
        (
            _adjudication(settled_findings=[None]),
            ["adjudication.settled_findings[0]: must have type ['string']"],
        ),
        (_adjudication(extra=True), ["adjudication.extra: unknown member"]),
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
        (_observation(kind="crash"), ["reasoning.observations[0].kind: invalid value"]),
        (_observation(family=1), ["reasoning.observations[0].family: must have type ['string']"]),
        (
            _observation(detail=None),
            ["reasoning.observations[0].detail: must have type ['string']"],
        ),
        (_observation(extra=1), ["reasoning.observations[0].extra: unknown member"]),
        ({"quorum": {"verdicts": {}}}, ["quorum.verdicts: must have type ['array']"]),
        ({"quorum": {"verdicts": [1]}}, ["quorum.verdicts[0]: must have type ['object']"]),
        (_verdict(issuer=1), ["quorum.verdicts[0].issuer: must have type ['string']"]),
        (_verdict(grounded="yes"), ["quorum.verdicts[0].grounded: must have type ['boolean']"]),
        (_verdict(counted=1), ["quorum.verdicts[0].counted: must have type ['boolean']"]),
        (_verdict(severity_max="P5"), ["quorum.verdicts[0].severity_max: invalid value"]),
        (_verdict(severity_max=1), ["quorum.verdicts[0].severity_max: invalid value"]),
        (_verdict(unexpected=True), ["quorum.verdicts[0].unexpected: unknown member"]),
        ({"quorum": {"rule": []}}, ["quorum.rule: must have type ['object']"]),
        (
            _rule(required_signals="2"),
            ["quorum.rule.required_signals: must have type ['integer']"],
        ),
        (
            _rule(required_signals=2.5),
            ["quorum.rule.required_signals: must have type ['integer']"],
        ),
        (
            _rule(requires_western_frontier=1),
            ["quorum.rule.requires_western_frontier: must have type ['boolean']"],
        ),
        (
            _rule(counted_families="claude"),
            ["quorum.rule.counted_families: must have type ['array']"],
        ),
        (
            _rule(counted_families=["claude", 2]),
            ["quorum.rule.counted_families[1]: must have type ['string']"],
        ),
        (_rule(extra=1), ["quorum.rule.extra: unknown member"]),
        (
            {"quorum": {"dissent": {"findings": {}}}},
            ["quorum.dissent.findings: must have type ['array']"],
        ),
        (
            {"quorum": {"dissent": {"findings": [["x"]]}}},
            ["quorum.dissent.findings[0]: must have type ['object']"],
        ),
        (_finding(severity="P7"), ["quorum.dissent.findings[0].severity: invalid value"]),
        (
            _finding(blocking="true"),
            ["quorum.dissent.findings[0].blocking: must have type ['boolean']"],
        ),
        (
            _finding(location=1),
            ["quorum.dissent.findings[0].location: must have type ['string']"],
        ),
        (_finding(text=1), ["quorum.dissent.findings[0].text: must have type ['string']"]),
        (_finding(extra=1), ["quorum.dissent.findings[0].extra: unknown member"]),
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
            "verdicts": [_verdict(counted="x")["quorum"]["verdicts"][0]],
        },
        "reasoning": {"observations": "x"},
        "subject": {"base_sha": 1, "head_sha": 2, "pr_number": "3", "repository": 4},
        "adjudication": _adjudication(kind="x")["adjudication"],
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
    def verdict(**members: Any) -> dict[str, Any]:
        return _verdict(**members)["quorum"]["verdicts"][0]

    doc = {
        "quorum": {
            "verdicts": [
                verdict(issuer=1, counted="x"),
                "not-an-object",
                verdict(severity_max="P9", extra=1),
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
    assert errors == [
        "pre-existing",
        "subject.pr_number: must have type ['integer']",
        # The backstop runs after the declared paths and reports what this fragment omits.
        "subject: missing required member: identifier",
        "subject: missing required member: digest",
    ]


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


def test_one_of_below_a_walked_parent_uses_the_present_branch_unless_the_value_is_a_marker():
    # Every oneOf in the profile is <present block> | absent marker, so branch 0 is used
    # for ordinary values and branch 1 only for a bare ``status``/``reason`` marker.
    leaf = {"oneOf": [{"type": "integer"}, {"type": "string"}]}
    assert _leaf_errors(1, leaf) == []
    for value in ("s", None, []):
        assert _leaf_errors(value, leaf) == ["subject.repository: must have type ['integer']"], (
            repr(value)
        )
    assert _leaf_errors({"status": "absent", "reason": "r"}, leaf) == [
        "subject.repository: must have type ['string']"
    ]


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


# ---------------------------------------------------------------------------
# The schema backstop: every member the schema types, reported once
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("doc", "expected"),
    [
        ({"source": "x"}, ["source: must have type ['object']"]),
        (
            {"source": {"system": 5, "schema": "DecisionReceipt", "receipt_id": "r"}},
            ["source.system: must have type ['string']"],
        ),
        (
            {"quorum": _independence(x=1)},
            ["quorum.independence.x: unknown member"],
        ),
        (
            {"quorum": _independence(distinct_model_families="x")},
            ["quorum.independence.distinct_model_families: must have type ['integer']"],
        ),
        (
            {"quorum": _independence(distinct_model_families=-1)},
            ["quorum.independence.distinct_model_families: outside the schema's permitted range"],
        ),
        (
            {"cruxes": {"status": "present", "items": []}},
            ["cruxes.items: shorter than the schema's minimum of 1"],
        ),
    ],
    ids=[
        "source-non-object",
        "source-members",
        "independence-unknown",
        "independence-type",
        "independence-below-minimum",
        "cruxes-below-min-items",
    ],
)
def test_backstop_types_members_no_declared_extension_path_reaches(
    doc: dict[str, Any], expected: list[str]
) -> None:
    # Only the backstop reaches these members, so the verdict no longer depends on whether
    # the optional ``jsonschema`` extra is installed. The fragments name no complete block,
    # so the block-level ``missing required member`` lines are filtered out here and pinned
    # by test_incomplete_object_shapes_name_each_missing_member instead.
    assert _errors(doc) == []
    assert [e for e in _all_errors(doc) if "missing required member" not in e] == expected


def test_backstop_does_not_restate_a_finding_the_declared_walk_already_named() -> None:
    doc = {"subject": {"repository": 5}}
    assert _errors(doc) == ["subject.repository: must have type ['string']"]
    assert _all_errors(doc) == [
        "subject.repository: must have type ['string']",
        "subject: missing required member: identifier",
        "subject: missing required member: digest",
    ]
