#!/usr/bin/env python3
"""Work-mix gate: evaluate the rolling merge mix against the budget (epic #9039, issue #9041).

STEER-phase check for the work-mix governor
(docs/plans/2026-07-08-vision-audit-and-work-mix-governor.md §4.2): the
rolling 7-day merged-PR mix must keep product >= 50% and substrate <= 25%.
ADVISORY BY DEFAULT — ``check`` only prints the verdict; the substrate-freeze
marker is written only with ``--enforce``. Goal selection honoring the marker
is Phase 2 (issue #9045). Main-red repair and security fixes are exempt from
the budget (classified but not counted).
"""

from __future__ import annotations

import argparse
import json
import sys

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from aragora.nomic.throughput import (
    ThroughputLedger,
    freeze_active,
    mix_from_records,
    write_freeze_marker,
)
from aragora.nomic.work_mix import MixBudget, classify_paths, evaluate_budget


def cmd_check(args: argparse.Namespace) -> int:
    ledger = ThroughputLedger(args.repo_root)
    mix = mix_from_records(ledger.records(), window_days=args.window_days)
    budget = MixBudget(
        product_min=args.product_min,
        substrate_max=args.substrate_max,
        window_days=args.window_days,
    )
    verdict = evaluate_budget(mix, budget)
    print(
        json.dumps(
            {
                "window_days": args.window_days,
                "countable_merges": mix.total,
                "product_share": round(mix.product_share, 3),
                "substrate_share": round(mix.substrate_share, 3),
                "ok": verdict.ok,
                "substrate_breach": verdict.substrate_breach,
                "product_shortfall": verdict.product_shortfall,
                "freeze_recommended": verdict.freeze_recommended,
                "reasons": verdict.reasons,
                "mode": "enforce" if args.enforce else "advisory",
            },
            indent=2,
        )
    )
    if verdict.freeze_recommended and args.enforce:
        path = write_freeze_marker(args.repo_root, reason="; ".join(verdict.reasons))
        print(f"substrate freeze marker written: {path}", file=sys.stderr)
    return 0 if verdict.ok or not args.enforce else 1


def cmd_classify(args: argparse.Namespace) -> int:
    classified = classify_paths(args.paths, title=args.title, labels=args.label or [])
    print(
        json.dumps(
            {
                "work_class": classified.work_class.value,
                "exempt": classified.exempt,
                "rationale": classified.rationale,
                "file_counts": {
                    cls.value: count for cls, count in classified.file_counts.items() if count
                },
            },
            indent=2,
        )
    )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    payload = freeze_active(args.repo_root)
    print(json.dumps({"freeze_active": payload is not None, "marker": payload}, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", help="repo checkout root")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="evaluate the rolling mix against the budget")
    check.add_argument("--window-days", type=int, default=7)
    check.add_argument("--product-min", type=float, default=0.50)
    check.add_argument("--substrate-max", type=float, default=0.25)
    check.add_argument(
        "--enforce",
        action="store_true",
        help="write the substrate-freeze marker on breach (default: advisory)",
    )
    check.set_defaults(func=cmd_check)

    classify = sub.add_parser("classify", help="classify a set of changed paths")
    classify.add_argument("paths", nargs="+")
    classify.add_argument("--title", default="")
    classify.add_argument("--label", action="append")
    classify.set_defaults(func=cmd_classify)

    status = sub.add_parser("status", help="print freeze-marker state")
    status.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
