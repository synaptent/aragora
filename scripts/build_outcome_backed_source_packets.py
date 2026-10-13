#!/usr/bin/env python3
"""Materialize hash-verified, outcome-blind decision-quality source packets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aragora.evaluation.outcome_backed_packets import (
    DEFAULT_MAX_SOURCE_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
    SourcePacketError,
    materialize_source_packets,
)


DEFAULT_CORPUS_DIR = Path("docs/benchmarks/decision_quality/tranches")
DEFAULT_OUTPUT_ROOT = Path(".aragora/outcome_backed/source_packets")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", required=True, choices=("development", "holdout"))
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="target directory (default: .aragora/outcome_backed/source_packets/<split>)",
    )
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--max-source-bytes", type=int, default=DEFAULT_MAX_SOURCE_BYTES)
    parser.add_argument("--json", action="store_true", help="emit the packet-set manifest")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    output_dir = args.output_dir or DEFAULT_OUTPUT_ROOT / args.split
    try:
        manifest = materialize_source_packets(
            args.corpus_dir,
            output_dir,
            split=args.split,
            timeout_seconds=args.timeout_seconds,
            max_source_bytes=args.max_source_bytes,
        )
    except (OSError, SourcePacketError, ValueError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True))
        else:
            print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(
            json.dumps(
                {"ok": True, "output_dir": str(output_dir), **manifest}, indent=2, sort_keys=True
            )
        )
    else:
        print(
            f"PASS: wrote {manifest['packet_count']} {args.split} packets "
            f"from {manifest['source_count']} verified sources to {output_dir}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
