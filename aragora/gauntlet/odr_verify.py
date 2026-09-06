"""In-package verification engine for Open Decision Receipts (ODR v0.1).

This is an in-tree **library** engine, not a wired API: it reuses the
emitter's canonicalization and digest (``odr_export.jcs_canonicalize`` /
``odr_content_digest`` / ``load_odr_schema``) so a receipt verifies against the
exact bytes it was emitted and signed over. No shipped CLI subcommand or HTTP
route calls it today — the existing ``/api/v2/receipts/{id}/verify*`` and
``/receipts/{id}/verify`` routes verify the native or legacy receipt instead
(see ``docs/specs/RECEIPT_LINEAGE_RECONCILIATION.md`` "Two verifiers" for the
full picture). It is available for internal callers to import directly and is
exercised by its own test suite.

The standalone, zero-Aragora-dependency mirror of this engine is the
``aragora-verify`` PyPI package (issue #8226); the two are kept in lockstep —
both follow the same content profile (``docs/specs/OPEN_DECISION_RECEIPT.md``)
and signature construction (§6 / issue #8225), so a receipt verifies
identically whether checked here or by an external auditor with only the
public key.

Checks:

1. **schema conformance** to the ODR v0.1 profile;
2. **canonical digest** — ``SHA-256(JCS(doc - signatures))``, the signed value;
3. **Ed25519 signatures** — verified against a supplied public key when the
   optional ``cryptography`` dependency is available (gracefully skipped, never
   failed, when it is not);
4. **quorum consistency** — supporting/dissenting agents are disclosed
   participants (spec §8: a mismatch is a malformed/tamper signal);
5. **hash-chain linkage** — receipt anchored in a supplied chain with
   continuous links.

Absent markers and ``"undisclosed"`` model families *weaken* a receipt
(reported as warnings), never fail it (spec §8).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from .odr_export import (
    ODR_PROFILE_URI,
    ODR_VERSION,
    jcs_canonicalize,  # noqa: F401 - re-exported for callers/tests
    odr_content_digest,
)

__all__ = [
    "Check",
    "VerifyResult",
    "verify_odr_document",
    "compute_key_id",
    "load_public_key",
    "ODRVerificationError",
]

PASS = "pass"
FAIL = "fail"
WARN = "warn"
SKIP = "skip"

MERGE_QUORUM_CONTEXT = "aragora-merge-quorum"

_REQUIRED_MEMBERS = (
    "odr_version",
    "profile",
    "receipt_id",
    "issued_at",
    "subject",
    "claim",
    "reasoning",
    "quorum",
    "confidence",
    "cruxes",
    "attestation",
    "routing",
    "signatures",
)


class ODRVerificationError(Exception):
    """Raised for unrecoverable input problems (e.g. an unreadable public key)."""


@dataclass(frozen=True)
class Check:
    """One named verification step and its outcome."""

    name: str
    status: str  # pass | fail | warn | skip
    detail: str


@dataclass
class VerifyResult:
    """Structured verdict; ``ok`` is the single PASS/FAIL signal."""

    ok: bool
    receipt_id: str
    odr_digest: str
    checks: list[Check] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "authenticity_unverified": self.authenticity_unverified,
            "receipt_id": self.receipt_id,
            "odr_digest": self.odr_digest,
            "checks": [asdict(c) for c in self.checks],
            "warnings": list(self.warnings),
        }

    @property
    def authenticity_unverified(self) -> bool:
        """True when authenticity was requested or implied but no signature was checked."""
        return any(c.name == "signature" and c.status == SKIP for c in self.checks)


# ---------------------------------------------------------------------------
# Structural conformance (dependency-free; jsonschema not a core dependency)
#
# This section is a hand-rolled mirror of ``aragora/gauntlet/odr_schema.json``
# (the normative v0.1 profile): every required member, member type, enum/const,
# minLength/minItems bound, and ``additionalProperties: false`` policy in the
# schema is enforced here member-for-member. Keep the two in lockstep — a
# schema change without a matching change here reopens the #8765 bypass class.
#
# One deliberate, test-pinned deviation: the schema types
# ``quorum.independence.distinct_model_families`` as a non-negative integer,
# but a malformed value there degrades to a *weakening warning* (see
# ``_weakening_warnings``) rather than a schema FAIL, per the prior #8389
# review round (head e0e7df74: "weakening signals warn-only").
# ---------------------------------------------------------------------------

_ALLOWED_TOP_LEVEL = frozenset(_REQUIRED_MEMBERS) | {"source"}

_QUORUM_REQUIRED = (
    "method",
    "reached",
    "supporting_agents",
    "participants",
    "independence",
    "dissent",
)


def _is_absent_marker(value: Any) -> bool:
    # Absent markers are exactly {"status": "absent", "reason": <non-empty str>}
    # (both members required, additionalProperties: false).
    return (
        isinstance(value, dict)
        and set(value) == {"status", "reason"}
        and value.get("status") == "absent"
        and isinstance(value.get("reason"), str)
        and bool(value.get("reason"))
    )


def _unknown_members(
    errors: list[str], path: str, value: dict[str, Any], allowed: frozenset[str]
) -> None:
    for key in sorted(set(value) - allowed):
        errors.append(f"{path}.{key}: unknown member (additionalProperties: false)")


def _string_array(errors: list[str], path: str, value: Any) -> None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        errors.append(f"{path}: must be an array of strings")


def _optional_string(errors: list[str], path: str, value: dict[str, Any], key: str) -> None:
    if key in value and not isinstance(value[key], str):
        errors.append(f"{path}.{key}: must be a string")


def _validate_structure(doc: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["receipt: top-level value must be a JSON object"]

    for member in _REQUIRED_MEMBERS:
        if member not in doc:
            errors.append(f"missing required member: {member}")
    for key in sorted(set(doc) - _ALLOWED_TOP_LEVEL):
        errors.append(f"unknown top-level member: {key} (additionalProperties: false)")

    if doc.get("odr_version") != ODR_VERSION:
        errors.append(f"odr_version: must be '{ODR_VERSION}'")
    if doc.get("profile") != ODR_PROFILE_URI:
        errors.append(f"profile: must be '{ODR_PROFILE_URI}'")
    if not isinstance(doc.get("receipt_id"), str) or not doc.get("receipt_id"):
        errors.append("receipt_id: required non-empty string")
    if "issued_at" in doc:
        issued_at = doc["issued_at"]
        if issued_at is not None and not isinstance(issued_at, str):
            errors.append("issued_at: must be a string or null")

    if "subject" in doc:
        _validate_subject(errors, doc["subject"])
    if "claim" in doc:
        _validate_claim(errors, doc["claim"])
    if "reasoning" in doc:
        _validate_reasoning(errors, doc["reasoning"])
    if "quorum" in doc:
        _validate_quorum(errors, doc["quorum"])
    if "confidence" in doc:
        _validate_confidence(errors, doc["confidence"])
    if "cruxes" in doc:
        _validate_cruxes(errors, doc["cruxes"])
    if "attestation" in doc:
        _validate_attestation(errors, doc["attestation"])
    if "routing" in doc:
        _validate_routing(errors, doc["routing"])
    if "signatures" in doc:
        _validate_signatures(errors, doc["signatures"])
    if "source" in doc:
        _validate_source(errors, doc["source"])
    return errors


def _validate_subject(errors: list[str], value: Any) -> None:
    if not isinstance(value, dict):
        errors.append("subject: must be an object")
        return
    _unknown_members(errors, "subject", value, frozenset({"identifier", "digest", "summary"}))
    if not isinstance(value.get("identifier"), str):
        errors.append("subject.identifier: required string")
    if "digest" not in value:
        errors.append("subject.digest: required (present block or absent marker)")
    else:
        digest = value["digest"]
        if not _is_absent_marker(digest):
            if not isinstance(digest, dict) or digest.get("status") != "present":
                errors.append("subject.digest: must be a present block or an absent marker")
            else:
                _unknown_members(
                    errors, "subject.digest", digest, frozenset({"status", "alg", "value"})
                )
                if not isinstance(digest.get("alg"), str):
                    errors.append("subject.digest.alg: required string when present")
                if not isinstance(digest.get("value"), str) or not digest.get("value"):
                    errors.append("subject.digest.value: required non-empty string when present")
    _optional_string(errors, "subject", value, "summary")


def _validate_claim(errors: list[str], value: Any) -> None:
    if not isinstance(value, dict):
        errors.append("claim: must be an object")
        return
    _unknown_members(errors, "claim", value, frozenset({"verdict", "statement"}))
    if not isinstance(value.get("verdict"), str) or not value.get("verdict"):
        errors.append("claim.verdict: required non-empty string")
    if "statement" not in value:
        errors.append("claim.statement: required (non-empty string or absent marker)")
    else:
        statement = value["statement"]
        if not _is_absent_marker(statement) and (not isinstance(statement, str) or not statement):
            errors.append("claim.statement: must be a non-empty string or an absent marker")


def _validate_reasoning(errors: list[str], value: Any) -> None:
    if _is_absent_marker(value):
        return
    if not isinstance(value, dict) or value.get("status") != "present":
        errors.append("reasoning: must be a present block or an absent marker")
        return
    _unknown_members(errors, "reasoning", value, frozenset({"status", "summary"}))
    if not isinstance(value.get("summary"), str) or not value.get("summary"):
        errors.append("reasoning.summary: required non-empty string when present")


def _validate_quorum(errors: list[str], value: Any) -> None:
    if _is_absent_marker(value):
        return
    if not isinstance(value, dict) or value.get("status") != "present":
        errors.append("quorum: must be a present block or an absent marker")
        return
    _unknown_members(errors, "quorum", value, frozenset({"status", *_QUORUM_REQUIRED}))
    for required in _QUORUM_REQUIRED:
        if required not in value:
            errors.append(f"quorum.{required}: required when present")
    if "method" in value and not isinstance(value["method"], str):
        errors.append("quorum.method: must be a string")
    # A non-boolean ``reached`` (e.g. "yes" or 1) is a malformed/tamper signal,
    # not a truthy convenience: the schema types it strictly as boolean.
    if "reached" in value and not isinstance(value["reached"], bool):
        errors.append("quorum.reached: must be a boolean")
    if "supporting_agents" in value:
        _string_array(errors, "quorum.supporting_agents", value["supporting_agents"])
    if "participants" in value:
        _validate_participants(errors, value["participants"])
    if "independence" in value:
        _validate_independence(errors, value["independence"])
    if "dissent" in value:
        _validate_dissent(errors, value["dissent"])


def _validate_participants(errors: list[str], value: Any) -> None:
    # A present-but-non-list value (e.g. ``participants: null``) is a
    # malformed/tamper signal that must FAIL validation, not slip through and
    # crash the downstream quorum cross-check.
    if not isinstance(value, list):
        errors.append("quorum.participants: must be a list when present")
        return
    for i, participant in enumerate(value):
        if not isinstance(participant, dict):
            errors.append(f"quorum.participants[{i}]: must be an object")
            continue
        _unknown_members(
            errors,
            f"quorum.participants[{i}]",
            participant,
            frozenset({"agent", "model_family", "model_id"}),
        )
        if not isinstance(participant.get("agent"), str) or not participant.get("agent"):
            errors.append(f"quorum.participants[{i}].agent: required non-empty string")
        if not isinstance(participant.get("model_family"), str):
            errors.append(f"quorum.participants[{i}].model_family: required string")
        if not isinstance(participant.get("model_id"), str):
            errors.append(f"quorum.participants[{i}].model_id: required string")


def _validate_independence(errors: list[str], value: Any) -> None:
    if not isinstance(value, dict):
        errors.append("quorum.independence: must be an object")
        return
    _unknown_members(
        errors,
        "quorum.independence",
        value,
        frozenset({"disclosed", "distinct_model_families", "model_families", "note"}),
    )
    for required in ("disclosed", "distinct_model_families", "model_families"):
        if required not in value:
            errors.append(f"quorum.independence.{required}: required")
    if "disclosed" in value and not isinstance(value["disclosed"], bool):
        errors.append("quorum.independence.disclosed: must be a boolean")
    # Deliberate schema deviation (see section comment): a non-integer
    # ``distinct_model_families`` degrades to a weakening warning, never a
    # schema FAIL — the member need only be present here.
    if "model_families" in value:
        _string_array(errors, "quorum.independence.model_families", value["model_families"])
    _optional_string(errors, "quorum.independence", value, "note")


def _validate_dissent(errors: list[str], value: Any) -> None:
    if not isinstance(value, dict):
        errors.append("quorum.dissent: must be an object")
        return
    _unknown_members(
        errors, "quorum.dissent", value, frozenset({"present", "dissenting_agents", "views"})
    )
    for required in ("present", "dissenting_agents", "views"):
        if required not in value:
            errors.append(f"quorum.dissent.{required}: required")
    if "present" in value and not isinstance(value["present"], bool):
        errors.append("quorum.dissent.present: must be a boolean")
    if "dissenting_agents" in value:
        _string_array(errors, "quorum.dissent.dissenting_agents", value["dissenting_agents"])
    if "views" in value:
        _string_array(errors, "quorum.dissent.views", value["views"])


def _validate_confidence(errors: list[str], value: Any) -> None:
    if _is_absent_marker(value):
        return
    if not isinstance(value, dict) or value.get("status") != "present":
        errors.append("confidence: must be a present block or an absent marker")
        return
    _unknown_members(
        errors, "confidence", value, frozenset({"status", "value", "scale", "calibration"})
    )
    val = value.get("value")
    if not isinstance(val, (int, float)) or isinstance(val, bool) or not (0 <= val <= 1):
        errors.append("confidence.value: required number in [0, 1] when present")
    if value.get("scale") != "unit_interval":
        errors.append("confidence.scale: must be 'unit_interval' when present")
    if "calibration" not in value:
        errors.append("confidence.calibration: required when present")
    else:
        _validate_calibration(errors, value["calibration"])


def _validate_calibration(errors: list[str], value: Any) -> None:
    if _is_absent_marker(value):
        return
    if not isinstance(value, dict) or value.get("status") != "present":
        errors.append("confidence.calibration: must be a present block or an absent marker")
        return
    _unknown_members(
        errors, "confidence.calibration", value, frozenset({"status", "provenance_ref"})
    )
    ref = value.get("provenance_ref")
    if not isinstance(ref, dict):
        errors.append("confidence.calibration.provenance_ref: required object when present")
        return
    # provenance_ref allows additional members (additionalProperties: true).
    if not isinstance(ref.get("type"), str) or not ref.get("type"):
        errors.append("confidence.calibration.provenance_ref.type: required non-empty string")
    _optional_string(errors, "confidence.calibration.provenance_ref", ref, "receipt_id")
    _optional_string(errors, "confidence.calibration.provenance_ref", ref, "uri")


def _validate_cruxes(errors: list[str], value: Any) -> None:
    if _is_absent_marker(value):
        return
    if not isinstance(value, dict) or value.get("status") != "present":
        errors.append("cruxes: must be a present block or an absent marker")
        return
    _unknown_members(errors, "cruxes", value, frozenset({"status", "items"}))
    items = value.get("items")
    if not isinstance(items, list) or not items or not all(isinstance(i, dict) for i in items):
        errors.append("cruxes.items: required non-empty array of objects when present")


def _validate_attestation(errors: list[str], value: Any) -> None:
    if not isinstance(value, dict):
        errors.append("attestation: must be an object")
        return
    _unknown_members(
        errors,
        "attestation",
        value,
        frozenset(
            {
                "disposition",
                "attestor",
                "attested_at",
                "method",
                "execution_identity",
                "observed",
                "mechanism",
            }
        ),
    )
    disposition = value.get("disposition")
    if disposition not in ("human_attested", "autonomous"):
        errors.append("attestation.disposition: must be 'human_attested' or 'autonomous'")
    attestor = value.get("attestor")
    if "attestor" in value and not isinstance(attestor, dict):
        errors.append("attestation.attestor: must be an object")
    elif isinstance(attestor, dict):
        # attestor allows additional members (additionalProperties: true).
        for key in ("id", "name", "role"):
            _optional_string(errors, "attestation.attestor", attestor, key)
    if disposition == "human_attested" and not isinstance(attestor, dict):
        errors.append("attestation.attestor: required object when disposition is human_attested")
    _optional_string(errors, "attestation", value, "attested_at")
    _optional_string(errors, "attestation", value, "method")
    # Oversight extension members (ODR-6 / #8230); shapes mirror the schema.
    execution_identity = value.get("execution_identity")
    if "execution_identity" in value and not isinstance(execution_identity, dict):
        errors.append("attestation.execution_identity: must be an object")
    elif isinstance(execution_identity, dict):
        for key in ("id", "name", "role"):
            _optional_string(errors, "attestation.execution_identity", execution_identity, key)
        # Identity separation (TET H2): a human_attested receipt whose
        # attestor IS the executing identity is self-attestation, refused at
        # verify time too (beyond JSON Schema expressiveness).
        attestor_id = attestor.get("id") if isinstance(attestor, dict) else None
        execution_id = execution_identity.get("id")
        if (
            disposition == "human_attested"
            and isinstance(attestor_id, str)
            and isinstance(execution_id, str)
            and attestor_id.strip()
            and attestor_id.strip().lower() == execution_id.strip().lower()
        ):
            errors.append(
                "attestation: attestor.id must differ from execution_identity.id "
                "(self-attestation is not oversight)"
            )
    observed = value.get("observed")
    if "observed" in value and not isinstance(observed, dict):
        errors.append("attestation.observed: must be an object")
    elif isinstance(observed, dict):
        for key in ("head_sha", "evidence_digest"):
            _optional_string(errors, "attestation.observed", observed, key)
    mechanism = value.get("mechanism")
    if "mechanism" in value and not isinstance(mechanism, dict):
        errors.append("attestation.mechanism: must be an object")
    elif isinstance(mechanism, dict):
        if not isinstance(mechanism.get("type"), str) or not mechanism.get("type"):
            errors.append("attestation.mechanism.type: required non-empty string")
        for key in ("context", "ref"):
            _optional_string(errors, "attestation.mechanism", mechanism, key)


def _validate_routing(errors: list[str], value: Any) -> None:
    if not isinstance(value, dict):
        errors.append("routing: must be an object")
        return
    _unknown_members(errors, "routing", value, frozenset({"status"}))
    if value.get("status") != "reserved":
        errors.append("routing.status: must be 'reserved' in v0.1")


def _validate_signatures(errors: list[str], value: Any) -> None:
    if not isinstance(value, list):
        errors.append("signatures: must be an array")
        return
    for i, sig in enumerate(value):
        if not isinstance(sig, dict):
            errors.append(f"signatures[{i}]: must be an object")
            continue
        _unknown_members(
            errors,
            f"signatures[{i}]",
            sig,
            frozenset({"alg", "key_id", "signature", "signed_at"}),
        )
        for field_name in ("alg", "key_id", "signature"):
            if not isinstance(sig.get(field_name), str) or not sig.get(field_name):
                errors.append(f"signatures[{i}].{field_name}: required non-empty string")
        if isinstance(sig.get("alg"), str) and sig.get("alg") != "Ed25519":
            errors.append(f"signatures[{i}].alg: only 'Ed25519' is defined in v0.1")
        # signed_at is optional but strictly a string when present: a non-string
        # value would silently corrupt the signing-time audit trail.
        _optional_string(errors, f"signatures[{i}]", sig, "signed_at")


def _validate_source(errors: list[str], value: Any) -> None:
    if not isinstance(value, dict):
        errors.append("source: must be an object")
        return
    _unknown_members(
        errors,
        "source",
        value,
        frozenset({"system", "schema", "schema_version", "receipt_id", "artifact_hash"}),
    )
    for required in ("system", "schema", "receipt_id"):
        if required not in value:
            errors.append(f"source.{required}: required")
    for key in ("system", "schema", "schema_version", "receipt_id", "artifact_hash"):
        _optional_string(errors, "source", value, key)


# ---------------------------------------------------------------------------
# Public-key handling (optional cryptography dependency)
# ---------------------------------------------------------------------------


def _load_ed25519() -> tuple[Any, Any, Any] | None:
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError:
        return None
    return Ed25519PublicKey, serialization, InvalidSignature


def load_public_key(data: bytes) -> Any:
    """Load an Ed25519 public key from PEM, DER, raw 32 bytes, or base64/hex text."""
    loaded = _load_ed25519()
    if loaded is None:
        raise ODRVerificationError(
            "signature verification requires the optional 'cryptography' dependency"
        )
    ed25519_cls, serialization, _ = loaded
    # Raw keys are checked before strip(): a 32-byte key may legitimately
    # begin or end with a whitespace byte, and stripping it would corrupt it.
    if len(data) == 32:
        return ed25519_cls.from_public_bytes(data)
    text = data.strip()
    if b"-----BEGIN" in text:
        return serialization.load_pem_public_key(text)
    if len(text) == 32:
        return ed25519_cls.from_public_bytes(text)
    as_str = text.decode("ascii", errors="ignore").strip()
    for decoder in (_maybe_b64, _maybe_hex):
        raw = decoder(as_str)
        if raw is not None and len(raw) == 32:
            return ed25519_cls.from_public_bytes(raw)
    try:
        return serialization.load_der_public_key(data)
    except (ValueError, TypeError) as exc:
        raise ODRVerificationError(
            "could not parse public key (expected PEM/DER/raw/base64/hex)"
        ) from exc


def compute_key_id(public_key: Any) -> str:
    """``ed25519-`` + first 16 hex of SHA-256(raw public key) — the #8225 key id."""
    loaded = _load_ed25519()
    if loaded is None:  # pragma: no cover - guarded by callers
        raise ODRVerificationError("the 'cryptography' dependency is required")
    _, serialization, _ = loaded
    raw = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return "ed25519-" + hashlib.sha256(raw).hexdigest()[:16]


def _maybe_b64(text: str) -> bytes | None:
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        return None


def _maybe_hex(text: str) -> bytes | None:
    try:
        return bytes.fromhex(text)
    except ValueError:
        return None


def _decode_signature(value: str) -> bytes | None:
    raw = _maybe_b64(value)
    if raw is not None and len(raw) == 64:
        return raw
    raw = _maybe_hex(value)
    if raw is not None and len(raw) == 64:
        return raw
    return None


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_signatures(doc: dict[str, Any], digest_hex: str, public_key: Any) -> Check:
    signatures = doc.get("signatures")
    signatures = signatures if isinstance(signatures, list) else []
    if not signatures and public_key is None:
        return Check("signature", WARN, "receipt is unsigned (v0.1); authenticity not established")
    if not signatures and public_key is not None:
        return Check(
            "signature",
            SKIP,
            "receipt carries no signatures; authenticity NOT established even though "
            "a public key was supplied",
        )
    if signatures and public_key is None:
        return Check(
            "signature",
            SKIP,
            f"{len(signatures)} signature(s) present but no public key supplied; not verified",
        )

    loaded = _load_ed25519()
    if loaded is None:
        return Check(
            "signature",
            SKIP,
            "signatures present but 'cryptography' is not installed; not verified",
        )
    _, _, invalid_signature = loaded
    message = bytes.fromhex(digest_hex)
    provided_key_id = compute_key_id(public_key)
    verified_any = False
    failed_matching = False
    key_id_mismatch = False
    notes: list[str] = []
    for i, sig in enumerate(signatures):
        if not isinstance(sig, dict):
            continue
        key_id = str(sig.get("key_id") or "")
        raw_sig = _decode_signature(str(sig.get("signature") or ""))
        if raw_sig is None:
            notes.append(f"sig[{i}]: undecodable signature")
            if key_id == provided_key_id:
                failed_matching = True
            continue
        try:
            public_key.verify(raw_sig, message)
        except invalid_signature:
            notes.append(f"sig[{i}] (key_id={key_id or '?'}): INVALID")
            if key_id == provided_key_id:
                failed_matching = True
            continue
        # A signature only counts as verified when its recorded key_id binds
        # to the supplied key; a cryptographically-valid signature under a
        # mismatched key_id would let a tampered key_id claim a false signer.
        if key_id == provided_key_id:
            verified_any = True
            notes.append(f"sig[{i}] (key_id={key_id or '?'}): verified")
        else:
            key_id_mismatch = True
            notes.append(
                f"sig[{i}]: signature verifies with the supplied key but key_id "
                f"{key_id or '?'} != {provided_key_id} — signer identity not bound"
            )

    detail = "; ".join(notes) or "no signatures evaluated"
    if failed_matching:
        return Check(
            "signature", FAIL, f"signature from the supplied key did not verify — {detail}"
        )
    if verified_any:
        return Check("signature", PASS, f"Ed25519 signature verified — {detail}")
    if key_id_mismatch:
        return Check(
            "signature",
            FAIL,
            f"signature verifies but its key_id does not match the supplied key — {detail}",
        )
    return Check("signature", FAIL, f"no signature verified with the supplied key — {detail}")


def _check_quorum_consistency(doc: dict[str, Any]) -> Check:
    quorum = doc.get("quorum")
    if not isinstance(quorum, dict) or quorum.get("status") != "present":
        return Check("quorum_consistency", SKIP, "no present quorum block to cross-check")

    # Coerce list-valued subfields defensively: a present-but-null value makes
    # ``dict.get(key, [])`` return ``None`` (the default fires only on absence),
    # so iterate over a guaranteed list to turn malformed input into a verdict,
    # never a crash.
    def _as_list(v: Any) -> list[Any]:
        return v if isinstance(v, list) else []

    participants = {
        str(p.get("agent"))
        for p in _as_list(quorum.get("participants"))
        if isinstance(p, dict) and p.get("agent")
    }
    referenced: set[str] = set()
    referenced.update(
        str(a) for a in _as_list(quorum.get("supporting_agents")) if isinstance(a, str)
    )
    dissent = quorum.get("dissent")
    if isinstance(dissent, dict):
        referenced.update(
            str(a) for a in _as_list(dissent.get("dissenting_agents")) if isinstance(a, str)
        )
    missing = sorted(referenced - participants)
    if missing:
        return Check(
            "quorum_consistency",
            FAIL,
            "agents referenced but not in participants (malformed/tamper signal per spec §8): "
            + ", ".join(missing),
        )
    return Check(
        "quorum_consistency", PASS, "supporting/dissenting agents all appear in participants"
    )


def _check_chain(doc: dict[str, Any], digest_hex: str, chain: list[dict[str, Any]] | None) -> Check:
    if chain is None:
        return Check("chain_link", SKIP, "no chain supplied")
    if not chain:
        return Check("chain_link", FAIL, "chain is empty")

    prev_keys = ("prev_hash", "previous_hash", "parent_hash")
    hash_keys = ("hash", "entry_hash", "leaf_hash")
    broken: list[str] = []
    last_hash: str | None = None
    saw_links = False
    for i, entry in enumerate(chain):
        cur = next((str(entry[k]) for k in hash_keys if entry.get(k)), None)
        prev = next((str(entry[k]) for k in prev_keys if entry.get(k)), None)
        if prev is not None:
            saw_links = True
            if i > 0 and last_hash is not None and prev != last_hash:
                broken.append(f"entry[{i}].prev != entry[{i - 1}].hash")
        last_hash = cur if cur is not None else last_hash

    receipt_id = str(doc.get("receipt_id") or "")
    anchored = False
    for entry in chain:
        values = {str(v) for v in entry.values() if isinstance(v, (str, int))}
        if digest_hex in values or (receipt_id and receipt_id in values):
            anchored = True
            break

    if broken:
        return Check("chain_link", FAIL, "broken hash-chain linkage: " + "; ".join(broken))
    if not anchored:
        return Check("chain_link", FAIL, "receipt digest/receipt_id not found among chain entries")
    link_note = "linkage continuous" if saw_links else "no prev-hash links present"
    return Check("chain_link", PASS, f"receipt anchored in chain; {link_note}")


def _weakening_warnings(doc: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    attestation = doc.get("attestation")
    if isinstance(attestation, dict) and attestation.get("disposition") == "autonomous":
        warnings.append("attestation: autonomous — no human accepted the risk for this decision")

    quorum = doc.get("quorum")
    if isinstance(quorum, dict) and quorum.get("status") == "absent":
        warnings.append("quorum: absent — no adversarial review recorded")
    elif isinstance(quorum, dict) and quorum.get("status") == "present":
        independence = quorum.get("independence", {})
        if isinstance(independence, dict):
            if not independence.get("disclosed", False):
                warnings.append("quorum.independence: model diversity not disclosed")
            else:
                # Weakening signals warn, never fail (spec §8): a non-numeric
                # families value degrades to a warning instead of raising.
                try:
                    families = int(independence.get("distinct_model_families", 0) or 0)
                except (TypeError, ValueError):
                    families = None
                if families is None:
                    warnings.append(
                        "quorum.independence: distinct_model_families is not numeric — "
                        "adversarial diversity unverifiable"
                    )
                elif families < 2:
                    warnings.append(
                        "quorum.independence: single model family — limited adversarial diversity"
                    )
        participants = quorum.get("participants", [])
        if isinstance(participants, list) and any(
            isinstance(p, dict) and p.get("model_family") == "undisclosed" for p in participants
        ):
            warnings.append("quorum.participants: one or more model families undisclosed")

    confidence = doc.get("confidence")
    if isinstance(confidence, dict) and confidence.get("status") == "present":
        calibration = confidence.get("calibration")
        if isinstance(calibration, dict) and calibration.get("status") == "absent":
            warnings.append("confidence: present but uncalibrated (no calibration provenance)")

    reasoning = doc.get("reasoning")
    if isinstance(reasoning, dict) and reasoning.get("status") == "absent":
        warnings.append("reasoning: absent — no recorded justification")
    return warnings


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def verify_odr_document(
    doc: Any,
    *,
    public_key: Any | None = None,
    chain: list[dict[str, Any]] | None = None,
) -> VerifyResult:
    """Verify an ODR document. ``public_key`` is a loaded Ed25519 key
    (see :func:`load_public_key`); ``chain`` is a list of parsed chain entries.
    """
    receipt_id = str(doc.get("receipt_id") or "") if isinstance(doc, dict) else ""
    checks: list[Check] = []

    structure_errors = _validate_structure(doc)
    if structure_errors:
        checks.append(Check("schema_conformance", FAIL, "; ".join(structure_errors[:12])))
        return VerifyResult(ok=False, receipt_id=receipt_id, odr_digest="", checks=checks)
    checks.append(Check("schema_conformance", PASS, "conforms to ODR v0.1 profile"))

    # Boundary contract: this engine verifies untrusted/possibly-tampered receipts,
    # so any exception raised while checking structurally-valid-but-malformed input
    # must become a FAIL verdict — never propagate as a crash. Each check below is
    # run through this guard so one malformed subfield cannot abort verification.
    def _safe_check(name: str, fn: Callable[[], Check]) -> Check:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - boundary: malformed input -> FAIL, not crash
            return Check(
                name, FAIL, f"verification raised on malformed input: {type(exc).__name__}: {exc}"
            )

    try:
        digest_hex = odr_content_digest(doc)
    except Exception as exc:  # noqa: BLE001 - boundary: malformed input -> FAIL, not crash
        checks.append(
            Check(
                "canonical_digest", FAIL, f"digest computation raised: {type(exc).__name__}: {exc}"
            )
        )
        return VerifyResult(ok=False, receipt_id=receipt_id, odr_digest="", checks=checks)
    checks.append(Check("canonical_digest", PASS, f"sha-256:{digest_hex}"))
    checks.append(_safe_check("signature", lambda: _check_signatures(doc, digest_hex, public_key)))
    checks.append(_safe_check("quorum_consistency", lambda: _check_quorum_consistency(doc)))
    checks.append(_safe_check("chain_link", lambda: _check_chain(doc, digest_hex, chain)))

    warnings: list[str] = []
    try:
        warnings = _weakening_warnings(doc)
    except Exception as exc:  # noqa: BLE001 - boundary: malformed input -> WARN, not crash
        # Weakening signals warn, never fail (spec §8): an unscannable receipt
        # loses its advisory signals but that alone cannot flip the verdict.
        checks.append(
            Check(
                "weakening_signals",
                WARN,
                f"weakening-signal scan raised on malformed input: {type(exc).__name__}: {exc}",
            )
        )
    ok = not any(c.status == FAIL for c in checks)
    return VerifyResult(
        ok=ok, receipt_id=receipt_id, odr_digest=digest_hex, checks=checks, warnings=warnings
    )
