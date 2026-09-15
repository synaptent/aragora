"""Opt-in verification of operator-grant *data*, never action authorization.

No signer, key discovery, storage, network, legacy conversion, or live caller.
Trusted observations must come from a separate trusted caller, not the grant.
See docs/governance/OPERATOR_GRANT_VERIFICATION.md for the closed wire contract.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import PurePosixPath
from typing import Any

from aragora.storage.receipt_signing import Ed25519Signer

SCHEMA_VERSION = "aragora-operator-grant/1.0"
DOMAIN = b"aragora/operator-grant/v1\n"
MAX_BYTES = 65_536
MAX_OBSERVATION_AGE = timedelta(seconds=60)
ACTION_NAMES = frozenset(
    {"branch_write", "validate", "draft_publish", "ready", "evidence_apply", "protected_squash"}
)
HARD_DENIALS = frozenset(
    {
        "authority_change",
        "grant_issue",
        "grant_renew",
        "grant_revoke",
        "subdelegate",
        "admin_merge",
        "force_push",
        "delete",
        "deploy",
        "credentials",
        "workflow_change",
        "schedule_change",
        "paid_inference",
    }
)
CONTEXT_FIELDS = frozenset(
    {
        "grant_id",
        "grant_version",
        "repository_id",
        "repository",
        "operator",
        "delegate",
        "campaign_id",
        "goal_digest",
        "acceptance_digest",
        "policy_version",
        "policy_digest",
        "enforcement_digest",
        "key_id",
        "trust_version",
        "revocation_source",
    }
)
_FIELDS = CONTEXT_FIELDS | {
    "schema_version",
    "approval_ref",
    "approval_digest",
    "issued_at",
    "not_before",
    "expires_at",
    "actions",
    "denied_actions",
    "scope",
    "contract_ids",
    "validation_commands",
    "review_requirements",
    "budget",
    "can_subdelegate",
}


class VerificationCode(str, Enum):
    VERIFIED = "verified_data_only"
    MALFORMED = "malformed_grant"
    CONTEXT_MISMATCH = "context_mismatch"
    INVALID_TIME = "invalid_time"
    UNTRUSTED = "untrusted_key_or_observation"
    REVOKED = "revoked"
    INVALID_SIGNATURE = "invalid_signature"
    CRYPTO_UNAVAILABLE = "crypto_unavailable"


class GrantValidationError(ValueError):
    """Invalid closed-schema payload; also used by offline payload encoders."""


@dataclass(frozen=True)
class TrustedKey:
    operator: str
    public_key: bytes
    trust_version: int
    revoked: bool
    observed_at: datetime
    valid_until: datetime


@dataclass(frozen=True)
class RevocationObservation:
    source: str
    grant_id: str
    grant_version: int
    revoked: bool
    observed_at: datetime
    valid_until: datetime


@dataclass(frozen=True)
class VerifiedGrant:
    """Immutable signed bytes, not a reusable authorization decision."""

    canonical_payload: bytes
    payload_sha256: str


@dataclass(frozen=True)
class VerificationResult:
    code: VerificationCode
    grant: VerifiedGrant | None = None


def _require(condition: bool) -> None:
    if not condition:
        raise GrantValidationError("invalid operator-grant shape or constraint")


def _fields(value: Any, fields: set[str] | frozenset[str]) -> None:
    _require(type(value) is dict and value.keys() == fields)


def _text(value: Any) -> None:
    _require(type(value) is str and 0 < len(value) <= 2048)
    _require(value == value.strip() and not any(ord(c) < 32 or ord(c) == 127 for c in value))
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise GrantValidationError("invalid UTF-8 text") from exc


def _integer(value: Any, low: int = 1, high: int = 2**53 - 1) -> None:
    _require(type(value) is int and low <= value <= high)


def _strings(value: Any, *, empty: bool = False) -> None:
    _require(type(value) is list and (0 if empty else 1) <= len(value) <= 64)
    for item in value:
        _text(item)
    _require(len(set(value)) == len(value))


def _timestamp(value: Any) -> datetime:
    _text(value)
    _require(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value) is not None)
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise GrantValidationError("invalid UTC timestamp") from exc


def _validate_payload(p: dict[str, Any]) -> None:
    _fields(p, _FIELDS)
    for name, value in p.items():
        if name not in {
            "grant_version",
            "repository_id",
            "trust_version",
            "actions",
            "denied_actions",
            "scope",
            "contract_ids",
            "validation_commands",
            "review_requirements",
            "budget",
            "can_subdelegate",
        }:
            _text(value)
        if name.endswith("_digest"):
            _require(re.fullmatch(r"[0-9a-f]{64}", value) is not None)
    _require(p["schema_version"] == SCHEMA_VERSION and p["can_subdelegate"] is False)
    for name in ("grant_version", "repository_id", "trust_version"):
        _integer(p[name])
    _require(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", p["repository"]) is not None)
    for name in (
        "actions",
        "denied_actions",
        "contract_ids",
        "validation_commands",
        "review_requirements",
    ):
        _strings(p[name])
    _require(set(p["actions"]) <= ACTION_NAMES)
    _require(HARD_DENIALS <= set(p["denied_actions"]))
    _require(not set(p["actions"]) & set(p["denied_actions"]))
    scope = p["scope"]
    _fields(scope, {"branches", "paths", "denied_paths", "surfaces", "risk_classes", "tiers"})
    for name in ("branches", "paths", "denied_paths", "surfaces", "risk_classes"):
        _strings(scope[name], empty=name == "denied_paths")
    for name in ("branches", "paths", "denied_paths"):
        for path in scope[name]:
            parsed = PurePosixPath(path)
            _require(not parsed.is_absolute() and parsed.as_posix() == path)
            _require(path != "." and ".." not in parsed.parts)
            _require(not any(c in path for c in "\\:*?[]{}"))
    _require(not set(scope["paths"]) & set(scope["denied_paths"]))
    _require(type(scope["tiers"]) is list and 1 <= len(scope["tiers"]) <= 5)
    for tier in scope["tiers"]:
        _integer(tier, 0, 4)
    _require(len(set(scope["tiers"])) == len(scope["tiers"]))
    budget = p["budget"]
    _fields(
        budget,
        {"active_prs", "merges", "attempts", "wall_seconds", "paid_microdollars", "subdelegates"},
    )
    for name, value in budget.items():
        _integer(value, 0)
    _require(budget["active_prs"] == 1 and 0 <= budget["merges"] <= 10)
    _require(budget["attempts"] > 0 and 0 < budget["wall_seconds"] <= 7 * 86400)
    _require(budget["paid_microdollars"] == 0 and budget["subdelegates"] == 0)
    issued, start, end = (_timestamp(p[n]) for n in ("issued_at", "not_before", "expires_at"))
    _require(issued <= start < end and (end - issued).total_seconds() <= budget["wall_seconds"])


def canonical_grant_payload(payload: dict[str, Any]) -> bytes:
    """Encode the closed schema for verification/offline test signing, without issuing it."""
    _validate_payload(payload)
    encoded = DOMAIN + json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    _require(len(encoded) <= MAX_BYTES)
    return encoded


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _utc(value: Any) -> bool:
    return type(value) is datetime and value.tzinfo is UTC


def _fresh(observed: Any, until: Any, now: datetime) -> bool:
    return (
        _utc(observed)
        and _utc(until)
        and observed <= now < until
        and until - observed <= MAX_OBSERVATION_AGE
    )


def verify_operator_grant(
    envelope: bytes,
    *,
    expected: Mapping[str, str | int],
    trusted_keys: Mapping[str, TrustedKey] | None,
    revocation: RevocationObservation | None,
    now: datetime,
) -> VerificationResult:
    """Verify signed data against explicitly supplied, fresh trusted inputs.

    VERIFIED does not approve the referenced commands, scopes, reviews, or actions.
    No default/global trust or clock is read; no mutations can be performed here.
    """
    invalid = VerificationResult
    try:
        _require(type(envelope) is bytes and len(envelope) <= MAX_BYTES)
        outer = json.loads(envelope.decode("utf-8"), object_pairs_hook=_unique_object)
        _fields(outer, {"payload", "signature"})
        p = outer["payload"]
        canonical = canonical_grant_payload(p)
        _text(outer["signature"])
        signature = base64.b64decode(outer["signature"], validate=True)
        _require(len(signature) == 64)
        _require(base64.b64encode(signature).decode("ascii") == outer["signature"])
    except (ValueError, TypeError, RecursionError, binascii.Error):
        return invalid(VerificationCode.MALFORMED)
    if not isinstance(expected, Mapping) or set(expected) != CONTEXT_FIELDS:
        return invalid(VerificationCode.CONTEXT_MISMATCH)
    if any(type(expected[k]) is not type(p[k]) or expected[k] != p[k] for k in CONTEXT_FIELDS):
        return invalid(VerificationCode.CONTEXT_MISMATCH)
    if not _utc(now) or not (_timestamp(p["not_before"]) <= now < _timestamp(p["expires_at"])):
        return invalid(VerificationCode.INVALID_TIME)
    if not isinstance(trusted_keys, Mapping):
        return invalid(VerificationCode.UNTRUSTED)
    key = trusted_keys.get(p["key_id"])
    if (
        type(key) is not TrustedKey
        or key.operator != p["operator"]
        or type(key.trust_version) is not int
        or key.trust_version != p["trust_version"]
        or type(key.public_key) is not bytes
        or len(key.public_key) != 32
        or type(key.revoked) is not bool
        or not _fresh(key.observed_at, key.valid_until, now)
    ):
        return invalid(VerificationCode.UNTRUSTED)
    if (
        type(revocation) is not RevocationObservation
        or revocation.source != p["revocation_source"]
        or revocation.grant_id != p["grant_id"]
        or type(revocation.grant_version) is not int
        or revocation.grant_version != p["grant_version"]
        or type(revocation.revoked) is not bool
        or not _fresh(revocation.observed_at, revocation.valid_until, now)
    ):
        return invalid(VerificationCode.UNTRUSTED)
    if key.revoked or revocation.revoked:
        return invalid(VerificationCode.REVOKED)
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        verifier = Ed25519Signer(
            public_key=Ed25519PublicKey.from_public_bytes(key.public_key), key_id=p["key_id"]
        )
        if not verifier.verify(canonical, signature):
            return invalid(VerificationCode.INVALID_SIGNATURE)
    except (ImportError, RuntimeError):
        return invalid(VerificationCode.CRYPTO_UNAVAILABLE)
    except (ValueError, TypeError):
        return invalid(VerificationCode.INVALID_SIGNATURE)
    return VerificationResult(
        VerificationCode.VERIFIED, VerifiedGrant(canonical, hashlib.sha256(canonical).hexdigest())
    )
