#!/usr/bin/env python3
"""Codex worktree autopilot for high-churn multi-session development.

This utility automates the worktree lifecycle to reduce manual intervention
when concurrent sessions frequently mutate branch/worktree state.

Commands:
  ensure    Ensure a usable managed worktree exists (create if needed)
  reconcile Rebase managed worktrees onto origin/<base> when safe
  cleanup   Remove stale/expired managed worktrees and prune git metadata
  status    Show managed worktree/session state
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

UTC = timezone.utc


@dataclass
class WorktreeEntry:
    path: Path
    branch: str | None
    detached: bool = False


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _run_git(
    repo_root: Path,
    *args: str,
    cwd: Path | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=cwd or repo_root,
        text=True,
        capture_output=True,
        check=check,
    )


def _repo_root_from(path: Path) -> Path:
    proc = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Not a git repo: {path}")
    return Path(proc.stdout.strip()).resolve()


def _parse_worktree_porcelain(text: str) -> list[WorktreeEntry]:
    entries: list[WorktreeEntry] = []
    current_path: Path | None = None
    current_branch: str | None = None
    detached = False

    def flush() -> None:
        nonlocal current_path, current_branch, detached
        if current_path is not None:
            entries.append(
                WorktreeEntry(path=current_path, branch=current_branch, detached=detached)
            )
        current_path = None
        current_branch = None
        detached = False

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue
        if line.startswith("worktree "):
            flush()
            current_path = Path(line[len("worktree ") :]).resolve()
            continue
        if line.startswith("branch refs/heads/"):
            current_branch = line[len("branch refs/heads/") :]
            continue
        if line == "detached":
            detached = True
            continue

    flush()
    return entries


def _get_worktree_entries(repo_root: Path) -> list[WorktreeEntry]:
    proc = _run_git(repo_root, "worktree", "list", "--porcelain")
    if proc.returncode != 0:
        return []
    return _parse_worktree_porcelain(proc.stdout)


def _state_path(managed_root: Path) -> Path:
    return managed_root / "state.json"


def _load_state(state_file: Path) -> dict[str, Any]:
    if not state_file.exists():
        return {"version": 1, "updated_at": "", "sessions": []}
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "updated_at": "", "sessions": []}
    if not isinstance(data, dict):
        return {"version": 1, "updated_at": "", "sessions": []}
    data.setdefault("version", 1)
    data.setdefault("updated_at", "")
    data.setdefault("sessions", [])
    if not isinstance(data["sessions"], list):
        data["sessions"] = []
    return data


def _save_state(state_file: Path, state: dict[str, Any]) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = _utc_now().isoformat()
    state_file.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _session_key(session: dict[str, Any]) -> tuple[str, str]:
    return (str(session.get("agent", "")), str(session.get("session_id", "")))


def _upsert_session(state: dict[str, Any], session: dict[str, Any]) -> None:
    incoming = _session_key(session)
    sessions = state.get("sessions", [])
    for idx, existing in enumerate(sessions):
        if _session_key(existing) == incoming:
            sessions[idx] = session
            return
    sessions.append(session)


def _active_path_set(entries: list[WorktreeEntry]) -> set[str]:
    return {str(entry.path) for entry in entries}


def _prune_stale_state(
    state: dict[str, Any],
    active_paths: set[str],
) -> tuple[dict[str, Any], int]:
    pruned: list[dict[str, Any]] = []
    removed = 0
    for session in state.get("sessions", []):
        path = str(session.get("path", ""))
        if not path or not Path(path).exists() or path not in active_paths:
            removed += 1
            continue
        pruned.append(session)
    state["sessions"] = pruned
    return state, removed


def _branch_exists(repo_root: Path, branch: str) -> bool:
    proc = _run_git(repo_root, "rev-parse", "--verify", f"refs/heads/{branch}")
    return proc.returncode == 0


def _ensure_fetched(repo_root: Path, base: str) -> None:
    _run_git(repo_root, "fetch", "origin", base)


def _worktree_status(repo_root: Path, worktree: Path, base: str) -> dict[str, Any]:
    status_proc = _run_git(repo_root, "status", "--porcelain", cwd=worktree)
    dirty = bool(status_proc.stdout.strip())

    counts_proc = _run_git(
        repo_root, "rev-list", "--left-right", "--count", f"origin/{base}...HEAD", cwd=worktree
    )
    ahead = 0
    behind = 0
    if counts_proc.returncode == 0:
        parts = counts_proc.stdout.strip().split()
        if len(parts) == 2:
            behind = int(parts[0])
            ahead = int(parts[1])

    return {
        "dirty": dirty,
        "ahead": ahead,
        "behind": behind,
    }


def _integrate_worktree(
    repo_root: Path,
    worktree: Path,
    base: str,
    strategy: str,
) -> tuple[bool, str]:
    _ensure_fetched(repo_root, base)
    status = _worktree_status(repo_root, worktree, base)
    if status["dirty"]:
        return True, "skipped_dirty"
    if status["behind"] == 0:
        return True, "up_to_date"

    if strategy == "none":
        return True, "skipped_strategy_none"
    if strategy == "rebase":
        rebase_proc = _run_git(repo_root, "rebase", f"origin/{base}", cwd=worktree)
        if rebase_proc.returncode == 0:
            return True, "rebased"
        _run_git(repo_root, "rebase", "--abort", cwd=worktree)
        return False, "rebase_failed"
    if strategy == "ff-only":
        ff_proc = _run_git(repo_root, "merge", "--ff-only", f"origin/{base}", cwd=worktree)
        if ff_proc.returncode == 0:
            return True, "fast_forwarded"
        return False, "ff_only_failed"
    if strategy == "merge":
        merge_proc = _run_git(repo_root, "merge", "--no-edit", f"origin/{base}", cwd=worktree)
        if merge_proc.returncode == 0:
            return True, "merged"
        _run_git(repo_root, "merge", "--abort", cwd=worktree)
        return False, "merge_conflict"

    return False, "unknown_strategy"


def _choose_reusable_session(
    state: dict[str, Any],
    *,
    agent: str,
    session_id: str | None,
    active_paths: set[str],
) -> dict[str, Any] | None:
    sessions = state.get("sessions", [])
    candidates: list[dict[str, Any]] = []
    for s in sessions:
        if s.get("agent") != agent:
            continue
        if session_id and s.get("session_id") != session_id:
            continue
        path = str(s.get("path", ""))
        if not path or path not in active_paths:
            continue
        candidates.append(s)

    if not candidates:
        return None

    def sort_key(item: dict[str, Any]) -> str:
        return str(item.get("last_seen_at", item.get("created_at", "")))

    candidates.sort(key=sort_key, reverse=True)
    return candidates[0]


def _create_managed_worktree(
    repo_root: Path,
    managed_root: Path,
    *,
    agent: str,
    base: str,
    session_id: str | None,
) -> dict[str, Any]:
    _ensure_fetched(repo_root, base)
    now = _utc_now()
    token = uuid4().hex[:8]
    sid = session_id or f"{agent}-{now.strftime('%Y%m%d-%H%M%S')}-{token}"
    branch = f"codex/{sid}"
    while _branch_exists(repo_root, branch):
        branch = f"{branch}-{uuid4().hex[:4]}"
    worktree_path = (managed_root / sid).resolve()

    if worktree_path.exists():
        shutil.rmtree(worktree_path, ignore_errors=True)
    worktree_path.parent.mkdir(parents=True, exist_ok=True)

    source = f"origin/{base}"
    add_proc = _run_git(
        repo_root,
        "worktree",
        "add",
        "-b",
        branch,
        str(worktree_path),
        source,
    )
    if add_proc.returncode != 0:
        add_proc = _run_git(
            repo_root,
            "worktree",
            "add",
            "-b",
            branch,
            str(worktree_path),
            base,
        )
    if add_proc.returncode != 0:
        raise RuntimeError(add_proc.stderr.strip() or "git worktree add failed")

    return {
        "session_id": sid,
        "agent": agent,
        "branch": branch,
        "path": str(worktree_path),
        "base_branch": base,
        "created_at": now.isoformat(),
        "last_seen_at": now.isoformat(),
    }


def cmd_ensure(args: argparse.Namespace) -> int:
    repo_root = _repo_root_from(Path(args.repo))
    managed_root = (repo_root / args.managed_dir).resolve()
    state_file = _state_path(managed_root)

    entries = _get_worktree_entries(repo_root)
    active_paths = _active_path_set(entries)
    state = _load_state(state_file)
    state, _ = _prune_stale_state(state, active_paths)

    session: dict[str, Any] | None = None
    if not args.force_new:
        session = _choose_reusable_session(
            state,
            agent=args.agent,
            session_id=args.session_id,
            active_paths=active_paths,
        )

    created = False
    if session is None:
        session = _create_managed_worktree(
            repo_root,
            managed_root,
            agent=args.agent,
            base=args.base,
            session_id=args.session_id,
        )
        created = True
    else:
        session["last_seen_at"] = _utc_now().isoformat()
        if args.reconcile:
            session_path = Path(session["path"])
            if session_path.exists() and _has_active_session(session_path):
                ok, status = True, "skipped_active_session"
            else:
                ok, status = _integrate_worktree(
                    repo_root,
                    session_path,
                    args.base,
                    args.strategy,
                )
            session["reconcile_status"] = status
            if not ok:
                # Fallback: auto-create replacement worktree if integration fails.
                session = _create_managed_worktree(
                    repo_root,
                    managed_root,
                    agent=args.agent,
                    base=args.base,
                    session_id=None,
                )
                created = True

    _upsert_session(state, session)
    _save_state(state_file, state)

    payload = {
        "ok": True,
        "created": created,
        "session": session,
        "repo_root": str(repo_root),
    }

    if args.print_path:
        print(session["path"])
    elif args.json:
        print(json.dumps(payload, indent=2))
    else:
        action = "created" if created else "reused"
        print(f"[{action}] {session['branch']}")
        print(f"  path: {session['path']}")
        print(f"  repo: {repo_root}")
    return 0


def _iter_target_sessions(
    state: dict[str, Any],
    *,
    active_paths: set[str],
    target_path: str | None,
) -> list[dict[str, Any]]:
    sessions = []
    target_norm = str(Path(target_path).resolve()) if target_path else None
    for session in state.get("sessions", []):
        path = str(session.get("path", ""))
        if not path or path not in active_paths:
            continue
        if target_norm and path != target_norm:
            continue
        sessions.append(session)
    return sessions


def cmd_reconcile(args: argparse.Namespace) -> int:
    repo_root = _repo_root_from(Path(args.repo))
    managed_root = (repo_root / args.managed_dir).resolve()
    state_file = _state_path(managed_root)

    entries = _get_worktree_entries(repo_root)
    active_paths = _active_path_set(entries)
    state = _load_state(state_file)
    state, _ = _prune_stale_state(state, active_paths)

    target_path: str | None = None
    if args.path:
        target_path = args.path
    elif not args.all:
        target_path = str(Path.cwd().resolve())

    sessions = _iter_target_sessions(state, active_paths=active_paths, target_path=target_path)
    results: list[dict[str, Any]] = []
    skipped_active_session = 0

    for session in sessions:
        path = Path(session["path"])
        if path.exists() and _has_active_session(path):
            ok, status = True, "skipped_active_session"
            skipped_active_session += 1
        else:
            ok, status = _integrate_worktree(repo_root, path, args.base, args.strategy)
        session["last_seen_at"] = _utc_now().isoformat()
        session["reconcile_status"] = status
        results.append(
            {
                "session_id": session["session_id"],
                "branch": session["branch"],
                "path": session["path"],
                "ok": ok,
                "status": status,
            }
        )

    _save_state(state_file, state)

    failed = [r for r in results if not r["ok"]]
    payload = {
        "ok": not failed,
        "count": len(results),
        "skipped_active_session": skipped_active_session,
        "results": results,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        for row in results:
            mark = "ok" if row["ok"] else "fail"
            print(f"[{mark}] {row['branch']} -> {row['status']}")
        if not results:
            print("No managed sessions matched target.")
    return 0 if not failed else 2


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(value)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


def _branch_ahead_count(repo_root: Path, base: str, branch: str) -> int:
    proc = _run_git(repo_root, "rev-list", "--count", f"{base}..{branch}")
    if proc.returncode != 0:
        return 0
    out = proc.stdout.strip()
    return int(out) if out.isdigit() else 0


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)  # Signal 0 = existence check, no actual signal
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # Process exists but owned by another user


def _parse_lock_pids(lock_file: Path) -> list[int]:
    raw = lock_file.read_text(encoding="utf-8").strip()
    if not raw:
        return []

    # Claude hooks write JSON lock payloads.
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict):
        pids: list[int] = []
        for key in ("ppid", "pid"):
            value = data.get(key)
            if isinstance(value, int):
                pids.append(value)
            elif isinstance(value, str) and value.isdigit():
                pids.append(int(value))
        return pids

    # codex_session.sh writes key=value lock payloads.
    pids = []
    for line in raw.splitlines():
        line = line.strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() not in {"pid", "ppid"}:
            continue
        value = value.strip()
        if value.isdigit():
            pids.append(int(value))
    return pids


def _has_active_session(worktree_path: Path) -> bool:
    """Check if a worktree has an active Claude/Codex session via lock files.

    If any known session lock exists and has a live PID, the worktree is active.
    Conservative behavior: unreadable or unparseable lock files are treated as
    active to avoid destructive cleanup/reconcile on in-progress sessions.
    """
    lock_names = (".claude-session-active", ".codex_session_active", ".nomic-session-active")
    for lock_name in lock_names:
        lock_file = worktree_path / lock_name
        if not lock_file.exists():
            continue
        try:
            pids = _parse_lock_pids(lock_file)
        except OSError:
            return True
        if not pids:
            return True
        for pid in pids:
            if _pid_alive(pid):
                return True
    # Locks missing or all recorded PIDs dead — safe to proceed.
    return False


def _remove_worktree(repo_root: Path, path: Path) -> bool:
    proc = _run_git(repo_root, "worktree", "remove", "--force", str(path))
    return proc.returncode == 0


def _delete_branch(repo_root: Path, branch: str) -> bool:
    if not _branch_exists(repo_root, branch):
        return True
    proc = _run_git(repo_root, "branch", "-D", branch)
    return proc.returncode == 0


def cmd_cleanup(args: argparse.Namespace) -> int:
    repo_root = _repo_root_from(Path(args.repo))
    managed_root = (repo_root / args.managed_dir).resolve()
    state_file = _state_path(managed_root)

    entries = _get_worktree_entries(repo_root)
    active_paths = _active_path_set(entries)
    state = _load_state(state_file)

    now = _utc_now()
    ttl = timedelta(hours=args.ttl_hours)
    kept: list[dict[str, Any]] = []
    removed = 0
    skipped_unmerged = 0
    failed_worktree_removals = 0
    failed_branch_deletions = 0

    skipped_active_session = 0

    for session in state.get("sessions", []):
        path = Path(str(session.get("path", ""))).resolve()
        branch = str(session.get("branch", ""))
        created = _parse_ts(str(session.get("created_at", "")))
        age = (now - created) if created else timedelta.max
        active = str(path) in active_paths and path.exists()
        expired = age > ttl
        stale = not active

        if not stale and not expired:
            kept.append(session)
            continue

        # CRITICAL: Never delete a worktree with an active Claude/Codex session.
        # Session locks are checked via PID liveness; active sessions are skipped.
        if path.exists() and _has_active_session(path):
            kept.append(session)
            skipped_active_session += 1
            continue

        if active and branch:
            ahead = _branch_ahead_count(repo_root, args.base, branch)
            if ahead > 0 and not args.force_unmerged:
                kept.append(session)
                skipped_unmerged += 1
                continue

        if active:
            if not _remove_worktree(repo_root, path):
                kept.append(session)
                failed_worktree_removals += 1
                continue
        elif path.exists():
            shutil.rmtree(path, ignore_errors=True)

        if args.delete_branches and branch.startswith("codex/"):
            if not _delete_branch(repo_root, branch):
                failed_branch_deletions += 1
        removed += 1

    state["sessions"] = kept
    _run_git(repo_root, "worktree", "prune")
    _save_state(state_file, state)

    payload = {
        "ok": True,
        "removed": removed,
        "kept": len(kept),
        "skipped_unmerged": skipped_unmerged,
        "skipped_active_session": skipped_active_session,
        "failed_worktree_removals": failed_worktree_removals,
        "failed_branch_deletions": failed_branch_deletions,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(
            f"cleanup complete: removed={removed} kept={len(kept)} "
            f"skipped_unmerged={skipped_unmerged} "
            f"skipped_active_session={skipped_active_session} "
            f"failed_worktree_removals={failed_worktree_removals} "
            f"failed_branch_deletions={failed_branch_deletions}"
        )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    repo_root = _repo_root_from(Path(args.repo))
    managed_root = (repo_root / args.managed_dir).resolve()
    state = _load_state(_state_path(managed_root))
    entries = _get_worktree_entries(repo_root)
    active_paths = _active_path_set(entries)

    rows: list[dict[str, Any]] = []
    for session in state.get("sessions", []):
        path = str(session.get("path", ""))
        rows.append(
            {
                "session_id": session.get("session_id"),
                "agent": session.get("agent"),
                "branch": session.get("branch"),
                "path": path,
                "active": path in active_paths,
                "created_at": session.get("created_at"),
                "last_seen_at": session.get("last_seen_at"),
                "reconcile_status": session.get("reconcile_status"),
            }
        )

    payload = {"repo_root": str(repo_root), "managed_root": str(managed_root), "sessions": rows}
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"managed root: {managed_root}")
        if not rows:
            print("no managed sessions")
        for row in rows:
            marker = "active" if row["active"] else "stale"
            print(f"[{marker}] {row['branch']} :: {row['path']}")
    return 0


def cmd_maintain(args: argparse.Namespace) -> int:
    script_path = str(Path(__file__).resolve())
    reconcile_proc = subprocess.run(
        [
            sys.executable,
            script_path,
            "--repo",
            args.repo,
            "--managed-dir",
            args.managed_dir,
            "reconcile",
            "--all",
            "--base",
            args.base,
            "--strategy",
            args.strategy,
            "--json",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    cleanup_cmd = [
        sys.executable,
        script_path,
        "--repo",
        args.repo,
        "--managed-dir",
        args.managed_dir,
        "cleanup",
        "--base",
        args.base,
        "--ttl-hours",
        str(args.ttl_hours),
        "--json",
    ]
    if args.force_unmerged:
        cleanup_cmd.append("--force-unmerged")
    if not args.delete_branches:
        cleanup_cmd.append("--no-delete-branches")
    cleanup_proc = subprocess.run(
        cleanup_cmd,
        text=True,
        capture_output=True,
        check=False,
    )

    reconcile_out: dict[str, Any] = {"ok": False, "error": reconcile_proc.stderr.strip()}
    cleanup_out: dict[str, Any] = {"ok": False, "error": cleanup_proc.stderr.strip()}
    if reconcile_proc.returncode == 0 and reconcile_proc.stdout.strip():
        try:
            reconcile_out = json.loads(reconcile_proc.stdout)
        except json.JSONDecodeError:
            reconcile_out = {"ok": False, "error": "invalid_reconcile_output"}
    if cleanup_proc.returncode == 0 and cleanup_proc.stdout.strip():
        try:
            cleanup_out = json.loads(cleanup_proc.stdout)
        except json.JSONDecodeError:
            cleanup_out = {"ok": False, "error": "invalid_cleanup_output"}

    ok = bool(reconcile_out.get("ok")) and bool(cleanup_out.get("ok"))
    payload = {"ok": ok, "reconcile": reconcile_out, "cleanup": cleanup_out}
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(
            "maintain complete: "
            f"reconcile_ok={bool(reconcile_out.get('ok'))} "
            f"cleanup_ok={bool(cleanup_out.get('ok'))}"
        )
    return 0 if ok else 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Autopilot worktree lifecycle for Codex sessions.")
    parser.add_argument(
        "--repo",
        default=".",
        help="Path inside repository (default: current directory)",
    )
    parser.add_argument(
        "--managed-dir",
        default=".worktrees/codex-auto",
        help="Managed worktree root relative to repo root",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    ensure = sub.add_parser("ensure", help="Ensure a usable managed worktree exists")
    ensure.add_argument("--agent", default="codex")
    ensure.add_argument("--base", default="main")
    ensure.add_argument("--session-id", default=None)
    ensure.add_argument("--force-new", action="store_true")
    ensure.add_argument("--reconcile", action="store_true")
    ensure.add_argument(
        "--strategy",
        choices=("merge", "rebase", "ff-only", "none"),
        default="ff-only",
        help="Upstream integration strategy when --reconcile is enabled",
    )
    ensure.add_argument("--print-path", action="store_true")
    ensure.add_argument("--json", action="store_true")
    ensure.set_defaults(func=cmd_ensure)

    reconcile = sub.add_parser("reconcile", help="Reconcile managed worktrees with origin/base")
    reconcile.add_argument("--base", default="main")
    reconcile.add_argument(
        "--strategy",
        choices=("merge", "rebase", "ff-only", "none"),
        default="ff-only",
        help="Upstream integration strategy",
    )
    reconcile.add_argument("--all", action="store_true")
    reconcile.add_argument("--path", default=None, help="Specific worktree path to reconcile")
    reconcile.add_argument("--json", action="store_true")
    reconcile.set_defaults(func=cmd_reconcile)

    cleanup = sub.add_parser("cleanup", help="Cleanup stale/expired managed worktrees")
    cleanup.add_argument("--base", default="main")
    cleanup.add_argument("--ttl-hours", type=int, default=24)
    cleanup.add_argument("--force-unmerged", action="store_true")
    cleanup.add_argument("--delete-branches", dest="delete_branches", action="store_true")
    cleanup.add_argument(
        "--no-delete-branches",
        dest="delete_branches",
        action="store_false",
        help="Keep local codex/* branches while removing stale worktrees",
    )
    cleanup.set_defaults(delete_branches=True)
    cleanup.add_argument("--json", action="store_true")
    cleanup.set_defaults(func=cmd_cleanup)

    maintain = sub.add_parser(
        "maintain",
        help="Reconcile all managed worktrees then cleanup stale/expired sessions",
    )
    maintain.add_argument("--base", default="main")
    maintain.add_argument(
        "--strategy",
        choices=("merge", "rebase", "ff-only", "none"),
        default="ff-only",
        help="Upstream integration strategy for the reconcile phase",
    )
    maintain.add_argument("--ttl-hours", type=int, default=24)
    maintain.add_argument("--force-unmerged", action="store_true")
    maintain.add_argument("--delete-branches", dest="delete_branches", action="store_true")
    maintain.add_argument(
        "--no-delete-branches",
        dest="delete_branches",
        action="store_false",
        help="Keep local codex/* branches while removing stale worktrees",
    )
    maintain.set_defaults(delete_branches=True)
    maintain.add_argument("--json", action="store_true")
    maintain.set_defaults(func=cmd_maintain)

    status = sub.add_parser("status", help="Show managed session status")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_status)

    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
