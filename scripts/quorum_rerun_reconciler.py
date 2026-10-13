#!/usr/bin/env python3
"""Re-run stale-but-satisfiable ``aragora-merge-quorum`` check runs.

Phase 1 item A1 of ``docs/governance/BOSS_LOOP_MERGE_GATE_RESILIENCE.md`` and
Sprint 3 goal 3(i) in ``docs/strategy/FOCUS.md``: the merge-quorum workflow does not
re-trigger when review evidence arrives after the last push, so a PR can sit
stale-FAILURE for hours (observed 2.5h on #7727) even though the live
merge-packet is satisfiable. This reconciler detects that state and re-runs
the read-only evaluation workflow.

Safety model:
- Read-only by default; ``--apply`` is required to execute ``gh run rerun``.
- Staleness is decided by the live merge-packet verdict (the ground truth),
  never by comment heuristics.
- Only completed FAILURE/TIMED_OUT/ACTION_REQUIRED quorum runs older than
  ``--min-age-minutes`` are eligible; in-progress runs are never touched.
- ``--max-reruns`` (default 3) bounds work per invocation.
- Apply failures exit non-zero (fail closed); dry-run always exits 0.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from typing import Any, Callable

FAILURE_CONCLUSIONS = {"FAILURE", "TIMED_OUT", "ACTION_REQUIRED"}
SATISFIABLE_PACKET_STATUSES = {"satisfied", "needs_model_review_quorum"}
# repair_or_wait is accepted ONLY when the sole failing check is the stale
# quorum run itself (circular short-circuit: resilience doc root cause #3,
# observed live on run-20260610 PR #8100 — packet counted ['grok'] yet
# reported repair_or_wait because its own stale FAILURE row counts as a
# failing check).
CIRCULAR_REPAIR_STATUS = "repair_or_wait"
DEFAULT_REPO = "synaptent/aragora"
GH_TIMEOUT_SECONDS = 120


def parse_iso(raw: str | None) -> datetime | None:
    """Parse a GitHub ISO-8601 timestamp; return None when absent/invalid."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_run_id(details_url: str) -> str | None:
    """Extract the GitHub Actions run id from a check details URL."""
    match = re.search(r"/actions/runs/(\d+)", details_url or "")
    return match.group(1) if match else None


def _check_identity(check: dict[str, Any]) -> str:
    workflow = str(check.get("workflowName") or check.get("workflow") or "").strip()
    name = str(check.get("name") or check.get("context") or "").strip()
    if not name:
        return ""
    return f"{workflow}:{name}" if workflow else name


def latest_rollup(checks: list[Any]) -> list[dict[str, Any]]:
    """Collapse superseded check rows to the latest row per identity."""
    latest: dict[str, tuple[str, int, dict[str, Any]]] = {}
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            continue
        identity = _check_identity(check)
        if not identity:
            continue
        timestamp = str(
            check.get("completedAt") or check.get("startedAt") or check.get("createdAt") or ""
        )
        previous = latest.get(identity)
        if previous is None or (timestamp, index) >= (previous[0], previous[1]):
            latest[identity] = (timestamp, index, check)
    return [item[2] for item in sorted(latest.values(), key=lambda item: item[1])]


def is_merge_quorum_check(check: dict[str, Any]) -> bool:
    workflow = str(check.get("workflowName") or "").lower()
    name = str(check.get("name") or check.get("context") or "").lower()
    return "merge quorum" in workflow or "merge-quorum" in workflow or "merge-quorum" in name


def count_non_quorum_failures(detail: dict[str, Any]) -> int:
    """Count failing checks at the head that are NOT the merge-quorum check."""
    failures = 0
    for check in latest_rollup(detail.get("statusCheckRollup") or []):
        if is_merge_quorum_check(check):
            continue
        conclusion = str(check.get("conclusion") or "").upper()
        if conclusion in FAILURE_CONCLUSIONS:
            failures += 1
    return failures


def find_stale_quorum_failure(
    detail: dict[str, Any], *, now: datetime, min_age_minutes: int
) -> dict[str, Any] | None:
    """Return the quorum check row if it is a completed, aged failure."""
    for check in latest_rollup(detail.get("statusCheckRollup") or []):
        if not is_merge_quorum_check(check):
            continue
        if str(check.get("conclusion") or "").upper() not in FAILURE_CONCLUSIONS:
            return None
        completed = parse_iso(str(check.get("completedAt") or ""))
        if completed is None:
            return None
        if now - completed < timedelta(minutes=min_age_minutes):
            return None
        return check
    return None


def build_plan(
    prs: list[dict[str, Any]],
    *,
    fetch_pr_detail: Callable[[int], dict[str, Any]],
    fetch_packet: Callable[[int], dict[str, Any]],
    now: datetime,
    min_age_minutes: int,
    max_reruns: int,
) -> list[dict[str, Any]]:
    """Plan ``gh run rerun`` actions for stale-but-satisfiable quorum checks."""
    plan: list[dict[str, Any]] = []
    for pr in prs:
        if len(plan) >= max_reruns:
            break
        if pr.get("isDraft"):
            continue
        number = int(pr["number"])
        detail = fetch_pr_detail(number)
        stale = find_stale_quorum_failure(detail, now=now, min_age_minutes=min_age_minutes)
        if stale is None:
            continue
        run_id = parse_run_id(str(stale.get("detailsUrl") or ""))
        if not run_id:
            continue
        packet = fetch_packet(number)
        status = str(packet.get("status") or "").strip().lower()
        if status not in SATISFIABLE_PACKET_STATUSES:
            if status != CIRCULAR_REPAIR_STATUS:
                continue
            # Circular case: accept repair_or_wait only when the quorum run
            # itself is the sole failure, reviewers are already counted, and
            # there is no unresolved dissent. The rerun is read-only either way.
            if count_non_quorum_failures(detail) > 0:
                continue
            if not packet.get("counted_reviewer_ids"):
                continue
            if packet.get("unresolved_dissent"):
                continue
        plan.append(
            {
                "pr": number,
                "run_id": run_id,
                "packet_status": status,
                "completed_at": str(stale.get("completedAt") or ""),
                "command": ["gh", "run", "rerun", run_id],
            }
        )
    return plan


def _gh_json(args: list[str]) -> Any:
    result = subprocess.run(
        ["gh", *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=GH_TIMEOUT_SECONDS,
    )
    return json.loads(result.stdout or "null")


def _fetch_open_prs(repo: str) -> list[dict[str, Any]]:
    return (
        _gh_json(
            [
                "pr",
                "list",
                "--repo",
                repo,
                "--state",
                "open",
                "--json",
                "number,isDraft",
                "--limit",
                "200",
            ]
        )
        or []
    )


def _fetch_pr_detail(repo: str, number: int) -> dict[str, Any]:
    return (
        _gh_json(
            [
                "pr",
                "view",
                str(number),
                "--repo",
                repo,
                "--json",
                "statusCheckRollup,headRefOid",
            ]
        )
        or {}
    )


def _fetch_packet(repo: str, number: int) -> dict[str, Any]:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "aragora.cli.main",
            "review-queue",
            "merge-packet",
            "--pr",
            str(number),
            "--repo",
            repo,
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        return {}
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return {}
    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    return payload if isinstance(payload, dict) else {}


def _run_command(command: list[str]) -> int:
    return subprocess.run(command, timeout=GH_TIMEOUT_SECONDS).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=DEFAULT_REPO, help="GitHub repo owner/name")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute the planned gh run rerun commands (default: dry-run)",
    )
    parser.add_argument(
        "--min-age-minutes",
        type=int,
        default=10,
        help="Skip quorum failures younger than this (default: 10)",
    )
    parser.add_argument(
        "--max-reruns",
        type=int,
        default=3,
        help="Maximum reruns planned per invocation (default: 3)",
    )
    args = parser.parse_args(argv)

    now = datetime.now().astimezone()
    plan = build_plan(
        _fetch_open_prs(args.repo),
        fetch_pr_detail=lambda n: _fetch_pr_detail(args.repo, n),
        fetch_packet=lambda n: _fetch_packet(args.repo, n),
        now=now,
        min_age_minutes=args.min_age_minutes,
        max_reruns=args.max_reruns,
    )

    failures = 0
    for action in plan:
        print(json.dumps({**action, "mode": "apply" if args.apply else "dry-run"}))
        if args.apply:
            if _run_command(action["command"]) != 0:
                failures += 1
    if not plan:
        print(json.dumps({"plan": "empty", "mode": "apply" if args.apply else "dry-run"}))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
