#!/usr/bin/env python3
"""Funnel telemetry snapshot for the autonomous PR pipeline (READ-ONLY).

The pipeline (writer lanes -> outbox publisher -> draft PRs -> ready ->
evidence -> quorum -> arbiter merge) has no time-in-state measurement per
funnel stage, so pileups go unnoticed until they are hundreds of units deep.
This script takes one read-only snapshot per run:

1. One ``gh pr list`` call for open automation PRs (draft + ready stages,
   ``--limit 300``), filtered by ``--branch-prefix`` (default ``codex/``,
   repeatable).
2. One ``gh pr list --state merged --search "merged:>=<ISO 24h ago>"`` call
   (``--limit 100``). If the search variant fails, the snapshot degrades
   gracefully to ``merged_24h: null`` with an annotation rather than failing.
3. Outbox depth: count of ``*.json`` files directly in ``--outbox-dir``
   (default ``.aragora/automation-outbox``; missing dir = 0 with an
   annotation).

Emits JSON to stdout (and atomically to ``--out`` when given)::

    {generated_at, outbox_depth,
     stages: {draft: {count, age_hours: {p50, p90, max}},
              ready: {count, age_hours: {p50, p90, max}}},
     merged_24h, stale_tail, thresholds, thresholds_breached[], annotations[]}

``stale_tail`` counts open automation PRs older than ``--stale-days``
(default 4). ``thresholds_breached`` records a breach when the draft-stage
age p90 exceeds ``--max-draft-age-hours`` (default 72) or ``stale_tail``
exceeds ``--max-stale-tail`` (default 20).

Exit codes (sentinel-friendly): 0 normal, 3 if any threshold breached,
1 on failure.

Safety model (mirrors ``backlog_gate.py`` / ``pr_ready_triage.py``):
read-only against GitHub, no mutations; the only file this script can write
is the optional ``--out`` snapshot (temp file + ``os.replace``). Stdlib-only
by design so it can run anywhere ``gh`` is authenticated.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

DEFAULT_REPO = "synaptent/aragora"
DEFAULT_BRANCH_PREFIXES = ("codex/",)
DEFAULT_OUTBOX_DIR = os.path.join(".aragora", "automation-outbox")
DEFAULT_STALE_DAYS = 4
DEFAULT_MAX_DRAFT_AGE_HOURS = 72.0
DEFAULT_MAX_STALE_TAIL = 20
GH_TIMEOUT_SECONDS = 120
OPEN_LIST_LIMIT = 300
MERGED_LIST_LIMIT = 100

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_BREACH = 3

_GH_OPEN_FIELDS = "number,headRefName,isDraft,createdAt,updatedAt,labels"
_GH_MERGED_FIELDS = "number,headRefName,mergedAt,createdAt"


# --- Parsing / math helpers ----------------------------------------------------------


def _parse_iso(ts: Any) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def percentile(values: list[float], pct: float) -> float | None:
    """Linear-interpolated percentile of ``values``; None for an empty list."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (pct / 100.0)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[int(rank)]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def age_stats(ages_hours: list[float]) -> dict[str, float | None]:
    return {
        "p50": _round(percentile(ages_hours, 50)),
        "p90": _round(percentile(ages_hours, 90)),
        "max": _round(max(ages_hours)) if ages_hours else None,
    }


# --- Inputs (read-only) -------------------------------------------------------------


def default_list_open_prs(repo: str) -> list[dict[str, Any]]:
    """One ``gh pr list`` call for open PRs (read-only, capped at 300)."""
    command = [
        "gh",
        "pr",
        "list",
        "--repo",
        repo,
        "--state",
        "open",
        "--json",
        _GH_OPEN_FIELDS,
        "--limit",
        str(OPEN_LIST_LIMIT),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=GH_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh pr list failed (exit {result.returncode}): {result.stderr.strip()}")
    payload = json.loads(result.stdout or "[]")
    if not isinstance(payload, list):
        raise RuntimeError("gh pr list returned unexpected payload (expected a list)")
    return payload


def default_list_merged_prs(repo: str, since: datetime) -> list[dict[str, Any]]:
    """One ``gh pr list --state merged --search`` call (read-only, capped at 100).

    Raises on any failure; the caller degrades gracefully to
    ``merged_24h: null`` with an annotation rather than failing the snapshot.
    """
    command = [
        "gh",
        "pr",
        "list",
        "--repo",
        repo,
        "--state",
        "merged",
        "--json",
        _GH_MERGED_FIELDS,
        "--limit",
        str(MERGED_LIST_LIMIT),
        "--search",
        f"merged:>={since.strftime('%Y-%m-%dT%H:%M:%SZ')}",
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=GH_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"gh pr list (merged search) failed (exit {result.returncode}): {result.stderr.strip()}"
        )
    payload = json.loads(result.stdout or "[]")
    if not isinstance(payload, list):
        raise RuntimeError("gh pr list (merged search) returned unexpected payload")
    return payload


def count_outbox_depth(outbox_dir: str) -> tuple[int, bool]:
    """Count ``*.json`` files directly in the outbox dir.

    A missing directory is (0, True) -- annotated, never an error.
    (Deliberately duplicated from ``backlog_gate.py``: these scripts are
    freestanding stdlib files by design.)
    """
    if not os.path.isdir(outbox_dir):
        return 0, True
    depth = 0
    with os.scandir(outbox_dir) as entries:
        for entry in entries:
            if entry.is_file() and entry.name.endswith(".json"):
                depth += 1
    return depth, False


# --- Output ----------------------------------------------------------------------------


def atomic_write_json(path: str, payload: dict[str, Any]) -> None:
    """Write temp + ``os.replace`` so readers never observe a partial file."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except OSError:  # never mask the primary error with a cleanup failure
            pass


# --- Snapshot ---------------------------------------------------------------------------


def _matches_prefix(pr: dict[str, Any], branch_prefixes: tuple[str, ...]) -> bool:
    head = str(pr.get("headRefName") or "")
    return any(head.startswith(prefix) for prefix in branch_prefixes)


def run_snapshot(
    *,
    list_open_prs: Callable[[], list[dict[str, Any]]],
    list_merged_prs: Callable[[datetime], list[dict[str, Any]]],
    branch_prefixes: tuple[str, ...] = DEFAULT_BRANCH_PREFIXES,
    outbox_dir: str = DEFAULT_OUTBOX_DIR,
    stale_days: int = DEFAULT_STALE_DAYS,
    max_draft_age_hours: float = DEFAULT_MAX_DRAFT_AGE_HOURS,
    max_stale_tail: int = DEFAULT_MAX_STALE_TAIL,
    out_file: str | None = None,
    now: datetime | None = None,
    log: Callable[[str], None] = print,
) -> int:
    """Build one funnel snapshot; return 0 / 3 (threshold breach) / 1 (failure)."""
    if now is None:
        now = datetime.now(timezone.utc)
    annotations: list[str] = []

    try:
        raw_open = list_open_prs()
        open_prs = [
            pr for pr in raw_open if isinstance(pr, dict) and _matches_prefix(pr, branch_prefixes)
        ]
        outbox_depth, outbox_missing = count_outbox_depth(outbox_dir)
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"action": "error", "error": str(exc)[:500]}), file=sys.stderr)
        return EXIT_FAILURE

    # ``gh pr list`` truncates BEFORE the prefix filter, so a raw payload at
    # the limit makes every count derived from it a floor, not a total.
    open_truncated = len(raw_open) >= OPEN_LIST_LIMIT
    if open_truncated:
        annotations.append(f"list_truncated_open:>={OPEN_LIST_LIMIT}")

    if outbox_missing:
        annotations.append(f"outbox_dir_missing:{outbox_dir}")

    # Merged-in-24h, degrading gracefully when the search variant fails.
    since = now - timedelta(hours=24)
    merged_24h: int | None
    try:
        merged = list_merged_prs(since)
        if len(merged) >= MERGED_LIST_LIMIT:
            # Truncation happens before the prefix filter, so the filtered
            # count would be a misleading undercount; degrade to null like
            # the failed-search path instead of reporting it.
            merged_24h = None
            annotations.append(f"list_truncated_merged:>={MERGED_LIST_LIMIT}")
        else:
            merged_24h = 0
            for pr in merged:
                if not isinstance(pr, dict) or not _matches_prefix(pr, branch_prefixes):
                    continue
                merged_at = _parse_iso(pr.get("mergedAt"))
                if merged_at is not None and merged_at >= since:
                    merged_24h += 1
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
        merged_24h = None
        annotations.append(f"merged_search_failed:{str(exc)[:200]}")

    # Stage ages: unparseable createdAt is excluded from age math (and the
    # stale tail) but still counted in the stage count.
    draft_ages: list[float] = []
    ready_ages: list[float] = []
    draft_count = 0
    ready_count = 0
    stale_tail = 0
    stale_cutoff = timedelta(days=max(0, stale_days))
    for pr in open_prs:
        is_draft = bool(pr.get("isDraft"))
        if is_draft:
            draft_count += 1
        else:
            ready_count += 1
        created = _parse_iso(pr.get("createdAt"))
        if created is None:
            continue
        age_hours = (now - created).total_seconds() / 3600.0
        (draft_ages if is_draft else ready_ages).append(age_hours)
        if now - created > stale_cutoff:
            stale_tail += 1

    stages: dict[str, dict[str, Any]] = {
        "draft": {"count": draft_count, "age_hours": age_stats(draft_ages)},
        "ready": {"count": ready_count, "age_hours": age_stats(ready_ages)},
    }

    thresholds_breached: list[str] = []
    draft_p90 = stages["draft"]["age_hours"]["p90"]
    if draft_p90 is not None and draft_p90 > max_draft_age_hours:
        thresholds_breached.append(
            f"draft_age_p90:{draft_p90}>max_draft_age_hours:{max_draft_age_hours}"
        )
    if stale_tail > max_stale_tail:
        thresholds_breached.append(f"stale_tail:{stale_tail}>max_stale_tail:{max_stale_tail}")
    if open_truncated:
        # Stage counts and stale_tail are unreliable floors when the open
        # listing is truncated; the snapshot exists to surface breaches, and
        # unknown-because-truncated is breach-worthy.
        thresholds_breached.append("open_list_truncated")

    payload = {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "outbox_depth": outbox_depth,
        "stages": stages,
        "merged_24h": merged_24h,
        "stale_tail": stale_tail,
        "thresholds": {
            "max_draft_age_hours": max_draft_age_hours,
            "max_stale_tail": max_stale_tail,
            "stale_days": stale_days,
        },
        "thresholds_breached": thresholds_breached,
        "annotations": annotations,
    }

    log(json.dumps(payload, sort_keys=True))

    if out_file:
        try:
            atomic_write_json(out_file, payload)
        except OSError as exc:
            print(
                json.dumps({"action": "out_write_failed", "error": str(exc)[:300]}),
                file=sys.stderr,
            )
            return EXIT_FAILURE

    return EXIT_BREACH if thresholds_breached else EXIT_OK


_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def repo_arg(value: str) -> str:
    """Argparse type: validate ``owner/name`` at parse time, before any gh call."""
    if not _REPO_RE.match(value):
        raise argparse.ArgumentTypeError(f"--repo must look like owner/name, got {value!r}")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only funnel telemetry snapshot for automation PRs: per-stage "
            "counts and age percentiles, merged-in-24h, outbox depth, stale "
            "tail. Exits 0 normally, 3 if a threshold is breached, 1 on failure."
        )
    )
    parser.add_argument(
        "--repo", default=DEFAULT_REPO, type=repo_arg, help="GitHub repo (owner/name)"
    )
    parser.add_argument(
        "--branch-prefix",
        action="append",
        default=None,
        help=f"Head-branch prefix to count; repeatable (default: {list(DEFAULT_BRANCH_PREFIXES)})",
    )
    parser.add_argument(
        "--outbox-dir",
        default=DEFAULT_OUTBOX_DIR,
        help=f"Outbox directory whose direct *.json files are counted "
        f"(default {DEFAULT_OUTBOX_DIR}; missing dir counts as 0)",
    )
    parser.add_argument(
        "--stale-days",
        type=int,
        default=DEFAULT_STALE_DAYS,
        help=f"Open PRs older than this many days count toward the stale tail "
        f"(default {DEFAULT_STALE_DAYS})",
    )
    parser.add_argument(
        "--max-draft-age-hours",
        type=float,
        default=DEFAULT_MAX_DRAFT_AGE_HOURS,
        help=f"Breach when draft-stage age p90 exceeds this "
        f"(default {DEFAULT_MAX_DRAFT_AGE_HOURS})",
    )
    parser.add_argument(
        "--max-stale-tail",
        type=int,
        default=DEFAULT_MAX_STALE_TAIL,
        help=f"Breach when the stale tail exceeds this (default {DEFAULT_MAX_STALE_TAIL})",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Optional path to atomically write the snapshot JSON",
    )
    args = parser.parse_args(argv)

    prefixes = tuple(args.branch_prefix) if args.branch_prefix else DEFAULT_BRANCH_PREFIXES

    return run_snapshot(
        list_open_prs=lambda: default_list_open_prs(args.repo),
        list_merged_prs=lambda since: default_list_merged_prs(args.repo, since),
        branch_prefixes=prefixes,
        outbox_dir=args.outbox_dir,
        stale_days=args.stale_days,
        max_draft_age_hours=args.max_draft_age_hours,
        max_stale_tail=args.max_stale_tail,
        out_file=args.out,
    )


if __name__ == "__main__":
    sys.exit(main())
