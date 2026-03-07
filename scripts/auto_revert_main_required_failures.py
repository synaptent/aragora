#!/usr/bin/env python3
"""Auto-revert latest main commit when required checks fail.

Throughput-first safety model:
- do not block pushes/merges
- detect required-check failures quickly
- rollback the latest commit on main when required checks fail terminally
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any
from urllib import error, parse, request


DEFAULT_REQUIRED_CONTEXTS = [
    "lint",
    "typecheck",
    "sdk-parity",
    "Generate & Validate",
    "TypeScript SDK Type Check",
]
PASS_CONCLUSIONS = {"success", "neutral", "skipped"}
AUTO_REVERT_MARKER = "[auto-revert-required-checks]"


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
            "User-Agent": "aragora-main-required-auto-revert",
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

    def get_branch_head_sha(self, branch: str) -> str:
        data = self.get(f"/repos/{self.repo}/git/ref/heads/{branch}")
        obj = data.get("object", {}) if isinstance(data, dict) else {}
        return str(obj.get("sha", "")).strip()

    def get_commit(self, sha: str) -> dict[str, Any]:
        data = self.get(f"/repos/{self.repo}/commits/{sha}")
        if not isinstance(data, dict):
            raise GitHubApiError(f"Unexpected commit response type: {type(data)}")
        return data

    def list_check_runs(self, sha: str) -> list[dict[str, Any]]:
        page = 1
        out: list[dict[str, Any]] = []
        while True:
            data = self.get(
                f"/repos/{self.repo}/commits/{sha}/check-runs",
                query={"per_page": 100, "page": page},
            )
            runs = data.get("check_runs", []) if isinstance(data, dict) else []
            if not isinstance(runs, list):
                raise GitHubApiError("Invalid check-runs response shape")
            normalized = [r for r in runs if isinstance(r, dict)]
            out.extend(normalized)
            if len(normalized) < 100:
                break
            page += 1
            if page > 20:
                break
        return out

    def get_required_contexts(self, branch: str) -> list[str]:
        try:
            data = self.get(f"/repos/{self.repo}/branches/{branch}/protection")
        except GitHubApiError:
            return list(DEFAULT_REQUIRED_CONTEXTS)
        if not isinstance(data, dict):
            return list(DEFAULT_REQUIRED_CONTEXTS)
        checks = data.get("required_status_checks", {})
        if not isinstance(checks, dict):
            return list(DEFAULT_REQUIRED_CONTEXTS)
        contexts = checks.get("contexts", [])
        if not isinstance(contexts, list):
            return list(DEFAULT_REQUIRED_CONTEXTS)
        normalized = [str(c).strip() for c in contexts if str(c).strip()]
        return normalized or list(DEFAULT_REQUIRED_CONTEXTS)


def select_latest_check_runs(check_runs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Select latest check run per context name."""
    latest: dict[str, dict[str, Any]] = {}
    for run in check_runs:
        name = str(run.get("name", "")).strip()
        if not name:
            continue
        run_id = int(run.get("id", 0) or 0)
        current = latest.get(name)
        if current is None or int(current.get("id", 0) or 0) < run_id:
            latest[name] = run
    return latest


def evaluate_required_contexts(
    required_contexts: list[str],
    check_runs: list[dict[str, Any]],
) -> dict[str, list[str]]:
    """Classify required contexts into passed/pending/failed/missing buckets."""
    latest = select_latest_check_runs(check_runs)
    passed: list[str] = []
    pending: list[str] = []
    failed: list[str] = []
    missing: list[str] = []

    for context in required_contexts:
        run = latest.get(context)
        if run is None:
            missing.append(context)
            continue
        status = str(run.get("status", "")).strip().lower()
        conclusion = str(run.get("conclusion", "")).strip().lower()
        if status != "completed" or not conclusion:
            pending.append(context)
            continue
        if conclusion in PASS_CONCLUSIONS:
            passed.append(context)
        else:
            failed.append(f"{context}:{conclusion}")

    return {"passed": passed, "pending": pending, "failed": failed, "missing": missing}


def should_skip_commit_message(message: str) -> bool:
    msg = message.strip()
    if not msg:
        return False
    if msg.startswith("Revert "):
        return True
    if AUTO_REVERT_MARKER in msg:
        return True
    return False


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=False)


def _append_markers_to_last_commit(repo_path: Path) -> tuple[bool, str]:
    body_proc = _run(["git", "log", "-1", "--pretty=%B"], cwd=repo_path)
    if body_proc.returncode != 0:
        return False, body_proc.stderr.strip() or "failed to read commit message"
    body = body_proc.stdout.rstrip()
    if "[allow-direct-main]" not in body:
        body += "\n\n[allow-direct-main]"
    if "[auto-revert-required-checks]" not in body:
        body += "\n[auto-revert-required-checks]"
    amend_proc = _run(["git", "commit", "--amend", "-m", body], cwd=repo_path)
    if amend_proc.returncode != 0:
        return False, amend_proc.stderr.strip() or "failed to amend revert commit"
    return True, "amended"


def perform_revert(repo_path: Path, *, target_sha: str, base_branch: str) -> tuple[bool, str]:
    fetch_proc = _run(["git", "fetch", "origin", base_branch], cwd=repo_path)
    if fetch_proc.returncode != 0:
        return False, fetch_proc.stderr.strip() or "git fetch failed"

    checkout_proc = _run(
        ["git", "checkout", "-B", base_branch, f"origin/{base_branch}"],
        cwd=repo_path,
    )
    if checkout_proc.returncode != 0:
        return False, checkout_proc.stderr.strip() or "git checkout failed"

    head_proc = _run(["git", "rev-parse", "HEAD"], cwd=repo_path)
    if head_proc.returncode != 0:
        return False, head_proc.stderr.strip() or "git rev-parse failed"
    current_head = head_proc.stdout.strip()
    if current_head != target_sha:
        return True, f"skip_not_tip:{current_head}"

    parents_proc = _run(["git", "rev-list", "--parents", "-n", "1", target_sha], cwd=repo_path)
    if parents_proc.returncode != 0:
        return False, parents_proc.stderr.strip() or "failed to inspect commit parents"
    parts = parents_proc.stdout.strip().split()
    parent_count = max(0, len(parts) - 1)

    revert_cmd = ["git", "revert", "--no-edit", target_sha]
    if parent_count > 1:
        revert_cmd = ["git", "revert", "-m", "1", "--no-edit", target_sha]
    revert_proc = _run(revert_cmd, cwd=repo_path)
    if revert_proc.returncode != 0:
        stderr = revert_proc.stderr.strip()
        if "nothing to commit" in stderr.lower():
            return True, "already_reverted"
        return False, stderr or "git revert failed"

    ok, msg = _append_markers_to_last_commit(repo_path)
    if not ok:
        return False, msg

    push_proc = _run(["git", "push", "origin", f"HEAD:{base_branch}"], cwd=repo_path)
    if push_proc.returncode != 0:
        return False, push_proc.stderr.strip() or "git push failed"
    return True, "reverted_and_pushed"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Auto-revert main when required checks fail")
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY", ""),
        help="GitHub repository in OWNER/REPO format",
    )
    parser.add_argument("--base", default="main", help="Base branch to protect")
    parser.add_argument(
        "--sha",
        default=os.environ.get("GITHUB_SHA", "").strip(),
        help="Commit SHA to evaluate (defaults to GITHUB_SHA or current base head)",
    )
    parser.add_argument(
        "--repo-path",
        default=".",
        help="Local repository path for git revert/push operations",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report actions without reverting")
    return parser.parse_args(argv)


def _recent_auto_revert_exists(repo_path: Path, minutes: int = 10) -> bool:
    """Check if an auto-revert commit was made in the last *minutes* minutes."""
    result = _run(
        [
            "git",
            "log",
            f"--since={minutes} minutes ago",
            "-F",
            "--grep",
            AUTO_REVERT_MARKER,
            "--oneline",
        ],
        cwd=repo_path,
    )
    if result.returncode != 0:
        return False
    return bool(result.stdout.strip())


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.repo:
        print("--repo is required (or set GITHUB_REPOSITORY)", file=sys.stderr)
        return 1
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print("GITHUB_TOKEN is required", file=sys.stderr)
        return 1

    try:
        client = GitHubClient(repo=args.repo, token=token)
        main_head_sha = client.get_branch_head_sha(args.base)
        target_sha = args.sha or main_head_sha
        if not target_sha:
            print("No target SHA available; skipping.")
            return 0

        if target_sha != main_head_sha:
            print(
                json.dumps(
                    {
                        "action": "skip",
                        "reason": "target_not_branch_tip",
                        "target_sha": target_sha,
                        "branch_tip_sha": main_head_sha,
                    }
                )
            )
            return 0

        commit = client.get_commit(target_sha)
        message = str(commit.get("commit", {}).get("message", "")).strip()
        if should_skip_commit_message(message):
            print(
                json.dumps(
                    {
                        "action": "skip",
                        "reason": "commit_already_revert_or_marked",
                        "target_sha": target_sha,
                    }
                )
            )
            return 0

        required_contexts = client.get_required_contexts(args.base)
        check_runs = client.list_check_runs(target_sha)
        assessment = evaluate_required_contexts(required_contexts, check_runs)
        summary = {
            "target_sha": target_sha,
            "required_contexts": required_contexts,
            "assessment": assessment,
            "dry_run": bool(args.dry_run),
        }
        print(json.dumps(summary))

        if assessment["missing"] or assessment["pending"]:
            return 0
        if not assessment["failed"]:
            return 0
        if args.dry_run:
            return 0

        repo_path = Path(args.repo_path).resolve()
        if _recent_auto_revert_exists(repo_path):
            print(
                json.dumps(
                    {
                        "action": "skip",
                        "reason": "rate_limited_recent_revert",
                        "target_sha": target_sha,
                        "detail": "A revert was performed in the last 10 minutes; skipping to prevent flap loop",
                    }
                )
            )
            return 0

        ok, message = perform_revert(
            repo_path,
            target_sha=target_sha,
            base_branch=args.base,
        )
        if not ok:
            print(f"Auto-revert failed: {message}", file=sys.stderr)
            return 1
        print(json.dumps({"action": "revert", "result": message, "target_sha": target_sha}))
        return 0
    except (GitHubApiError, ValueError) as exc:
        print(f"Auto-revert error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
