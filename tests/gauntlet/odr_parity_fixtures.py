"""Shared ODR signature parity fixtures for in-repo and standalone verifiers."""

from __future__ import annotations

import base64
import copy
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


@dataclass(frozen=True)
class ODRSignatureParityCase:
    name: str
    doc: dict[str, Any]
    public_key_pem: bytes
    expected_ok: bool
    expected_signature_status: str


@dataclass(frozen=True)
class ODRAuthenticityStateParityCase:
    name: str
    doc: dict[str, Any]
    public_key_pem: bytes | None
    expected_ok: bool
    expected_signature_status: str
    expected_authenticity_unverified: bool


def valid_odr() -> dict[str, Any]:
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


def signature_parity_cases(
    content_digest: Callable[[dict[str, Any]], str],
    compute_key_id: Callable[[Any], str],
) -> tuple[ODRSignatureParityCase, ...]:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    public_key_pem = public_key.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )

    signed = _sign(valid_odr(), private_key, content_digest, compute_key_id)

    content_tampered = copy.deepcopy(signed)
    content_tampered["claim"]["verdict"] = "FAIL"

    relabeled_key = copy.deepcopy(signed)
    relabeled_key["signatures"][0]["key_id"] = "ed25519-deadbeefdeadbeef"

    mixed_multi_signature = copy.deepcopy(signed)
    relabeled_extra = dict(
        mixed_multi_signature["signatures"][0],
        key_id="ed25519-feedfacefeedface",
    )
    mixed_multi_signature["signatures"] = [
        relabeled_extra,
        mixed_multi_signature["signatures"][0],
    ]

    return (
        ODRSignatureParityCase("valid", signed, public_key_pem, True, "pass"),
        ODRSignatureParityCase("content_tampered", content_tampered, public_key_pem, False, "fail"),
        ODRSignatureParityCase("relabeled_key", relabeled_key, public_key_pem, False, "fail"),
        ODRSignatureParityCase(
            "mixed_multi_signature", mixed_multi_signature, public_key_pem, True, "pass"
        ),
    )


def authenticity_state_parity_cases(
    content_digest: Callable[[dict[str, Any]], str],
    compute_key_id: Callable[[Any], str],
) -> tuple[ODRAuthenticityStateParityCase, ...]:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    public_key_pem = public_key.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    other_key = Ed25519PrivateKey.generate().public_key()
    other_key_pem = other_key.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )

    unsigned = valid_odr()
    signed = _sign(valid_odr(), private_key, content_digest, compute_key_id)

    return (
        ODRAuthenticityStateParityCase("unsigned_no_pubkey", unsigned, None, True, "warn", False),
        ODRAuthenticityStateParityCase(
            "unsigned_supplied_pubkey", unsigned, public_key_pem, True, "skip", True
        ),
        ODRAuthenticityStateParityCase("signed_no_pubkey", signed, None, True, "skip", True),
        ODRAuthenticityStateParityCase(
            "signed_wrong_pubkey", signed, other_key_pem, False, "fail", False
        ),
    )


def _sign(
    doc: dict[str, Any],
    private_key: Ed25519PrivateKey,
    content_digest: Callable[[dict[str, Any]], str],
    compute_key_id: Callable[[Any], str],
) -> dict[str, Any]:
    signed = copy.deepcopy(doc)
    message = bytes.fromhex(content_digest(signed))
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
