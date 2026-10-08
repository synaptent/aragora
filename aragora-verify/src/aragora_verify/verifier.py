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
   §6 / issue #8225, chosen by the document's ``odr_version`` with no fallback:
   ``0.1`` signs the 32 raw bytes of the digest above; ``0.2`` signs
   ``JCS({"odr_digest", "odr_signature_input": "0.2", "protected"})`` with
   ``protected`` = the entry minus ``signature`` (metadata signer-committed).
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
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from types import ModuleType
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .acta import verify_acta_projection
from .jcs import jcs_canonicalize, odr_content_digest, odr_signature_message
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

#: Members a v0.1 signature cannot commit; their presence on a v0.1 document
#: is reported as unauthenticated (``signed_at`` was always a legal v0.1 member).
_UNAUTHENTICATED_V01_MEMBERS = ("issuer", "role", "expires_at")


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
    dissent_trail: list[str] = field(default_factory=list)
    key_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "authenticity_unverified": self.authenticity_unverified,
            "receipt_id": self.receipt_id,
            "odr_digest": self.odr_digest,
            "checks": [asdict(c) for c in self.checks],
            "warnings": list(self.warnings),
            "dissent_trail": list(self.dissent_trail),
            "key_id": self.key_id,
        }

    @property
    def authenticity_unverified(self) -> bool:
        """True iff authenticity could not be established -- i.e. the ``signature``
        check is SKIP: either the receipt carries signatures that were NOT checked
        (no public key supplied; PR #8388 review [P2a]), or a public key was
        supplied but the receipt carries no signatures to check (PR #8802 round-5
        review [P2]). Such a receipt is structurally OK but NOT authenticated, so
        callers must not treat it as "verified" even though no check hard-failed.
        An unsigned receipt verified WITHOUT a key stays WARN (the v0.1 norm).
        An ACTA projection always carries a signature (it is REQUIRED by the
        envelope shape), so a skipped `acta_signature` is unverified too."""
        return any(
            c.name in ("signature", "acta_signature") and c.status == SKIP for c in self.checks
        )


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
    doc: dict[str, Any],
    digest_hex: str,
    public_key: Ed25519PublicKey | None,
    warnings: list[str],
    verified: list[dict[str, Any]],
) -> Check:
    signatures = doc.get("signatures")
    signatures = signatures if isinstance(signatures, list) else []
    if not signatures and public_key is None:
        return Check(
            "signature",
            WARN,
            f"receipt is unsigned (v{doc['odr_version']}); authenticity not established",
        )
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
    odr_version = doc.get("odr_version")
    provided_key_id = compute_key_id(public_key)
    verified_any = False
    failed_matching = False
    key_id_mismatch = False
    notes: list[str] = []
    for i, sig in enumerate(signatures):
        if not isinstance(sig, dict):
            continue
        key_id = str(sig.get("key_id") or "")
        if key_id != provided_key_id:
            warnings.append(f"signatures[{i}]: key_id_mismatch: {key_id} != {provided_key_id}")
        raw_sig = _decode_signature(str(sig.get("signature") or ""))
        if raw_sig is None:
            notes.append(f"sig[{i}]: undecodable signature")
            if key_id == provided_key_id:
                failed_matching = True
            continue
        # Spec §6: the DOCUMENT's version picks the construction; a 0.2 entry's
        # protected members are rebuilt from the entry, so tampering fails here.
        protected = {k: v for k, v in sig.items() if k != "signature"}
        message = odr_signature_message(digest_hex, odr_version, protected)
        try:
            public_key.verify(raw_sig, message)
            if key_id == provided_key_id:
                verified_any = True
                verified.append(sig)
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

    def _as_list(container: dict[str, Any], key: str) -> list[Any]:
        # A member present but null is not an absent member, so dict.get's
        # default never fires; schema_conformance is what reports the defect.
        value = container.get(key)
        return value if isinstance(value, list) else []

    participants = {
        str(p.get("agent"))
        for p in _as_list(quorum, "participants")
        if isinstance(p, dict) and p.get("agent")
    }
    referenced: set[str] = set()
    referenced.update(str(a) for a in _as_list(quorum, "supporting_agents") if isinstance(a, str))
    dissent = quorum.get("dissent")
    if isinstance(dissent, dict):
        referenced.update(
            str(a) for a in _as_list(dissent, "dissenting_agents") if isinstance(a, str)
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


def _verdicts_consistency_checks(quorum: dict[str, Any]) -> list[Check]:
    participants = {p["agent"] for p in quorum["participants"]}
    missing = sorted({v["issuer"] for v in quorum.get("verdicts", [])} - participants)
    if not missing:
        return []
    return [
        Check("verdicts_consistency", FAIL, "issuers not in participants: " + ", ".join(missing))
    ]


def _dissent_finding_checks(findings: list[dict[str, Any]]) -> list[Check]:
    checks = []
    for i, finding in enumerate(findings):
        want = finding["severity"] in ("P0", "P1")
        if finding["blocking"] != want:
            detail = f"findings[{i}].blocking: expected {want!r} for {finding['severity']}"
            checks.append(Check("dissent_consistency", FAIL, f"quorum.dissent.{detail}"))
    return checks


def _dissent_rollup_checks(dissent: dict[str, Any]) -> list[Check]:
    severities = [f["severity"] for f in dissent["findings"]]
    expected: dict[str, object] = {
        "severity_max": min(severities, default=None),
        "blocking": any(s in ("P0", "P1") for s in severities),
    }
    checks = []
    for member, value in expected.items():
        if member in dissent and dissent[member] != value:
            checks.append(
                Check(
                    "dissent_consistency",
                    FAIL,
                    f"quorum.dissent.{member}: expected {value!r} from findings",
                )
            )
    return checks


def _quorum_rule_checks(quorum: dict[str, Any], dissent: dict[str, Any]) -> list[Check]:
    rule = quorum.get("rule")
    if not rule:
        return []
    # The recorded rule is a necessary bar; merge-quorum also requires posting.
    families = set(rule["counted_families"])
    reached = len(families) >= rule["required_signals"]
    if rule["requires_western_frontier"]:
        reached = reached and bool(families & {"claude", "openai"})
    if dissent.get("present") or dissent.get("dissenting_agents"):
        reached = False
    if reached != quorum["reached"] and (quorum["reached"] or quorum["method"] != "merge-quorum"):
        return [
            Check(
                "quorum_rule",
                WARN,
                f"quorum.reached: recorded {quorum['reached']}, rule implies {reached}",
            )
        ]
    return []


def _check_v02_consistency(doc: dict[str, Any]) -> list[Check]:
    """Cross-check recorded content, never infer gate dissent from findings."""
    quorum = doc["quorum"]
    if doc["odr_version"] != "0.2" or quorum.get("status") != "present":
        return []
    checks = _verdicts_consistency_checks(quorum)
    dissent = quorum["dissent"]
    if "findings" in dissent:
        checks.extend(_dissent_finding_checks(dissent["findings"]))
        checks.extend(_dissent_rollup_checks(dissent))
    checks.extend(_quorum_rule_checks(quorum, dissent))
    return checks


def _check_expiry(
    doc: dict[str, Any], now: datetime | None, strict: bool, verified: list[dict[str, Any]]
) -> list[Check]:
    if doc["odr_version"] != "0.2":
        return []
    clock = now if now is not None else datetime.now(timezone.utc)
    checks = []
    for i, sig in enumerate(doc["signatures"]):
        if sig not in verified or "expires_at" not in sig:
            continue
        detail = ""
        try:
            expires = datetime.fromisoformat(sig["expires_at"].replace("Z", "+00:00"))
            if expires.utcoffset() is None or clock.utcoffset() is None:
                raise ValueError("a timezone is required")
            if clock >= expires:
                detail = f"signatures[{i}]: expired at {sig['expires_at']}"
        except ValueError:
            detail = (
                f"signatures[{i}]: cannot evaluate expires_at (timezone-aware timestamps required)"
            )
        if detail:
            checks.append(Check("signature_expiry", FAIL if strict else WARN, detail))
    return checks


def _dissent_trail(doc: dict[str, Any]) -> list[str]:
    trail = []
    for finding in doc["quorum"].get("dissent", {}).get("findings", []):
        label = "blocking" if finding["severity"] in ("P0", "P1") else "advisory"
        trail.append(f"[{finding['severity']}] {finding['issuer']} ({label}): {finding['text']}")
    if "adjudication" in doc:
        if not trail:
            trail.append("(no dissent recorded)")
        adj = doc["adjudication"]
        trail.append(f"Adjudication: {adj['verdict']} — {adj['reason']}")
    return trail


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
            else:
                # Weakening signals warn, never fail (spec §8): a non-numeric
                # families value degrades to a warning instead of raising, as
                # aragora.gauntlet.odr_verify does for the same member.
                try:
                    families: int | None = int(independence.get("distinct_model_families", 0) or 0)
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

    # A v0.1 signature covers only the digest, so entry metadata on a v0.1
    # document is a claim nobody signed (spec §6); v0.2 entries commit it.
    if doc.get("odr_version") != "0.2":
        for i, sig in enumerate(doc.get("signatures") or ()):
            loose = [m for m in _UNAUTHENTICATED_V01_MEMBERS if isinstance(sig, dict) and m in sig]
            if loose:
                warnings.append(
                    f"signatures[{i}]: unauthenticated signature metadata ({', '.join(loose)}) "
                    "— a v0.1 signature does not cover these members"
                )
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


def looks_like_acta_envelope(doc: Any) -> bool:
    """Heuristic: is ``doc`` an ACTA-02 projection rather than an ODR document?

    A projection carries the receipt inside ``payload.odr``, so the CLI can
    accept a ``.acta.json`` directly instead of the ``.odr.json`` beside it.
    """
    if not isinstance(doc, dict) or "signature" not in doc:
        return False
    payload = doc.get("payload")
    return isinstance(payload, dict) and "odr" in payload


def _check_projection(envelope: Any, doc: dict[str, Any], public_key: Any | None) -> list[Check]:
    """Projection checks plus the binding of the envelope to THIS receipt."""
    result = verify_acta_projection(envelope, public_key)
    checks = [Check(c.name, c.status, c.detail) for c in result.checks]
    payload = envelope.get("payload") if isinstance(envelope, dict) else None
    projected = payload.get("odr") if isinstance(payload, dict) else None
    # Canonical bytes, not dict equality: JSON `true` and `1` compare equal in
    # Python but hash differently, and this check backs a digest claim.
    try:
        matches = jcs_canonicalize(projected) == jcs_canonicalize(doc)
    except (TypeError, ValueError):
        matches = False
    checks.append(
        Check(
            "acta_receipt_match",
            PASS if matches else FAIL,
            (
                "projection carries this receipt"
                if matches
                else "payload.odr is not the receipt being verified"
            ),
        )
    )
    return checks


_NATIVE_RECEIPT_HINT = (
    "input looks like a native Aragora receipt, not an ODR document -- convert "
    "it first: aragora receipt export <file> --format odr -o receipt.odr.json, "
    "then re-run aragora-verify on receipt.odr.json"
)


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


def _safe_check(name: str, fn: Callable[[], Check]) -> Check:
    """Boundary contract: this engine verifies untrusted, possibly-tampered
    receipts, so an exception raised while checking structurally-valid-but-
    malformed input becomes a FAIL verdict instead of propagating as a crash
    (mirrors ``aragora.gauntlet.odr_verify``). The v0.2 consistency checks are
    not wrapped: they read only schema-validated members."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - boundary: malformed input -> FAIL, not crash
        return Check(
            name, FAIL, f"verification raised on malformed input: {type(exc).__name__}: {exc}"
        )


def verify(
    doc: Any,
    *,
    public_key: Any | None = None,
    chain: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
    strict_expiry: bool = False,
    require_issuer: str | None = None,
    acta: dict[str, Any] | None = None,
) -> VerifyResult:
    """Verify an ODR document. ``public_key`` is a loaded Ed25519 key (see
    :func:`load_public_key`); ``chain`` is a list of parsed JSONL chain entries.
    ``now`` overrides the timezone-aware expiry clock; ``strict_expiry`` fails
    on expiry. ``require_issuer`` requires a verifying signer-committed v0.2 issuer.
    ``acta`` is an ACTA-02 projection envelope that must carry exactly this
    document (``aragora_verify.acta``).
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
    checks.append(
        Check("schema_conformance", PASS, f"conforms to ODR v{doc['odr_version']} profile")
    )
    checks.append(_safe_check("quorum_consistency", lambda: _check_quorum_consistency(doc)))
    checks.extend(_check_v02_consistency(doc))

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

    warnings: list[str] = []
    verified: list[dict[str, Any]] = []
    checks.append(
        _safe_check(
            "signature", lambda: _check_signatures(doc, digest_hex, public_key, warnings, verified)
        )
    )
    checks.extend(_check_expiry(doc, now, strict_expiry, verified))
    if require_issuer is not None:
        found = doc["odr_version"] == "0.2" and any(
            sig.get("issuer") == require_issuer for sig in verified
        )
        checks.append(
            Check(
                "require_issuer",
                PASS if found else FAIL,
                f"issuer {require_issuer!r}: "
                + ("verified" if found else "no verifying v0.2 signature"),
            )
        )
    checks.append(_safe_check("chain_link", lambda: _check_chain(doc, digest_hex, chain)))
    if acta is not None:
        checks.extend(_check_projection(acta, doc, public_key))

    warnings.extend(
        c.detail
        for c in checks
        if c.status == WARN and c.name in ("quorum_rule", "signature_expiry")
    )
    warnings.extend(_weakening_warnings(doc))
    ok = not any(c.status == FAIL for c in checks)
    return VerifyResult(
        ok=ok,
        receipt_id=receipt_id,
        odr_digest=digest_hex,
        checks=checks,
        warnings=warnings,
        dissent_trail=_dissent_trail(doc),
        key_id=verified[0]["key_id"] if verified else None,
    )


def verify_path(
    receipt_path: str,
    *,
    pubkey_path: str | None = None,
    chain_path: str | None = None,
    now: datetime | None = None,
    strict_expiry: bool = False,
    require_issuer: str | None = None,
    acta_path: str | None = None,
) -> VerifyResult:
    """Convenience wrapper that reads files from disk and calls :func:`verify`.

    With no ``acta_path``, a receipt file that is itself an ACTA-02 projection
    is detected and verified as one, against the ODR document it carries.
    """
    with open(receipt_path, "rb") as fh:
        doc = json.loads(fh.read())
    acta: dict[str, Any] | None = None
    if acta_path:
        with open(acta_path, "rb") as fh:
            acta = json.loads(fh.read())
    if looks_like_acta_envelope(doc):
        if acta is not None:
            # Verifying the --acta file while printing a verdict for the file
            # the caller named would leave that file unchecked.
            raise VerificationError(
                f"{receipt_path} is itself an ACTA-02 projection: pass it alone, "
                "or pass the ODR document it carries with --acta"
            )
        acta, doc = doc, doc["payload"]["odr"]
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
    return verify(
        doc,
        public_key=public_key,
        chain=chain,
        now=now,
        strict_expiry=strict_expiry,
        require_issuer=require_issuer,
        acta=acta,
    )
