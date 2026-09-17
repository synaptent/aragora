"""Emit a verifiable ODR receipt from a merge-quorum CollectOutcome JSON.

This is the offline glue the M2 GitHub Action calls. It reads a CollectOutcome
dict (as produced by ``collect_quorum_evidence.py --json``), bridges it to a
``DecisionReceipt`` (``aragora/swarm/quorum_receipt.py``), exports the portable
Open Decision Receipt (``aragora/gauntlet/odr_export.py``), optionally validates
it, and writes the receipt JSON. No model calls. Signing uses a configured local
file or AWS Secrets Manager; unconfigured deployments emit an unsigned receipt.

Examples
--------
::

    python3 scripts/collect_quorum_evidence.py --repo o/r --pr 1 --json > outcome.json
    python3 scripts/emit_pr_receipt.py --outcome outcome.json --out receipt.odr.json --verify
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from aragora.gauntlet.odr_export import (  # noqa: E402
    decision_receipt_to_odr,
    load_odr_schema,
    odr_content_digest,
    sign_odr_if_configured,
)
from aragora.gauntlet.odr_signing import OdrSigningError  # noqa: E402
from aragora.swarm.quorum_evidence import collect_outcome_from_dict  # noqa: E402
from aragora.swarm.quorum_receipt import collect_outcome_to_decision_receipt  # noqa: E402


def build_receipt(outcome_dict: dict[str, Any]) -> dict[str, Any]:
    """CollectOutcome dict -> portable ODR receipt dict (never fabricates)."""
    outcome = collect_outcome_from_dict(outcome_dict)
    receipt = collect_outcome_to_decision_receipt(outcome)
    return sign_odr_if_configured(decision_receipt_to_odr(receipt))


def verify_receipt(odr: dict[str, Any]) -> tuple[str, bool]:
    """Recompute the JCS digest (always) and validate the schema when possible.

    Returns ``(digest_hex, fully_validated)``. The digest is the cryptographic
    content check and needs no third-party dependency. Full JSON-Schema
    validation additionally requires ``jsonschema``; when that package is absent
    (e.g. a slim CI runtime) verification degrades to digest-only with
    ``fully_validated=False`` rather than crashing. A genuine schema violation
    still raises.
    """
    digest = odr_content_digest(odr)
    try:
        import jsonschema
    except ModuleNotFoundError:
        return digest, False
    jsonschema.validate(odr, load_odr_schema())
    return digest, True


def _write_github_output(handle: Any, key: str, value: object) -> None:
    """Write one GitHub Actions output after rejecting multiline injection."""
    text = str(value)
    if "\n" in text or "\r" in text:
        raise ValueError(f"github output {key!r} contains a newline")
    handle.write(f"{key}={text}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--outcome",
        type=Path,
        required=True,
        help="CollectOutcome JSON (from collect_quorum_evidence.py --json)",
    )
    parser.add_argument(
        "--out", type=Path, required=True, help="path to write the ODR receipt JSON"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="validate schema + recompute the canonical digest before writing succeeds",
    )
    parser.add_argument(
        "--github-output",
        type=Path,
        default=None,
        help="append receipt_* key=value lines for GitHub Actions step outputs",
    )
    args = parser.parse_args(argv)

    outcome_dict = json.loads(args.outcome.read_text(encoding="utf-8"))
    try:
        odr = build_receipt(outcome_dict)
    except OdrSigningError:
        print(
            "Error: ODR signing key is configured but could not be used; "
            "refusing to export an unsigned receipt",
            file=sys.stderr,
        )
        return 1

    # Write the receipt FIRST so a verification hiccup never loses the artifact.
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(odr, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    digest = odr_content_digest(odr)
    verified = False
    if args.verify:
        digest, verified = verify_receipt(odr)

    verdict = odr.get("claim", {}).get("verdict", "")
    receipt_id = odr.get("receipt_id", "")
    print(f"receipt {receipt_id} verdict={verdict} digest=sha-256:{digest} verified={verified}")

    if args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8") as fh:
            _write_github_output(fh, "receipt_path", args.out)
            _write_github_output(fh, "receipt_verdict", verdict)
            _write_github_output(fh, "receipt_digest", digest)
            _write_github_output(fh, "receipt_verified", "true" if verified else "false")

    if args.verify and not verified:
        print("receipt verification failed: jsonschema validation did not run", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
