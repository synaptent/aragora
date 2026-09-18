"""Optional v0.2 content members preserve the v0.1 profile."""

import copy
import json
from pathlib import Path

import pytest

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
    doc["unexpected"] = True
    assert not verify(doc).ok
    doc["status"] = "absent"
    assert not verify(doc).ok


def _extension_errors(doc):
    """Collect only the optional-extension errors for ``doc``."""
    errors: list[str] = []
    schema._validate_extensions(errors, doc, schema.load_bundled_schema())
    return errors


def test_extension_type_mismatches_report_the_declared_type_list():
    doc = valid_odr()
    doc["subject"]["repository"] = 5
    doc["subject"]["pr_number"] = "12"
    assert _extension_errors(doc) == [
        "subject.repository: must have type ['string']",
        "subject.pr_number: must have type ['integer']",
    ]


def test_extension_enum_and_const_values_are_rejected():
    doc = valid_odr()
    doc["adjudication"] = {"status": "present", "kind": "wrong.v1", "verdict": "nope"}
    assert _extension_errors(doc) == [
        "adjudication.kind: invalid value",
        "adjudication.verdict: invalid value",
    ]


def test_extension_list_items_recurse_with_indexed_paths():
    doc = valid_odr()
    doc["adjudication"] = {"blocking_findings": ["ok", 7, None]}
    assert _extension_errors(doc) == [
        "adjudication.blocking_findings[1]: must have type ['string']",
        "adjudication.blocking_findings[2]: must have type ['string']",
    ]


def test_extension_nested_properties_recurse_in_member_order():
    doc = valid_odr()
    doc["adjudication"] = {"policy": {"anything": 1}, "bogus": 1, "reason": 3}
    assert _extension_errors(doc) == [
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
    doc = valid_odr()
    doc["quorum"]["dissent"]["severity_max"] = value
    assert _extension_errors(doc) == ["quorum.dissent.severity_max: invalid value"]


def test_extension_refs_resolve_inside_nested_list_items():
    doc = valid_odr()
    doc["quorum"]["dissent"]["findings"] = [{"severity": "nope", "oops": 1}]
    assert _extension_errors(doc) == [
        "quorum.dissent.findings[0].severity: invalid value",
        "quorum.dissent.findings[0].oops: unknown member",
    ]


@pytest.mark.parametrize("value", [3, 3.0])
def test_extension_integer_type_accepts_integral_numbers(value):
    doc = valid_odr()
    doc["subject"]["pr_number"] = value
    assert _extension_errors(doc) == []


@pytest.mark.parametrize("value", [True, 3.5, "3", None])
def test_extension_integer_type_rejects_bools_fractions_and_others(value):
    doc = valid_odr()
    doc["subject"]["pr_number"] = value
    assert _extension_errors(doc) == ["subject.pr_number: must have type ['integer']"]


@pytest.mark.parametrize(
    "block", [{"status": "absent", "reason": "none recorded", "observations": 5}, "not-a-dict"]
)
def test_extension_absent_and_non_dict_blocks_are_skipped(block):
    doc = valid_odr()
    doc["reasoning"] = block
    assert _extension_errors(doc) == []


def test_extension_errors_follow_the_declared_path_order():
    doc = valid_odr()
    doc["adjudication"] = {"verdict": "nope"}
    doc["subject"]["repository"] = 5
    doc["reasoning"]["observations"] = 5
    doc["quorum"]["rule"] = 5
    doc["quorum"]["dissent"]["blocking"] = 5
    doc["attestation"] = {"mechanism": {"type": "t", "action": 5}}
    assert _extension_errors(doc) == [
        "adjudication.verdict: invalid value",
        "subject.repository: must have type ['string']",
        "reasoning.observations: must have type ['array']",
        "quorum.rule: must have type ['object']",
        "quorum.dissent.blocking: must have type ['boolean']",
        "attestation.mechanism.action: must have type ['string']",
    ]


def test_extension_errors_surface_through_validate_structure(monkeypatch):
    monkeypatch.setattr(schema, "_jsonschema_errors", lambda doc: [])
    assert schema.validate_structure(valid_odr()) == []
    doc = valid_odr()
    doc["subject"]["mystery"] = 1
    assert schema.validate_structure(doc) == ["subject.mystery: unknown member"]
