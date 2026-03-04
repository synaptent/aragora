#!/usr/bin/env python3
"""Cancel stale PR workflow runs to reduce CI queue pressure.

Stale runs are queued/in-progress PR runs where:
- the run branch has no open active PR (closed branch), or
- the run SHA is not the latest head SHA for that open PR branch.

By default, draft PR branches are treated as inactive.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any
from urllib import error, parse, request


ACTIVE_RUN_STATUSES = {"queued", "in_progress", "requested", "waiting", "pending"}
PR_EVENTS = {"pull_request", "pull_request_target"}


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
    ) -> tuple[Any, request.addinfourl]:
        body: bytes | None = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")

        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "aragora-pr-stale-run-gc",
        }
        req = request.Request(url=url, data=body, headers=headers, method=method)
        try:
            resp = request.urlopen(req, timeout=30)
            raw = resp.read().decode("utf-8")
            parsed = json.loads(raw) if raw else {}
            return parsed, resp
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise GitHubApiError(
                f"GitHub API {method} {url} failed: {exc.code} {exc.reason}\n{details}"
            ) from exc

    def _api(self, path: str, query: dict[str, Any] | None = None) -> str:
        url = f"{self.api_base}{path}"
        if query:
            url += "?" + parse.urlencode(query, doseq=True)
        return url

    def get(self, path: str, query: dict[str, Any] | None = None) -> Any:
        data, _ = self._request_json("GET", self._api(path, query))
        return data

    def post(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        data, _ = self._request_json("POST", self._api(path), payload=payload)
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

    def list_open_pulls(self) -> list[dict[str, Any]]:
        pulls = self.paginate(
            f"/repos/{self.repo}/pulls",
            query={"state": "open", "per_page": 100},
            max_pages=5,
        )
        return [p for p in pulls if isinstance(p, dict)]

    def list_recent_workflow_runs(self, max_runs: int) -> list[dict[str, Any]]:
        runs = self.paginate(
            f"/repos/{self.repo}/actions/runs",
            query={"per_page": 100},
            max_pages=max(1, (max_runs + 99) // 100),
        )
        normalized = [r for r in runs if isinstance(r, dict)]
        return normalized[:max_runs]

    def cancel_workflow_run(self, run_id: int) -> tuple[bool, str]:
        try:
            self.post(f"/repos/{self.repo}/actions/runs/{run_id}/cancel")
            return True, "cancel_requested"
        except GitHubApiError as exc:
            message = str(exc)
            if "409" in message:
                return False, "already_completed"
            return False, message


def compute_active_head_map(
    open_pulls: list[dict[str, Any]],
    *,
    keep_draft_runs: bool,
) -> dict[str, str]:
    """Return branch -> head_sha for active PR heads."""
    active: dict[str, str] = {}
    for pr in open_pulls:
        if bool(pr.get("draft")) and not keep_draft_runs:
            continue
        head = pr.get("head", {})
        branch = str(head.get("ref", "")).strip()
        sha = str(head.get("sha", "")).strip()
        if branch and sha:
            active[branch] = sha
    return active


def compute_stale_runs(
    runs: list[dict[str, Any]],
    *,
    active_heads: dict[str, str],
    cancel_events: set[str],
) -> list[dict[str, Any]]:
    """Determine which runs are stale and should be cancelled."""
    stale: list[dict[str, Any]] = []
    for run in runs:
        event_name = str(run.get("event", "")).strip()
        status = str(run.get("status", "")).strip()
        if event_name not in cancel_events:
            continue
        if status not in ACTIVE_RUN_STATUSES:
            continue

        run_id = int(run.get("id") or run.get("databaseId"))
        branch = str(run.get("head_branch", "") or run.get("headBranch", "")).strip()
        sha = str(run.get("head_sha", "") or run.get("headSha", "")).strip()
        if not branch:
            stale.append(
                {"run_id": run_id, "reason": "missing-branch", "branch": branch, "sha": sha}
            )
            continue

        active_sha = active_heads.get(branch)
        if active_sha is None:
            stale.append(
                {
                    "run_id": run_id,
                    "reason": "no-active-pr-head",
                    "branch": branch,
                    "sha": sha,
                }
            )
            continue
        if active_sha != sha:
            stale.append(
                {
                    "run_id": run_id,
                    "reason": "stale-sha",
                    "branch": branch,
                    "sha": sha,
                    "active_sha": active_sha,
                }
            )
    return stale


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cancel stale PR workflow runs")
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
        "--keep-draft-runs",
        action="store_true",
        help="Treat draft PR branches as active and keep their runs",
    )
    parser.add_argument(
        "--events",
        default="pull_request,pull_request_target",
        help="Comma-separated run events to consider for cancellation",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print actions without cancelling")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.repo:
        print("--repo is required (or set GITHUB_REPOSITORY)", file=sys.stderr)
        return 1
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print("GITHUB_TOKEN is required", file=sys.stderr)
        return 1
    if args.max_runs < 1:
        print("--max-runs must be >= 1", file=sys.stderr)
        return 1

    cancel_events = {e.strip() for e in args.events.split(",") if e.strip()}
    if not cancel_events:
        cancel_events = set(PR_EVENTS)

    try:
        client = GitHubClient(repo=args.repo, token=token)
        open_pulls = client.list_open_pulls()
        active_heads = compute_active_head_map(
            open_pulls, keep_draft_runs=bool(args.keep_draft_runs)
        )
        runs = client.list_recent_workflow_runs(max_runs=args.max_runs)
        stale_runs = compute_stale_runs(
            runs, active_heads=active_heads, cancel_events=cancel_events
        )

        cancelled = 0
        failed = 0
        reasons: dict[str, int] = {}

        for run in stale_runs:
            reason = str(run["reason"])
            reasons[reason] = reasons.get(reason, 0) + 1
            if args.dry_run:
                continue
            ok, _msg = client.cancel_workflow_run(int(run["run_id"]))
            if ok:
                cancelled += 1
            else:
                failed += 1

        summary = {
            "open_prs_total": len(open_pulls),
            "active_heads_total": len(active_heads),
            "runs_scanned": len(runs),
            "stale_runs_found": len(stale_runs),
            "cancelled": cancelled,
            "failed_to_cancel": failed,
            "dry_run": bool(args.dry_run),
            "reasons": reasons,
        }
        print(json.dumps(summary))
        return 0
    except (GitHubApiError, ValueError) as exc:
        print(f"Stale-run GC error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
