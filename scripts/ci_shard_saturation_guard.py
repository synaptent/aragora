#!/usr/bin/env python3
"""Early-warning guard for CI test-shard saturation.

Why this exists:
The ``test-fast`` matrix in ``.github/workflows/test.yml`` runs sharded
pytest jobs on GitHub-hosted runners with a 30-minute cap. Shards grow
organically as tests are added, and historically saturation was only
noticed when jobs started getting killed at the cap (the ``debate-am``
shard saturated twice: rebalanced in PR #9280 on 2026-07-14, then
re-saturated within days and was re-split into debate-phases/1/2/3 in
PR #9307). This guard surfaces the trend *before* the cap kills jobs.

What it does (read-only against the GitHub API):
1. Lists recent completed runs of the target workflow via
   ``gh api repos/<repo>/actions/workflows/test.yml/runs``.
2. Fetches per-run jobs via ``gh api repos/<repo>/actions/runs/<id>/jobs``
   and keeps matrix jobs named ``test-fast (<shard>, ...)``.
3. Discards jobs whose ``Run <shard> tests`` step was skipped — the
   path-filter (``test-shard-scope``) lets irrelevant shards complete in
   seconds, and counting those would drag the percentiles down.
4. Computes per-shard duration percentiles (p50/p95/max, nearest-rank)
   over the lookback window and counts jobs that ran into the cap.
5. Emits a ``::warning::`` annotation per shard whose p95 exceeds the
   threshold (default 20 min against the 30-min cap), plus a markdown
   table to ``$GITHUB_STEP_SUMMARY`` and ``breach``/``report`` outputs
   to ``$GITHUB_OUTPUT`` so a wrapping workflow can open/update a
   tracking issue.

Retired shards: after a re-split, the lookback window still contains
samples from shards that no longer exist (e.g. ``debate-am`` after the
#9307 re-split). The current shard layout is read from the ``test-fast``
matrix in the checked-out workflow file; shards absent from it are shown
in the report as "retired (aging out)" but never trigger warnings or
issue creation. If the matrix cannot be parsed, all shards are treated
as active (fail open — a stale warning beats a silent miss).

When a shard breaches, rebalance it *before* it hits the cap. Shard
sizing methodology: per-file pytest test counts multiplied by measured
seconds-per-test for that area, with the resulting alphabetic/directory
boundaries encoded in ``scripts/ci_resolve_test_shard.py`` (see the
sub-sharding history comment above the ``test-fast`` matrix in
``.github/workflows/test.yml``).

Usage::

    python3 scripts/ci_shard_saturation_guard.py                  # defaults
    python3 scripts/ci_shard_saturation_guard.py --days 14 --max-runs 80
    python3 scripts/ci_shard_saturation_guard.py --threshold-minutes 18

Requires an authenticated ``gh`` CLI (``GH_TOKEN`` in CI).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Matrix jobs render as e.g.
#   "test-fast (debate-am, debate-am, debate, 30)"
# and GitHub truncates long names with a trailing "..." — the shard name
# is always the first comma/paren-delimited token inside the parens.
_JOB_NAME_RE = re.compile(r"^test-fast \(([^,)]+)")

# The pytest step inside each shard job ("Run <shard> tests"). When the
# path-filter skips a shard, this step's conclusion is "skipped".
_RUN_STEP_RE = re.compile(r"^Run .* tests$")

DEFAULT_REPO = "synaptent/aragora"
DEFAULT_WORKFLOW = "test.yml"
DEFAULT_WORKFLOW_FILE = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "test.yml"
DEFAULT_DAYS = 14
DEFAULT_MAX_RUNS = 80
DEFAULT_THRESHOLD_MINUTES = 20.0
DEFAULT_CAP_MINUTES = 30.0


@dataclass
class ShardStats:
    shard: str
    samples: int
    p50_minutes: float
    p95_minutes: float
    max_minutes: float
    cap_hits: int
    breach: bool
    active: bool = True


# ---------------------------------------------------------------------------
# GitHub API access (via gh CLI; kept thin so tests can inject job data)
# ---------------------------------------------------------------------------


def _gh_api_json(path: str) -> dict:
    proc = subprocess.run(
        ["gh", "api", path],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"gh api {path} failed (exit {proc.returncode}): {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def fetch_recent_run_ids(repo: str, workflow: str, days: int, max_runs: int) -> list[int]:
    """Return ids of the most recent completed runs within the lookback window."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    run_ids: list[int] = []
    page = 1
    # per_page must stay constant across pages: the API computes offsets as
    # (page-1)*per_page, so shrinking it mid-pagination rereads earlier runs.
    while len(run_ids) < max_runs:
        data = _gh_api_json(
            f"repos/{repo}/actions/workflows/{workflow}/runs"
            f"?status=completed&created=%3E%3D{since}&per_page=100&page={page}"
        )
        batch = data.get("workflow_runs", [])
        if not batch:
            break
        run_ids.extend(run["id"] for run in batch)
        if len(batch) < 100:
            break
        page += 1
    return run_ids[:max_runs]


def fetch_run_jobs(repo: str, run_id: int) -> list[dict]:
    """Return all jobs for a run (paginated; test.yml has ~44 jobs/run)."""
    jobs: list[dict] = []
    page = 1
    while True:
        data = _gh_api_json(
            f"repos/{repo}/actions/runs/{run_id}/jobs?filter=latest&per_page=100&page={page}"
        )
        batch = data.get("jobs", [])
        jobs.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return jobs


# ---------------------------------------------------------------------------
# Pure analysis helpers (unit-tested)
# ---------------------------------------------------------------------------


def load_active_shards(workflow_file: Path) -> frozenset[str] | None:
    """Shard names in the current test-fast matrix, or None if unparsable.

    Stdlib-only on purpose (no PyYAML dependency in CI): slices the
    ``test-fast`` job block out of the workflow text, then the matrix
    ``category:`` list up to ``steps:``, and collects each entry's
    ``- name: <shard>``. Returns None (= treat every shard as active)
    when the file or the expected structure is missing.
    """
    try:
        text = workflow_file.read_text(encoding="utf-8")
    except OSError:
        return None
    # Job block: from "  test-fast:" to the next 2-space-indented key.
    job_match = re.search(r"^  test-fast:\n(.*?)(?=^  \S|\Z)", text, re.M | re.S)
    if not job_match:
        return None
    block = job_match.group(1)
    category_match = re.search(r"^\s+category:\n(.*?)(?=^\s{4,6}steps:|\Z)", block, re.M | re.S)
    if not category_match:
        return None
    shards = frozenset(re.findall(r"^\s+- name: (\S+)\s*$", category_match.group(1), re.M))
    return shards or None


def parse_shard_name(job_name: str) -> str | None:
    """Extract the shard name from a ``test-fast (<shard>, ...)`` job name."""
    match = _JOB_NAME_RE.match(job_name)
    return match.group(1).strip() if match else None


def _run_step_conclusion(job: dict) -> str | None:
    for step in job.get("steps") or []:
        if _RUN_STEP_RE.match(step.get("name") or ""):
            return step.get("conclusion")
    return None


def job_executed(job: dict) -> bool:
    """True when the shard's pytest step actually ran (not path-filtered out)."""
    return _run_step_conclusion(job) not in (None, "skipped")


def _parse_timestamp(value: str) -> datetime:
    # GitHub currently emits ...T00:00:00Z, but fromisoformat also tolerates
    # fractional seconds and explicit offsets, unlike a pinned strptime format.
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def job_duration_minutes(job: dict) -> float | None:
    started = job.get("started_at")
    completed = job.get("completed_at")
    if not started or not completed:
        return None
    try:
        delta = _parse_timestamp(completed) - _parse_timestamp(started)
    except ValueError:
        return None
    minutes = delta.total_seconds() / 60.0
    return minutes if minutes >= 0 else None


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile; ``values`` need not be sorted."""
    if not values:
        raise ValueError("percentile of empty list")
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100.0 * len(ordered)))
    return ordered[rank - 1]


def collect_shard_durations(
    jobs: list[dict], cap_minutes: float = DEFAULT_CAP_MINUTES
) -> dict[str, list[float]]:
    """Group executed test-fast job durations (minutes) by shard name.

    Cancelled jobs near the runner cap are cap kills — the saturation signal
    this guard exists to catch — and must count. Jobs cancelled well before
    the cap (superseded runs, concurrency cancels) are truncated samples that
    would drag p95 *down*, so they are dropped.
    """
    durations: dict[str, list[float]] = {}
    for job in jobs:
        shard = parse_shard_name(job.get("name") or "")
        if shard is None:
            continue
        conclusion = _run_step_conclusion(job)
        if conclusion in (None, "skipped"):
            continue
        minutes = job_duration_minutes(job)
        if minutes is None:
            continue
        if conclusion == "cancelled" and minutes < cap_minutes - 1.0:
            continue
        durations.setdefault(shard, []).append(minutes)
    return durations


def analyze(
    durations_by_shard: dict[str, list[float]],
    threshold_minutes: float,
    cap_minutes: float,
    active_shards: frozenset[str] | None = None,
) -> list[ShardStats]:
    """Per-shard stats, sorted by p95 descending so the hottest shard leads.

    Shards absent from ``active_shards`` (retired by a re-split, still in
    the lookback window) never breach — they appear in the report only.
    ``active_shards=None`` means the current layout is unknown; fail open
    and treat every shard as active.
    """
    stats = []
    for shard, durations in durations_by_shard.items():
        p95 = percentile(durations, 95)
        active = active_shards is None or shard in active_shards
        stats.append(
            ShardStats(
                shard=shard,
                samples=len(durations),
                p50_minutes=round(percentile(durations, 50), 1),
                p95_minutes=round(p95, 1),
                max_minutes=round(max(durations), 1),
                # Jobs killed at the cap report durations a hair under it.
                cap_hits=sum(1 for d in durations if d >= cap_minutes - 1.0),
                breach=active and p95 > threshold_minutes,
                active=active,
            )
        )
    return sorted(stats, key=lambda s: s.p95_minutes, reverse=True)


def render_markdown_table(stats: list[ShardStats], threshold_minutes: float) -> str:
    lines = [
        "| Shard | Samples | p50 (min) | p95 (min) | Max (min) | Cap hits | Status |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in stats:
        if s.breach:
            status = f"⚠️ p95 > {threshold_minutes:g}m"
        elif not s.active:
            status = "retired (aging out)"
        else:
            status = "OK"
        lines.append(
            f"| {s.shard} | {s.samples} | {s.p50_minutes} | {s.p95_minutes} "
            f"| {s.max_minutes} | {s.cap_hits} | {status} |"
        )
    return "\n".join(lines)


def emit_outputs(
    stats: list[ShardStats],
    threshold_minutes: float,
    cap_minutes: float,
    runs_analyzed: int,
    days: int,
) -> None:
    """Print the report and write annotations / step summary / outputs."""
    breaches = [s for s in stats if s.breach]
    table = render_markdown_table(stats, threshold_minutes)
    header = (
        f"test-fast shard durations — p95 over {runs_analyzed} runs, "
        f"last {days} days (threshold {threshold_minutes:g}m, cap {cap_minutes:g}m)"
    )

    print(header)
    print(table)

    for s in breaches:
        print(
            f"::warning title=CI shard saturation risk::Shard '{s.shard}' p95 is "
            f"{s.p95_minutes}m (threshold {threshold_minutes:g}m, runner cap "
            f"{cap_minutes:g}m, {s.cap_hits} cap hits in {s.samples} samples). "
            f"Rebalance via scripts/ci_resolve_test_shard.py before jobs get "
            f"killed at the cap."
        )

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(f"## {header}\n\n{table}\n")

    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as fh:
            fh.write("status=ok\n")
            fh.write(f"breach={'1' if breaches else '0'}\n")
            fh.write(f"breach_shards={','.join(s.shard for s in breaches)}\n")
            fh.write(f"report<<CI_SHARD_REPORT_EOF\n{header}\n\n{table}\nCI_SHARD_REPORT_EOF\n")


def emit_no_data_outputs(message: str) -> None:
    """Report an early exit so the workflow's green path can't overstate it."""
    print(message)
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as fh:
            fh.write("status=no_data\n")
            fh.write("breach=0\n")
            fh.write("breach_shards=\n")
            fh.write(f"report<<CI_SHARD_REPORT_EOF\n{message}\nCI_SHARD_REPORT_EOF\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--workflow", default=DEFAULT_WORKFLOW)
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="lookback window")
    parser.add_argument(
        "--max-runs",
        type=int,
        default=DEFAULT_MAX_RUNS,
        help="cap on runs analyzed (keeps API usage cheap; most recent first)",
    )
    parser.add_argument("--threshold-minutes", type=float, default=DEFAULT_THRESHOLD_MINUTES)
    parser.add_argument("--cap-minutes", type=float, default=DEFAULT_CAP_MINUTES)
    parser.add_argument(
        "--workflow-file",
        type=Path,
        default=DEFAULT_WORKFLOW_FILE,
        help="checked-out workflow to read the current shard layout from "
        "(retired shards report but never breach)",
    )
    parser.add_argument(
        "--fail-on-breach",
        action="store_true",
        help="exit 2 when any shard breaches (default: annotate only, exit 0)",
    )
    args = parser.parse_args(argv)

    run_ids = fetch_recent_run_ids(args.repo, args.workflow, args.days, args.max_runs)
    if not run_ids:
        emit_no_data_outputs(
            f"No completed {args.workflow} runs in the last {args.days} days; nothing measured."
        )
        return 0

    all_jobs: list[dict] = []
    for run_id in run_ids:
        all_jobs.extend(fetch_run_jobs(args.repo, run_id))

    durations = collect_shard_durations(all_jobs, args.cap_minutes)
    if not durations:
        emit_no_data_outputs(
            f"Analyzed {len(run_ids)} runs but found no executed test-fast shard "
            f"jobs (all path-filtered?); nothing measured."
        )
        return 0

    active_shards = load_active_shards(args.workflow_file)
    if active_shards is None:
        print(
            f"::notice::Could not parse the test-fast matrix from {args.workflow_file}; "
            f"treating all shards as active."
        )

    stats = analyze(durations, args.threshold_minutes, args.cap_minutes, active_shards)
    emit_outputs(stats, args.threshold_minutes, args.cap_minutes, len(run_ids), args.days)

    if args.fail_on_breach and any(s.breach for s in stats):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
