#!/usr/bin/env python3
"""Advisory live-vs-snapshot drift check for the canonical model catalog.

NEVER wired into required CI (required checks validate offline against the
committed snapshot). Run manually or from a scheduled ADVISORY job:

    python3 scripts/model_catalog_drift.py            # report drift, exit 1 if any
    python3 scripts/model_catalog_drift.py --refresh  # rewrite the snapshot from live

Provider reprices are real and frequent: three were caught by adversarial
review in a single week (gpt-5.5 2.50/10 -> 5/30; qwen3.7-max 1.25/3.75 ->
1.475/4.425; kimi-k2.7-code 0.72 -> 0.75). This tool makes that discovery
mechanical instead of review-driven.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from aragora.models import CATALOG, load_snapshot, snapshot_path  # noqa: E402

LIVE_URL = "https://openrouter.ai/api/v1/models"


def fetch_live() -> dict[str, dict[str, float | int | None]]:
    req = urllib.request.Request(LIVE_URL, headers={"User-Agent": "aragora-catalog-drift"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    wanted = {spec.openrouter_id for spec in CATALOG.values()}
    live: dict[str, dict[str, float | int | None]] = {}
    for model in data.get("data", []):
        if model.get("id") in wanted:
            pricing = model.get("pricing", {})
            live[model["id"]] = {
                "input_per_mtok": round(float(pricing.get("prompt", 0)) * 1e6, 4),
                "output_per_mtok": round(float(pricing.get("completion", 0)) * 1e6, 4),
                "context_length": model.get("context_length"),
            }
    return live


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Catalog snapshot drift (advisory)")
    parser.add_argument("--refresh", action="store_true", help="rewrite the snapshot from live")
    args = parser.parse_args(argv)

    live = fetch_live()
    missing = [s.openrouter_id for s in CATALOG.values() if s.openrouter_id not in live]
    if args.refresh:
        snapshot = {
            "_comment": [
                "Committed capture of the live OpenRouter catalog for OFFLINE catalog",
                "validation (required CI never calls the network). Refresh with:",
                "  python3 scripts/model_catalog_drift.py --refresh",
                "and commit the diff; the scheduled advisory drift job reports when",
                "this snapshot disagrees with the live catalog.",
            ],
            "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": LIVE_URL,
            "models": live,
        }
        snapshot_path().write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
        print(f"snapshot refreshed: {len(live)} models -> {snapshot_path()}")
        if missing:
            print(f"WARNING: not in live catalog (dead slugs?): {missing}", file=sys.stderr)
        return 0

    committed = load_snapshot()
    drift: list[str] = []
    for or_id, live_row in sorted(live.items()):
        committed_row = committed.get(or_id)
        if committed_row is None:
            drift.append(f"{or_id}: in live catalog but not in snapshot")
            continue
        for key in ("input_per_mtok", "output_per_mtok"):
            live_value = live_row[key]
            if live_value is None:
                drift.append(f"{or_id}: {key} missing from live catalog")
                continue
            if float(committed_row.get(key, -1)) != float(live_value):
                drift.append(
                    f"{or_id}: {key} snapshot={committed_row.get(key)} live={live_row[key]}"
                )
    for or_id in missing:
        drift.append(f"{or_id}: MISSING from live catalog (dead slug?)")
    report = {"drift_count": len(drift), "drift": drift, "checked": len(live)}
    print(json.dumps(report, indent=2))
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
