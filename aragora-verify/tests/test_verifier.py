"""Verifier behavior: schema, signatures, quorum consistency, chain, warnings."""

from __future__ import annotations


import pytest

import aragora_verify.schema as schema
from aragora_verify import compute_key_id, load_public_key, verify
from aragora_verify.verifier import FAIL, PASS, SKIP, WARN

from _fixtures import make_keypair, sign_odr, valid_odr


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


def test_epistemic_block_is_allowed_without_jsonschema(monkeypatch) -> None:
    monkeypatch.setattr(schema, "_jsonschema_errors", lambda doc: [])
    doc = valid_odr()
    doc["epistemic"] = {
        "status": "present",
        "unverified": ["independent replication pending"],
        "assumptions": ["source fixture remains unchanged"],
        "falsification": {
            "observation": "fixture digest mismatch",
            "source": "standalone package test",
            "check_by": "2026-07-06",
        },
    }

    assert schema.validate_structure(doc) == []
    result = verify(doc)
    assert result.ok is True
    assert _check(result, "schema_conformance").status == PASS


def test_malformed_epistemic_block_fails_without_jsonschema(monkeypatch) -> None:
    monkeypatch.setattr(schema, "_jsonschema_errors", lambda doc: [])
    doc = valid_odr()
    doc["epistemic"] = {
        "status": "present",
        "falsification": {"observation": "fixture digest mismatch"},
    }

    errors = schema.validate_structure(doc)
    assert "epistemic.falsification.check_by: required non-empty string" in errors
    result = verify(doc)
    assert result.ok is False
    assert _check(result, "schema_conformance").status == FAIL


def test_source_block_is_validated_without_jsonschema(monkeypatch) -> None:
    monkeypatch.setattr(schema, "_jsonschema_errors", lambda doc: [])
    doc = valid_odr()
    doc["source"] = {
        "system": "aragora",
        "schema": "open-decision-receipt",
        "schema_version": "0.1",
        "receipt_id": "native-rcpt-0001",
        "artifact_hash": "sha-256:deadbeef",
    }

    assert schema.validate_structure(doc) == []
    result = verify(doc)
    assert result.ok is True
    assert _check(result, "schema_conformance").status == PASS


def test_malformed_source_block_fails_without_jsonschema(monkeypatch) -> None:
    monkeypatch.setattr(schema, "_jsonschema_errors", lambda doc: [])
    doc = valid_odr()
    doc["source"] = {
        "system": 42,
        "schema_version": "0.1",
        "receipt_id": "native-rcpt-0001",
        "extra": "unexpected",
    }

    errors = schema.validate_structure(doc)
    assert "source.schema: required" in errors
    assert "source.system: must be a string" in errors
    assert "source.extra: unknown member (additionalProperties: false)" in errors
    result = verify(doc)
    assert result.ok is False
    assert _check(result, "schema_conformance").status == FAIL


def test_unknown_top_level_member_fails_without_jsonschema(monkeypatch) -> None:
    monkeypatch.setattr(schema, "_jsonschema_errors", lambda doc: [])
    doc = valid_odr()
    doc["unexpected"] = {"status": "present"}

    errors = schema.validate_structure(doc)
    assert "unknown top-level member: unexpected (additionalProperties: false)" in errors
    result = verify(doc)
    assert result.ok is False
    assert _check(result, "schema_conformance").status == FAIL


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
