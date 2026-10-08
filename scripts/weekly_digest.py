#!/usr/bin/env python3
"""Render the weekly founder digest from the throughput ledger (epic #9039, issue #9041).

ACCOUNT-phase output of the work-mix governor
(docs/plans/2026-07-08-vision-audit-and-work-mix-governor.md §4.5): throughput
table with week-over-week deltas, work-mix breakdown vs budget, external
artifacts, freeze/kill-switch state, and a random merge-classification sample
for the anti-gaming spot-audit. Reads only the local ledger — no network.
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta, timezone

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from aragora.nomic.throughput import (
    ThroughputLedger,
    compute_metrics,
    freeze_active,
    render_digest,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", help="repo checkout root")
    parser.add_argument("--window-days", type=int, default=7)
    parser.add_argument("--samples", type=int, default=5, help="spot-audit sample size")
    parser.add_argument("--out", default="-", help="output path, or - for stdout")
    args = parser.parse_args(argv)

    ledger = ThroughputLedger(args.repo_root)
    records = ledger.records()
    now = datetime.now(timezone.utc)
    current = compute_metrics(records, now=now, window_days=args.window_days)
    previous = compute_metrics(
        records,
        now=now - timedelta(days=args.window_days),
        window_days=args.window_days,
    )

    cutoff = now - timedelta(days=args.window_days)
    window_merges = [r.data for r in records if r.kind == "merge" and r.when >= cutoff]
    samples = random.sample(window_merges, min(args.samples, len(window_merges)))

    digest = render_digest(
        current,
        previous=previous,
        freeze=freeze_active(args.repo_root),
        samples=samples,
    )
    if args.out == "-":
        print(digest)
    else:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(digest)
        print(f"digest written to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
