"""Optional v0.2 content members preserve the v0.1 profile."""

import copy
import json
from pathlib import Path

import pytest

import aragora_verify
from aragora_verify import schema
from aragora_verify.verifier import verify
from _fixtures import valid_odr


@pytest.mark.parametrize("version,profile_version", [("0.1", "0.2"), ("0.2", "0.1")])
def test_schema_pairs_version_and_profile(monkeypatch, version, profile_version):
    jsonschema = pytest.importorskip("jsonschema")
    doc = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "docs/specs/examples/example-approved-clean.odr.json"
        ).read_text()
    )
    bundled = schema.load_bundled_schema()
    jsonschema.validate(doc, bundled)
    assert verify(doc).ok
    doc.update(
        odr_version=version,
        profile=f"https://aragora.ai/specs/open-decision-receipt/v{profile_version}",
    )
    monkeypatch.setattr(schema, "_jsonschema_errors", lambda doc: [])
    assert "profile: must match odr_version" in schema.validate_structure(doc)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, bundled)


def test_version_constants_name_v02_while_both_versions_keep_verifying():
    # The constants are informational: validate_structure accepts 0.1 and 0.2 by
    # literal, so re-pointing them never narrows what the verifier reads.
    assert schema.ODR_VERSION == "0.2"
    assert schema.ODR_PROFILE_URI == "https://aragora.ai/specs/open-decision-receipt/v0.2"
    assert aragora_verify.ODR_VERSION == schema.ODR_VERSION
    assert aragora_verify.ODR_PROFILE_URI == schema.ODR_PROFILE_URI
    assert schema.validate_structure(valid_odr()) == []
    assert schema.validate_structure(v02(valid_odr())) == []


def test_bundled_schema_is_cached_and_returned_as_a_fresh_deep_copy():
    first = schema.load_bundled_schema()
    first["x"] = 1
    first["properties"]["subject"]["x"] = 1
    second = schema.load_bundled_schema()
    assert first is not second
    assert "x" not in second and "x" not in second["properties"]["subject"]
    assert schema._load_bundled_schema_cached.cache_info().hits >= 1


def test_v02_schema_members_are_optional():
    bundled = schema.load_bundled_schema()
    props = bundled["properties"]
    assert props["odr_version"]["enum"] == ["0.1", "0.2"]
    assert props["profile"]["enum"] == [
        f"https://aragora.ai/specs/open-decision-receipt/v{v}" for v in ("0.1", "0.2")
    ]
    for version in ("0.1", "0.2"):
        doc = valid_odr()
        doc.update(odr_version=version, profile=props["profile"]["enum"][version == "0.2"])
        assert verify(doc).ok
    quorum = props["quorum"]["oneOf"][0]
    assert {"verdicts", "rule"} <= quorum["properties"].keys()
    assert {"findings", "severity_max", "blocking"} <= quorum["properties"]["dissent"][
        "properties"
    ].keys()
    assert "adjudication" in props and "adjudication" not in bundled["required"]
    for block in (quorum, props["subject"], props["reasoning"]["oneOf"][0]):
        assert not set(block["required"]) & {
            "verdicts",
            "rule",
            "observations",
            "repository",
            "pr_number",
            "head_sha",
            "base_sha",
        }


@pytest.mark.parametrize("version", ["0.1", "0.2"])
def test_versions_and_unknown_members_without_jsonschema(monkeypatch, version):
    monkeypatch.setattr(schema, "_jsonschema_errors", lambda doc: [])
    doc = valid_odr()
    doc.update(
        odr_version=version, profile=f"https://aragora.ai/specs/open-decision-receipt/v{version}"
    )
    assert verify(doc).ok
    wrong = copy.deepcopy(doc)
    wrong["profile"] = "https://aragora.ai/specs/open-decision-receipt/v9"
    assert not verify(wrong).ok
    for member, bad, msg in (
        ("method", 5, "a string"),
        ("reached", "yes", "a boolean"),
        ("independence", 5, "an object"),
        ("supporting_agents", ["claude", 5], "an array of strings"),
    ):
        mutant = copy.deepcopy(doc)
        mutant["quorum"][member] = bad
        assert schema.validate_structure(mutant) == [f"quorum.{member}: must be {msg}"]
        assert not verify(mutant).ok
    doc["unexpected"] = True
    assert not verify(doc).ok
    doc["status"] = "absent"
    assert not verify(doc).ok


def _extension_errors(doc):
    """Collect only the optional-extension errors for ``doc``."""
    errors: list[str] = []
    schema._validate_extensions(errors, doc, schema.load_bundled_schema())
    return errors


# The v0.2 members below are version-scoped: on a "0.1" document each is reported as
# ``not in profile 0.1`` and never shape-checked, so every shape characterization
# declares 0.2 through v02() to reach the check it pins.


def test_extension_type_mismatches_report_the_declared_type_list():
    doc = v02(valid_odr())
    doc["subject"]["repository"] = 5
    doc["subject"]["pr_number"] = "12"
    assert _extension_errors(doc) == [
        "subject.repository: must have type ['string']",
        "subject.pr_number: must have type ['integer']",
    ]


def test_extension_enum_and_const_values_are_rejected():
    doc = v02(valid_odr())
    doc["adjudication"] = {"status": "present", "kind": "wrong.v1", "verdict": "nope"}
    assert _extension_errors(doc) == [
        "adjudication: missing required member: reason",
        "adjudication.status: unknown member",
        "adjudication.kind: invalid value",
        "adjudication.verdict: invalid value",
    ]


def test_extension_list_items_recurse_with_indexed_paths():
    doc = v02(valid_odr())
    doc["adjudication"] = {"blocking_findings": ["ok", 7, None]}
    assert _extension_errors(doc) == [
        "adjudication: missing required member: kind",
        "adjudication: missing required member: verdict",
        "adjudication: missing required member: reason",
        "adjudication.blocking_findings[1]: must have type ['string']",
        "adjudication.blocking_findings[2]: must have type ['string']",
    ]


def test_extension_nested_properties_recurse_in_member_order():
    doc = v02(valid_odr())
    doc["adjudication"] = {"policy": {"anything": 1}, "bogus": 1, "reason": 3}
    assert _extension_errors(doc) == [
        "adjudication: missing required member: kind",
        "adjudication: missing required member: verdict",
        "adjudication.bogus: unknown member",
        "adjudication.reason: must have type ['string']",
    ]


def test_extension_closed_block_reports_unknown_members():
    doc = valid_odr()
    doc["subject"]["mystery"] = 1
    assert _extension_errors(doc) == ["subject.mystery: unknown member"]


def test_extension_open_block_accepts_additional_members():
    doc = valid_odr()
    doc["attestation"] = {
        "disposition": "autonomous",
        "mechanism": {"type": "settlement_status", "extra": 1, "tier": "bad"},
    }
    assert _extension_errors(doc) == [
        "attestation.mechanism.tier: must have type ['integer', 'null']"
    ]


@pytest.mark.parametrize("value", ["not-a-severity", 3])
def test_extension_refs_are_resolved_against_defs(value):
    doc = v02(valid_odr())
    doc["quorum"]["dissent"]["severity_max"] = value
    assert _extension_errors(doc) == ["quorum.dissent.severity_max: invalid value"]


def test_extension_refs_resolve_inside_nested_list_items():
    doc = v02(valid_odr())
    doc["quorum"]["dissent"]["findings"] = [{"severity": "nope", "oops": 1}]
    assert _extension_errors(doc) == [
        "quorum.dissent.findings[0]: missing required member: issuer",
        "quorum.dissent.findings[0]: missing required member: blocking",
        "quorum.dissent.findings[0]: missing required member: text",
        "quorum.dissent.findings[0].severity: invalid value",
        "quorum.dissent.findings[0].oops: unknown member",
    ]


@pytest.mark.parametrize("value", [3, 3.0])
def test_extension_integer_type_accepts_integral_numbers(value):
    doc = v02(valid_odr())
    doc["subject"]["pr_number"] = value
    assert _extension_errors(doc) == []


@pytest.mark.parametrize("value", [True, 3.5, "3", None])
def test_extension_integer_type_rejects_bools_fractions_and_others(value):
    doc = v02(valid_odr())
    doc["subject"]["pr_number"] = value
    assert _extension_errors(doc) == ["subject.pr_number: must have type ['integer']"]


@pytest.mark.parametrize(
    "block,expected",
    [
        ({"status": "absent", "reason": "none recorded"}, []),
        (
            {"status": "absent", "reason": "none recorded", "observations": 5},
            [
                "reasoning.reason: unknown member",
                "reasoning.observations: must have type ['array']",
                "reasoning: missing required member: summary",
                "reasoning.status: invalid value",
            ],
        ),
        ("not-a-dict", ["reasoning: must have type ['object']"]),
    ],
    ids=["strict-marker", "marker-with-members", "not-a-dict"],
)
def test_extension_absent_marker_is_skipped_only_when_it_carries_nothing(block, expected):
    # A strict marker is still skipped outright. A marker that also carries members is
    # neither branch of its oneOf, so the members are checked like a present block's; a
    # non-dict block is typed by the schema backstop rather than passed over.
    doc = v02(valid_odr())
    doc["reasoning"] = block
    assert _extension_errors(doc) == expected


def test_extension_errors_follow_the_declared_path_order():
    doc = v02(valid_odr())
    doc["adjudication"] = {"verdict": "nope"}
    doc["subject"]["repository"] = 5
    doc["reasoning"]["observations"] = 5
    doc["quorum"]["rule"] = 5
    doc["quorum"]["dissent"]["blocking"] = 5
    doc["attestation"] = {"mechanism": {"type": "t", "action": 5}}
    assert _extension_errors(doc) == [
        "adjudication: missing required member: kind",
        "adjudication: missing required member: reason",
        "adjudication.verdict: invalid value",
        "subject.repository: must have type ['string']",
        "reasoning.observations: must have type ['array']",
        "quorum.rule: must have type ['object']",
        "quorum.dissent.blocking: must have type ['boolean']",
        "attestation.mechanism.action: must have type ['string']",
        # Appended by the schema backstop after the declared paths, never interleaved.
        "attestation: missing required member: disposition",
    ]


def test_extension_errors_surface_through_validate_structure(monkeypatch):
    monkeypatch.setattr(schema, "_jsonschema_errors", lambda doc: [])
    assert schema.validate_structure(valid_odr()) == []
    doc = valid_odr()
    doc["subject"]["mystery"] = 1
    assert schema.validate_structure(doc) == ["subject.mystery: unknown member"]


# ---------------------------------------------------------------------------
# Version-scoped membership, adjudication shape, required sub-members and one
# diagnostic per unknown member (spec §4.10 and §8 rule 5).
# ---------------------------------------------------------------------------

V02_PROFILE = "https://aragora.ai/specs/open-decision-receipt/v0.2"
COMPLETE_VERDICT = {
    "issuer": "claude",
    "verdict": "pass",
    "model_family": "claude",
    "model_id": "undisclosed",
}
COMPLETE_RULE = {
    "required_signals": 1,
    "requires_western_frontier": False,
    "western_only_counted": False,
    "counted_families": ["openai"],
}
COMPLETE_FINDING = {"issuer": "claude", "severity": "P3", "blocking": False, "text": "x"}
COMPLETE_OBSERVATION = {"kind": "failure", "family": "grok", "detail": "x"}
MINIMAL_ADJUDICATION = {"kind": "review_adjudication.v1", "verdict": "settle", "reason": "x"}
# The shape AdjudicationResult.to_receipt_dict() emits (aragora is not importable here).
VERBATIM_ADJUDICATION = {
    "kind": "review_adjudication.v1",
    "verdict": "not_applicable",
    "reason": "no findings",
    "groundedness_bar": 0.5,
    "advisory_severity_policy": "cap_at_advisory",
    "assessments": [],
    "settled_findings": [],
    "escalated_findings": [],
    "blocking_findings": [],
}

# Every version-scoped v0.2 member: (path, mutation adding a complete value).
V02_MEMBERS = [
    ("adjudication", lambda d: d.__setitem__("adjudication", dict(MINIMAL_ADJUDICATION))),
    ("subject.repository", lambda d: d["subject"].__setitem__("repository", "o/r")),
    ("subject.pr_number", lambda d: d["subject"].__setitem__("pr_number", 1)),
    ("subject.head_sha", lambda d: d["subject"].__setitem__("head_sha", "a" * 40)),
    ("subject.base_sha", lambda d: d["subject"].__setitem__("base_sha", "b" * 40)),
    ("quorum.verdicts", lambda d: d["quorum"].__setitem__("verdicts", [dict(COMPLETE_VERDICT)])),
    ("quorum.rule", lambda d: d["quorum"].__setitem__("rule", dict(COMPLETE_RULE))),
    (
        "quorum.dissent.findings",
        lambda d: d["quorum"]["dissent"].__setitem__("findings", [dict(COMPLETE_FINDING)]),
    ),
    (
        "quorum.dissent.severity_max",
        lambda d: d["quorum"]["dissent"].__setitem__("severity_max", COMPLETE_FINDING["severity"]),
    ),
    ("quorum.dissent.blocking", lambda d: d["quorum"]["dissent"].__setitem__("blocking", False)),
    (
        "reasoning.observations",
        lambda d: d["reasoning"].__setitem__("observations", [dict(COMPLETE_OBSERVATION)]),
    ),
]
INCOMPLETE_SHAPES = [
    (
        lambda d: d["quorum"].__setitem__("verdicts", [{}]),
        "quorum.verdicts[0]: missing required member: issuer",
    ),
    (
        lambda d: d["quorum"].__setitem__("rule", {}),
        "quorum.rule: missing required member: required_signals",
    ),
    (
        lambda d: d["quorum"]["dissent"].__setitem__("findings", [{"blocking": False}]),
        "quorum.dissent.findings[0]: missing required member: issuer",
    ),
    (
        lambda d: d["reasoning"].__setitem__("observations", [{}]),
        "reasoning.observations[0]: missing required member: kind",
    ),
    (
        lambda d: d.__setitem__("adjudication", {"status": "absent"}),
        "adjudication: missing required member: kind",
    ),
    (lambda d: d.__setitem__("adjudication", {}), "adjudication: missing required member: kind"),
    (
        lambda d: d.__setitem__("adjudication", {"status": "absent", "reason": "none"}),
        "adjudication.status: unknown member",
    ),
]
ABSENT = {"status": "absent", "reason": "not supplied"}
# An absent marker that also carries members is neither branch of its oneOf, so those
# members are checked like a present block's: (version, mutation, one expected line).
MARKERS_WITH_MEMBERS = [
    (
        "0.1",
        lambda d: d["subject"].update(ABSENT, pr_number=1),
        "subject.pr_number: not in profile 0.1",
    ),
    ("0.1", lambda d: d.update(quorum={**ABSENT, "rule": {}}), "quorum.rule: not in profile 0.1"),
    (
        "0.2",
        lambda d: d["quorum"]["dissent"].update(ABSENT, findings=[{}]),
        "quorum.dissent.findings[0]: missing required member: issuer",
    ),
]
MARKER_IDS = [f"{v}-{expected.split(':')[0]}" for v, _, expected in MARKERS_WITH_MEMBERS]


def v01_or_v02(version):
    return valid_odr() if version == "0.1" else v02(valid_odr())


def v02(doc):
    doc.update(odr_version="0.2", profile=V02_PROFILE)
    return doc


@pytest.fixture
def walker_only(monkeypatch):
    monkeypatch.setattr(schema, "_jsonschema_errors", lambda doc: [])


@pytest.mark.parametrize("path,mutate", V02_MEMBERS, ids=[path for path, _ in V02_MEMBERS])
def test_v02_member_alone_on_v01_document_is_not_in_profile(walker_only, path, mutate):
    doc = valid_odr()
    mutate(doc)
    assert schema.validate_structure(doc) == [f"{path}: not in profile 0.1"]
    result = verify(doc)
    assert not result.ok
    assert f"{path}: not in profile 0.1" in result.checks[0].detail
    doc = v02(valid_odr())
    mutate(doc)
    assert schema.validate_structure(doc) == [] and verify(doc).ok


def test_all_v02_members_on_v01_document_name_each_path_once(walker_only):
    doc = valid_odr()
    for _path, mutate in V02_MEMBERS:
        mutate(doc)
    expected = sorted(f"{path}: not in profile 0.1" for path, _ in V02_MEMBERS)
    assert sorted(schema.validate_structure(doc)) == expected
    assert verify(v02(doc)).ok


def test_mechanism_extras_stay_legal_on_v01_documents(walker_only):
    doc = valid_odr()
    doc["attestation"]["mechanism"] = {"type": "merge-quorum", "tier": 2, "policy_version": 3}
    assert schema.validate_structure(doc) == []
    assert verify(doc).ok


@pytest.mark.parametrize("version,mutate,expected", MARKERS_WITH_MEMBERS, ids=MARKER_IDS)
def test_absent_marker_with_members_is_checked_like_a_present_block(
    walker_only, version, mutate, expected
):
    mutate(doc := v01_or_v02(version))
    assert expected in schema.validate_structure(doc)
    result = verify(doc)
    assert not result.ok and expected in result.checks[0].detail


@pytest.mark.parametrize("value", [MINIMAL_ADJUDICATION, VERBATIM_ADJUDICATION])
def test_adjudication_minimal_and_verbatim_shapes_verify(walker_only, value):
    doc = v02(valid_odr())
    doc["adjudication"] = copy.deepcopy(value)
    assert schema.validate_structure(doc) == []
    assert verify(doc).ok


@pytest.mark.parametrize(
    "mutate,expected", INCOMPLETE_SHAPES, ids=[e for _, e in INCOMPLETE_SHAPES]
)
def test_incomplete_v02_object_shapes_fail(walker_only, mutate, expected):
    doc = v02(valid_odr())
    mutate(doc)
    errors = schema.validate_structure(doc)
    assert expected in errors
    result = verify(doc)
    assert not result.ok and expected in result.checks[0].detail


def test_unknown_members_reported_once_without_jsonschema(walker_only):
    doc = v02(valid_odr())
    doc["not_in_profile"] = 1
    doc["subject"]["bogus"] = 1
    text = "\n".join(schema.validate_structure(doc))
    assert text.count("subject.bogus: unknown member") == 1
    assert text.count("not_in_profile") == 1
    assert not verify(doc).ok


def test_unknown_members_reported_once_with_jsonschema():
    pytest.importorskip("jsonschema")
    doc = v02(valid_odr())
    doc["not_in_profile"] = 1
    doc["subject"]["bogus"] = 1
    result = verify(doc)
    text = "\n".join(check.detail for check in result.checks)
    assert not result.ok
    assert text.count("bogus") == 1 and text.count("subject.bogus: unknown member") == 1
    assert text.count("not_in_profile") == 1


def test_missing_required_members_reported_once_with_jsonschema():
    pytest.importorskip("jsonschema")
    doc = v02(valid_odr())
    doc["adjudication"] = {"status": "absent"}
    doc["quorum"]["verdicts"] = [{}]
    errors = schema.validate_structure(doc)
    assert [e for e in errors if "required" in e] == [
        "adjudication: missing required member: kind",
        "adjudication: missing required member: verdict",
        "adjudication: missing required member: reason",
        "quorum.verdicts[0]: missing required member: issuer",
        "quorum.verdicts[0]: missing required member: verdict",
        "quorum.verdicts[0]: missing required member: model_family",
        "quorum.verdicts[0]: missing required member: model_id",
    ]
    assert "adjudication.status: unknown member" in errors
    assert not [e for e in errors if e.startswith("schema[adjudication]")]
    del doc["subject"]
    assert "missing required member: subject" in schema.validate_structure(doc)
    assert not [e for e in schema.validate_structure(doc) if "'subject' is a required" in e]


def test_walker_reaches_source_and_jsonschema_does_not_restate_it():
    pytest.importorskip("jsonschema")
    doc = valid_odr()
    doc["source"] = {
        "system": "aragora",
        "schema": "DecisionReceipt",
        "receipt_id": "r",
        "extra": 1,
    }
    assert schema.validate_structure(doc) == ["source.extra: unknown member"]


def test_v01_with_v02_members_has_one_line_per_path_with_jsonschema():
    pytest.importorskip("jsonschema")
    doc = valid_odr()
    for _path, mutate in V02_MEMBERS:
        mutate(doc)
    expected = sorted(f"{path}: not in profile 0.1" for path, _ in V02_MEMBERS)
    assert sorted(schema.validate_structure(doc)) == expected


def test_schema_requires_the_non_optional_sub_members():
    bundled = schema.load_bundled_schema()
    adjudication = bundled["properties"]["adjudication"]
    assert sorted(adjudication["required"]) == ["kind", "reason", "verdict"]
    assert "status" not in adjudication["properties"]
    assert {"groundedness_bar", "advisory_severity_policy"} <= adjudication["properties"].keys()
    quorum = bundled["properties"]["quorum"]["oneOf"][0]["properties"]
    reasoning = bundled["properties"]["reasoning"]["oneOf"][0]["properties"]
    assert sorted(quorum["verdicts"]["items"]["required"]) == sorted(COMPLETE_VERDICT)
    assert sorted(quorum["rule"]["required"]) == sorted(COMPLETE_RULE)
    findings = quorum["dissent"]["properties"]["findings"]["items"]
    assert sorted(findings["required"]) == sorted(COMPLETE_FINDING)
    assert sorted(reasoning["observations"]["items"]["required"]) == sorted(COMPLETE_OBSERVATION)
    clause = next(c for c in bundled["allOf"] if c["if"].get("required") == ["odr_version"])
    assert clause["if"]["properties"]["odr_version"] == {"const": "0.1"}
    assert "attestation" not in clause["then"]["properties"]


@pytest.mark.parametrize("path,mutate", V02_MEMBERS, ids=[path for path, _ in V02_MEMBERS])
def test_version_scoping_agrees_with_jsonschema(path, mutate):
    jsonschema = pytest.importorskip("jsonschema")
    bundled = schema.load_bundled_schema()
    doc = valid_odr()
    mutate(doc)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, bundled)
    jsonschema.validate(v02(doc), bundled)


@pytest.mark.parametrize(
    "mutate,expected", INCOMPLETE_SHAPES, ids=[e for _, e in INCOMPLETE_SHAPES]
)
def test_incomplete_shapes_agree_with_jsonschema(mutate, expected):
    jsonschema = pytest.importorskip("jsonschema")
    doc = v02(valid_odr())
    mutate(doc)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, schema.load_bundled_schema())


@pytest.mark.parametrize("version,mutate,expected", MARKERS_WITH_MEMBERS, ids=MARKER_IDS)
def test_markers_with_members_agree_with_jsonschema(version, mutate, expected):
    jsonschema = pytest.importorskip("jsonschema")
    mutate(doc := v01_or_v02(version))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, schema.load_bundled_schema())
