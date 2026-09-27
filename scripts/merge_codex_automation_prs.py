#!/usr/bin/env python3
"""Merge clearly safe codex automation PRs from a normal user shell.

Codex desktop automations can inspect and summarize PRs from their sandboxed
runtime, but reliable merging should happen from a normal user environment
where ``gh`` auth and network access are available. This helper only auto-
merges obviously safe codex PRs and leaves anything sensitive or ambiguous for
the in-app PR shepherd or a human.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SAFE_CHECK_CONCLUSIONS = {"success", "neutral", "skipped"}
SENSITIVE_PATH_TOKENS = (
    "/auth/",
    "/billing/",
    "secret",
    "kubernetes/",
    "helm/",
    "terraform/",
    ".github/workflows/",
    "deploy",
)
FULL_HEAD_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class PullRequestSnapshot:
    number: int
    title: str
    head_ref: str
    head_sha: str
    is_draft: bool
    mergeable: str
    body: str
    url: str
    changed_files: list[str]
    status_rollup: list[dict[str, Any]]
    files_snapshot_error: str | None = None


@dataclass(frozen=True)
class MergeDecision:
    number: int
    title: str
    head_ref: str
    head_sha: str
    eligible: bool
    reason: str
    url: str
    changed_files: list[str]


def _run(
    args: list[str],
    *,
    cwd: Path,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=check,
    )


def _repo_root(path: Path) -> Path:
    proc = _run(["git", "rev-parse", "--show-toplevel"], cwd=path)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "not a git repository")
    return Path(proc.stdout.strip()).resolve()


def _ensure_gh_auth(repo_root: Path) -> None:
    proc = _run(["gh", "auth", "status"], cwd=repo_root)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "gh auth failed")


def _open_codex_prs(repo_root: Path, repo: str, limit: int) -> list[dict[str, Any]]:
    proc = _run(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--limit",
            str(limit),
            "--json",
            "number,headRefName",
        ],
        cwd=repo_root,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "failed to list open PRs")
    payload = json.loads(proc.stdout or "[]")
    return [
        item
        for item in payload
        if isinstance(item, dict) and str(item.get("headRefName", "")).startswith("codex/")
    ]


def _pr_snapshot(repo_root: Path, repo: str, number: int) -> dict[str, Any]:
    proc = _run(
        [
            "gh",
            "pr",
            "view",
            str(number),
            "--repo",
            repo,
            "--json",
            "number,title,headRefName,headRefOid,isDraft,mergeable,body,url,changedFiles,files,statusCheckRollup",
        ],
        cwd=repo_root,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"failed to inspect PR #{number}")
    payload = json.loads(proc.stdout or "{}")
    if not isinstance(payload, dict):
        raise RuntimeError(f"unexpected PR payload for #{number}")
    return payload


def collect_pull_requests(repo_root: Path, repo: str, *, limit: int) -> list[PullRequestSnapshot]:
    snapshots: list[PullRequestSnapshot] = []
    for pr in _open_codex_prs(repo_root, repo, limit):
        number = int(pr["number"])
        metadata = _pr_snapshot(repo_root, repo, number)
        snapshot_number = metadata.get("number")
        if isinstance(snapshot_number, bool) or not isinstance(snapshot_number, int):
            raise RuntimeError(f"missing PR number in snapshot for #{number}")
        if snapshot_number != number:
            raise RuntimeError(
                f"snapshot PR number mismatch: requested #{number}, got #{snapshot_number}"
            )
        files = metadata.get("files")
        changed_file_count = metadata.get("changedFiles")
        changed_files: list[str] = []
        files_snapshot_error: str | None = None
        if not isinstance(files, list):
            files_snapshot_error = f"unexpected files payload for PR #{number}"
        elif (
            isinstance(changed_file_count, bool)
            or not isinstance(changed_file_count, int)
            or changed_file_count < 0
            or changed_file_count != len(files)
        ):
            files_snapshot_error = (
                f"incomplete or malformed files snapshot for PR #{number}: "
                f"changedFiles={changed_file_count!r}, returned_entries={len(files)}"
            )
        else:
            for index, item in enumerate(files):
                if not isinstance(item, Mapping):
                    files_snapshot_error = f"malformed file entry for PR #{number} at index {index}"
                    break
                path = item.get("path")
                if not isinstance(path, str) or not path.strip():
                    files_snapshot_error = (
                        f"malformed file entry for PR #{number} at index {index}: "
                        "path must be a non-empty string"
                    )
                    break
                changed_files.append(path)
            if files_snapshot_error:
                changed_files = []
        snapshots.append(
            PullRequestSnapshot(
                number=snapshot_number,
                title=str(metadata.get("title", "")),
                head_ref=str(metadata.get("headRefName", "")),
                head_sha=str(metadata.get("headRefOid", "")),
                is_draft=bool(metadata.get("isDraft", False)),
                mergeable=str(metadata.get("mergeable", "")),
                body=str(metadata.get("body", "") or ""),
                url=str(metadata.get("url", "")),
                changed_files=changed_files,
                status_rollup=list(metadata.get("statusCheckRollup") or []),
                files_snapshot_error=files_snapshot_error,
            )
        )
    return snapshots


def _status_reason(items: list[dict[str, Any]]) -> str:
    if not items:
        return "no_status_checks"
    for item in items:
        status = str(item.get("status", "") or "").lower()
        conclusion = str(item.get("conclusion", "") or "").lower()
        if status != "completed":
            return "checks_pending"
        if conclusion not in SAFE_CHECK_CONCLUSIONS:
            return "checks_failed"
    return "checks_clear"


def _path_is_sensitive(path: str) -> bool:
    lowered = f"/{path.lower().lstrip('/')}"
    return any(token in lowered for token in SENSITIVE_PATH_TOKENS)


def _has_validation_evidence(body: str) -> bool:
    lowered = body.lower()
    return "validation" in lowered or "validated" in lowered


def _is_full_head_sha(value: str) -> bool:
    return FULL_HEAD_SHA_RE.fullmatch(value) is not None


def select_mergeable_prs(
    pull_requests: list[PullRequestSnapshot],
    *,
    max_files: int = 6,
) -> list[MergeDecision]:
    decisions: list[MergeDecision] = []

    for pr in sorted(pull_requests, key=lambda item: item.number):
        reason = "eligible"
        if not pr.head_ref.startswith("codex/"):
            reason = "not_codex_branch"
        elif not _is_full_head_sha(pr.head_sha):
            reason = "invalid_head_sha"
        elif pr.files_snapshot_error:
            reason = "files_snapshot_incomplete"
        elif pr.is_draft:
            reason = "draft"
        elif pr.mergeable != "MERGEABLE":
            reason = "not_mergeable"
        else:
            checks_reason = _status_reason(pr.status_rollup)
            if checks_reason != "checks_clear":
                reason = checks_reason
            elif not pr.changed_files:
                reason = "no_changed_files"
            elif len(pr.changed_files) > max_files:
                reason = "too_many_files"
            elif any(_path_is_sensitive(path) for path in pr.changed_files):
                reason = "sensitive_paths"
            elif not _has_validation_evidence(pr.body):
                reason = "missing_validation"

        decisions.append(
            MergeDecision(
                number=pr.number,
                title=pr.title,
                head_ref=pr.head_ref,
                head_sha=pr.head_sha,
                eligible=reason == "eligible",
                reason=reason,
                url=pr.url,
                changed_files=pr.changed_files,
            )
        )

    return decisions


def _merge_pr(repo_root: Path, repo: str, number: int, head_sha: str) -> None:
    if not _is_full_head_sha(head_sha):
        raise RuntimeError(f"refusing to merge PR #{number}: missing or malformed head SHA")
    proc = _run(
        [
            "gh",
            "pr",
            "merge",
            str(number),
            "--repo",
            repo,
            "--squash",
            "--admin",
            "--match-head-commit",
            head_sha,
            "--delete-branch=false",
        ],
        cwd=repo_root,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            proc.stderr.strip() or proc.stdout.strip() or f"failed to merge #{number}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Merge clearly safe codex automation PRs from a normal shell."
    )
    parser.add_argument(
        "--repo",
        default="synaptent/aragora",
        help="GitHub repository in OWNER/NAME form (default: %(default)s)",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Path inside the repository to inspect (default: current directory)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of open codex PRs to inspect and merge (default: %(default)s)",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=6,
        help="Maximum changed files allowed for auto-merge (default: %(default)s)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually merge eligible PRs instead of only reporting decisions",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON decisions and actions",
    )
    args = parser.parse_args(argv)

    repo_root = _repo_root(Path(args.root).resolve())
    _ensure_gh_auth(repo_root)

    snapshots = collect_pull_requests(repo_root, args.repo, limit=args.limit)
    decisions = select_mergeable_prs(snapshots, max_files=args.max_files)
    merged_numbers: list[int] = []

    if args.apply:
        for decision in decisions:
            if not decision.eligible:
                continue
            _merge_pr(repo_root, args.repo, decision.number, decision.head_sha)
            merged_numbers.append(decision.number)

    if args.json:
        print(
            json.dumps(
                {
                    "repo": args.repo,
                    "inspected": len(decisions),
                    "merged": merged_numbers,
                    "decisions": [asdict(decision) for decision in decisions],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        for decision in decisions:
            status = "MERGED" if decision.number in merged_numbers else decision.reason
            print(f"#{decision.number} {decision.head_ref} {status} {decision.title}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - CLI guard
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
