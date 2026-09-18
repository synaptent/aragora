"""Verifier behavior: schema, signatures, quorum consistency, chain, warnings."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from aragora_verify import compute_key_id, load_public_key, verify
from aragora_verify.cli import main
from aragora_verify.jcs import odr_content_digest, odr_signature_message
from aragora_verify.verifier import FAIL, PASS, SKIP, WARN

from _fixtures import make_keypair, sign_odr, valid_odr


def _v02_signed(doc=None):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    # Public test material, identical to tests/gauntlet/odr_test_keys.py.
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    if doc is None:
        doc = valid_odr(odr_version="0.2")
        doc["quorum"]["dissent"].update(
            findings=[{"issuer": "claude", "severity": "P2", "blocking": False, "text": "Review"}],
            severity_max="P2",
            blocking=False,
        )
    entry = {
        "alg": "Ed25519",
        "key_id": compute_key_id(key.public_key()),
        "issuer": "aragora",
        "signed_at": "2000-01-01T00:00:00Z",
        "expires_at": "2001-01-01T00:00:00Z",
    }
    entry["signature"] = base64.b64encode(
        key.sign(odr_signature_message(odr_content_digest(doc), "0.2", entry))
    ).decode()
    doc["signatures"] = [entry]
    return doc, key


def test_v02_per_finding_blocking_consistency():
    doc = valid_odr(odr_version="0.2")
    doc["quorum"]["dissent"].update(
        findings=[{"issuer": "claude", "severity": "P1", "blocking": False, "text": "Review"}],
        severity_max="P1",
        blocking=True,
    )
    doc, key = _v02_signed(doc)
    fails = [c for c in verify(doc, public_key=key.public_key()).checks if c.status == FAIL]
    assert [c.name for c in fails] == ["dissent_consistency"]
    assert fails[0].detail == "quorum.dissent.findings[0].blocking: expected True for P1"
    assert verify(valid_odr()).ok


@pytest.mark.parametrize("member,value", [("severity_max", "P0"), ("blocking", True)])
def test_v02_dissent_consistency_precedes_signature(member, value):
    doc, key = _v02_signed()
    doc["quorum"]["dissent"][member] = value
    result = verify(doc, public_key=key.public_key())
    assert next(c.name for c in result.checks if c.status == FAIL) == "dissent_consistency"
    assert verify(valid_odr()).ok


def test_v02_cli_flags_trail_and_issuer(tmp_path, capsys):
    doc, key = _v02_signed()
    receipt, pub = tmp_path / "r.json", tmp_path / "pub.pem"
    receipt.write_text(json.dumps(doc))
    pub.write_bytes(_pubkey_bytes(key.public_key()))
    base = [str(receipt), "--pubkey", str(pub)]
    assert main(base + ["--require-issuer", "aragora"]) == 0
    output = capsys.readouterr().out
    assert output.splitlines().count("Dissent trail") == 1
    assert "[P2] claude (advisory): Review" in output
    assert output.rstrip().endswith(f"=> VERIFIED (key_id={doc['signatures'][0]['key_id']})")
    assert main(base + ["--strict-expiry"]) == 1
    assert main(base + ["--strict-expiry", "--now", "2000-06-01T00:00:00Z"]) == 0
    capsys.readouterr()
    assert main(base + ["--now", "2000-06-01T00:00:00Z", "--json"]) == 0
    assert not any("expire" in w for w in json.loads(capsys.readouterr().out)["warnings"])
    for timestamp in ("bad", "2000-01-01T00:00:00"):
        with pytest.raises(SystemExit) as exc:
            main(base + ["--now", timestamp])
        assert exc.value.code == 2
    assert main(base + ["--require-issuer", "missing"]) == 1
    assert main([str(receipt), "--require-issuer", "aragora"]) == 1
    assert main([str(receipt)]) == 3
    capsys.readouterr()
    assert main(base + ["--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["key_id"] == compute_key_id(key.public_key())
    assert result["dissent_trail"] == ["[P2] claude (advisory): Review"]
    doc = sign_odr(valid_odr(), key)
    doc["signatures"][0]["issuer"] = "aragora"
    receipt.write_text(json.dumps(doc))
    assert main(base + ["--require-issuer", "aragora"]) == 1
    receipt.write_text(json.dumps(valid_odr()))
    assert main([str(receipt)]) == 0
    assert "(no dissent recorded)" in capsys.readouterr().out
    assert main([str(receipt), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["dissent_trail"] == [] and result["key_id"] is None


def test_v02_issuer_requires_verifying_entry():
    doc, key = _v02_signed()
    doc["signatures"].insert(
        0, dict(doc["signatures"][0], issuer="forged", key_id="ed25519-feedfacefeedface")
    )
    assert verify(doc, public_key=key.public_key(), require_issuer="aragora").ok
    assert not verify(doc, public_key=key.public_key(), require_issuer="forged").ok
    assert not verify(doc, public_key=make_keypair()[1], require_issuer="aragora").ok
    assert not verify(valid_odr(), require_issuer="aragora").ok


def test_v02_schema_labels_and_help(capsys):
    doc, key = _v02_signed()
    assert "ODR v0.2" in _check(verify(doc), "schema_conformance").detail
    example = (
        Path(__file__).resolve().parents[2] / "docs/specs/examples/example-approved-clean.odr.json"
    )
    legacy = json.loads(example.read_text()) if example.exists() else valid_odr()
    assert "ODR v0.1" in _check(verify(legacy), "schema_conformance").detail
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])
    assert exit_info.value.code == 0
    assert "v0.2" in capsys.readouterr().out


@pytest.mark.parametrize("severity", ["P0", "P1", "P2", "P3", None])
def test_v02_adjudication_trail(severity, tmp_path, capsys):
    doc = valid_odr(odr_version="0.2")
    blocking = severity in ("P0", "P1")
    doc["quorum"]["dissent"]["findings"] = (
        [{"issuer": "claude", "severity": severity, "blocking": blocking, "text": "Finding"}]
        if severity
        else []
    )
    doc["adjudication"] = {
        "kind": "review_adjudication.v1",
        "verdict": "settle",
        "reason": "Reviewed",
    }
    doc, key = _v02_signed(doc)
    path = tmp_path / "adjudicated.json"
    pub = tmp_path / "pub.pem"
    path.write_text(json.dumps(doc))
    pub.write_bytes(_pubkey_bytes(key.public_key()))
    assert main([str(path), "--pubkey", str(pub)]) == 0
    lines = capsys.readouterr().out.splitlines()
    label = "blocking" if blocking else "advisory"
    finding = f"[{severity}] claude ({label}): Finding" if severity else "(no dissent recorded)"
    assert lines[-4:] == [
        "Dissent trail",
        finding,
        "Adjudication: settle — Reviewed",
        f"  => VERIFIED (key_id={compute_key_id(key.public_key())})",
    ]
    assert verify(valid_odr()).ok


def _check(result, name):
    return next(c for c in result.checks if c.name == name)


# --- schema conformance ----------------------------------------------------


def test_valid_unsigned_receipt_passes_structurally() -> None:
    result = verify(valid_odr())
    assert result.ok is True
    assert _check(result, "schema_conformance").status == PASS
    assert _check(result, "signature").status == WARN  # unsigned


def test_missing_required_member_fails_schema() -> None:
    doc = valid_odr()
    del doc["claim"]
    result = verify(doc)
    assert result.ok is False
    assert _check(result, "schema_conformance").status == FAIL
    assert result.odr_digest == ""


def test_wrong_profile_uri_fails() -> None:
    doc = valid_odr()
    doc["profile"] = "https://evil.example/profile"
    result = verify(doc)
    assert result.ok is False
    assert "profile" in _check(result, "schema_conformance").detail


def test_routing_must_be_reserved() -> None:
    doc = valid_odr()
    doc["routing"] = {"status": "active"}
    result = verify(doc)
    assert result.ok is False


def test_native_aragora_receipt_fails_with_export_hint() -> None:
    """A native DecisionReceipt (what ``aragora demo --receipt`` writes) must
    still FAIL, but the failure names the format mistake and the exact
    ``aragora receipt export --format odr`` bridge command (issue #9185)."""
    native = {
        "receipt_id": "DR-MOCK-BCDFC27A",
        "schema_version": "1.0",
        "verdict": "consensus",
        "artifact_hash": "e4a05033dc61c808",
        "question": "Should we adopt microservices?",
    }
    result = verify(native)
    assert result.ok is False
    detail = _check(result, "schema_conformance").detail
    assert "missing required member: odr_version" in detail
    assert "native Aragora receipt" in detail
    assert "aragora receipt export <file> --format odr" in detail


def test_non_native_schema_failure_gets_no_native_hint() -> None:
    """Arbitrary invalid JSON (not recognizably a native receipt) keeps the
    plain schema errors -- no misleading export suggestion."""
    result = verify({"receipt_id": "DR-X"})
    assert result.ok is False
    assert "native Aragora receipt" not in _check(result, "schema_conformance").detail


def test_odr_document_with_schema_errors_gets_no_native_hint() -> None:
    """A real ODR document with a defect is not misdiagnosed as native."""
    doc = valid_odr()
    del doc["claim"]
    result = verify(doc)
    assert result.ok is False
    assert "native Aragora receipt" not in _check(result, "schema_conformance").detail


# --- signatures ------------------------------------------------------------


def _pubkey_bytes(public_key):
    from cryptography.hazmat.primitives import serialization

    return public_key.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def test_signed_receipt_verifies_with_correct_key() -> None:
    private_key, public_key = make_keypair()
    signed = sign_odr(valid_odr(), private_key)
    result = verify(signed, public_key=load_public_key(_pubkey_bytes(public_key)))
    assert result.ok is True
    assert _check(result, "signature").status == PASS


def test_mutated_byte_fails_signature() -> None:
    private_key, public_key = make_keypair()
    signed = sign_odr(valid_odr(), private_key)
    signed["claim"]["verdict"] = "FAIL"  # tamper after signing
    result = verify(signed, public_key=load_public_key(_pubkey_bytes(public_key)))
    assert result.ok is False
    assert _check(result, "signature").status == FAIL


def test_tampered_key_id_fails_signature() -> None:
    # A cryptographically valid signature must not count when its recorded
    # key_id has been relabeled: signatures[] is outside the signed digest,
    # so key_id is attacker-mutable unless bound to the supplied key.
    private_key, public_key = make_keypair()
    signed = sign_odr(valid_odr(), private_key)
    signed["signatures"][0]["key_id"] = "spoofed-signer-label"
    result = verify(signed, public_key=load_public_key(_pubkey_bytes(public_key)))
    assert result.ok is False
    check = _check(result, "signature")
    assert check.status == FAIL
    assert "signer-label tampering" in check.detail


def test_valid_bound_signature_wins_over_relabeled_extra() -> None:
    # Precedence parity with aragora.gauntlet.odr_verify (#8802 round-5 [P2],
    # #8810): one valid, correctly-bound signature establishes authenticity
    # even when an extra entry carries the same signature bytes under a
    # relabeled key_id. The mislabeled entry is surfaced in the detail.
    private_key, public_key = make_keypair()
    signed = sign_odr(valid_odr(), private_key)
    relabeled = dict(signed["signatures"][0], key_id="spoofed-extra-label")
    signed["signatures"].append(relabeled)
    result = verify(signed, public_key=load_public_key(_pubkey_bytes(public_key)))
    assert result.ok is True
    check = _check(result, "signature")
    assert check.status == PASS
    assert "signer-label tampering" in check.detail


def test_unsigned_receipt_with_pubkey_is_unverified() -> None:
    # #8802 round-5 [P2]: supplying a key for an unsigned receipt must not
    # yield VERIFIED/exit 0 -- authenticity was requested and cannot be
    # established, so the signature check is SKIP -> UNVERIFIED (exit 3).
    private_key, public_key = make_keypair()
    result = verify(valid_odr(), public_key=load_public_key(_pubkey_bytes(public_key)))
    assert result.ok is True
    assert _check(result, "signature").status == SKIP
    assert result.authenticity_unverified is True


def test_wrong_key_does_not_verify() -> None:
    private_key, _ = make_keypair()
    _, other_public = make_keypair()
    signed = sign_odr(valid_odr(), private_key)
    result = verify(signed, public_key=load_public_key(_pubkey_bytes(other_public)))
    assert result.ok is False
    assert _check(result, "signature").status == FAIL


def test_signed_receipt_without_key_is_skipped_not_failed() -> None:
    private_key, _ = make_keypair()
    signed = sign_odr(valid_odr(), private_key)
    result = verify(signed)
    assert result.ok is True
    assert _check(result, "signature").status == SKIP


def test_raw_and_pem_keys_both_load() -> None:
    from cryptography.hazmat.primitives import serialization

    private_key, public_key = make_keypair()
    signed = sign_odr(valid_odr(), private_key)
    raw = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    assert verify(signed, public_key=load_public_key(raw)).ok is True


def test_compute_key_id_matches_emitted_signature() -> None:
    private_key, public_key = make_keypair()
    signed = sign_odr(valid_odr(), private_key)
    assert signed["signatures"][0]["key_id"] == compute_key_id(public_key)


# --- quorum consistency ----------------------------------------------------


def test_quorum_inconsistency_fails_as_malformed() -> None:
    doc = valid_odr()
    doc["quorum"]["supporting_agents"].append("ghost-agent")
    result = verify(doc)
    assert result.ok is False
    assert _check(result, "quorum_consistency").status == FAIL
    assert "ghost-agent" in _check(result, "quorum_consistency").detail


def test_dissenting_agent_must_be_participant() -> None:
    doc = valid_odr()
    doc["quorum"]["dissent"] = {
        "present": True,
        "dissenting_agents": ["nobody"],
        "views": ["disagree"],
    }
    result = verify(doc)
    assert result.ok is False
    assert _check(result, "quorum_consistency").status == FAIL


def test_absent_quorum_skips_consistency() -> None:
    doc = valid_odr()
    doc["quorum"] = {"status": "absent", "reason": "no consensus proof recorded"}
    result = verify(doc)
    assert _check(result, "quorum_consistency").status == SKIP


# --- hash chain ------------------------------------------------------------


def test_chain_anchored_receipt_passes() -> None:
    doc = valid_odr()
    from aragora_verify import odr_content_digest

    digest = odr_content_digest(doc)
    chain = [
        {"hash": "h0"},
        {"hash": "h1", "prev_hash": "h0", "odr_digest": digest},
    ]
    result = verify(doc, chain=chain)
    # Anchored + declared links present but NOT recomputed -> WARN (honest about
    # the non-integrity limitation); still does not fail verification.
    assert _check(result, "chain_link").status == WARN
    assert result.ok is True


def test_chain_broken_linkage_fails() -> None:
    doc = valid_odr()
    from aragora_verify import odr_content_digest

    digest = odr_content_digest(doc)
    chain = [
        {"hash": "h0"},
        {"hash": "h1", "prev_hash": "WRONG", "odr_digest": digest},
    ]
    result = verify(doc, chain=chain)
    assert result.ok is False
    assert _check(result, "chain_link").status == FAIL


def test_chain_without_receipt_fails_anchoring() -> None:
    chain = [{"hash": "h0"}, {"hash": "h1", "prev_hash": "h0"}]
    result = verify(valid_odr(), chain=chain)
    assert result.ok is False
    assert "not anchored" in _check(result, "chain_link").detail


def test_no_chain_is_skipped() -> None:
    assert _check(verify(valid_odr()), "chain_link").status == SKIP


# --- weakening warnings ----------------------------------------------------


def test_autonomous_and_uncalibrated_surface_as_warnings() -> None:
    result = verify(valid_odr())
    joined = " ".join(result.warnings)
    assert "autonomous" in joined
    assert "uncalibrated" in joined
    assert result.ok is True  # warnings never fail


def test_single_family_quorum_warns() -> None:
    doc = valid_odr()
    doc["quorum"]["independence"] = {
        "disclosed": True,
        "distinct_model_families": 1,
        "model_families": ["anthropic"],
    }
    result = verify(doc)
    assert any("single model family" in w for w in result.warnings)


def test_to_dict_is_json_serializable() -> None:
    import json

    private_key, public_key = make_keypair()
    signed = sign_odr(valid_odr(), private_key)
    result = verify(signed, public_key=load_public_key(_pubkey_bytes(public_key)))
    json.dumps(result.to_dict())  # must not raise


def test_load_public_key_rejects_garbage() -> None:
    from aragora_verify import VerificationError

    with pytest.raises(VerificationError):
        load_public_key(b"not a key")


# --- v0.2 signature entries: signer-committed metadata (spec §6) ------------

_T0, _T1 = "2026-09-05T00:00:00+00:00", "2027-09-05T00:00:00+00:00"
_DELETE = object()


def _valid_odr_v02():
    doc = valid_odr()
    doc.update(odr_version="0.2", profile="https://aragora.ai/specs/open-decision-receipt/v0.2")
    return doc


def _sign_v02(doc, private_key, *, over_v01_message=False, **metadata):
    """Sign per the v0.2 construction: JCS({odr_digest, odr_signature_input, protected})."""
    import base64

    from aragora_verify.jcs import jcs_canonicalize, odr_content_digest

    protected = {"alg": "Ed25519", "key_id": compute_key_id(private_key.public_key())}
    protected.update({"issuer": "aragora", "role": "emitter", "signed_at": _T0, **metadata})
    digest_hex = odr_content_digest(doc)
    payload = {"odr_digest": digest_hex, "odr_signature_input": "0.2", "protected": protected}
    message = bytes.fromhex(digest_hex) if over_v01_message else jcs_canonicalize(payload)
    signature = base64.b64encode(private_key.sign(message)).decode("ascii")
    return dict(doc, signatures=[dict(protected, signature=signature)])


def _verify_with(signed, public_key):
    return verify(signed, public_key=load_public_key(_pubkey_bytes(public_key)))


def _unauthenticated(result):
    return [w for w in result.warnings if "unauthenticated signature metadata" in w]


@pytest.mark.parametrize(
    "metadata", [{}, {"role": "reviewer", "expires_at": _T1}], ids=["default", "with_expiry"]
)
def test_v02_signed_receipt_with_metadata_verifies(metadata) -> None:
    private_key, public_key = make_keypair()
    result = _verify_with(_sign_v02(_valid_odr_v02(), private_key, **metadata), public_key)
    assert result.ok is True, result.checks
    assert _check(result, "signature").status == PASS
    assert _unauthenticated(result) == []


@pytest.mark.parametrize(
    "member,value",
    [
        pytest.param("issuer", "mallory", id="issuer_changed"),
        pytest.param("expires_at", "2099-01-01T00:00:00Z", id="expires_at_added"),
        pytest.param("signed_at", _DELETE, id="signed_at_stripped"),
        pytest.param("role", "notary", id="role_changed"),
        pytest.param("issuer", _DELETE, id="issuer_stripped"),
        pytest.param("key_id", "ed25519-deadbeefdeadbeef", id="key_id_relabeled"),
    ],
)
def test_v02_metadata_tamper_fails_signature_but_not_digest(member, value) -> None:
    private_key, public_key = make_keypair()
    signed = _sign_v02(_valid_odr_v02(), private_key)
    if value is _DELETE:
        del signed["signatures"][0][member]
    else:
        signed["signatures"][0][member] = value
    result = _verify_with(signed, public_key)
    assert result.ok is False
    assert _check(result, "canonical_digest").status == PASS
    assert _check(result, "signature").status == FAIL


def test_v02_entry_over_v01_message_fails() -> None:
    # No fallback between constructions: a 0.2 document is only ever checked
    # under the 0.2 message, so an entry made over the raw digest bytes fails.
    private_key, public_key = make_keypair()
    signed = _sign_v02(_valid_odr_v02(), private_key, over_v01_message=True)
    result = _verify_with(signed, public_key)
    assert result.ok is False
    assert _check(result, "canonical_digest").status == PASS
    assert _check(result, "signature").status == FAIL


def test_v01_signature_construction_unchanged_and_metadata_only_warns() -> None:
    # The shared fixture signs a 0.1 document over the raw digest bytes with a
    # signed_at member (no new warning); other metadata warns, with or without a key.
    private_key, public_key = make_keypair()
    signed = sign_odr(valid_odr(), private_key)
    assert set(signed["signatures"][0]) == {"alg", "key_id", "signature", "signed_at"}
    result = _verify_with(signed, public_key)
    assert result.ok is True and _check(result, "signature").status == PASS
    assert _unauthenticated(result) == []
    signed["signatures"][0]["issuer"] = "aragora"
    result = _verify_with(signed, public_key)
    assert result.ok is True and _check(result, "signature").status == PASS
    assert len(_unauthenticated(result)) == 1 and "issuer" in _unauthenticated(result)[0]
    assert len(_unauthenticated(verify(signed))) == 1


@pytest.mark.parametrize(
    "member,value", [("issuer", ""), ("role", "auditor"), ("expires_at", 5), ("note", "x")]
)
def test_hand_written_signature_checks_without_jsonschema(monkeypatch, member, value) -> None:
    from aragora_verify import schema

    monkeypatch.setattr(schema, "_jsonschema_errors", lambda doc: [])
    signed = _sign_v02(_valid_odr_v02(), make_keypair()[0])
    signed["signatures"][0][member] = value
    errors = schema.validate_structure(signed)
    assert any(e.startswith(f"signatures[0].{member}: ") for e in errors), errors
    assert _check(verify(signed), "schema_conformance").status == FAIL
