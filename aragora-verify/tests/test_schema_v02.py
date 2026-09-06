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
