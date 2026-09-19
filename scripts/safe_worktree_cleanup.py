#!/usr/bin/env python3
"""Guarded worktree inspection and cleanup for ad-hoc side branches."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import codex_worktree_autopilot as autopilot

BRANCH_LOOKUP_FAILED = "__branch_lookup_failed__"
DEFAULT_GIT_TIMEOUT_SECONDS = float(os.environ.get("SAFE_WORKTREE_CLEANUP_GIT_TIMEOUT", "20"))
DEFAULT_GH_TIMEOUT_SECONDS = float(os.environ.get("SAFE_WORKTREE_CLEANUP_GH_TIMEOUT", "20"))
DEFAULT_PATCH_EQUIV_TIMEOUT_SECONDS = int(
    float(os.environ.get("SAFE_WORKTREE_CLEANUP_PATCH_EQUIV_TIMEOUT", "45"))
)


@dataclass
class WorktreeInspection:
    path: str
    exists: bool
    tracked_worktree: bool
    branch: str | None
    active_session: bool
    lock_files: list[str]
    dirty: bool
    unique_commits_ahead: int
    ahead_lookup_failed: bool
    patch_equivalent_to_origin_main: bool
    patch_equivalence_lookup_failed: bool
    open_prs: list[dict[str, Any]]
    pr_lookup_failed: bool
    blockers: list[str]


_BLOCKER_DETAILS: dict[str, tuple[str, str, str]] = {
    "missing_path": (
        "absent",
        "Path no longer exists; there is nothing for this helper to remove.",
        "verify registry state separately before pruning metadata",
    ),
    "active_session": (
        "owned",
        "An active session marker was detected for this worktree.",
        "preserve and route cleanup through the live owner",
    ),
    "dirty_worktree": (
        "unsafe_to_delete",
        "The worktree has uncommitted changes or git status could not prove cleanliness.",
        "preserve until dirty state is harvested, discarded by owner, or independently proven safe",
    ),
    "branch_ahead_of_origin_main": (
        "unsafe_to_delete",
        "The branch has commits not proven present or patch-equivalent on origin/main.",
        "harvest or reconcile branch value before cleanup",
    ),
    "patch_equivalence_lookup_failed": (
        "unknown",
        "Patch-equivalence lookup failed, so duplicate/harvested status is unproven.",
        "rerun inspection when patch-equivalence helper is healthy",
    ),
    "branch_lookup_failed": (
        "unknown",
        "Branch lookup timed out or failed, so ownership and value checks are incomplete.",
        "preserve until branch identity can be recovered",
    ),
    "open_pr": (
        "referenced",
        "A live open PR references this branch.",
        "preserve until the PR is merged, closed, or explicitly superseded",
    ),
    "ahead_lookup_failed": (
        "unknown",
        "Ahead/behind lookup failed, so unique-commit status is unproven.",
        "preserve until git history lookup succeeds",
    ),
    "pr_lookup_failed": (
        "unknown",
        "Open-PR lookup failed while the branch may still contain unique work.",
        "preserve until GitHub lookup succeeds or local proof is sufficient",
    ),
}


def cleanup_safety(inspection: WorktreeInspection) -> dict[str, Any]:
    """Return structured deletion-safety diagnostics for cleanup agents.

    ``blockers`` remains the stable fail-closed contract.  This derived
    payload explains *why* each blocker matters and classifies clear cases
    such as owned, harvested, stale, referenced, and unsafe-to-delete.
    """

    blocker_details = [
        {
            "blocker": blocker,
            "category": _BLOCKER_DETAILS.get(blocker, ("unknown", "", ""))[0],
            "reason": _BLOCKER_DETAILS.get(blocker, ("unknown", "Unclassified blocker.", ""))[1],
            "next_action": _BLOCKER_DETAILS.get(
                blocker, ("unknown", "", "preserve until manually reviewed")
            )[2],
        }
        for blocker in inspection.blockers
    ]
    categories = {detail["category"] for detail in blocker_details}

    if "owned" in categories:
        classification = "owned"
        decision = "preserve"
    elif "unsafe_to_delete" in categories:
        classification = "unsafe_to_delete"
        decision = "preserve"
    elif "unknown" in categories:
        classification = "unknown_preserve"
        decision = "preserve"
    elif "referenced" in categories:
        classification = "referenced_preserve"
        decision = "preserve"
    elif "absent" in categories:
        classification = "absent_noop"
        decision = "noop"
    elif inspection.patch_equivalent_to_origin_main:
        classification = "harvested_or_duplicate"
        decision = "cleanup_candidate"
    elif inspection.branch and inspection.unique_commits_ahead == 0:
        classification = "stale_or_merged"
        decision = "cleanup_candidate"
    elif inspection.exists and not inspection.tracked_worktree:
        classification = "untracked_residue"
        decision = "cleanup_candidate"
    else:
        classification = "cleanup_candidate"
        decision = "cleanup_candidate"

    return {
        "removable": not inspection.blockers,
        "classification": classification,
        "decision": decision,
        "blocker_details": blocker_details,
        "signals": {
            "exists": inspection.exists,
            "tracked_worktree": inspection.tracked_worktree,
            "branch": inspection.branch,
            "active_session": inspection.active_session,
            "lock_files": inspection.lock_files,
            "dirty": inspection.dirty,
            "unique_commits_ahead": inspection.unique_commits_ahead,
            "ahead_lookup_failed": inspection.ahead_lookup_failed,
            "patch_equivalent_to_origin_main": inspection.patch_equivalent_to_origin_main,
            "patch_equivalence_lookup_failed": inspection.patch_equivalence_lookup_failed,
            "open_pr_count": len(inspection.open_prs),
            "pr_lookup_failed": inspection.pr_lookup_failed,
        },
    }


def _active_lock_files(path: Path) -> list[str]:
    return [
        name
        for name in (".claude-session-active", ".codex_session_active", ".nomic-session-active")
        if (path / name).exists()
    ]


def _get_worktree_entry(repo_root: Path, path: Path) -> autopilot.WorktreeEntry | None:
    target = path.resolve()
    for entry in _get_worktree_entries(repo_root):
        if entry.path.resolve() == target:
            return entry
    return None


def _get_worktree_entries(repo_root: Path) -> list[autopilot.WorktreeEntry]:
    try:
        proc = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
            timeout=DEFAULT_GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return []
    if proc.returncode != 0:
        return []
    return autopilot._parse_worktree_porcelain(proc.stdout)


def _branch_for_path(path: Path, entry: autopilot.WorktreeEntry | None) -> str | None:
    if entry and entry.branch:
        return entry.branch
    if not path.exists():
        return None
    if not (path / ".git").exists():
        return None
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=path,
            text=True,
            capture_output=True,
            check=False,
            timeout=DEFAULT_GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return BRANCH_LOOKUP_FAILED
    if proc.returncode != 0:
        return None
    branch = proc.stdout.strip()
    return None if not branch or branch == "HEAD" else branch


def _lookup_open_prs(repo_root: Path, branch: str | None) -> tuple[list[dict[str, Any]], bool]:
    if not branch:
        return [], False
    try:
        proc = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--state",
                "open",
                "--head",
                branch,
                "--json",
                "number,title,url",
            ],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
            timeout=DEFAULT_GH_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return [], True
    if proc.returncode != 0:
        return [], True
    try:
        payload = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return [], True
    if not isinstance(payload, list):
        return [], True
    return payload, False


_WRAPPER_SENTINEL_FILENAMES = frozenset(
    {
        ".claude-session-anchor",
        ".codex-session-anchor",
        ".codex-session",
        ".droid-session-anchor",
        ".session-anchor",
    }
)


def _is_empty_nested_wrapper(path: Path) -> bool:
    if not path.is_dir():
        return False
    try:
        has_any_file = False
        for entry in path.rglob("*"):
            if entry.is_file():
                has_any_file = True
                if entry.name not in _WRAPPER_SENTINEL_FILENAMES:
                    return False
        return has_any_file
    except OSError:
        return False


def _worktree_is_dirty(path: Path) -> bool:
    if not path.exists():
        return False
    if _is_empty_nested_wrapper(path):
        return False
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=path,
            text=True,
            capture_output=True,
            check=False,
            timeout=DEFAULT_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        # A failed inspection is not evidence that local work is absent.
        return True
    if proc.returncode != 0:
        return True
    return bool(proc.stdout.strip())


def _unique_commits_ahead_of_main(
    repo_root: Path,
    branch: str | None,
) -> tuple[int, bool]:
    if not branch:
        return 0, False
    if branch == BRANCH_LOOKUP_FAILED:
        return 0, True
    try:
        proc = subprocess.run(
            ["git", "rev-list", "--count", f"origin/main..{branch}"],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
            timeout=DEFAULT_GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return 0, True
    if proc.returncode != 0:
        return 0, True
    try:
        return int(proc.stdout.strip() or "0"), False
    except ValueError:
        return 0, True


def _patch_equivalent_to_main(repo_root: Path, branch: str | None) -> tuple[bool, bool]:
    if not branch:
        return False, False
    try:
        from audit_codex_branch_backlog import is_patch_equivalent
    except Exception:
        return False, True
    try:
        return (
            is_patch_equivalent(
                repo_root,
                "origin/main",
                branch,
                timeout=DEFAULT_PATCH_EQUIV_TIMEOUT_SECONDS,
            ),
            False,
        )
    except subprocess.TimeoutExpired:
        return False, True


def _pr_lookup_failure_blocks(
    branch: str | None,
    *,
    unique_commits_ahead: int,
    ahead_lookup_failed: bool,
    patch_equivalent_to_main: bool,
) -> bool:
    if not branch:
        return False
    if ahead_lookup_failed:
        return True
    if patch_equivalent_to_main:
        return False
    return unique_commits_ahead > 0


def inspect_worktree(
    repo_root: Path, path: Path, *, branch_override: str | None = None
) -> WorktreeInspection:
    path = path.resolve()
    exists = path.exists()
    entry = _get_worktree_entry(repo_root, path)
    tracked_worktree = entry is not None
    branch = branch_override or _branch_for_path(path, entry)
    active_session = exists and autopilot._has_active_session(path)
    lock_files = _active_lock_files(path) if exists else []
    dirty = _worktree_is_dirty(path) if exists else False
    unique_commits_ahead, ahead_lookup_failed = _unique_commits_ahead_of_main(repo_root, branch)
    patch_equivalent_to_main = False
    patch_equivalence_lookup_failed = False
    if branch and unique_commits_ahead > 0 and not ahead_lookup_failed and not dirty:
        patch_equivalent_to_main, patch_equivalence_lookup_failed = _patch_equivalent_to_main(
            repo_root, branch
        )
    open_prs, pr_lookup_failed = _lookup_open_prs(repo_root, branch)

    blockers: list[str] = []
    if not exists:
        blockers.append("missing_path")
    if active_session:
        blockers.append("active_session")
    if dirty:
        blockers.append("dirty_worktree")
    if unique_commits_ahead > 0 and not patch_equivalent_to_main:
        blockers.append("branch_ahead_of_origin_main")
    if patch_equivalence_lookup_failed:
        blockers.append("patch_equivalence_lookup_failed")
    if branch == BRANCH_LOOKUP_FAILED:
        blockers.append("branch_lookup_failed")
    if open_prs:
        blockers.append("open_pr")
    if branch and ahead_lookup_failed:
        blockers.append("ahead_lookup_failed")
    if pr_lookup_failed and _pr_lookup_failure_blocks(
        branch,
        unique_commits_ahead=unique_commits_ahead,
        ahead_lookup_failed=ahead_lookup_failed,
        patch_equivalent_to_main=patch_equivalent_to_main,
    ):
        blockers.append("pr_lookup_failed")

    return WorktreeInspection(
        path=str(path),
        exists=exists,
        tracked_worktree=tracked_worktree,
        branch=branch,
        active_session=active_session,
        lock_files=lock_files,
        dirty=dirty,
        unique_commits_ahead=unique_commits_ahead,
        ahead_lookup_failed=ahead_lookup_failed,
        patch_equivalent_to_origin_main=patch_equivalent_to_main,
        patch_equivalence_lookup_failed=patch_equivalence_lookup_failed,
        open_prs=open_prs,
        pr_lookup_failed=pr_lookup_failed,
        blockers=blockers,
    )


def _print_inspection(inspection: WorktreeInspection, *, as_json: bool) -> None:
    payload = asdict(inspection)
    payload["removable"] = not inspection.blockers
    payload["cleanup_safety"] = cleanup_safety(inspection)
    if as_json:
        print(json.dumps(payload, indent=2))
        return

    print(f"path: {inspection.path}")
    print(f"exists: {inspection.exists}")
    print(f"tracked_worktree: {inspection.tracked_worktree}")
    print(f"branch: {inspection.branch or '-'}")
    print(f"active_session: {inspection.active_session}")
    if inspection.lock_files:
        print(f"lock_files: {', '.join(inspection.lock_files)}")
    print(f"dirty: {inspection.dirty}")
    if inspection.branch:
        print(f"unique_commits_ahead: {inspection.unique_commits_ahead}")
        print(f"ahead_lookup_failed: {inspection.ahead_lookup_failed}")
        print(f"patch_equivalent_to_origin_main: {inspection.patch_equivalent_to_origin_main}")
        print(f"patch_equivalence_lookup_failed: {inspection.patch_equivalence_lookup_failed}")
    print(f"open_prs: {len(inspection.open_prs)}")
    if inspection.open_prs:
        for pr in inspection.open_prs:
            print(f"  - #{pr.get('number')} {pr.get('title')} :: {pr.get('url')}")
    print(f"removable: {not inspection.blockers}")
    safety = cleanup_safety(inspection)
    print(f"cleanup_classification: {safety['classification']}")
    print(f"cleanup_decision: {safety['decision']}")
    if inspection.blockers:
        print("blockers:")
        for detail in safety["blocker_details"]:
            print(f"  - {detail['blocker']} [{detail['category']}]: {detail['next_action']}")


def _delete_branch(repo_root: Path, branch: str) -> bool:
    if not autopilot._branch_exists(repo_root, branch):
        return True
    try:
        proc = subprocess.run(
            ["git", "branch", "-D", branch],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
            timeout=DEFAULT_GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return False
    return proc.returncode == 0


def _path_still_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _residual_paths(path: Path, *, limit: int = 50) -> list[str]:
    """Return a bounded list of residual entries under a failed purge path."""

    if not _path_still_exists(path):
        return []
    if path.is_file() or path.is_symlink():
        return [path.name]
    residuals: list[str] = []
    pending = [path]
    while pending:
        current = pending.pop()
        try:
            entries = current.iterdir()
            for entry in entries:
                residuals.append(str(entry.relative_to(path)))
                if entry.is_dir() and not entry.is_symlink():
                    pending.append(entry)
                if len(residuals) >= limit:
                    residuals.append("...")
                    return residuals
        except OSError:
            if residuals:
                residuals.append("<lookup_failed>")
                return residuals
            return ["<lookup_failed>"]
    return residuals or ["."]


def _purge_residual_path(path: Path) -> tuple[bool, str | None, list[str]]:
    """Delete an untracked residue path and report truthfully if anything remains."""

    if not _path_still_exists(path):
        return True, None, []
    purge_error: str | None = None
    try:
        if path.is_file() or path.is_symlink():
            path.unlink()
        else:
            shutil.rmtree(path)
    except OSError as exc:
        purge_error = str(exc)
    residuals = _residual_paths(path)
    path_purged = not _path_still_exists(path)
    if path_purged:
        purge_error = None
    return path_purged, purge_error, residuals


def remove_worktree(
    repo_root: Path,
    inspection: WorktreeInspection,
    *,
    delete_branch: bool,
    purge_path: bool,
    force: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": inspection.path,
        "branch": inspection.branch,
        "removed": False,
        "branch_deleted": False,
        "path_purged": False,
        "requires_purge_path": False,
        "git_remove_failed": False,
        "git_worktree_removed": False,
        "recovery_action": None,
        "residual_paths": [],
        "purge_error": None,
        "blockers": list(inspection.blockers),
        "cleanup_safety": cleanup_safety(inspection),
    }
    path = Path(inspection.path)
    if inspection.blockers and not force:
        result["status"] = "blocked"
        return result

    if inspection.tracked_worktree:
        try:
            proc = subprocess.run(
                ["git", "worktree", "remove", "--force", inspection.path],
                cwd=repo_root,
                text=True,
                capture_output=True,
                check=False,
                timeout=DEFAULT_GIT_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            result["status"] = "remove_failed"
            result["git_remove_failed"] = True
            result["stderr"] = f"git worktree remove timed out after {exc.timeout}s"
            result["recovery_action"] = (
                "git worktree remove timed out; rerun inspect before retrying cleanup"
            )
            return result
        if proc.returncode != 0:
            result["status"] = "remove_failed"
            result["git_remove_failed"] = True
            result["stderr"] = proc.stderr.strip()
            result["recovery_action"] = (
                "git worktree remove failed; rerun inspect before retrying cleanup"
            )
            if not purge_path:
                return result
        else:
            result["removed"] = True
            result["status"] = "removed"
            result["git_worktree_removed"] = True
    else:
        result["status"] = "untracked_path"
        if not purge_path:
            result["requires_purge_path"] = True
            result["recovery_action"] = (
                "rerun remove with --purge-path only after a fresh inspect returns "
                "removable=true, blockers=[], dirty=false, active_session=false, "
                "and open_prs=[] for this exact path"
            )
            return result

    if _path_still_exists(path) and purge_path:
        path_purged, purge_error, residuals = _purge_residual_path(path)
        result["path_purged"] = path_purged
        result["residual_paths"] = residuals
        if purge_error:
            result["purge_error"] = purge_error
        if result["path_purged"]:
            if result["git_remove_failed"]:
                result["status"] = "remove_failed_path_purged"
                result["removed"] = False
                result["recovery_action"] = (
                    "filesystem path was purged, but git worktree remove failed; "
                    "rerun inspect and reconcile git worktree metadata before deleting "
                    "the branch or treating cleanup as complete"
                )
            else:
                result["removed"] = True
        else:
            if result["git_remove_failed"]:
                result["status"] = "remove_failed_purge_incomplete"
            else:
                result["status"] = "purge_incomplete"
            result["removed"] = False
            result["recovery_action"] = (
                "path was not fully removed; inspect residual_paths and rerun cleanup "
                "only after the remaining files are proven disposable"
            )

    if delete_branch and inspection.branch and result.get("removed"):
        result["branch_deleted"] = _delete_branch(repo_root, inspection.branch)

    if result.get("status") in {"removed", "untracked_path"} and not result["removed"]:
        result["status"] = "partial"
    elif result.get("status") == "untracked_path" and result["removed"]:
        result["status"] = "purged"

    return result


def _repo_root_from_arg(repo: str) -> Path:
    return autopilot._repo_root_from(Path(repo))


def cmd_inspect(args: argparse.Namespace) -> int:
    repo_root = _repo_root_from_arg(args.repo)
    inspection = inspect_worktree(repo_root, Path(args.path), branch_override=args.branch)
    _print_inspection(inspection, as_json=args.json)
    return 0 if not inspection.blockers else 1


def cmd_remove(args: argparse.Namespace) -> int:
    repo_root = _repo_root_from_arg(args.repo)
    inspection = inspect_worktree(repo_root, Path(args.path), branch_override=args.branch)
    result = remove_worktree(
        repo_root,
        inspection,
        delete_branch=args.delete_branch,
        purge_path=args.purge_path,
        force=args.force,
    )
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps(result, indent=2))
    status = str(result.get("status", ""))
    if status in {
        "blocked",
        "remove_failed",
        "remove_failed_path_purged",
        "remove_failed_purge_incomplete",
        "untracked_path",
        "partial",
        "purge_incomplete",
    }:
        return 1
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect and safely remove ad-hoc worktrees.")
    parser.add_argument("--repo", default=".", help="Path inside the target repository")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser(
        "inspect", help="Inspect a worktree for active-session / open-PR blockers"
    )
    inspect_parser.add_argument("path", help="Worktree path to inspect")
    inspect_parser.add_argument(
        "--branch", help="Override the branch name for orphaned or partially deleted paths"
    )
    inspect_parser.add_argument("--json", action="store_true")
    inspect_parser.set_defaults(func=cmd_inspect)

    remove_parser = subparsers.add_parser(
        "remove", help="Safely remove a worktree if no blockers exist"
    )
    remove_parser.add_argument("path", help="Worktree path to remove")
    remove_parser.add_argument(
        "--branch", help="Override the branch name for orphaned or partially deleted paths"
    )
    remove_parser.add_argument(
        "--delete-branch",
        action="store_true",
        help="Delete the local branch after removing the worktree",
    )
    remove_parser.add_argument(
        "--purge-path",
        action="store_true",
        help=(
            "Delete the filesystem path after safety gates pass; required for untracked "
            "residue and verified after removal"
        ),
    )
    remove_parser.add_argument(
        "--force", action="store_true", help="Bypass active-session/open-PR blockers"
    )
    remove_parser.add_argument("--json", action="store_true")
    remove_parser.set_defaults(func=cmd_remove)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
