#!/usr/bin/env python3
"""Build an outcome-blind deterministic plan for development benchmark cases."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aragora.evaluation.outcome_backed_batch import (  # noqa: E402
    DEFAULT_BATCH_SIZE,
    DevelopmentBatchPlanError,
    build_development_plan,
    load_packet_set_manifest,
    write_development_plan,
)
from aragora.evaluation.outcome_backed_corpus import (  # noqa: E402
    VisibleCorpusError,
    load_visible_cases,
)


DEFAULT_CORPUS_DIR = Path("docs/benchmarks/decision_quality/tranches")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR)
    parser.add_argument("--packet-set", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true", help="emit the complete plan")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        cases = load_visible_cases(args.corpus_dir)
        packet_set = load_packet_set_manifest(args.packet_set)
        plan = build_development_plan(cases, packet_set, batch_size=args.batch_size)
        if args.output is not None:
            write_development_plan(args.output, plan, cases=cases, packet_set=packet_set)
    except (DevelopmentBatchPlanError, VisibleCorpusError, OSError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(plan, indent=2, sort_keys=True))
    else:
        destination = f" -> {args.output}" if args.output is not None else ""
        print(
            f"PASS: planned {plan['case_count']} development cases in "
            f"{plan['batch_count']} batches{destination}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
