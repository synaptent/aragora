"""Signature-dependent tests for the ODR verification engine.

Mirrors the standalone ``aragora-verify`` package's behavior; both must agree on
the same content profile and signature construction so a receipt verifies
identically here and for an external auditor.

This module holds only the tests that need the optional ``cryptography``
package (key generation, signing, key loading) and skips as a whole when it is
absent. The dependency-free verifier tests (schema conformance, quorum
cross-checks, chain linkage, weakening signals) live in
``test_odr_verify_schema.py`` and must run without ``cryptography`` (#8765 P3).
"""

from __future__ import annotations

import base64
import copy
from typing import Any

import pytest

from aragora.gauntlet.odr_export import odr_content_digest
from aragora.gauntlet.odr_verify import (
    FAIL,
    PASS,
    SKIP,
    ODRVerificationError,
    compute_key_id,
    load_public_key,
    verify_odr_document,
)

cryptography = pytest.importorskip("cryptography")
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402


def _valid_odr() -> dict[str, Any]:
    return {
        "odr_version": "0.1",
        "profile": "https://aragora.ai/specs/open-decision-receipt/v0.1",
        "receipt_id": "rcpt-0001",
        "issued_at": "2026-06-14T00:00:00Z",
        "subject": {
            "identifier": "5f1b14e4b5e113dc978d60d1f6bd21b5a478c744",
            "digest": {"status": "present", "alg": "sha-256", "value": "deadbeef"},
            "summary": "PR #8360",
        },
        "claim": {"verdict": "PASS", "statement": "merge PR #8360"},
        "reasoning": {"status": "present", "summary": "all checks green; quorum reached"},
        "quorum": {
            "status": "present",
            "method": "majority",
            "reached": True,
            "supporting_agents": ["claude", "grok"],
            "participants": [
                {"agent": "claude", "model_family": "anthropic", "model_id": "claude-opus-4-8"},
                {"agent": "grok", "model_family": "xai", "model_id": "grok-4"},
            ],
            "independence": {
                "disclosed": True,
                "distinct_model_families": 2,
                "model_families": ["anthropic", "xai"],
            },
            "dissent": {"present": False, "dissenting_agents": [], "views": []},
        },
        "confidence": {
            "status": "present",
            "value": 0.9,
            "scale": "unit_interval",
            "calibration": {"status": "absent", "reason": "no calibration record"},
        },
        "cruxes": {"status": "absent", "reason": "no crux set supplied"},
        "attestation": {"disposition": "autonomous"},
        "routing": {"status": "reserved"},
        "signatures": [],
    }


def _sign(doc: dict[str, Any], private_key: Ed25519PrivateKey) -> dict[str, Any]:
    signed = copy.deepcopy(doc)
    message = bytes.fromhex(odr_content_digest(signed))
    signature = private_key.sign(message)
    signed["signatures"] = [
        {
            "alg": "Ed25519",
            "key_id": compute_key_id(private_key.public_key()),
            "signature": base64.b64encode(signature).decode("ascii"),
            "signed_at": "2026-06-14T00:00:01Z",
        }
    ]
    return signed


def _pem(public_key: Any) -> bytes:
    return public_key.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def _check(result: Any, name: str) -> Any:
    return next(c for c in result.checks if c.name == name)


def test_signed_verifies_with_correct_key() -> None:
    priv = Ed25519PrivateKey.generate()
    signed = _sign(_valid_odr(), priv)
    result = verify_odr_document(signed, public_key=load_public_key(_pem(priv.public_key())))
    assert result.ok is True
    assert _check(result, "signature").status == PASS


def test_mutated_byte_fails_signature() -> None:
    priv = Ed25519PrivateKey.generate()
    signed = _sign(_valid_odr(), priv)
    signed["claim"]["verdict"] = "FAIL"
    result = verify_odr_document(signed, public_key=load_public_key(_pem(priv.public_key())))
    assert result.ok is False
    assert _check(result, "signature").status == FAIL


def test_wrong_key_fails() -> None:
    priv = Ed25519PrivateKey.generate()
    other = Ed25519PrivateKey.generate()
    signed = _sign(_valid_odr(), priv)
    result = verify_odr_document(signed, public_key=load_public_key(_pem(other.public_key())))
    assert result.ok is False


def test_signed_without_key_is_skipped() -> None:
    priv = Ed25519PrivateKey.generate()
    signed = _sign(_valid_odr(), priv)
    result = verify_odr_document(signed)
    assert result.ok is True
    assert _check(result, "signature").status == SKIP


def test_raw_key_loads() -> None:
    priv = Ed25519PrivateKey.generate()
    signed = _sign(_valid_odr(), priv)
    raw = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    assert verify_odr_document(signed, public_key=load_public_key(raw)).ok is True


def test_to_dict_json_serializable() -> None:
    import json

    priv = Ed25519PrivateKey.generate()
    signed = _sign(_valid_odr(), priv)
    result = verify_odr_document(signed, public_key=load_public_key(_pem(priv.public_key())))
    json.dumps(result.to_dict())


def test_load_public_key_rejects_garbage() -> None:
    with pytest.raises(ODRVerificationError):
        load_public_key(b"not a key")


def test_tampered_key_id_fails_even_with_valid_signature() -> None:
    # A cryptographically valid signature must not count when its recorded
    # key_id does not bind to the supplied key (signer-identity binding).
    priv = Ed25519PrivateKey.generate()
    signed = _sign(_valid_odr(), priv)
    signed["signatures"][0]["key_id"] = "ed25519-deadbeefdeadbeef"
    result = verify_odr_document(signed, public_key=load_public_key(_pem(priv.public_key())))
    assert result.ok is False
    check = _check(result, "signature")
    assert check.status == FAIL
    assert "key_id" in check.detail


def test_non_numeric_model_families_fails_before_the_signature_check() -> None:
    # The schema types distinct_model_families as an integer, so a malformed
    # value is rejected structurally and verification never reaches signatures:
    # a valid signature over a malformed body is still not a verified receipt.
    priv = Ed25519PrivateKey.generate()
    doc = _valid_odr()
    doc["quorum"]["independence"]["distinct_model_families"] = "n/a"
    signed = _sign(doc, priv)
    result = verify_odr_document(signed, public_key=load_public_key(_pem(priv.public_key())))
    assert result.ok is False
    assert [c.name for c in result.checks] == ["schema_conformance"]
    detail = _check(result, "schema_conformance").detail
    assert "quorum.independence.distinct_model_families" in detail


def test_raw_key_with_leading_whitespace_byte_loads() -> None:
    # A raw 32-byte key may begin/end with a whitespace byte; strip() must
    # not be applied to the raw form.
    raw = b"\n" + b"\x11" * 31
    key = load_public_key(raw)
    got = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    assert got == raw
