"""Both verifiers accept new optional content and unchanged v0.1 receipts."""

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "aragora-verify" / "src"))

from aragora_verify import schema, verify  # noqa: E402
from aragora.gauntlet.odr_export import decision_receipt_to_odr  # noqa: E402
from aragora.gauntlet.odr_verify import verify_odr_document  # noqa: E402
from aragora.gauntlet.receipt_models import DecisionReceipt  # noqa: E402
from aragora.gauntlet.odr_signing import sign_odr_receipt  # noqa: E402
from tests.gauntlet.odr_test_keys import odr_test_key  # noqa: E402


def legacy_document():
    return json.loads((ROOT / "docs/specs/examples/example-approved-clean.odr.json").read_text())


def receipt():
    return DecisionReceipt.from_dict(
        {
            "receipt_id": "test",
            "verdict_reasoning": "Source reasoning",
            "consensus_proof": {"reached": True, "confidence": 1.0},
        }
    )


def test_default_is_v01_and_matches_origin_shape():
    source = receipt()
    source.settlement_metadata = {"repo": "o/r", "pr": 1, "odr": {"adjudication": {}}}
    doc = decision_receipt_to_odr(source)
    assert set(doc) == set(
        "odr_version profile receipt_id issued_at subject claim reasoning quorum "
        "confidence cruxes attestation routing signatures source".split()
    )
    assert doc["odr_version"] == "0.1"
    assert doc["profile"] == "https://aragora.ai/specs/open-decision-receipt/v0.1"
    assert not {"repository", "pr_number", "head_sha", "base_sha"} & doc["subject"].keys()
    assert verify(doc).ok and verify_odr_document(doc).ok


def test_requested_v02_changes_only_version_and_profile():
    source = receipt()
    default = decision_receipt_to_odr(source)
    requested = decision_receipt_to_odr(source, odr_version="0.2")
    default.update(odr_version="0.2", profile="https://aragora.ai/specs/open-decision-receipt/v0.2")
    assert requested == default


@pytest.mark.parametrize("version", ["0.3", "", None])
def test_unknown_version_raises_value_error(version):
    with pytest.raises(ValueError, match=r"0\.1.*0\.2"):
        decision_receipt_to_odr(receipt(), odr_version=version)


def test_emitter_v02_preserves_v01_absence():
    legacy = legacy_document()
    assert verify(legacy).ok and verify_odr_document(legacy).ok
    doc = decision_receipt_to_odr(receipt(), odr_version="0.2")
    assert doc["odr_version"] == "0.2"
    assert doc["profile"].endswith("/v0.2")
    assert doc["signatures"] == [] and "adjudication" not in doc
    assert not {"repository", "pr_number", "head_sha"} & doc["subject"].keys()
    assert verify(doc).ok and verify_odr_document(doc).ok


def test_findings_do_not_change_legacy_dissent_present():
    doc = decision_receipt_to_odr(receipt(), odr_version="0.2")
    assert doc["quorum"]["dissent"]["present"] is False
    finding = {"issuer": "claude", "severity": "P3", "blocking": False, "text": "[P3] advisory"}
    doc["quorum"]["dissent"].update(findings=[finding], severity_max="P3", blocking=False)
    assert verify(doc).ok and verify_odr_document(doc).ok


@pytest.mark.parametrize("reasoning", ["", "Real source reasoning"])
def test_observations_preserve_legacy_reasoning_marker(reasoning):
    source = DecisionReceipt.from_dict({"receipt_id": "test", "verdict_reasoning": reasoning})
    doc = decision_receipt_to_odr(source, odr_version="0.2")
    if reasoning:
        doc["reasoning"]["observations"] = [{"kind": "failure", "family": "grok", "detail": "x"}]
        assert doc["reasoning"]["summary"] == reasoning
    else:
        assert doc["reasoning"]["status"] == "absent"
        assert "observations" not in doc["reasoning"]
    assert verify(doc).ok and verify_odr_document(doc).ok


def test_extension_walkers_accept_integral_numbers_but_not_booleans():
    from aragora.gauntlet.odr_verify import _validate_extensions

    doc = decision_receipt_to_odr(receipt(), odr_version="0.2")
    assert verify(doc).ok and verify_odr_document(doc).ok
    bundled = schema.load_bundled_schema()
    assert bundled["properties"]["subject"]["properties"]["pr_number"] == {"type": "integer"}
    for walker in (_validate_extensions, schema._validate_extensions):
        for value, ok in ((1, True), (1.0, True), (1.5, False), (True, False)):
            doc["subject"]["pr_number"] = value
            errors: list[str] = []
            walker(errors, doc, bundled)
            assert bool(errors) == (not ok), f"{walker.__module__}: {value!r}"


@pytest.mark.parametrize("version", ["0.1", "0.2"])
def test_three_member_signatures_verify_for_both_versions(version):
    doc = decision_receipt_to_odr(receipt(), odr_version=version)
    assert verify(doc).ok and verify_odr_document(doc).ok
    key = odr_test_key()
    signed = sign_odr_receipt(doc, key)
    assert set(signed["signatures"][0]) == {"alg", "key_id", "signature"}
    assert verify(signed, public_key=key.public_key()).ok
    assert verify_odr_document(signed, public_key=key.public_key()).ok


@pytest.mark.parametrize("version", ["0.1", "0.2"])
@pytest.mark.parametrize(
    "member", ["verdicts", "rule", "findings", "observations", "adjudication", "subject"]
)
def test_optional_content_types_and_unknowns(monkeypatch, version, member):
    monkeypatch.setattr(schema, "_jsonschema_errors", lambda doc: [])
    doc = decision_receipt_to_odr(receipt(), odr_version=version)
    assert verify(doc).ok and verify_odr_document(doc).ok
    blocks = {
        "verdicts": (doc["quorum"], [{"issuer": "reviewer", "counted": False}]),
        "rule": (doc["quorum"], {"required_signals": 2, "counted_families": ["claude"]}),
        "findings": (
            doc["quorum"]["dissent"],
            [{"issuer": "reviewer", "severity": "P1", "blocking": True, "text": "finding"}],
        ),
        "observations": (
            doc["reasoning"],
            [{"kind": "timeout", "family": "grok", "detail": "deadline"}],
        ),
        "adjudication": (
            doc,
            {"kind": "review_adjudication.v1", "verdict": "settle", "reason": "x"},
        ),
        "subject": (
            doc,
            {**doc["subject"], "repository": "o/r", "pr_number": 1, "head_sha": "a" * 40},
        ),
    }
    parent, value = blocks[member]
    parent[member] = copy.deepcopy(value)
    assert verify(doc).ok and verify_odr_document(doc).ok
    target = parent[member][0] if isinstance(value, list) else parent[member]
    target["unexpected"] = True
    assert not verify(doc).ok and not verify_odr_document(doc).ok
    parent[member] = 42
    assert not verify(doc).ok and not verify_odr_document(doc).ok
