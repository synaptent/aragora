#!/usr/bin/env python3
"""Preflight the frozen development benchmark without making model calls."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aragora.evaluation.outcome_backed_preflight import (
    OutcomeBackedPreflightError,
    preflight_development_run,
)


DEFAULT_CORPUS_DIR = Path("docs/benchmarks/decision_quality/tranches")
DEFAULT_PACKET_DIR = Path(".aragora/outcome_backed/source_packets/development")
DEFAULT_BUDGET_LEDGER = Path(".aragora/outcome_backed/budget.jsonl")


def _current_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise OutcomeBackedPreflightError("cannot resolve current git HEAD")
    return result.stdout.strip()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR)
    parser.add_argument("--packet-dir", type=Path, default=DEFAULT_PACKET_DIR)
    parser.add_argument("--budget-ledger", type=Path, default=DEFAULT_BUDGET_LEDGER)
    parser.add_argument("--implementation-sha", help="exact 40-hex implementation SHA")
    parser.add_argument("--output", type=Path, help="optional atomic JSON artifact path")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = preflight_development_run(
            args.corpus_dir,
            args.packet_dir,
            args.budget_ledger,
            implementation_sha=args.implementation_sha or _current_head(),
        )
    except (OSError, OutcomeBackedPreflightError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True))
        return 2

    payload = report.to_dict()
    payload["ok"] = report.ready
    if args.output is not None:
        try:
            _write_json(args.output, payload)
        except OSError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True))
            return 2
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if report.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
