"""Requested v0.2 consistency and signature policy, with v0.1 parity."""

import copy
import base64
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "aragora-verify/src"))

from aragora_verify import verify  # noqa: E402
from aragora_verify import schema  # noqa: E402
from aragora_verify.jcs import jcs_canonicalize as standalone_jcs  # noqa: E402
from aragora.gauntlet.odr_export import (
    decision_receipt_to_odr,
    jcs_canonicalize,
    odr_content_digest,
)  # noqa: E402
from aragora.gauntlet.odr_verify import verify_odr_document  # noqa: E402
from aragora.gauntlet.odr_signing import sign_odr_receipt  # noqa: E402
from aragora.gauntlet.receipt_models import DecisionReceipt  # noqa: E402
from tests.gauntlet.odr_test_keys import odr_test_key  # noqa: E402


def document():
    doc = decision_receipt_to_odr(
        DecisionReceipt.from_dict(
            {"receipt_id": "v02", "consensus_proof": {"reached": True, "confidence": 1.0}}
        ),
        odr_version="0.2",
    )
    quorum = doc["quorum"]
    quorum["participants"] = [
        {"agent": "claude", "model_family": "anthropic", "model_id": "undisclosed"}
    ]
    quorum["supporting_agents"] = ["claude"]
    quorum["verdicts"] = [
        {
            "issuer": "claude",
            "verdict": "pass",
            "model_family": "anthropic",
            "model_id": "undisclosed",
        }
    ]
    quorum["rule"] = {
        "required_signals": 1,
        "requires_western_frontier": True,
        "western_only_counted": True,
        "counted_families": ["claude"],
    }
    quorum["dissent"].update(
        findings=[{"issuer": "claude", "severity": "P2", "blocking": False, "text": "Review"}],
        severity_max="P2",
        blocking=False,
    )
    return doc


def legacy():
    return json.loads((ROOT / "docs/specs/examples/example-approved-clean.odr.json").read_text())


@pytest.fixture(params=[verify_odr_document, verify])
def engine(request):
    return request.param


@pytest.mark.parametrize(
    "path,value,name",
    [
        ("quorum.verdicts.0.issuer", "mallory", "verdicts_consistency"),
        ("quorum.supporting_agents", ["mallory"], "quorum_consistency"),
        ("quorum.dissent.dissenting_agents", ["mallory"], "quorum_consistency"),
        ("quorum.dissent.severity_max", "P0", "dissent_consistency"),
        ("quorum.dissent.blocking", True, "dissent_consistency"),
        ("quorum.dissent.findings.0.blocking", True, "dissent_consistency"),
        ("quorum.dissent", 5, "schema_conformance"),
        ("quorum.dissent", "abc", "schema_conformance"),
        ("quorum.participants", "abc", "schema_conformance"),
        ("quorum.participants", {}, "schema_conformance"),
        ("quorum.participants.0.agent", [], "schema_conformance"),
        ("not_in_profile", 1, "schema_conformance"),
    ],
)
def test_v02_consistency_first_and_v01_unchanged(engine, path, value, name, monkeypatch):
    monkeypatch.setattr(schema, "_jsonschema_errors", lambda doc: [])
    assert engine(legacy()).ok
    key = odr_test_key()
    doc = sign_odr_receipt(document(), key, issuer="aragora")
    target = doc
    *parents, member = path.split(".")
    for part in parents:
        target = target[int(part)] if isinstance(target, list) else target[part]
    target[member] = value
    result = engine(doc, public_key=key.public_key())
    check = next(c for c in result.checks if c.status == "fail")
    assert check.name == name
    if name == "verdicts_consistency":
        assert "mallory" in check.detail


def test_v02_optional_summaries_rule_warning_and_digest(engine):
    doc = document()
    dissent = doc["quorum"]["dissent"]
    dissent["findings"][0].update(severity="P1", blocking=True)
    dissent["severity_max"] = "P1"
    assert next(c.name for c in engine(doc).checks if c.status == "fail") == "dissent_consistency"
    for member in ("findings", "severity_max", "blocking"):
        del dissent[member]
    assert engine(doc).ok
    assert "ODR v0.2" in engine(doc).checks[0].detail
    doc["quorum"]["reached"] = False
    before = copy.deepcopy(doc)
    result = engine(doc)
    assert result.ok and any("reached" in w for w in result.warnings)
    assert doc == before
    content = {k: v for k, v in doc.items() if k != "signatures"}
    assert jcs_canonicalize(content) == standalone_jcs(content)
    assert result.odr_digest == odr_content_digest(doc) == verify(doc).odr_digest
    doc["quorum"]["method"] = "merge-quorum"
    doc["quorum"]["dissent"].update(present=True, dissenting_agents=["claude"])
    assert not any("reached" in w for w in engine(doc).warnings)
    doc["quorum"]["dissent"].update(present=False, dissenting_agents=[])
    doc["quorum"]["supporting_agents"] = []
    assert not any("reached" in w for w in engine(doc).warnings)
    assert "ODR v0.1" in engine(legacy()).checks[0].detail


def test_v02_per_finding_blocking_and_v01(engine):
    key = odr_test_key()
    doc = document()
    dissent = doc["quorum"]["dissent"]
    dissent["findings"][0]["severity"] = "P1"
    dissent.update(severity_max="P1", blocking=True)
    result = engine(sign_odr_receipt(doc, key, issuer="aragora"), public_key=key.public_key())
    fails = [c for c in result.checks if c.status == "fail"]
    assert [c.name for c in fails] == ["dissent_consistency"]
    assert fails[0].detail == "quorum.dissent.findings[0].blocking: expected True for P1"
    assert engine(legacy()).ok


@pytest.mark.parametrize(
    "timestamp",
    [
        "2000-01-01 00:00:00Z",
        "20000101T000000Z",
        "2000-01-01T00:00:00Z",
        "2000-01-01T00:00:00+00:00",
    ],
)
def test_v02_signer_normalizes_utc_output(timestamp, engine):
    key = odr_test_key()
    doc = sign_odr_receipt(
        document(),
        key,
        issuer="aragora",
        signed_at=timestamp,
        expires_at=timestamp.replace("2000", "2001"),
    )
    entry = doc["signatures"][0]
    assert entry["signed_at"] == "2000-01-01T00:00:00+00:00"
    assert entry["expires_at"] == "2001-01-01T00:00:00+00:00"
    assert engine(doc, public_key=key.public_key()).ok
    assert not any("expire" in w for w in engine(doc).warnings)
    assert not engine(doc, public_key=key.public_key(), strict_expiry=True).ok
    legacy = decision_receipt_to_odr(
        DecisionReceipt.from_dict({"receipt_id": "legacy"}), odr_version="0.1"
    )
    assert engine(sign_odr_receipt(legacy, key), public_key=key.public_key()).ok


@pytest.mark.parametrize("version", ["0.1", "0.2"])
@pytest.mark.parametrize("foreign", [False, True])
@pytest.mark.parametrize("signature", ["copy", "zero", "undecodable"])
def test_v02_multi_signature_warnings_and_legacy(version, foreign, signature, engine):
    key = odr_test_key()
    doc = document() if version == "0.2" else legacy()
    doc = sign_odr_receipt(doc, key, **({"issuer": "aragora"} if version == "0.2" else {}))
    extra = dict(doc["signatures"][0])
    if foreign:
        extra["key_id"] = "ed25519-feedfacefeedface"
        if version == "0.2":
            extra["expires_at"] = "1999-01-01T00:00:00Z"
    if signature != "copy":
        extra["signature"] = base64.b64encode(bytes(64)).decode() if signature == "zero" else "bad"
    doc["signatures"].insert(0, extra)
    result = engine(doc, public_key=key.public_key(), strict_expiry=True)
    assert result.ok is (foreign or signature == "copy")
    assert not any("expire" in w for w in result.warnings)
    mismatch = [w for w in result.warnings if "key_id_mismatch" in w]
    assert len(mismatch) == int(foreign)
    if foreign:
        assert extra["key_id"] in mismatch[0]
        doc["signatures"].pop()
        assert not engine(doc, public_key=key.public_key()).ok


def test_v02_expiry_clock_parity_and_legacy(engine):
    key = odr_test_key()
    doc = sign_odr_receipt(
        document(),
        key,
        issuer="aragora",
        signed_at="2000-01-01T00:00:00Z",
        expires_at="2001-01-01T00:00:00Z",
    )
    for year, expired in [(2000, False), (2001, True), (2002, True)]:
        now = datetime(year, 1, 1, tzinfo=timezone.utc)
        result = engine(doc, public_key=key.public_key(), now=now)
        assert result.ok and any("expire" in w for w in result.warnings) is expired
        assert (
            engine(doc, public_key=key.public_key(), now=now, strict_expiry=True).ok is not expired
        )
    signed = sign_odr_receipt(legacy(), key)
    assert engine(signed, public_key=key.public_key(), strict_expiry=True).ok
