"""``aragora-verify`` command-line interface.

    aragora-verify receipt.json [--pubkey key.pem] [--chain chain.jsonl] [--json]

Exit status: ``0`` when the receipt verifies (no failed checks and any present
signatures were checked), ``1`` when any check fails, ``2`` for usage/input
errors, ``3`` when the receipt is structurally OK but carries signatures that
were never checked (no ``--pubkey`` supplied). With ``--json`` the structured
:class:`~aragora_verify.verifier.VerifyResult` is printed instead of the report.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from . import __version__
from .verifier import VerificationError, VerifyResult, verify_path

_GLYPH = {"pass": "PASS", "fail": "FAIL", "warn": "WARN", "skip": "----"}


def _render(result: VerifyResult) -> str:
    lines: list[str] = []
    if not result.ok:
        verdict = "FAILED"
    elif result.authenticity_unverified:
        verdict = "UNVERIFIED"
    else:
        verdict = "VERIFIED"
    lines.append(f"Open Decision Receipt — {verdict}")
    lines.append(f"  receipt_id: {result.receipt_id or '<missing>'}")
    if result.odr_digest:
        lines.append(f"  odr_digest: sha-256:{result.odr_digest}")
    if verdict == "UNVERIFIED":
        lines.append(
            "  note: signatures are present but were NOT checked (no --pubkey); "
            "authenticity is NOT established"
        )
    lines.append("")
    lines.append("  checks:")
    for check in result.checks:
        lines.append(f"    [{_GLYPH.get(check.status, check.status)}] {check.name}: {check.detail}")
    if result.warnings:
        lines.append("")
        lines.append("  weakening signals (do not fail verification):")
        for warning in result.warnings:
            lines.append(f"    ! {warning}")
    lines.append("")
    lines.append(f"  => {verdict}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aragora-verify",
        description=(
            "Offline verifier for Open Decision Receipts (ODR v0.1): schema "
            "conformance, JCS canonical digest, Ed25519 signature, hash-chain "
            "link, and quorum consistency. No Aragora install or account required."
        ),
    )
    parser.add_argument("receipt", help="path to the ODR receipt JSON")
    parser.add_argument(
        "--pubkey",
        metavar="KEY",
        help="Ed25519 public key (PEM/DER/raw/base64/hex) to verify signatures with",
    )
    parser.add_argument(
        "--chain",
        metavar="JSONL",
        help="hash-chain file (JSONL); checks the receipt is anchored and the chain links",
    )
    parser.add_argument("--json", action="store_true", help="emit the structured result as JSON")
    parser.add_argument("--version", action="version", version=f"aragora-verify {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = verify_path(args.receipt, pubkey_path=args.pubkey, chain_path=args.chain)
    except FileNotFoundError as exc:
        print(f"error: file not found: {exc.filename}", file=sys.stderr)
        return 2
    except (OSError, UnicodeDecodeError) as exc:
        print(f"error: cannot read input: {exc}", file=sys.stderr)
        return 2
    except (json.JSONDecodeError, VerificationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        print(_render(result))
    if not result.ok:
        return 1
    if result.authenticity_unverified:
        return 3  # structurally OK but present signatures were never checked
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
