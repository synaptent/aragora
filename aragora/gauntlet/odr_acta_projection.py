"""ACTA-02 envelope projection of an Open Decision Receipt.

An ODR document says what was decided; the ACTA interop profile
(``draft-farley-acta-signed-receipts-02``) says how a signed receipt travels.
The projection wraps a whole ODR document in the draft's two-member envelope::

    {"payload": {type, issued_at, issuer_id, chain_scope, previousReceiptHash,
                 payload_digest, odr},
     "signature": {"alg": "EdDSA", "kid": <key id>, "sig": <hex Ed25519>}}

``payload_digest`` covers the JCS bytes of the ENTIRE ODR document, signatures
included, so it equals the receipt's own ``odr_digest`` (which excludes
``signatures``) only while the document is unsigned. ``previousReceiptHash`` is
the SHA-256 of the JCS bytes of the whole previous envelope -- the draft's
whole-signed-receipt scope, named explicitly in ``chain_scope`` because the
sibling ASQAV draft links payload-scoped digests under the same member name.

This module is duplicated verbatim as ``aragora_verify/acta.py``: a stranger
must be able to check a projection with the standalone verifier and
``cryptography`` alone, with no ``aragora`` install. Keep the two copies
byte-identical; only the JCS canonicalizer beside each copy differs.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, cast

# The JCS canonicalizer has a different module name in each of the two copies;
# importing the same name in two branches would be a mypy redefinition.
_JCS_MODULE = f"{__package__}.odr_jcs"
if importlib.util.find_spec(_JCS_MODULE) is None:
    _JCS_MODULE = f"{__package__}.jcs"
jcs_canonicalize = cast(
    Callable[[Any], bytes], importlib.import_module(_JCS_MODULE).jcs_canonicalize
)

__all__ = [
    "ACTA_CHAIN_SCOPE",
    "ACTA_PAYLOAD_TYPE",
    "ACTA_SIGNATURE_ALG",
    "ActaCheck",
    "ActaVerifyResult",
    "GENESIS_PREVIOUS_RECEIPT_HASH",
    "PREVIEW_MAX_CHARS",
    "acta_envelope_hash",
    "acta_payload_digest",
    "ed25519_key_id",
    "project_to_acta",
    "verify_acta_projection",
]

#: Namespaced payload type of a projected decision receipt.
ACTA_PAYLOAD_TYPE = "aragora:decision"
#: Digest scope of ``previousReceiptHash``: the whole signed predecessor envelope.
ACTA_CHAIN_SCOPE = "acta-02"
#: JOSE name of the Ed25519 signature algorithm (the draft's spelling).
ACTA_SIGNATURE_ALG = "EdDSA"
#: First link of a chain has no predecessor.
GENESIS_PREVIOUS_RECEIPT_HASH = "0" * 64
#: Upper bound on the optional human-readable ``payload_digest.preview``.
PREVIEW_MAX_CHARS = 256

PASS = "pass"
FAIL = "fail"
SKIP = "skip"

_HASH_PREFIX = "sha256:"
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")
_ED25519_SIG_HEX = re.compile(r"[0-9a-f]{128}")
_RFC3339 = re.compile(
    r"(?P<date>\d{4}-\d{2}-\d{2})[Tt](?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})"
    r"(\.\d+)?([Zz]|[+-](?P<offset_hour>\d{2}):(?P<offset_minute>\d{2}))"
)
_PAYLOAD_MEMBERS = frozenset(
    {
        "type",
        "issued_at",
        "issuer_id",
        "chain_scope",
        "previousReceiptHash",
        "payload_digest",
        "odr",
    }
)
_SIGNATURE_MEMBERS = frozenset({"alg", "kid", "sig"})
_DIGEST_REQUIRED = frozenset({"hash", "size"})
_DIGEST_MEMBERS = _DIGEST_REQUIRED | {"preview"}


@dataclass(frozen=True)
class ActaCheck:
    """One named projection check and its outcome (``pass``/``fail``/``skip``)."""

    name: str
    status: str
    detail: str


@dataclass
class ActaVerifyResult:
    """Structured projection verdict.

    ``ok`` is the single PASS/FAIL: nothing checked contradicts the envelope.
    It is NOT a statement about authenticity — without a public key the
    signature is skipped rather than failed, exactly as an unkeyed ODR
    verification behaves. Callers that need "this envelope is authentic" must
    read ``authenticity_unverified`` too, which is what the bundled CLI does
    before it prints UNVERIFIED.
    """

    ok: bool
    checks: list[ActaCheck] = field(default_factory=list)

    @property
    def reasons(self) -> list[str]:
        """``"<check>: <detail>"`` for every failing check, in check order."""
        return [f"{check.name}: {check.detail}" for check in self.checks if check.status == FAIL]

    @property
    def authenticity_unverified(self) -> bool:
        """True when nothing authenticated the envelope, e.g. no public key."""
        return any(c.name == "acta_signature" and c.status == SKIP for c in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "authenticity_unverified": self.authenticity_unverified,
            "checks": [
                {"name": c.name, "status": c.status, "detail": c.detail} for c in self.checks
            ],
            "reasons": self.reasons,
        }


def acta_payload_digest(odr_doc: Mapping[str, Any]) -> dict[str, Any]:
    """``{hash, size, preview}`` over the JCS bytes of the WHOLE ODR document."""
    canonical = jcs_canonicalize(odr_doc)
    return {
        "hash": _HASH_PREFIX + hashlib.sha256(canonical).hexdigest(),
        "size": len(canonical),
        "preview": canonical.decode("utf-8")[:PREVIEW_MAX_CHARS],
    }


def ed25519_key_id(public_key: Any) -> str | None:
    """``ed25519-`` + first 16 hex of SHA-256(raw public key), or ``None``.

    The same key id both packages' ``compute_key_id`` produce (asserted by
    tests on both sides). It is recomputed here rather than imported so this
    module keeps working as a verbatim copy in either package. ``None`` means
    the object is not an Ed25519 public key, so no label can be bound to it.
    """
    try:
        from cryptography.hazmat.primitives import serialization
    except ImportError:  # pragma: no cover - declared dependency of both packages
        return None
    try:
        raw = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    except (AttributeError, TypeError, ValueError):
        return None
    return "ed25519-" + hashlib.sha256(raw).hexdigest()[:16]


def acta_envelope_hash(envelope: Mapping[str, Any]) -> str:
    """SHA-256 hex of the JCS bytes of a whole signed envelope (``acta-02`` scope).

    This is the value the NEXT link carries in ``previousReceiptHash``.
    """
    return hashlib.sha256(jcs_canonicalize(envelope)).hexdigest()


def project_to_acta(
    odr_doc: Mapping[str, Any],
    *,
    private_key: Any,
    kid: str,
    previous_receipt_hash: str | None = None,
    issued_at: datetime | str | None = None,
) -> dict[str, Any]:
    """Project an ODR document into a signed ACTA-02 envelope.

    Args:
        odr_doc: The ODR document to carry, verbatim. It is not mutated.
        private_key: The Ed25519 signing key; ``sig`` covers ``JCS(payload)``.
        kid: The signing key's id -- ``compute_key_id(private_key.public_key())``,
            so it equals ``odr_doc["signatures"][0]["key_id"]`` for a document
            signed with the same key. It is also the payload's ``issuer_id``.
        previous_receipt_hash: 64 lowercase hex, the previous envelope's
            :func:`acta_envelope_hash`. ``None`` is genesis (all zero).
        issued_at: Envelope issue time (RFC 3339 UTC); defaults to now. Pinning
            it makes the projection reproducible for committed test vectors.

    Returns:
        ``{"payload": {...}, "signature": {"alg", "kid", "sig"}}``.
    """
    if not isinstance(odr_doc, Mapping):
        raise TypeError(f"odr_doc must be an ODR document mapping, got {type(odr_doc).__name__}")
    if not isinstance(kid, str) or not kid:
        raise ValueError("kid must be the non-empty key id of the signing key")
    link = GENESIS_PREVIOUS_RECEIPT_HASH if previous_receipt_hash is None else previous_receipt_hash
    if not isinstance(link, str) or not _SHA256_HEX.fullmatch(link):
        raise ValueError(
            "previous_receipt_hash must be 64 lowercase hex characters "
            "(SHA-256 of the JCS bytes of the previous envelope)"
        )
    document = copy.deepcopy(dict(odr_doc))
    payload = {
        "type": ACTA_PAYLOAD_TYPE,
        "issued_at": _rfc3339(issued_at),
        "issuer_id": kid,
        "chain_scope": ACTA_CHAIN_SCOPE,
        "previousReceiptHash": link,
        "payload_digest": acta_payload_digest(document),
        "odr": document,
    }
    signature = private_key.sign(jcs_canonicalize(payload))
    return {
        "payload": payload,
        "signature": {"alg": ACTA_SIGNATURE_ALG, "kid": kid, "sig": signature.hex()},
    }


def verify_acta_projection(
    envelope: Any,
    public_key: Any | None = None,
    *,
    previous_envelope: Mapping[str, Any] | None = None,
) -> ActaVerifyResult:
    """Verify envelope shape, the ODR binding, the signature and the chain link.

    ``signature.kid`` (and therefore ``payload.issuer_id``) must name the
    verifying key, so a valid signer cannot relabel an envelope as another
    issuer. ``previousReceiptHash`` is always checked for being 64 lowercase
    hex; it is compared against a recomputed digest ONLY when
    ``previous_envelope`` is supplied, and stays SKIP otherwise, so a single
    non-genesis link verifies on its own. Without ``public_key`` the signature
    check is SKIP, not FAIL.
    """
    shape = _check_shape(envelope)
    checks = [shape]
    if shape.status == FAIL:
        return ActaVerifyResult(ok=False, checks=checks)
    payload = envelope["payload"]
    checks.append(_check_binding(payload))
    checks.append(_check_signature(payload, envelope["signature"], public_key))
    checks.append(_check_chain(payload, previous_envelope))
    return ActaVerifyResult(ok=not any(c.status == FAIL for c in checks), checks=checks)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _rfc3339(value: datetime | str | None) -> str:
    if value is None:
        value = datetime.now(timezone.utc)
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not isinstance(value, str) or not value:
        raise ValueError("issued_at must be a datetime or a non-empty RFC 3339 string")
    return value


def _is_rfc3339(value: str) -> bool:
    """RFC 3339 shape AND a real instant: the shape alone admits 9999-99-99T99:99:99Z."""
    match = _RFC3339.fullmatch(value)
    if match is None:
        return False
    try:
        datetime.strptime(match["date"], "%Y-%m-%d")
    except ValueError:
        return False
    # second 60 is the RFC 3339 leap second.
    if int(match["hour"]) > 23 or int(match["minute"]) > 59 or int(match["second"]) > 60:
        return False
    if match["offset_hour"] is None:
        return True
    return int(match["offset_hour"]) <= 23 and int(match["offset_minute"]) <= 59


def _shape_errors(envelope: Any) -> list[str]:
    if not isinstance(envelope, Mapping):
        return [f"envelope must be an object, got {type(envelope).__name__}"]
    errors: list[str] = []
    members = set(envelope)
    if members != {"payload", "signature"}:
        errors.append(
            f"envelope members must be exactly payload, signature (got {_names(members)})"
        )
    signature = envelope.get("signature")
    kid: Any = None
    if not isinstance(signature, Mapping):
        errors.append("signature must be an object")
    else:
        if set(signature) != _SIGNATURE_MEMBERS:
            errors.append(
                f"signature members must be exactly alg, kid, sig (got {_names(set(signature))})"
            )
        if signature.get("alg") != ACTA_SIGNATURE_ALG:
            errors.append(f"signature.alg must be {ACTA_SIGNATURE_ALG!r}")
        kid = signature.get("kid")
        if not isinstance(kid, str) or not kid:
            errors.append("signature.kid must be a non-empty string")
        sig = signature.get("sig")
        if not isinstance(sig, str) or not _ED25519_SIG_HEX.fullmatch(sig):
            errors.append("signature.sig must be a 128-character lowercase hex Ed25519 signature")
    payload = envelope.get("payload")
    if not isinstance(payload, Mapping):
        errors.append("payload must be an object")
        return errors
    if set(payload) != _PAYLOAD_MEMBERS:
        errors.append(
            f"payload members must be exactly {_names(_PAYLOAD_MEMBERS)} (got {_names(set(payload))})"
        )
    if payload.get("type") != ACTA_PAYLOAD_TYPE:
        errors.append(f"payload.type must be {ACTA_PAYLOAD_TYPE!r}")
    if payload.get("chain_scope") != ACTA_CHAIN_SCOPE:
        errors.append(f"payload.chain_scope must be {ACTA_CHAIN_SCOPE!r}")
    issued_at = payload.get("issued_at")
    if not isinstance(issued_at, str) or not _is_rfc3339(issued_at):
        errors.append("payload.issued_at must be an RFC 3339 timestamp with a UTC offset")
    if kid is not None and payload.get("issuer_id") != kid:
        errors.append("payload.issuer_id must equal signature.kid")
    link = payload.get("previousReceiptHash")
    if not isinstance(link, str) or not _SHA256_HEX.fullmatch(link):
        errors.append("payload.previousReceiptHash must be 64 lowercase hex characters")
    errors.extend(_digest_errors(payload.get("payload_digest")))
    if not isinstance(payload.get("odr"), Mapping):
        errors.append("payload.odr must be the projected ODR document object")
    return errors


def _digest_errors(digest: Any) -> list[str]:
    if not isinstance(digest, Mapping):
        return ["payload.payload_digest must be an object"]
    errors: list[str] = []
    members = set(digest)
    if not _DIGEST_REQUIRED <= members or not members <= _DIGEST_MEMBERS:
        errors.append(
            f"payload.payload_digest members must be hash, size and optionally preview "
            f"(got {_names(members)})"
        )
    value = digest.get("hash")
    if not isinstance(value, str) or not value.startswith(_HASH_PREFIX):
        errors.append(f"payload.payload_digest.hash must start with {_HASH_PREFIX!r}")
    elif not _SHA256_HEX.fullmatch(value[len(_HASH_PREFIX) :]):
        errors.append("payload.payload_digest.hash must carry 64 lowercase hex characters")
    size = digest.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        errors.append("payload.payload_digest.size must be a non-negative integer")
    if "preview" in members and not (
        isinstance(digest["preview"], str) and 0 < len(digest["preview"]) <= PREVIEW_MAX_CHARS
    ):
        # An empty preview would satisfy the prefix binding check while claiming
        # nothing; a producer with nothing to show omits the member instead.
        errors.append(
            f"payload.payload_digest.preview must be 1-{PREVIEW_MAX_CHARS} characters when present"
        )
    return errors


def _check_shape(envelope: Any) -> ActaCheck:
    errors = _shape_errors(envelope)
    if errors:
        return ActaCheck("acta_envelope", FAIL, "; ".join(errors[:6]))
    return ActaCheck("acta_envelope", PASS, f"{ACTA_CHAIN_SCOPE} envelope for {ACTA_PAYLOAD_TYPE}")


def _check_binding(payload: Mapping[str, Any]) -> ActaCheck:
    declared = payload["payload_digest"]
    try:
        recomputed = acta_payload_digest(payload["odr"])
    except (TypeError, ValueError) as exc:
        return ActaCheck("acta_binding", FAIL, f"cannot canonicalize payload.odr: {exc}")
    if declared["hash"] != recomputed["hash"]:
        return ActaCheck(
            "acta_binding",
            FAIL,
            f"payload.odr hashes to {recomputed['hash']}, envelope declares {declared['hash']}",
        )
    if declared["size"] != recomputed["size"]:
        return ActaCheck(
            "acta_binding",
            FAIL,
            f"payload.odr is {recomputed['size']} JCS bytes, envelope declares {declared['size']}",
        )
    preview = declared.get("preview")
    if preview is not None and not recomputed["preview"].startswith(preview):
        return ActaCheck("acta_binding", FAIL, "payload_digest.preview is not a payload prefix")
    return ActaCheck("acta_binding", PASS, f"payload.odr matches {declared['hash']}")


def _check_signature(
    payload: Mapping[str, Any], signature: Mapping[str, Any], public_key: Any | None
) -> ActaCheck:
    kid = signature["kid"]
    if public_key is None:
        return ActaCheck("acta_signature", SKIP, f"no public key supplied for kid={kid}")
    try:
        from cryptography.exceptions import InvalidSignature
    except ImportError as exc:  # pragma: no cover - declared dependency of both packages
        return ActaCheck("acta_signature", FAIL, f"cryptography is required to verify: {exc}")
    verifying_kid = ed25519_key_id(public_key)
    if verifying_kid is not None and kid != verifying_kid:
        # kid is also payload.issuer_id, the identity a chain consumer reads.
        return ActaCheck(
            "acta_signature",
            FAIL,
            f"signature.kid is {kid}, the verifying key is {verifying_kid} "
            "(possible signer-label tampering)",
        )
    try:
        public_key.verify(bytes.fromhex(signature["sig"]), jcs_canonicalize(payload))
    except InvalidSignature:
        return ActaCheck(
            "acta_signature", FAIL, f"EdDSA signature (kid={kid}) does not verify over JCS(payload)"
        )
    except (TypeError, ValueError) as exc:
        return ActaCheck("acta_signature", FAIL, f"cannot verify EdDSA signature: {exc}")
    return ActaCheck("acta_signature", PASS, f"EdDSA over JCS(payload) verified (kid={kid})")


def _check_chain(
    payload: Mapping[str, Any], previous_envelope: Mapping[str, Any] | None
) -> ActaCheck:
    link = payload["previousReceiptHash"]
    if previous_envelope is None:
        if link == GENESIS_PREVIOUS_RECEIPT_HASH:
            return ActaCheck("acta_chain", PASS, "genesis link (no predecessor)")
        return ActaCheck(
            "acta_chain", SKIP, f"links to {link} (predecessor not supplied, link not recomputed)"
        )
    try:
        expected = acta_envelope_hash(previous_envelope)
    except (TypeError, ValueError) as exc:
        return ActaCheck("acta_chain", FAIL, f"cannot canonicalize the previous envelope: {exc}")
    if link != expected:
        return ActaCheck(
            "acta_chain", FAIL, f"previousReceiptHash is {link}, predecessor hashes to {expected}"
        )
    return ActaCheck("acta_chain", PASS, f"links to the supplied predecessor {expected}")


def _names(members: Any) -> str:
    return ", ".join(sorted(str(member) for member in members)) or "<none>"
