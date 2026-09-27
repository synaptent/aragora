"""
CLI command: aragora verify -- validate decision receipt integrity.

Runs the following checks on a decision receipt JSON file:

- **Decision-integrity hash** (``integrity`` check): recomputes the SHA-256
  content hash and compares it to the stored value. Receipts store this hash under
  the canonical ``artifact_hash`` field (as emitted by ``DecisionReceipt.to_dict``).
  A legacy ``checksum`` field is accepted as a fallback for older/alternate
  producers, and is also validated when present alongside ``artifact_hash`` so
  dual-field receipts cannot hide a mismatched proof. This hash covers the
  *decision-integrity fields* --
  ``receipt_id``, ``gauntlet_id``, ``input_hash``, ``risk_summary``, ``verdict``,
  and ``confidence`` -- so tampering with any of those is detected. Crux receipts
  (schema >= 1.2) additionally bind ``cruxes`` and ``schema_version`` into the
  hash, so a 1.2 -> 1.1 downgrade is detected as tampering. The hash does **not**
  cover presentational/metadata fields such as ``timestamp`` (or
  ``schema_version`` on pre-crux receipts); for full-payload tamper-evidence,
  sign the receipt and use the signature check (or ``aragora receipt verify``).
  The reported coverage is scoped accordingly so the command does not overclaim.
- **Presence/format checks** (non-integrity): confirms ``schema_version`` is
  present, ``verdict`` is a recognised Verdict enum value, and ``timestamp`` is
  valid ISO 8601. These validate well-formedness, not tamper-evidence.
- **Signature** (optional): if the receipt is cryptographically signed, verifies
  the signature chain, which covers the full serialised payload.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def create_verify_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'verify' subcommand."""
    parser = subparsers.add_parser(
        "verify",
        help="Verify a decision receipt's integrity",
        description=(
            "Validate a decision receipt JSON file. Recomputes the SHA-256 "
            "decision-integrity hash (artifact_hash, plus legacy checksum fallback; "
            "both are checked when both are present) to detect tampering of the decision-integrity fields (receipt_id, "
            "gauntlet_id, input_hash, risk_summary, verdict, confidence; crux receipts "
            "additionally bind cruxes and schema_version); also checks "
            "schema_version presence, that the verdict is a valid enum value, and "
            "timestamp format. Note: the integrity hash does not cover presentational "
            "fields like timestamp -- for full-payload tamper-evidence "
            "the receipt must be cryptographically signed (the signature is verified "
            "when present)."
        ),
    )
    parser.add_argument(
        "receipt_path",
        help="Path to the decision receipt JSON file",
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=["text", "json"],
        default="text",
        help="Output format: text (default) or json",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show full hash chain details",
    )
    parser.set_defaults(func=cmd_verify)


# ---------------------------------------------------------------------------
# Verdict validation
# ---------------------------------------------------------------------------

# Canonical verdict values from aragora.core_types.Verdict
_VALID_VERDICTS = frozenset(
    {
        "approved",
        "approved_with_conditions",
        "needs_review",
        "rejected",
        # Legacy / gauntlet aliases (case-insensitive matching applied separately)
        "pass",
        "fail",
        "conditional",
        # Zero-evidence receipts (issue #9303): a valid receipt that truthfully
        # asserts no deliberation occurred. Integrity-valid, never supportive.
        "no_evidence",
    }
)


def _is_valid_verdict(value: str) -> bool:
    """Check whether *value* is a recognised Verdict string."""
    return value.lower() in _VALID_VERDICTS


# ---------------------------------------------------------------------------
# Timestamp validation
# ---------------------------------------------------------------------------


def _is_valid_iso_timestamp(value: str) -> bool:
    """Return True if *value* can be parsed as an ISO 8601 timestamp."""
    try:
        datetime.fromisoformat(value)
        return True
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Integrity-hash helpers
# ---------------------------------------------------------------------------

# The exact decision-integrity fields covered by the canonical ``artifact_hash``
# (mirrors ``DecisionReceipt._calculate_hash``). These -- and ONLY these -- are the
# fields whose tampering this command's integrity check detects. Reported to the
# user via the ``covers`` key so the command does not overclaim coverage of
# presentational fields (timestamp, ...) the hash does not include. Receipts
# carrying ``cruxes`` additionally bind the crux block, and receipts stamped
# schema 1.2 also bind ``schema_version`` (downgrade-tamper protection) -- see
# ``_integrity_hash_fields``.
_INTEGRITY_HASH_FIELDS: tuple[str, ...] = (
    "receipt_id",
    "gauntlet_id",
    "input_hash",
    "risk_summary",
    "verdict",
    "confidence",
)

# Schema version at which receipts bind ``schema_version`` into the hash
# (mirrors ``RECEIPT_SCHEMA_VERSION_CRUXES`` in receipt_models; kept as a local
# literal so this command never hard-depends on the gauntlet package). The
# binding is version-gated, NOT crux-presence-gated: #9414 shipped crux binding
# before the 1.2 stamp existed, so receipts with cruxes + schema_version 1.1
# hashed without schema_version and must keep verifying.
_SCHEMA_VERSION_CRUXES = "1.2"
_SCHEMA_VERSION_EVIDENCE = "1.3"


def _integrity_hash_fields(data: dict[str, Any]) -> tuple[str, ...]:
    """Fields the artifact hash covers for THIS receipt (honest coverage)."""
    fields = _INTEGRITY_HASH_FIELDS
    if data.get("cruxes") is not None:
        fields = fields + ("cruxes",)
        if data.get("schema_version") == _SCHEMA_VERSION_CRUXES:
            fields = fields + ("schema_version",)
    if data.get("schema_version") == _SCHEMA_VERSION_EVIDENCE:
        fields = fields + (
            "decision_payload",
            "decision_payload_hash",
            "evidence_references",
            "schema_version",
        )
    return fields


def _inline_decision_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _inline_decision_value(value[key])
            for key in sorted(value, key=lambda item: str(item))
        }
    if isinstance(value, (list, tuple)):
        return [_inline_decision_value(item) for item in value]
    if isinstance(value, set):
        normalized = [_inline_decision_value(item) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True, default=str))
    return value


def _inline_evidence_references(references: Any) -> list[dict[str, Any]]:
    normalized = [
        value
        for reference in references or []
        if isinstance((value := _inline_decision_value(reference)), dict)
    ]
    return sorted(
        normalized,
        key=lambda item: (
            str(item.get("evidence_id", "")),
            str(item.get("path", "")),
            json.dumps(item, sort_keys=True, default=str),
        ),
    )


def _inline_decision_payload_hash(data: dict[str, Any]) -> str:
    content = json.dumps(
        {
            "decision_payload": _inline_decision_value(data.get("decision_payload") or {}),
            "evidence_references": _inline_evidence_references(data.get("evidence_references")),
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(content.encode()).hexdigest()


# Decision-integrity fields covered by the legacy ``checksum`` field.
_LEGACY_CHECKSUM_FIELDS: tuple[str, ...] = (
    "receipt_id",
    "verdict",
    "confidence",
    "findings_count",
    "critical_count",
    "timestamp",
    "audit_trail_id",
)


def _recompute_checksum(data: dict[str, Any]) -> str:
    """Recompute the legacy ``checksum`` field the same way the gauntlet pipeline does."""
    content = json.dumps(
        {
            "receipt_id": data.get("receipt_id", ""),
            "verdict": data.get("verdict", ""),
            "confidence": data.get("confidence", 0.0),
            "findings_count": len(data.get("findings", [])),
            "critical_count": data.get("critical_count", 0),
            "timestamp": data.get("timestamp", ""),
            "audit_trail_id": data.get("audit_trail_id"),
        },
        sort_keys=True,
    )
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _inline_artifact_hash(data: dict[str, Any]) -> str:
    """Inline fallback for :func:`_recompute_artifact_hash`.

    Byte-for-byte equivalent to ``compute_receipt_artifact_hash`` in
    ``aragora.gauntlet.receipt_models`` (equivalence is pinned by tests); used
    only when the gauntlet package is not importable. Covers the fields
    reported by :func:`_integrity_hash_fields`: the base decision-integrity
    fields, plus ``cruxes`` when present, plus ``schema_version`` only for
    receipts stamped :data:`_SCHEMA_VERSION_CRUXES` (downgrade-tamper
    protection, version-gated for #9414-era 1.1 crux receipts).
    """
    payload: dict[str, Any] = {
        "receipt_id": data.get("receipt_id", ""),
        "gauntlet_id": data.get("gauntlet_id", ""),
        "input_hash": data.get("input_hash", ""),
        "risk_summary": data.get("risk_summary", {}),
        "verdict": data.get("verdict", ""),
        "confidence": data.get("confidence", 0.0),
    }
    if data.get("cruxes") is not None:
        payload["cruxes"] = data.get("cruxes")
        # Missing schema_version defaults to "1.0" (the from_dict convention)
        # so the same JSON cannot hash two ways.
        schema_version = data.get("schema_version", "1.0")
        if schema_version == _SCHEMA_VERSION_CRUXES:
            payload["schema_version"] = schema_version
    if data.get("schema_version") == _SCHEMA_VERSION_EVIDENCE:
        payload["schema_version"] = _SCHEMA_VERSION_EVIDENCE
        payload["decision_payload_hash"] = data.get("decision_payload_hash", "")
        payload["evidence_references"] = _inline_evidence_references(
            data.get("evidence_references")
        )
    content = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()


def _recompute_artifact_hash(data: dict[str, Any]) -> str:
    """Recompute the canonical content-addressable ``artifact_hash``.

    Delegates to ``compute_receipt_artifact_hash`` -- the single canonical
    recipe shared with ``DecisionReceipt._calculate_hash`` -- so this command
    can never drift from the producer (an earlier inline copy omitted the
    ``cruxes`` branch and reported every untampered crux receipt as tampered).
    Falls back to the byte-equivalent :func:`_inline_artifact_hash` when the
    gauntlet package is not importable, so verification keeps working in
    minimal installs.
    """
    try:
        from aragora.gauntlet.receipt_models import compute_receipt_artifact_hash
    except ImportError:
        return _inline_artifact_hash(data)
    return compute_receipt_artifact_hash(data)


def _looks_like_artifact_hash_alias(value: Any) -> bool:
    """Return True when a ``checksum`` value is actually a full artifact hash."""
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdefABCDEF" for char in value)
    )


# ---------------------------------------------------------------------------
# Core verification logic
# ---------------------------------------------------------------------------


def _verify_receipt(data: dict[str, Any], *, verbose: bool = False) -> dict[str, Any]:
    """Run all verification checks on *data* and return a result dict.

    Returns a dict with keys:
        valid (bool): overall pass/fail
        checks (list[dict]): individual check results
        receipt_id (str): the receipt_id if present
        signed (bool): whether the receipt has a signature
    """
    checks: list[dict[str, Any]] = []
    overall_valid = True

    # -- 1. schema_version present ----------------------------------------
    schema_version = data.get("schema_version")
    if schema_version:
        checks.append(
            {
                "name": "schema_version",
                "passed": True,
                "detail": f"schema_version={schema_version}",
            }
        )
    else:
        checks.append(
            {
                "name": "schema_version",
                "passed": False,
                "detail": "schema_version is missing",
            }
        )
        overall_valid = False

    # -- 2. verdict is valid Verdict enum value ---------------------------
    verdict = data.get("verdict")
    if verdict and _is_valid_verdict(verdict):
        checks.append(
            {
                "name": "verdict",
                "passed": True,
                "detail": f"verdict={verdict}",
            }
        )
    elif verdict:
        checks.append(
            {
                "name": "verdict",
                "passed": False,
                "detail": f"verdict '{verdict}' is not a recognised Verdict value",
            }
        )
        overall_valid = False
    else:
        checks.append(
            {
                "name": "verdict",
                "passed": False,
                "detail": "verdict is missing",
            }
        )
        overall_valid = False

    # -- 3. timestamp is valid ISO format ---------------------------------
    timestamp = data.get("timestamp")
    if timestamp and _is_valid_iso_timestamp(timestamp):
        checks.append(
            {
                "name": "timestamp",
                "passed": True,
                "detail": f"timestamp={timestamp}",
            }
        )
    elif timestamp:
        checks.append(
            {
                "name": "timestamp",
                "passed": False,
                "detail": f"timestamp '{timestamp}' is not valid ISO 8601",
            }
        )
        overall_valid = False
    else:
        checks.append(
            {
                "name": "timestamp",
                "passed": False,
                "detail": "timestamp is missing",
            }
        )
        overall_valid = False

    # -- 4. decision-integrity hash ---------------------------------------
    # Receipts carry their integrity hash under one of two canonical fields:
    #   * ``artifact_hash`` -- the content-addressable hash emitted by the
    #     canonical producer ``DecisionReceipt.to_dict`` (``aragora demo`` and the
    #     gauntlet). This is the authoritative integrity field and the one that
    #     ``aragora receipt verify`` checks.
    #   * ``checksum`` -- a legacy field some pipelines emit instead.
    # ``artifact_hash`` is the canonical producer field, but when a receipt carries
    # multiple integrity proofs every present proof must validate. Otherwise a
    # dual-field receipt could hide tampering in fields covered only by the legacy
    # checksum.
    #
    # IMPORTANT (honest coverage): this hash only covers the *decision-integrity
    # fields* reported by ``_integrity_hash_fields`` -- it does NOT cover
    # presentational fields like ``timestamp``. (``schema_version`` IS covered
    # for crux receipts, schema >= 1.2, to block downgrade tampering; it is NOT
    # covered for pre-crux receipts.) The check is named ``integrity`` (not
    # ``checksum``) and reports a ``covers`` list so the command does not imply
    # whole-payload tamper-evidence. Full-payload coverage requires a
    # cryptographic signature (check #5 / ``aragora receipt verify``).
    stored_artifact_hash = data.get("artifact_hash")
    stored_checksum = data.get("checksum")
    proof_details: list[str] = []
    proof_failures: list[str] = []
    covered_fields: list[str] = []
    # Crux receipts (a ``cruxes`` block, or a schema 1.2 stamp) MUST be
    # verified against the full artifact hash: the legacy 16-char checksum
    # covers neither cruxes nor schema_version, so accepting it alone would
    # let an attacker strip ``artifact_hash`` and evade crux/downgrade
    # tamper-protection. Pre-crux receipts keep the legacy fallback.
    requires_full_artifact_hash = data.get("cruxes") is not None or data.get("schema_version") in {
        _SCHEMA_VERSION_CRUXES,
        _SCHEMA_VERSION_EVIDENCE,
    }
    if (
        requires_full_artifact_hash
        and not stored_artifact_hash
        and not _looks_like_artifact_hash_alias(stored_checksum)
    ):
        proof_failures.append(
            "receipt with crux/evidence content requires the full artifact_hash; "
            "the legacy checksum does not cover schema-bound decision evidence"
        )
    if data.get("schema_version") == _SCHEMA_VERSION_EVIDENCE:
        stored_decision_hash = data.get("decision_payload_hash")
        expected_decision_hash = _inline_decision_payload_hash(data)
        if not stored_decision_hash:
            proof_failures.append("schema 1.3 receipt is missing decision_payload_hash")
        elif stored_decision_hash != expected_decision_hash:
            proof_failures.append(
                f"decision_payload_hash mismatch: stored={stored_decision_hash[:16]}..., "
                f"recomputed={expected_decision_hash[:16]}..."
            )
    if stored_artifact_hash:
        expected_artifact_hash = _recompute_artifact_hash(data)
        covered_fields.extend(_integrity_hash_fields(data))
        if stored_artifact_hash == expected_artifact_hash:
            detail = f"artifact_hash={stored_artifact_hash[:16]}..."
            if verbose:
                detail += f" (recomputed={expected_artifact_hash[:16]}...)"
            proof_details.append(detail)
        else:
            proof_failures.append(
                f"artifact_hash mismatch: stored={stored_artifact_hash[:16]}..., "
                f"recomputed={expected_artifact_hash[:16]}..."
            )
    if stored_checksum:
        if _looks_like_artifact_hash_alias(stored_checksum):
            expected_checksum_alias = _recompute_artifact_hash(data)
            covered_fields.extend(_integrity_hash_fields(data))
            if stored_checksum == expected_checksum_alias:
                detail = f"checksum artifact_hash alias={stored_checksum[:16]}..."
                if verbose:
                    detail += f" (recomputed={expected_checksum_alias[:16]}...)"
                proof_details.append(detail)
            else:
                proof_failures.append(
                    f"checksum artifact_hash alias mismatch: stored={stored_checksum[:16]}..., "
                    f"recomputed={expected_checksum_alias[:16]}..."
                )
        else:
            expected_checksum = _recompute_checksum(data)
            covered_fields.extend(_LEGACY_CHECKSUM_FIELDS)
            if stored_checksum == expected_checksum:
                detail = f"checksum={stored_checksum}"
                if verbose:
                    detail += f" (recomputed={expected_checksum})"
                proof_details.append(detail)
            else:
                proof_failures.append(
                    f"checksum mismatch: stored={stored_checksum}, recomputed={expected_checksum}"
                )

    if not stored_artifact_hash and not stored_checksum:
        checks.append(
            {
                "name": "integrity",
                "passed": False,
                "detail": "no integrity hash present (expected artifact_hash or checksum)",
                "covers": [],
            }
        )
        overall_valid = False
    elif proof_failures:
        checks.append(
            {
                "name": "integrity",
                "passed": False,
                "detail": "; ".join(proof_failures) + " (a decision-integrity field was altered)",
                "covers": list(dict.fromkeys(covered_fields)),
            }
        )
        overall_valid = False
    else:
        checks.append(
            {
                "name": "integrity",
                "passed": True,
                "detail": "decision-integrity fields verified via " + " and ".join(proof_details),
                "covers": list(dict.fromkeys(covered_fields)),
            }
        )

    # -- 5. signature chain (optional, only for signed receipts) ----------
    is_signed = False
    signature_data = data.get("signature")
    signature_metadata = data.get("signature_metadata")

    if signature_data and signature_metadata:
        is_signed = True
        try:
            from aragora.export.decision_receipt import SignedDecisionReceipt

            signed_receipt = SignedDecisionReceipt.from_dict(data)
            sig_valid = signed_receipt.verify()
            checks.append(
                {
                    "name": "signature",
                    "passed": sig_valid,
                    "detail": (
                        "signature verified" if sig_valid else "signature verification failed"
                    ),
                }
            )
            if not sig_valid:
                overall_valid = False
        except ImportError:
            checks.append(
                {
                    "name": "signature",
                    "passed": False,
                    "detail": "signing backend not available for verification",
                }
            )
            overall_valid = False
        except (OSError, RuntimeError, ValueError) as exc:
            checks.append(
                {
                    "name": "signature",
                    "passed": False,
                    "detail": f"signature verification error: {exc}",
                }
            )
            overall_valid = False

    return {
        "valid": overall_valid,
        "checks": checks,
        "receipt_id": data.get("receipt_id", "unknown"),
        "signed": is_signed,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def cmd_verify(args: argparse.Namespace) -> int:
    """Verify a decision receipt's integrity.

    Returns 0 if the receipt is valid, 1 otherwise.
    """
    receipt_path = Path(args.receipt_path)
    output_format: str = getattr(args, "output_format", "text")
    verbose: bool = getattr(args, "verbose", False)

    # -- Load the file ----------------------------------------------------
    if not receipt_path.exists():
        _report_error(
            f"File not found: {receipt_path}",
            output_format=output_format,
        )
        return 1

    try:
        raw = receipt_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        _report_error(
            f"Invalid JSON: {exc}",
            output_format=output_format,
        )
        return 1

    if not isinstance(data, dict):
        _report_error(
            "Receipt JSON must be an object (dict), not a list or scalar",
            output_format=output_format,
        )
        return 1

    # -- Run checks -------------------------------------------------------
    result = _verify_receipt(data, verbose=verbose)

    # -- Output -----------------------------------------------------------
    if output_format == "json":
        print(json.dumps(result, indent=2))
    else:
        _print_text_report(result, verbose=verbose)

    return 0 if result["valid"] else 1


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _print_text_report(result: dict[str, Any], *, verbose: bool = False) -> None:
    """Pretty-print verification results to stdout."""
    receipt_id = result.get("receipt_id", "unknown")
    print(f"\nReceipt Verification: {receipt_id}")
    print("=" * 60)

    for check in result["checks"]:
        icon = "PASS" if check["passed"] else "FAIL"
        print(f"  [{icon}] {check['name']}: {check['detail']}")
        if verbose and check["name"] == "integrity" and check.get("covers"):
            print(f"           covers: {', '.join(check['covers'])}")

    print("")
    signed = result.get("signed")
    if result["valid"]:
        if signed:
            # Signature covers the full serialised payload.
            print("Result: VALID -- full-payload integrity verified (signed)")
        else:
            # Unsigned: only the decision-integrity fields are tamper-evident.
            print("Result: VALID -- decision-integrity fields verified")
            print(
                "  (unsigned: timestamp/schema_version are checked for "
                "presence/format, not tamper-evidence)"
            )
    else:
        print("Result: INVALID -- integrity check failed")

    if signed:
        print("  (receipt is cryptographically signed)")
    print("")


def _report_error(message: str, *, output_format: str = "text") -> None:
    """Report an error in the requested format."""
    if output_format == "json":
        print(
            json.dumps(
                {"valid": False, "error": message, "checks": []},
                indent=2,
            )
        )
    else:
        print(f"Error: {message}", file=sys.stderr)
