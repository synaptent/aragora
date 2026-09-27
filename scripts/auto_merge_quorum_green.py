#!/usr/bin/env python3
"""Unattended Tier 0-2 auto-merge on green quorum. Dry-run by default.

Merges open PRs that the merge-quorum gate has ALREADY authorized for Tier 0-2
settlement (merge-packet ``status=satisfied`` / ``verdict=admin_squash_allowed``)
and whose live checks are all green -- without a human typing ``gh pr merge``.
This is the unattended *execution* of an already-authorized merge, not a new
risk judgment. The authority remains the merge-packet + the
``aragora-merge-quorum`` check.

Tier 3-4 PRs (which require human risk settlement) are NEVER touched here; they
continue to flow through ``scripts/settle_tier4_pr.py`` unchanged.

Composes after evidence collection: run ``scripts/auto_evidence_cycle.py --apply``
to drive Tier 0-2 PRs to green, then this to merge the green ones.

Safety:
- ``--dry-run`` (DEFAULT) merges NOTHING; it prints the plan. ``--apply`` is required.
- Every merge uses ``--match-head-commit`` so a push between decision and merge
  aborts rather than squashing a tree nobody reviewed (race-safe).
- ``--max-merges`` bounds a single pass.
- A cheap gh pre-filter (non-draft + mergeable + quorum green) decides whether
  to spend a merge-packet subprocess, so a full-queue scan stays affordable.
- The decision core (:mod:`aragora.swarm.auto_merge_green`) re-checks every gate
  defense-in-depth; this script only supplies I/O.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any

from aragora.swarm.auto_merge_green import (
    QUORUM_CHECK,
    apply_merges,
    context_from_gh,
    first_error_line,
    merge_eligible,
)

_VIEW_FIELDS = "number,headRefOid,isDraft,mergeable,mergeStateStatus,statusCheckRollup"

# Conservative default cap for a single unattended pass. Unbounded auto-merge is
# intentionally not the default; raise --max-merges for larger batches.
DEFAULT_MAX_MERGES = 10


def _gh_json(args: list[str], timeout: int = 60) -> Any:
    try:
        out = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return None


def list_open_pr_numbers(repo: str, limit: int) -> list[int]:
    data = _gh_json(
        [
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--limit",
            str(limit),
            "--json",
            "number,isDraft",
        ]
    )
    if not isinstance(data, list):
        return []
    numbers: list[int] = []
    for pr in data:
        if isinstance(pr, dict) and not pr.get("isDraft") and pr.get("number") is not None:
            numbers.append(int(pr["number"]))
    return numbers


def fetch_view(repo: str, pr: int) -> dict[str, Any] | None:
    view = _gh_json(["pr", "view", str(pr), "--repo", repo, "--json", _VIEW_FIELDS])
    return view if isinstance(view, dict) else None


def fetch_packet_entry(repo: str, pr: int, *, timeout: int = 120) -> dict[str, Any] | None:
    """Run ``review-queue merge-packet`` and return the entry for ``pr``."""
    try:
        out = subprocess.run(
            [
                sys.executable,
                "-m",
                "aragora.cli.main",
                "review-queue",
                "merge-packet",
                "--pr",
                str(pr),
                "--repo",
                repo,
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    try:
        payload = json.loads(out.stdout)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        entries = payload.get("entries")
        entries = entries if isinstance(entries, list) else [payload]
    elif isinstance(payload, list):
        entries = payload
    else:
        return None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            if int(entry.get("pr_number") or 0) == pr:
                return entry
        except (TypeError, ValueError):
            continue
    return None


def _cheaply_promising(view: dict[str, Any]) -> bool:
    """True if the cheap gh signals justify an authoritative packet fetch.

    Rollups can retain multiple historical quorum rows in arbitrary order. Any
    success is enough to spend the packet lookup; the packet remains the gate.
    """
    if view.get("isDraft") or view.get("mergeable") != "MERGEABLE":
        return False
    return any(
        str(item.get("conclusion") or item.get("state") or item.get("status") or "").upper()
        == "SUCCESS"
        for item in view.get("statusCheckRollup") or []
        if isinstance(item, dict) and (item.get("name") or item.get("context")) == QUORUM_CHECK
    )


def _make_merge_fn(repo: str):
    def merge_fn(pr: int, head: str) -> tuple[bool, str]:
        try:
            out = subprocess.run(
                [
                    "gh",
                    "pr",
                    "merge",
                    str(pr),
                    "--repo",
                    repo,
                    "--squash",
                    "--admin",
                    "--match-head-commit",
                    head,
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            return (False, f"merge invocation failed: {exc}")
        if out.returncode == 0:
            return (True, "merged")
        return (False, first_error_line(out.stderr, out.stdout))

    return merge_fn


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Unattended Tier 0-2 auto-merge on green quorum (dry-run by default)"
    )
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument(
        "--pr", type=int, action="append", help="specific PR(s); default scans open PRs"
    )
    parser.add_argument("--limit", type=int, default=300, help="max open PRs to scan")
    parser.add_argument(
        "--max-merges",
        type=int,
        default=DEFAULT_MAX_MERGES,
        help=f"cap merges in this pass (default {DEFAULT_MAX_MERGES}; raise N for larger batches)",
    )
    parser.add_argument("--apply", action="store_true", help="actually merge (default: dry-run)")
    parser.add_argument("--json", action="store_true", help="emit JSON summary")
    args = parser.parse_args(argv)

    prs = args.pr if args.pr else list_open_pr_numbers(args.repo, args.limit)
    contexts = []
    for pr in prs:
        view = fetch_view(args.repo, pr)
        if view is None:
            continue
        packet = fetch_packet_entry(args.repo, pr) if _cheaply_promising(view) else None
        contexts.append(context_from_gh(view, packet))

    decisions = merge_eligible(contexts)
    results = apply_merges(
        decisions,
        merge_fn=_make_merge_fn(args.repo),
        max_merges=args.max_merges,
        dry_run=not args.apply,
    )

    summary = {
        "repo": args.repo,
        "mode": "apply" if args.apply else "dry-run",
        "scanned": len(contexts),
        "eligible": sum(1 for d in decisions if d.should_merge),
        "results": results,
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(
            f"[auto-merge-green] {summary['mode']}: scanned {summary['scanned']}, {summary['eligible']} eligible"
        )
        for record in results:
            line = f"  #{record['pr']}: {record['action']}"
            blockers = record.get("blockers") or []
            if blockers:
                shown = "; ".join(blockers[:2])
                line += f"  ({shown}{'; …' if len(blockers) > 2 else ''})"
            elif record.get("detail"):
                line += f"  ({record['detail']})"
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
