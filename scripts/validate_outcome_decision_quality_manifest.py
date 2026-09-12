#!/usr/bin/env python3
"""Validate the frozen outcome-backed decision-quality manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from aragora.evaluation.decision_quality_manifest import validate_manifest  # noqa: E402

DEFAULT_MANIFEST = PROJECT_ROOT / "docs/benchmarks/decision_quality/benchmark-manifest.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = validate_manifest(args.manifest)
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True, allow_nan=False))
    return 0 if report.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
