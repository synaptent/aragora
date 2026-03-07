"""Shared runtime lifecycle service for worktree orchestration."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
from typing import Any, Callable

from aragora.worktree.autopilot import AutopilotRequest, run_autopilot

GitRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(slots=True)
class WorktreeOperationResult:
    """Result of a low-level git worktree operation."""

    success: bool
    returncode: int
    stdout: str
    stderr: str


@dataclass(slots=True)
class ManagedWorktreeSession:
    """Resolved managed worktree session returned by autopilot ensure."""

    session_id: str
    agent: str
    branch: str
    path: Path
    created: bool
    reconcile_status: str | None
    payload: dict[str, Any]


class WorktreeLifecycleService:
    """Canonical service for worktree lifecycle and maintainer operations."""

    def __init__(
        self,
        repo_root: Path | None = None,
        python_executable: str | None = None,
    ) -> None:
        self.repo_root = (repo_root or Path.cwd()).resolve()
        self.python_executable = python_executable

    def _run_git(
        self,
        *args: str,
        cwd: Path | None = None,
        check: bool = False,
        git_runner: GitRunner | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if git_runner is not None:
            return git_runner(*args, cwd=cwd, check=check)
        return subprocess.run(  # noqa: S603 -- subprocess with fixed args, no shell
            ["git", *args],  # noqa: S607 -- fixed command
            cwd=cwd or self.repo_root,
            capture_output=True,
            text=True,
            check=check,
        )

    def create_worktree(
        self,
        *,
        worktree_path: Path,
        ref: str,
        branch: str | None = None,
        git_runner: GitRunner | None = None,
    ) -> WorktreeOperationResult:
        cmd = ["worktree", "add"]
        if branch:
            cmd.extend(["-b", branch])
        cmd.extend([str(worktree_path), ref])

        proc = self._run_git(*cmd, check=False, git_runner=git_runner)
        return WorktreeOperationResult(
            success=proc.returncode == 0,
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )

    def remove_worktree(
        self,
        *,
        worktree_path: Path,
        force: bool = False,
        git_runner: GitRunner | None = None,
    ) -> WorktreeOperationResult:
        cmd = ["worktree", "remove", str(worktree_path)]
        if force:
            cmd.append("--force")
        proc = self._run_git(*cmd, check=False, git_runner=git_runner)
        return WorktreeOperationResult(
            success=proc.returncode == 0,
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )

    def discover_managed_dirs(self, managed_dirs: list[str] | None = None) -> list[str]:
        """Discover managed codex-auto directories relative to repo root."""
        if managed_dirs:
            seen: set[str] = set()
            ordered: list[str] = []
            for item in managed_dirs:
                norm = str(item).strip()
                if not norm or norm in seen:
                    continue
                seen.add(norm)
                ordered.append(norm)
            return ordered

        discovered: list[str] = [".worktrees/codex-auto"]
        base = self.repo_root / ".worktrees"
        if base.exists():
            for abs_path in sorted(base.glob("codex-auto*")):
                rel = f".worktrees/{abs_path.name}"
                if rel not in discovered:
                    discovered.append(rel)
        return discovered

    def has_active_lock(self, managed_dir: str) -> bool:
        """Return True when a managed directory has an active session lock."""
        abs_dir = (self.repo_root / managed_dir).resolve()
        if not abs_dir.exists():
            return False
        lock_names = (".claude-session-active", ".codex_session_active", ".nomic-session-active")
        return any(match for name in lock_names for match in abs_dir.glob(f"**/{name}"))

    @staticmethod
    def _parse_payload(stdout: str) -> dict[str, Any]:
        text = stdout.strip()
        if not text:
            return {}
        try:
            payload = json.loads(text)
            return payload if isinstance(payload, dict) else {"output": payload}
        except json.JSONDecodeError:
            return {"output": text}

    def run_autopilot_action(self, request: AutopilotRequest) -> subprocess.CompletedProcess[str]:
        return run_autopilot(
            repo_root=self.repo_root,
            request=request,
            python_executable=self.python_executable,
        )

    @staticmethod
    def _require_session_field(session: dict[str, Any], key: str) -> str:
        value = session.get(key)
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"autopilot ensure missing session.{key}")
        return value.strip()

    def ensure_managed_worktree(
        self,
        *,
        managed_dir: str = ".worktrees/codex-auto",
        base_branch: str = "main",
        agent: str = "codex",
        session_id: str | None = None,
        force_new: bool = False,
        reconcile: bool = True,
        strategy: str = "ff-only",
    ) -> ManagedWorktreeSession:
        """Ensure a managed worktree session exists and return its typed details."""
        request = AutopilotRequest(
            action="ensure",
            managed_dir=managed_dir,
            base_branch=base_branch,
            agent=agent,
            session_id=session_id,
            force_new=force_new,
            strategy=strategy,
            reconcile=reconcile,
            json_output=True,
        )
        proc = self.run_autopilot_action(request)
        payload = self._parse_payload(proc.stdout)
        if proc.returncode != 0:
            details = proc.stderr.strip() or json.dumps(payload, sort_keys=True)
            raise RuntimeError(f"autopilot ensure failed ({proc.returncode}): {details}")

        raw_session = payload.get("session")
        if not isinstance(raw_session, dict):
            raise RuntimeError("autopilot ensure missing session payload")

        resolved_path = Path(self._require_session_field(raw_session, "path")).resolve()
        if not resolved_path.exists():
            raise RuntimeError(f"autopilot ensure returned missing path: {resolved_path}")

        resolved_agent = raw_session.get("agent")
        if not isinstance(resolved_agent, str) or not resolved_agent.strip():
            resolved_agent = agent

        reconcile_status = raw_session.get("reconcile_status")
        if reconcile_status is not None and not isinstance(reconcile_status, str):
            reconcile_status = str(reconcile_status)

        return ManagedWorktreeSession(
            session_id=self._require_session_field(raw_session, "session_id"),
            agent=resolved_agent.strip(),
            branch=self._require_session_field(raw_session, "branch"),
            path=resolved_path,
            created=bool(payload.get("created", False)),
            reconcile_status=reconcile_status,
            payload=payload,
        )

    def maintain_managed_dirs(
        self,
        *,
        base_branch: str = "main",
        ttl_hours: int = 24,
        strategy: str = "ff-only",
        managed_dirs: list[str] | None = None,
        include_active: bool = False,
        reconcile_only: bool = False,
        delete_branches: bool = False,
    ) -> dict[str, Any]:
        """Run reconcile/maintain across all managed codex-auto directories."""
        resolved_dirs = self.discover_managed_dirs(managed_dirs)
        results: list[dict[str, Any]] = []
        processed = 0
        skipped_missing = 0
        skipped_active = 0
        failures = 0

        for managed_dir in resolved_dirs:
            abs_dir = (self.repo_root / managed_dir).resolve()
            if not abs_dir.exists():
                skipped_missing += 1
                results.append(
                    {
                        "managed_dir": managed_dir,
                        "status": "skipped_missing",
                    }
                )
                continue

            if not include_active and self.has_active_lock(managed_dir):
                skipped_active += 1
                results.append(
                    {
                        "managed_dir": managed_dir,
                        "status": "skipped_active",
                    }
                )
                continue

            action = "reconcile" if reconcile_only else "maintain"
            request = AutopilotRequest(
                action=action,
                managed_dir=managed_dir,
                base_branch=base_branch,
                strategy=strategy,
                ttl_hours=ttl_hours,
                reconcile_all=reconcile_only,
                delete_branches=delete_branches,
                json_output=True,
            )

            try:
                proc = self.run_autopilot_action(request)
            except FileNotFoundError as exc:
                failures += 1
                results.append(
                    {
                        "managed_dir": managed_dir,
                        "status": "failed",
                        "error": str(exc),
                    }
                )
                continue

            payload = self._parse_payload(proc.stdout)
            row = {
                "managed_dir": managed_dir,
                "status": "ok" if proc.returncode == 0 else "failed",
                "returncode": proc.returncode,
                "action": action,
                "payload": payload,
            }
            if proc.stderr.strip():
                row["stderr"] = proc.stderr.strip()
            results.append(row)
            processed += 1
            if proc.returncode != 0:
                failures += 1

        return {
            "ok": failures == 0,
            "repo_root": str(self.repo_root),
            "base_branch": base_branch,
            "ttl_hours": ttl_hours,
            "strategy": strategy,
            "include_active": include_active,
            "reconcile_only": reconcile_only,
            "delete_branches": delete_branches,
            "directories_total": len(resolved_dirs),
            "processed": processed,
            "skipped_missing": skipped_missing,
            "skipped_active": skipped_active,
            "failures": failures,
            "results": results,
        }
