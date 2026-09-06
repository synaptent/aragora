#!/usr/bin/env python3
"""Frozen outcome-backed decision-quality benchmark contract CLI.

This first slice exposes corpus/contract validation only. Model execution,
scoring, and report rendering land separately after the contract is frozen.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from aragora.evaluation.decision_quality_contract import (  # noqa: E402
    load_benchmark_bundle,
)

DEFAULT_MANIFEST = PROJECT_ROOT / "docs/benchmarks/decision_quality/benchmark-manifest.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)

    validate = subparsers.add_parser("validate-corpus", help="validate frozen corpus contract")
    validate.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)

    return parser


def _emit(payload: dict[str, Any], *, exit_code: int = 0) -> int:
    print(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False))
    return exit_code


def _validate(args: argparse.Namespace) -> int:
    _, report = load_benchmark_bundle(args.manifest)
    return _emit(
        {"operation": "validate-corpus", **report.to_dict()}, exit_code=0 if report.ok else 2
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.operation == "validate-corpus":
            return _validate(args)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _emit({"ok": False, "operation": args.operation, "error": str(exc)}, exit_code=2)
    return _emit(
        {"ok": False, "operation": args.operation, "error": "unknown operation"}, exit_code=2
    )


if __name__ == "__main__":
    raise SystemExit(main())
