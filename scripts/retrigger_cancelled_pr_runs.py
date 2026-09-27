#!/usr/bin/env python3
"""Re-run unexpectedly cancelled PROTECTED PR workflow runs — and advisory
runs displaced while still QUEUED — once each.

Cancellation-provenance-aware M1 guardian (docs/governance/
PR_RUN_CANCELLATION_DIAGNOSIS.md). The repo INTENTIONALLY cancels QUEUED
non-required advisory ``pull_request`` runs through
``.github/workflows/required-check-priority.yml`` (RCP) — that displacement
is the prioritization system working, and this guardian completes it by
rescheduling exactly those displaced runs once, so no run ends terminally
``cancelled`` merely because it yielded queue capacity. What must never stay
terminal-cancelled at all is the PROTECTED class: required checks and the
priority keep-list (observed live 2026-07-09: keep-listed test shards killed
mid-run — one at 96% all-passing — each clearing on manual rerun at 30-90min
settlement latency).

Provenance rule: a cancelled run is rerun-eligible if its workflow is in
``scripts/ci/required_workflow_manifest.json`` (the versioned protected
manifest mirroring the priority keep-list) —
``unexpected_required_cancellation`` — OR, one narrow exception, if it is an
advisory run that NEVER EXECUTED: a lazy jobs probe shows no job/step ever
started, meaning required-check-priority.yml displaced it while it was still
QUEUED (``queued_phase_advisory_displacement``). The exception is safe
because (a) it is bounded once per ``run_attempt`` like every other rerun,
(b) it never touches runs that actually started — an advisory run cancelled
mid-execution (e.g. at Checkout) stays cancelled, and upstream RCP's
queued-only rule now guarantees in-flight advisory runs are never cancelled
at all, so the rerun cannot loop with the canceller — and (c) without it
every queued-phase displacement ends as a terminal red ``cancelled``
conclusion that taxes merge settlement. Advisory runs with any executed
work remain ``intentional_advisory_priority`` and stay cancelled.

A cancelled run is re-run ONLY when ALL hold:
- ``conclusion == cancelled`` and the event is a PR event;
- its workflow path is in the protected manifest, OR the never-executed
  jobs probe above confirms a queued-phase advisory displacement;
- its ``head_sha`` equals the PR's CURRENT head (not superseded);
- no newer run of the same workflow+branch exists (rerun would be moot);
- the PR is open and not draft;
- the run is younger than ``--ttl-hours``;
- ``run_attempt == 1`` — a rerun bumps the attempt counter, so this is the
  stateless once-per-run marker that bounds re-run loops if the canceller
  strikes again.

Dry-run by default; ``--apply`` performs the reruns.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request

PR_EVENTS = {"pull_request"}
DEFAULT_MANIFEST = Path(__file__).resolve().parent / "ci" / "required_workflow_manifest.json"


def load_protected_manifest(path: Path = DEFAULT_MANIFEST) -> set[str]:
    """Load the protected workflow PATHS (names in the manifest are consumed
    only by the future required-check-priority.yml migration). Fail CLOSED on
    any problem:
    an unreadable or empty manifest yields empty sets, and with empty sets no
    run is rerun-eligible — the guardian then does nothing rather than risk
    re-running intentionally cancelled advisory runs."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {str(p).strip() for p in data.get("workflow_paths", []) if str(p).strip()}


class GitHubApiError(RuntimeError):
    """Raised when GitHub API calls fail."""


class GitHubClient:
    """Small GitHub API client using urllib and GITHUB_TOKEN."""

    def __init__(self, repo: str, token: str) -> None:
        if "/" not in repo:
            raise ValueError(f"Invalid repo format '{repo}', expected OWNER/REPO")
        self.repo = repo
        self.token = token
        self.api_base = "https://api.github.com"

    def _request_json(
        self,
        method: str,
        url: str,
        payload: dict[str, Any] | None = None,
    ) -> tuple[Any, Any]:
        body: bytes | None = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "aragora-cancelled-run-guardian",
        }
        req = request.Request(url=url, data=body, headers=headers, method=method)
        try:
            resp = request.urlopen(req, timeout=30)
            raw = resp.read().decode("utf-8")
            parsed = json.loads(raw) if raw else {}
            return parsed, resp
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:200]
            raise GitHubApiError(f"{method} {url} failed: {exc.code} {detail}") from exc
        except error.URLError as exc:
            raise GitHubApiError(f"{method} {url} failed: {exc.reason}") from exc

    def _api(self, path: str, query: dict[str, Any] | None = None) -> str:
        url = f"{self.api_base}{path}"
        if query:
            url = f"{url}?{parse.urlencode(query)}"
        return url

    def get(self, path: str, query: dict[str, Any] | None = None) -> Any:
        data, _ = self._request_json("GET", self._api(path, query))
        return data

    def post(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        data, _ = self._request_json("POST", self._api(path), payload)
        return data

    def paginate(
        self,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        max_pages: int = 10,
    ) -> list[Any]:
        items: list[Any] = []
        current_query = dict(query or {})
        current_query.setdefault("per_page", 100)
        current_query.setdefault("page", 1)
        pages = 0
        while pages < max_pages:
            pages += 1
            data, response = self._request_json("GET", self._api(path, current_query))
            if isinstance(data, list):
                page_items = data
            elif isinstance(data, dict) and "workflow_runs" in data:
                page_items = data["workflow_runs"]
            elif isinstance(data, dict) and "jobs" in data:
                page_items = data["jobs"]
            else:
                raise GitHubApiError(
                    f"Expected list-like response for paginated endpoint {path}, got {type(data)}"
                )
            if not page_items:
                break
            items.extend(page_items)
            link_header = response.headers.get("Link", "")
            if 'rel="next"' not in link_header:
                break
            current_query["page"] = int(current_query["page"]) + 1
        return items

    def list_open_pulls(self, max_pages: int = 10) -> tuple[list[dict[str, Any]], bool]:
        """Return (open PRs, scan_truncated). A truncated scan can only cause
        MISSED reruns (fail-safe direction), but it must be loud, not silent
        (#9133 openai P2): callers surface the flag in output and stderr."""
        pulls = self.paginate(
            f"/repos/{self.repo}/pulls",
            query={"state": "open", "per_page": 100},
            max_pages=max_pages,
        )
        normalized = [p for p in pulls if isinstance(p, dict)]
        truncated = len(normalized) >= max_pages * 100
        return normalized, truncated

    def list_recent_workflow_runs(self, max_runs: int) -> tuple[list[dict[str, Any]], bool]:
        """Return (runs, scan_truncated) — truncation is LOUD, mirroring the
        open-PR scan: it can only cause missed reruns, never wrong ones."""
        # Filter server-side to PR-event runs: without it, push/schedule/
        # dispatch runs consume the bounded window and eligible cancelled PR
        # runs can fall outside it in a high-churn repo (#9133 openai P2 r5).
        # Fetch one page BEYOND max_runs so truncation is detectable even
        # when max_runs lands exactly on a page boundary (#9133 r8: with
        # capacity == max_runs the flag could never fire).
        runs = self.paginate(
            f"/repos/{self.repo}/actions/runs",
            query={"per_page": 100, "event": "pull_request"},
            max_pages=max(1, (max_runs + 99) // 100) + 1,
        )
        normalized = [r for r in runs if isinstance(r, dict)]
        truncated = len(normalized) > max_runs
        return normalized[:max_runs], truncated

    def list_run_jobs(self, run_id: int, max_pages: int = 3) -> list[dict[str, Any]]:
        """Jobs of one run, for the queued-phase (never-executed) probe.

        Called LAZILY — only for advisory candidates that already passed every
        other guard — so the API budget is bounded by surviving candidates,
        not by --max-runs."""
        jobs = self.paginate(
            f"/repos/{self.repo}/actions/runs/{run_id}/jobs",
            query={"per_page": 100},
            max_pages=max_pages,
        )
        return [j for j in jobs if isinstance(j, dict)]

    def rerun_workflow_run(self, run_id: int) -> tuple[bool, str]:
        try:
            self.post(f"/repos/{self.repo}/actions/runs/{run_id}/rerun")
            return True, "rerun_requested"
        except GitHubApiError as exc:
            return False, str(exc)


def _parse_created_at(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def compute_active_head_pairs(open_pulls: list[dict[str, Any]]) -> set[tuple[str, str]]:
    """Return {(branch, head_sha)} pairs for open, NON-draft PR heads.

    Keyed by PAIR, not branch alone (#9133 openai P2): two open PRs — a fork
    and a same-repo branch, or two forks — can share a branch name with
    different SHAs; a branch-keyed dict lets whichever PR sorts last shadow
    the other and could qualify a stale-head run for rerun."""
    active: set[tuple[str, str]] = set()
    for pr in open_pulls:
        if bool(pr.get("draft")):
            continue
        head = pr.get("head", {})
        branch = str(head.get("ref", "")).strip()
        sha = str(head.get("sha", "")).strip()
        if branch and sha:
            active.add((branch, sha))
    return active


def run_never_executed(jobs: list[dict[str, Any]]) -> bool:
    """True iff a cancelled run was displaced while still QUEUED, i.e. it
    never executed anything. Two independent signals, either suffices:

    - every job has a null/empty ``started_at`` (nothing was ever assigned a
      runner), OR
    - no job contains any step with a non-null ``started_at`` (GitHub can
      stamp a job-level ``started_at`` on queued-cancelled jobs, but a STEP
      ``started_at`` appears only when the job genuinely began executing).

    A run cancelled mid-execution — e.g. at the Checkout step — HAS a started
    step and returns False; that class is eliminated upstream by RCP's
    queued-only cancellation rule and is never this guardian's to undo."""
    if all(not job.get("started_at") for job in jobs):
        return True
    return not any(
        step.get("started_at")
        for job in jobs
        for step in job.get("steps") or []
        if isinstance(step, dict)
    )


def compute_reruns(
    runs: list[dict[str, Any]],
    *,
    active_head_pairs: set[tuple[str, str]],
    now: datetime,
    open_pr_numbers: set[int] | None = None,
    ttl_hours: float,
    protected_paths: set[str],
    events: set[str] | None = None,
    fetch_jobs: Callable[[int], list[dict[str, Any]] | None] | None = None,
) -> list[dict[str, Any]]:
    """Select cancelled PR runs that deserve exactly one honest rerun.

    Two classes qualify; everything else stays cancelled:

    - ``unexpected_required_cancellation`` — the workflow is in the protected
      manifest (required checks + priority keep-list).
    - ``queued_phase_advisory_displacement`` — the workflow is advisory (not
      in the manifest) but the run NEVER EXECUTED: the jobs probe shows no
      started job/step, i.e. required-check-priority.yml displaced it while
      it was still queued. One rerun is safe: it is bounded by the
      run_attempt == 1 marker like every other rerun, and it cannot loop with
      the canceller because RCP now cancels queued runs only — once the rerun
      starts executing, priority sweeps can no longer touch it.

    An advisory run that actually STARTED (e.g. cancelled at the Checkout
    step) is never selected — intentional_advisory_priority stays cancelled —
    and that mid-execution class is eliminated upstream by RCP's queued-only
    rule anyway. The jobs probe is LAZY: it fires only for advisory
    candidates that already passed every other guard (attempt, head pair, PR
    association, TTL, supersession), so API spend scales with surviving
    candidates, not --max-runs. ``fetch_jobs=None`` (or a probe returning
    ``None``) disables/fails the advisory class CLOSED: only protected runs
    are then selected."""
    considered_events = events or PR_EVENTS
    cutoff = now - timedelta(hours=ttl_hours)
    # Supersession is judged ONLY among runs of the same PR event class AND
    # the same head SHA: a newer push/workflow_dispatch run does not
    # re-evaluate the PR's required contexts (#9133 openai P2 r2), and a newer
    # PR run at a DIFFERENT (stale) SHA does not cover the current head
    # (#9133 claude P2 r3). Ties on GitHub's second-granular timestamps are
    # broken by run id, so same-second bursts cannot both survive.
    newest_by_group: dict[tuple[Any, str, str], tuple[datetime, int]] = {}
    for run in runs:
        if str(run.get("event", "")).strip() not in considered_events:
            continue
        created = _parse_created_at(str(run.get("created_at", "")))
        if created is None:
            continue
        key = (
            run.get("workflow_id"),
            str(run.get("head_branch", "")).strip(),
            str(run.get("head_sha", "")).strip(),
        )
        stamp = (created, int(run.get("id") or 0))
        if key not in newest_by_group or stamp > newest_by_group[key]:
            newest_by_group[key] = stamp

    reruns: list[dict[str, Any]] = []
    for run in runs:
        if str(run.get("event", "")).strip() not in considered_events:
            continue
        if str(run.get("conclusion", "")).strip() != "cancelled":
            continue
        # Path-ONLY protection matching (#9133 claude P3): for pull_request
        # runs both path and name come from the PR branch's workflow file, but
        # spoofing a keep-list PATH requires the PR to modify a protected
        # workflow file — which itself triggers Tier-4 review — while spoofing
        # a display NAME is free. The residual blast radius is one bounded
        # rerun (run_attempt==1 marker), never authority.
        workflow_path = str(run.get("path", "")).split("@")[0].strip()
        is_protected = workflow_path in protected_paths
        if not is_protected and fetch_jobs is None:
            continue  # intentional_advisory_priority cancellation: stays cancelled
        if int(run.get("run_attempt") or 1) != 1:
            continue  # once-per-run marker: a rerun already happened
        branch = str(run.get("head_branch", "")).strip()
        sha = str(run.get("head_sha", "")).strip()
        if (branch, sha) not in active_head_pairs:
            continue  # superseded head, closed PR, or draft
        # Belt-and-braces PR association (#9133 r11 openai P2): when the API
        # names the run's pull_requests, at least one must be an open
        # non-draft PR we scanned; an empty list stays eligible (GitHub
        # omits it for fork runs).
        run_prs = [
            int(p.get("number") or 0) for p in run.get("pull_requests") or [] if isinstance(p, dict)
        ]
        if run_prs and open_pr_numbers is not None and not (set(run_prs) & open_pr_numbers):
            continue
        cancelled_at = _parse_created_at(
            str(run.get("updated_at", "")) or str(run.get("created_at", ""))
        )
        if cancelled_at is None or cancelled_at < cutoff:
            # TTL anchors to CANCELLATION time (updated_at), not run creation:
            # the motivating incidents were long-running shards cancelled
            # hours after they started (#9133 claude P3 r7).
            continue
        # Supersession compares run CREATION times — parse THIS run's own
        # created_at here (#9133 r8 convergent P1: a stale `created` leaking
        # from the newest_by_group loop skewed the comparison).
        created = _parse_created_at(str(run.get("created_at", "")))
        if created is None:
            continue
        group = (run.get("workflow_id"), branch, sha)
        newest = newest_by_group.get(group)
        if newest is not None and (created, int(run.get("id") or 0)) < newest:
            continue  # a newer same-head run of this workflow supersedes this one
        classification = "unexpected_required_cancellation"
        if not is_protected:
            # LAZY jobs probe — deliberately the LAST guard, reached only by
            # advisory candidates that survived every cheap guard above, so
            # each 20-minute pass spends at most one extra API call per
            # surviving candidate (not per --max-runs run scanned).
            assert fetch_jobs is not None  # guarded above
            jobs = fetch_jobs(int(run.get("id") or 0))
            if jobs is None or not run_never_executed(jobs):
                # Probe failed (fail closed: cannot PROVE it never executed)
                # or the run genuinely started before cancellation — an
                # in-flight advisory cancellation is not this guardian's to
                # undo.
                continue
            classification = "queued_phase_advisory_displacement"
        reruns.append(
            {
                "run_id": int(run.get("id") or 0),
                "workflow": str(run.get("name", "")).strip(),
                "branch": branch,
                "sha": sha,
                "created_at": str(run.get("created_at", "")),
                "classification": classification,
            }
        )
    return reruns


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Re-run externally cancelled PR workflow runs once"
    )
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY", ""),
        help="GitHub repository in OWNER/REPO format",
    )
    parser.add_argument(
        "--max-runs",
        type=int,
        default=300,
        help="Maximum recent workflow runs to inspect",
    )
    parser.add_argument(
        "--ttl-hours",
        type=float,
        default=6.0,
        help="Only rerun cancellations younger than this many hours",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually request reruns (default: dry-run report only)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.repo:
        print("--repo is required (or set GITHUB_REPOSITORY)", file=sys.stderr)
        return 2
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    if not token:
        print("GITHUB_TOKEN (or GH_TOKEN) is required", file=sys.stderr)
        return 2
    protected_paths = load_protected_manifest()
    if not protected_paths:
        # Fail closed AND loud: a permanently disarmed guardian must never
        # look green on the schedule (#9133 claude P3 r7).
        print("protected manifest empty/unreadable; failing closed (no reruns)", file=sys.stderr)
        print(json.dumps({"repo": args.repo, "rerun_count": 0, "reruns": []}, indent=2))
        return 2
    client = GitHubClient(args.repo, token)
    open_pulls, pr_scan_truncated = client.list_open_pulls()
    runs, run_scan_truncated = client.list_recent_workflow_runs(args.max_runs)
    if run_scan_truncated:
        print(
            "warning: workflow-run scan hit --max-runs; some protected "
            "cancelled runs may be missed this pass",
            file=sys.stderr,
        )
    if pr_scan_truncated:
        print(
            "warning: open-PR scan hit the pagination cap; some protected "
            "cancelled runs may be missed this pass",
            file=sys.stderr,
        )
    active_head_pairs = compute_active_head_pairs(open_pulls)
    open_pr_numbers = {int(pr.get("number") or 0) for pr in open_pulls if not bool(pr.get("draft"))}

    def fetch_jobs(run_id: int) -> list[dict[str, Any]] | None:
        try:
            return client.list_run_jobs(run_id)
        except GitHubApiError as exc:
            # Fail CLOSED per run: without a readable jobs probe we cannot
            # prove the run never executed, so it stays cancelled — but loud,
            # so a permanently broken probe never looks green on schedule.
            print(f"jobs probe failed for run {run_id}: {exc}", file=sys.stderr)
            return None

    reruns = compute_reruns(
        runs,
        active_head_pairs=active_head_pairs,
        now=datetime.now(timezone.utc),
        ttl_hours=args.ttl_hours,
        protected_paths=protected_paths,
        open_pr_numbers=open_pr_numbers,
        fetch_jobs=fetch_jobs,
    )
    apply_failures = 0
    for item in reruns:
        if args.apply:
            ok, detail = client.rerun_workflow_run(item["run_id"])
            item["applied"] = ok
            item["detail"] = detail
            if not ok:
                apply_failures += 1
        else:
            item["applied"] = False
            item["detail"] = "dry-run"
    print(
        json.dumps(
            {
                "repo": args.repo,
                "rerun_count": len(reruns),
                "open_pr_scan_truncated": pr_scan_truncated,
                "run_scan_truncated": run_scan_truncated,
                "apply_failures": apply_failures,
                "reruns": reruns,
            },
            indent=2,
        )
    )
    if apply_failures:
        # Fail LOUD: if actions:write is missing or GitHub rejects reruns, a
        # green scheduled run would hide the very regression this guardian
        # exists to repair (#9133 openai P3).
        print(f"{apply_failures} rerun request(s) failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
