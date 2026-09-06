"""Offline verification of an Open Decision Receipt (ODR v0.1).

This is the standalone library engine behind the ``aragora-verify`` CLI --
zero-Aragora-dependency, stdlib + ``cryptography`` only. It is kept in
lockstep with the in-tree mirror, ``aragora.gauntlet.odr_verify`` (issue
#8226): both follow the same content profile
(``docs/specs/OPEN_DECISION_RECEIPT.md``) and signature construction (§6 /
issue #8225), so a receipt verifies identically whether checked here or
in-tree. No shipped server endpoint wraps this engine today -- the existing
``/api/v2/receipts/{id}/verify*`` and ``/receipts/{id}/verify`` routes verify
the native or legacy receipt instead (see
``docs/specs/RECEIPT_LINEAGE_RECONCILIATION.md`` "Two verifiers" for the full
picture).

It establishes, with nothing but the receipt JSON (and optionally a public
key and a hash chain):

1. **Structural conformance** to the ODR v0.1 profile (``schema``).
2. **Canonical digest** — recomputes ``odr_digest = SHA-256(JCS(doc - signatures))``
   deterministically (``jcs``), the value any detached signature covers.
3. **Ed25519 signatures** — verifies each ``signatures[]`` entry against a
   supplied public key, per the construction in ``OPEN_DECISION_RECEIPT.md``
   §6 / issue #8225: the signed message is the SHA-256 digest above.
4. **Quorum consistency** — every supporting/dissenting agent appears among
   ``quorum.participants`` (spec §8: a mismatch is a malformed/tamper signal).
5. **Hash-chain linkage** — when a chain is supplied, the receipt is anchored
   in it and the chain's links are continuous.

Absent markers and ``"undisclosed"`` *weaken* a receipt (warnings) rather than
failing it — verification reports the evidence; policy thresholds are the
caller's choice (spec §8).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import asdict, dataclass, field
from types import ModuleType
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .jcs import odr_content_digest
from .schema import validate_structure

__all__ = [
    "Check",
    "VerifyResult",
    "verify",
    "compute_key_id",
    "load_public_key",
    "VerificationError",
]

PASS = "pass"
FAIL = "fail"
WARN = "warn"
SKIP = "skip"


class VerificationError(Exception):
    """Raised for unrecoverable input problems (e.g. unreadable public key)."""


@dataclass(frozen=True)
class Check:
    """One named verification step and its outcome."""

    name: str
    status: str  # pass | fail | warn | skip
    detail: str


@dataclass
class VerifyResult:
    """Structured verdict. ``ok`` is the single PASS/FAIL the CLI exits on."""

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
        """True iff authenticity could not be established -- i.e. the ``signature``
        check is SKIP: either the receipt carries signatures that were NOT checked
        (no public key supplied; PR #8388 review [P2a]), or a public key was
        supplied but the receipt carries no signatures to check (PR #8802 round-5
        review [P2]). Such a receipt is structurally OK but NOT authenticated, so
        callers must not treat it as "verified" even though no check hard-failed.
        An unsigned receipt verified WITHOUT a key stays WARN (the v0.1 norm)."""
        return any(c.name == "signature" and c.status == SKIP for c in self.checks)


# ---------------------------------------------------------------------------
# Public-key handling (the one crypto dependency)
# ---------------------------------------------------------------------------


def _load_ed25519() -> tuple[type[Ed25519PublicKey], ModuleType, type[InvalidSignature]]:
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:  # pragma: no cover - dependency declared in pyproject
        raise VerificationError(
            "the 'cryptography' package is required for signature verification; "
            "install with `pip install aragora-verify`"
        ) from exc
    return Ed25519PublicKey, serialization, InvalidSignature


def load_public_key(data: bytes) -> Ed25519PublicKey:
    """Load an Ed25519 public key from PEM, DER, raw 32 bytes, or base64/hex text."""
    Ed25519PublicKey, serialization, _ = _load_ed25519()  # noqa: N806 - Lazy import retains the class name.
    key = None
    # PEM (wrap parse errors instead of leaking a traceback on hostile input).
    if b"-----BEGIN" in data:
        try:
            key = serialization.load_pem_public_key(data.strip())
        except (ValueError, TypeError) as exc:
            raise VerificationError("could not parse PEM public key") from exc
    # Raw 32-byte key -- use the UNSTRIPPED bytes (a raw key may legitimately begin
    # or end with a whitespace-valued byte; stripping would corrupt it).
    elif len(data) == 32:
        key = Ed25519PublicKey.from_public_bytes(data)
    else:
        as_str = data.decode("ascii", errors="ignore").strip()
        for decoder in (_maybe_b64, _maybe_hex):
            raw = decoder(as_str)
            if raw is not None and len(raw) == 32:
                key = Ed25519PublicKey.from_public_bytes(raw)
                break
        if key is None:
            try:
                key = serialization.load_der_public_key(data)
            except Exception as exc:  # noqa: BLE001
                raise VerificationError(
                    "could not parse public key (expected PEM/DER/raw/base64/hex)"
                ) from exc
    # A valid RSA/ECDSA key parses fine but is the wrong algorithm; reject it
    # cleanly rather than crashing later in compute_key_id / verify (review [P2]).
    if not isinstance(key, Ed25519PublicKey):
        raise VerificationError(
            f"public key is not Ed25519 (got {type(key).__name__}); ODR signatures use Ed25519"
        )
    return key


def compute_key_id(public_key: Ed25519PublicKey) -> str:
    """``ed25519-`` + first 16 hex of SHA-256(raw public key) — the #8225 key id."""
    _, serialization, _ = _load_ed25519()
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
    """Signatures are base64 (preferred) or hex of the raw 64-byte Ed25519 sig."""
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


def _check_signatures(  # noqa: C901 - Preserve signature outcome precedence and tamper diagnostics.
    doc: dict[str, Any], digest_hex: str, public_key: Ed25519PublicKey | None
) -> Check:
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
            f"{len(signatures)} signature(s) present but no --pubkey supplied; authenticity NOT verified",
        )

    _, _, InvalidSignature = _load_ed25519()  # noqa: N806 - Lazy import retains the exception class name.
    public_key = cast("Ed25519PublicKey", public_key)  # None paths returned above.
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
            if key_id == provided_key_id:
                verified_any = True
                notes.append(f"sig[{i}] (key_id={key_id}): verified")
            else:
                key_id_mismatch = True
                notes.append(
                    f"sig[{i}]: signature verifies with the supplied key but its recorded "
                    f"key_id ({key_id or '?'}) does not match the supplied key's id "
                    f"({provided_key_id}) — possible signer-label tampering"
                )
        except InvalidSignature:
            notes.append(f"sig[{i}] (key_id={key_id or '?'}): INVALID")
            if key_id == provided_key_id:
                failed_matching = True

    detail = "; ".join(notes) or "no signatures evaluated"
    if failed_matching:
        return Check("signature", FAIL, f"signature check failed — {detail}")
    # A valid, correctly-bound signature wins even when an extra entry carries a
    # relabeled copy: authenticity is already established and the mislabeled entry
    # is surfaced in the detail. Mirrors aragora.gauntlet.odr_verify's separate
    # key_id_mismatch flag with verified_any-wins ordering (#8810 parity).
    if verified_any:
        return Check("signature", PASS, f"Ed25519 signature verified — {detail}")
    if key_id_mismatch:
        return Check("signature", FAIL, f"signer-label tampering suspected — {detail}")
    return Check("signature", FAIL, f"no signature verified with the supplied key — {detail}")


def _check_quorum_consistency(doc: dict[str, Any]) -> Check:
    quorum = doc.get("quorum")
    if not isinstance(quorum, dict) or quorum.get("status") != "present":
        return Check("quorum_consistency", SKIP, "no present quorum block to cross-check")
    participants = {
        str(p.get("agent"))
        for p in quorum.get("participants", [])
        if isinstance(p, dict) and p.get("agent")
    }
    referenced: set[str] = set()
    referenced.update(str(a) for a in quorum.get("supporting_agents", []) if isinstance(a, str))
    dissent = quorum.get("dissent")
    if isinstance(dissent, dict):
        referenced.update(
            str(a) for a in dissent.get("dissenting_agents", []) if isinstance(a, str)
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


def _check_chain(  # noqa: C901 - Keep continuity and digest anchoring checks ordered.
    doc: dict[str, Any], digest_hex: str, chain: list[dict[str, Any]] | None
) -> Check:
    if chain is None:
        return Check("chain_link", SKIP, "no --chain supplied")
    if not chain:
        return Check("chain_link", FAIL, "chain file is empty")

    # Linkage continuity, when entries carry hash/prev links.
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

    # Anchoring: the receipt's CONTENT DIGEST must appear in the chain. We do NOT
    # accept the mutable, non-cryptographic ``receipt_id`` as an anchor (PR #8388
    # review [P2b]): a tampered body could reuse a legitimate receipt_id and forge
    # a false "anchored" assurance. Only the JCS content digest binds.
    anchored = False
    for entry in chain:
        values = {str(v) for v in entry.values() if isinstance(v, (str, int))}
        if digest_hex in values:
            anchored = True
            break

    if broken:
        return Check("chain_link", FAIL, "broken hash-chain linkage: " + "; ".join(broken))
    if not anchored:
        return Check(
            "chain_link",
            FAIL,
            "receipt content digest not found among chain entries (not anchored)",
        )
    # NOTE: linkage only checks declared prev_hash == declared previous hash; it
    # asserts self-consistency of the supplied chain, not that each entry's hash
    # was recomputed from its content. Independent re-hashing is out of scope here.
    if saw_links:
        # Anchoring is real (the content digest IS in the chain), but we only
        # checked declared prev/hash self-consistency -- no entry hash was
        # recomputed, so this is NOT a tamper-proof integrity guarantee. Report
        # WARN, not PASS, so the human verdict never overstates the assurance
        # (review): an attacker who controls the chain file can fake linkage.
        return Check(
            "chain_link",
            WARN,
            "receipt anchored; declared prev/hash links are self-consistent but NOT "
            "recomputed -- this is not an integrity proof of the chain itself",
        )
    return Check("chain_link", PASS, "receipt anchored in chain (no prev-hash links to verify)")


def _weakening_warnings(doc: dict[str, Any]) -> list[str]:  # noqa: C901 - Keep independent ODR warning conditions together.
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
            elif int(independence.get("distinct_model_families", 0) or 0) < 2:
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


def _looks_like_native_receipt(doc: Any) -> bool:
    """Heuristic: is ``doc`` a native Aragora ``DecisionReceipt`` rather than an
    ODR document? ``aragora demo --receipt`` / ``aragora receipt`` write the
    native format, and strangers feed it to this verifier directly (issue
    #9185); an ODR document always carries ``odr_version``, while the native
    format carries its own distinctive members."""
    if not isinstance(doc, dict) or "odr_version" in doc:
        return False
    if not doc.get("receipt_id"):
        return False
    native_markers = ("artifact_hash", "gauntlet_id", "schema_version", "verdict")
    return any(marker in doc for marker in native_markers)


_NATIVE_RECEIPT_HINT = (
    "input looks like a native Aragora receipt, not an ODR document -- convert "
    "it first: aragora receipt export <file> --format odr -o receipt.odr.json, "
    "then re-run aragora-verify on receipt.odr.json"
)


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


def verify(
    doc: Any,
    *,
    public_key: Any | None = None,
    chain: list[dict[str, Any]] | None = None,
) -> VerifyResult:
    """Verify an ODR document. ``public_key`` is a loaded Ed25519 key (see
    :func:`load_public_key`); ``chain`` is a list of parsed JSONL chain entries.
    """
    receipt_id = str(doc.get("receipt_id") or "") if isinstance(doc, dict) else ""
    checks: list[Check] = []

    structure_errors = validate_structure(doc)
    if structure_errors:
        detail = "; ".join(structure_errors[:12])
        if _looks_like_native_receipt(doc):
            # Name the actual mistake and the exact bridge command instead of
            # dumping 12 opaque schema errors on the stranger (issue #9185).
            detail = f"{detail} | {_NATIVE_RECEIPT_HINT}"
        checks.append(Check("schema_conformance", FAIL, detail))
        # A structurally invalid receipt cannot be digested/verified meaningfully.
        return VerifyResult(
            ok=False, receipt_id=receipt_id, odr_digest="", checks=checks, warnings=[]
        )
    checks.append(Check("schema_conformance", PASS, "conforms to ODR v0.1 profile"))

    try:
        digest_hex = odr_content_digest(doc)
    except (ValueError, TypeError) as exc:
        # A crafted receipt (e.g. a non-finite number in an additionalProperties
        # region) must FAIL cleanly, never crash the verifier (review [P2]).
        checks.append(Check("canonical_digest", FAIL, f"cannot canonicalize receipt: {exc}"))
        return VerifyResult(
            ok=False,
            receipt_id=receipt_id,
            odr_digest="",
            checks=checks,
            warnings=_weakening_warnings(doc),
        )
    checks.append(Check("canonical_digest", PASS, f"sha-256:{digest_hex}"))

    checks.append(_check_signatures(doc, digest_hex, public_key))
    checks.append(_check_quorum_consistency(doc))
    checks.append(_check_chain(doc, digest_hex, chain))

    warnings = _weakening_warnings(doc)
    ok = not any(c.status == FAIL for c in checks)
    return VerifyResult(
        ok=ok, receipt_id=receipt_id, odr_digest=digest_hex, checks=checks, warnings=warnings
    )


def verify_path(
    receipt_path: str,
    *,
    pubkey_path: str | None = None,
    chain_path: str | None = None,
) -> VerifyResult:
    """Convenience wrapper that reads files from disk and calls :func:`verify`."""
    with open(receipt_path, "rb") as fh:
        doc = json.loads(fh.read())
    public_key = None
    if pubkey_path:
        with open(pubkey_path, "rb") as fh:
            public_key = load_public_key(fh.read())
    chain: list[dict[str, Any]] | None = None
    if chain_path:
        chain = []
        with open(chain_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    chain.append(json.loads(line))
    return verify(doc, public_key=public_key, chain=chain)
