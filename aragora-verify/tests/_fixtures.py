"""Shared fixtures: a valid ODR document and a spec-faithful Ed25519 signer."""

from __future__ import annotations

import base64
import copy
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aragora_verify import compute_key_id, odr_content_digest


def valid_odr(odr_version: str = "0.1") -> dict[str, Any]:
    """A schema-conformant ODR document, v0.1 unless explicitly requested."""
    return {
        "odr_version": odr_version,
        "profile": f"https://aragora.ai/specs/open-decision-receipt/v{odr_version}",
        "receipt_id": "rcpt-0001",
        "issued_at": "2026-06-14T00:00:00Z",
        "subject": {
            "identifier": "5f1b14e4b5e113dc978d60d1f6bd21b5a478c744",
            "digest": {"status": "present", "alg": "sha-256", "value": "deadbeef"},
            "summary": "PR #8360",
        },
        "claim": {"verdict": "PASS", "statement": "merge PR #8360"},
        "reasoning": {"status": "present", "summary": "all required checks green; quorum reached"},
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
            "calibration": {"status": "absent", "reason": "no calibration record for these agents"},
        },
        "cruxes": {"status": "absent", "reason": "no crux set supplied"},
        "attestation": {"disposition": "autonomous"},
        "routing": {"status": "reserved"},
        "signatures": [],
    }


def make_keypair() -> tuple[Ed25519PrivateKey, Any]:
    private_key = Ed25519PrivateKey.generate()
    return private_key, private_key.public_key()


def sign_odr(doc: dict[str, Any], private_key: Ed25519PrivateKey) -> dict[str, Any]:
    """Attach an Ed25519 detached signature per OPEN_DECISION_RECEIPT.md §6 / #8225.

    message = SHA-256(JCS(doc without signatures)); signature = Ed25519-sign(message).
    """
    signed = copy.deepcopy(doc)
    message = bytes.fromhex(odr_content_digest(signed))
    signature = private_key.sign(message)
    key_id = compute_key_id(private_key.public_key())
    signed["signatures"] = [
        {
            "alg": "Ed25519",
            "key_id": key_id,
            "signature": base64.b64encode(signature).decode("ascii"),
            "signed_at": "2026-06-14T00:00:01Z",
        }
    ]
    return signed
