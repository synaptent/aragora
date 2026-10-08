#!/usr/bin/env python3
"""Validate the frozen outcome-backed decision-quality corpus."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aragora.evaluation.outcome_backed_corpus import validate_corpus_directory


DEFAULT_CORPUS_DIR = Path("docs/benchmarks/decision_quality/tranches")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = validate_corpus_directory(args.corpus_dir)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    elif report.valid:
        print(
            f"PASS: {report.case_count} outcome-backed cases across "
            f"{report.corpus_files} corpus/sidecar pairs"
        )
    else:
        print(f"FAIL: {len(report.issues)} corpus-integrity issue(s)")
        for issue in report.issues:
            print(f"- {issue.code}: {issue.path}: {issue.message}")
    return 0 if report.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
