"""
CLI command: aragora verify -- validate decision receipt integrity.

Runs the following checks on a decision receipt JSON file:

- **Decision-integrity hash** (``integrity`` check): recomputes the SHA-256
  content hash and compares it to the stored value. Receipts store this hash under
  the canonical ``artifact_hash`` field (as emitted by ``DecisionReceipt.to_dict``).
  A legacy ``checksum`` field is accepted as a fallback for older/alternate
  producers, and older ``artifact_hash`` values that predate epistemic receipt
  fields are accepted with reduced coverage. Multiple integrity proofs are all
  validated when present so dual-field receipts cannot hide a mismatched proof.
  The current hash covers the *decision-integrity fields* --
  ``receipt_id``, ``gauntlet_id``, ``input_hash``, ``risk_summary``, ``verdict``,
  ``confidence``, ``unverified``, ``assumptions``, and ``falsification`` -- so
  tampering with any of those is detected. It does **not** cover presentational
  metadata fields such as ``timestamp`` or ``schema_version``;
  for full-payload tamper-evidence, sign the receipt and use the signature check
  (or ``aragora receipt verify``). The reported coverage is scoped accordingly so
  the command does not overclaim.
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
            "decision-integrity hash (artifact_hash, legacy artifact_hash fallback, "
            "and checksum fallback; all present proofs are checked) to detect tampering "
            "of the fields covered by the stored proof; also checks "
            "schema_version presence, that the verdict is a valid enum value, and "
            "timestamp format. Note: the integrity hash does not cover presentational "
            "fields like timestamp/schema_version -- for full-payload tamper-evidence "
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
# presentational fields (timestamp, schema_version, ...) the hash does not include.
_INTEGRITY_HASH_FIELDS: tuple[str, ...] = (
    "receipt_id",
    "gauntlet_id",
    "input_hash",
    "risk_summary",
    "verdict",
    "confidence",
    "unverified",
    "assumptions",
    "falsification",
)

_LEGACY_ARTIFACT_HASH_FIELDS: tuple[str, ...] = (
    "receipt_id",
    "gauntlet_id",
    "input_hash",
    "risk_summary",
    "verdict",
    "confidence",
)

_EPISTEMIC_HASH_FIELDS: tuple[str, ...] = ("unverified", "assumptions", "falsification")

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


def _normalize_epistemic_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if text:
            normalized.append(text)
    return normalized


def _normalize_falsification(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    normalized: dict[str, str] = {}
    for key in ("observation", "owner", "source", "check_by"):
        raw = value.get(key)
        if isinstance(raw, str) and raw.strip():
            normalized[key] = raw.strip()
    if "observation" not in normalized or "check_by" not in normalized:
        return None
    return normalized or None


def _malformed_epistemic_hash_field_reasons(data: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if "unverified" in data and data.get("unverified") != _normalize_epistemic_string_list(
        data.get("unverified")
    ):
        reasons.append("unverified must be a list of non-empty strings")
    if "assumptions" in data and data.get("assumptions") != _normalize_epistemic_string_list(
        data.get("assumptions")
    ):
        reasons.append("assumptions must be a list of non-empty strings")
    if "falsification" in data and data.get("falsification") != _normalize_falsification(
        data.get("falsification")
    ):
        reasons.append(
            "falsification must be an object with non-empty observation and check_by strings"
        )
    return reasons


def _raise_for_malformed_epistemic_hash_fields(data: dict[str, Any]) -> None:
    reasons = _malformed_epistemic_hash_field_reasons(data)
    if reasons:
        raise ValueError("malformed epistemic hash fields: " + "; ".join(reasons))


def _artifact_hash_payload(data: dict[str, Any], *, include_epistemic: bool) -> dict[str, Any]:
    payload = {
        "receipt_id": data.get("receipt_id", ""),
        "gauntlet_id": data.get("gauntlet_id", ""),
        "input_hash": data.get("input_hash", ""),
        "risk_summary": data.get("risk_summary", {}),
        "verdict": data.get("verdict", ""),
        "confidence": data.get("confidence", 0.0),
    }
    if include_epistemic:
        _raise_for_malformed_epistemic_hash_fields(data)
        if data.get("unverified"):
            payload["unverified"] = data.get("unverified", []) or []
        if data.get("assumptions"):
            payload["assumptions"] = data.get("assumptions", []) or []
        if data.get("falsification"):
            payload["falsification"] = data.get("falsification")
    return payload


def _hash_artifact_payload(payload: dict[str, Any]) -> str:
    content = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()


def _has_epistemic_hash_fields(data: dict[str, Any]) -> bool:
    if _malformed_epistemic_hash_field_reasons(data):
        return True
    return bool(
        _normalize_epistemic_string_list(data.get("unverified"))
        or _normalize_epistemic_string_list(data.get("assumptions"))
        or _normalize_falsification(data.get("falsification"))
    )


def _recompute_legacy_artifact_hash(data: dict[str, Any]) -> str:
    """Recompute the pre-epistemic six-field ``artifact_hash``."""
    return _hash_artifact_payload(_artifact_hash_payload(data, include_epistemic=False))


def _recompute_artifact_hash(data: dict[str, Any]) -> str:
    """Recompute the current canonical content-addressable ``artifact_hash``.

    Mirrors ``DecisionReceipt._calculate_hash`` so that receipts emitted by the
    canonical producer (``DecisionReceipt.to_dict``, used by ``aragora demo`` and
    the gauntlet) -- which store their integrity hash under ``artifact_hash`` and
    do *not* emit a separate ``checksum`` key -- can be verified by this command.

    Implemented inline (rather than importing ``DecisionReceipt``) so verification
    never hard-depends on the gauntlet package being importable. Covers exactly the
    fields in :data:`_INTEGRITY_HASH_FIELDS`.
    """
    return _hash_artifact_payload(_artifact_hash_payload(data, include_epistemic=True))


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
    # fields* listed in ``_INTEGRITY_HASH_FIELDS`` -- it does NOT cover presentational
    # fields like ``timestamp`` or ``schema_version``. The check is named
    # ``integrity`` (not ``checksum``) and reports a ``covers`` list so the command
    # does not imply whole-payload tamper-evidence. Full-payload coverage requires a
    # cryptographic signature (check #5 / ``aragora receipt verify``).
    stored_artifact_hash = data.get("artifact_hash")
    stored_checksum = data.get("checksum")
    proof_details: list[str] = []
    proof_failures: list[str] = []
    covered_fields: list[str] = []
    if stored_artifact_hash:
        try:
            expected_artifact_hash = _recompute_artifact_hash(data)
        except ValueError as exc:
            covered_fields.extend(_INTEGRITY_HASH_FIELDS)
            proof_failures.append(str(exc))
        else:
            if stored_artifact_hash == expected_artifact_hash:
                covered_fields.extend(_INTEGRITY_HASH_FIELDS)
                detail = f"artifact_hash={stored_artifact_hash[:16]}..."
                if verbose:
                    detail += f" (recomputed={expected_artifact_hash[:16]}...)"
                proof_details.append(detail)
            else:
                expected_legacy_artifact_hash = _recompute_legacy_artifact_hash(data)
                if stored_artifact_hash == expected_legacy_artifact_hash:
                    if _has_epistemic_hash_fields(data):
                        covered_fields.extend(_LEGACY_ARTIFACT_HASH_FIELDS)
                        proof_failures.append(
                            "legacy artifact_hash cannot validate epistemic fields "
                            "(unverified, assumptions, falsification)"
                        )
                    else:
                        covered_fields.extend(_LEGACY_ARTIFACT_HASH_FIELDS)
                        detail = f"legacy artifact_hash={stored_artifact_hash[:16]}..."
                        if verbose:
                            detail += f" (recomputed={expected_legacy_artifact_hash[:16]}...)"
                        proof_details.append(detail)
                else:
                    covered_fields.extend(_INTEGRITY_HASH_FIELDS)
                    proof_failures.append(
                        f"artifact_hash mismatch: stored={stored_artifact_hash[:16]}..., "
                        f"recomputed={expected_artifact_hash[:16]}..."
                    )
    if stored_checksum:
        if _looks_like_artifact_hash_alias(stored_checksum):
            try:
                expected_checksum_alias = _recompute_artifact_hash(data)
            except ValueError as exc:
                covered_fields.extend(_INTEGRITY_HASH_FIELDS)
                proof_failures.append(str(exc))
            else:
                if stored_checksum == expected_checksum_alias:
                    covered_fields.extend(_INTEGRITY_HASH_FIELDS)
                    detail = f"checksum artifact_hash alias={stored_checksum[:16]}..."
                    if verbose:
                        detail += f" (recomputed={expected_checksum_alias[:16]}...)"
                    proof_details.append(detail)
                else:
                    expected_legacy_checksum_alias = _recompute_legacy_artifact_hash(data)
                    if stored_checksum == expected_legacy_checksum_alias:
                        if _has_epistemic_hash_fields(data):
                            covered_fields.extend(_LEGACY_ARTIFACT_HASH_FIELDS)
                            proof_failures.append(
                                "legacy checksum artifact_hash alias cannot validate epistemic "
                                "fields (unverified, assumptions, falsification)"
                            )
                        else:
                            covered_fields.extend(_LEGACY_ARTIFACT_HASH_FIELDS)
                            detail = (
                                f"legacy checksum artifact_hash alias={stored_checksum[:16]}..."
                            )
                            if verbose:
                                detail += f" (recomputed={expected_legacy_checksum_alias[:16]}...)"
                            proof_details.append(detail)
                    else:
                        covered_fields.extend(_INTEGRITY_HASH_FIELDS)
                        proof_failures.append(
                            "checksum artifact_hash alias mismatch: "
                            f"stored={stored_checksum[:16]}..., "
                            f"recomputed={expected_checksum_alias[:16]}..."
                        )
        else:
            expected_checksum = _recompute_checksum(data)
            covered_fields.extend(_LEGACY_CHECKSUM_FIELDS)
            if stored_checksum == expected_checksum:
                if _has_epistemic_hash_fields(data):
                    proof_failures.append(
                        "legacy checksum cannot validate epistemic fields "
                        "(unverified, assumptions, falsification)"
                    )
                else:
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
