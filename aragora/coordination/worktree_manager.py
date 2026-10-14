"""Worktree Manager for multi-agent coordination.

Creates and manages isolated git worktrees so that multiple Claude Code
sessions (or other agents) can work in parallel without file conflicts.

Each worktree gets its own branch from a common base. The manager tracks
worktree health (last activity, stall detection) and auto-cleans abandoned
worktrees after a configurable timeout.

Usage:
    from aragora.coordination.worktree_manager import WorktreeManager

    manager = WorktreeManager(repo_path=Path("."))
    wt = await manager.create("feature-auth", track="security")
    # ... agent works in wt.path ...
    await manager.destroy(wt.worktree_id)
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from aragora.worktree.lifecycle import WorktreeLifecycleService

logger = logging.getLogger(__name__)


@dataclass
class WorktreeState:
    """Tracked state of a single git worktree."""

    worktree_id: str
    branch_name: str
    path: Path
    track: str | None = None
    base_branch: str = "main"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_activity: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_commit_sha: str | None = None
    status: str = "active"  # active, stalled, abandoned, destroyed
    assigned_task: str | None = None
    agent_id: str | None = None
    managed_dir: str | None = None
    managed_session_id: str | None = None
    commit_count: int = 0


@dataclass
class WorktreeManagerConfig:
    """Configuration for WorktreeManager."""

    base_branch: str = "main"
    branch_prefix: str = "dev"
    worktree_dir: Path | None = None  # Default: <repo>/../aragora-worktrees/
    stall_timeout_seconds: int = 600  # 10 minutes with no activity
    abandon_timeout_seconds: int = 3600  # 1 hour -> auto-cleanup
    max_worktrees: int = 20


class WorktreeManager:
    """Manages isolated git worktrees for parallel agent sessions.

    Wraps git-worktree operations with lifecycle tracking, health monitoring,
    and automatic cleanup of abandoned worktrees.
    """

    def __init__(
        self,
        repo_path: Path | None = None,
        config: WorktreeManagerConfig | None = None,
    ):
        self.repo_path = (repo_path or Path.cwd()).resolve()
        self.config = config or WorktreeManagerConfig()
        self._worktree_dir = self.config.worktree_dir or self.repo_path.parent / "aragora-worktrees"
        self._worktrees: dict[str, WorktreeState] = {}
        self._lifecycle = WorktreeLifecycleService(repo_root=self.repo_path)

    @property
    def worktrees(self) -> dict[str, WorktreeState]:
        """Read-only access to tracked worktrees."""
        return dict(self._worktrees)

    @property
    def active_worktrees(self) -> list[WorktreeState]:
        """Return all worktrees with status 'active'."""
        return [wt for wt in self._worktrees.values() if wt.status == "active"]

    def _run_git(
        self,
        *args: str,
        cwd: Path | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Run a git command in the repo or a specific directory."""
        cmd = ["git"] + list(args)
        return subprocess.run(  # subprocess with fixed args, no shell
            cmd,
            cwd=cwd or self.repo_path,
            capture_output=True,
            text=True,
            check=check,
        )

    @staticmethod
    def _managed_session_slug(name: str) -> str:
        """Build a safe session slug for managed autopilot session IDs."""
        slug = "".join(ch if (ch.isalnum() or ch in "-_.") else "-" for ch in name.lower())
        slug = slug.strip("-_.")
        return slug or "session"

    async def create(
        self,
        name: str,
        track: str | None = None,
        base_branch: str | None = None,
        agent_id: str | None = None,
        managed_dir: str | None = None,
        managed_agent: str | None = None,
        managed_session_id: str | None = None,
        reconcile: bool = True,
        strategy: str = "merge",
        force_new: bool = False,
    ) -> WorktreeState:
        """Create a new isolated worktree.

        Args:
            name: Human-readable name (used in branch and directory names).
            track: Development track (e.g. "sme", "security").
            base_branch: Branch to fork from (default: config.base_branch).
            agent_id: Optional identifier for the agent using this worktree.
            managed_dir: Optional managed directory for autopilot-backed allocation.
            managed_agent: Optional managed-session agent label.
            managed_session_id: Optional managed session identifier.
            reconcile: Reconcile reused managed sessions with upstream.
            strategy: Integration strategy used by managed ensure.
            force_new: Force creation of a new managed session.

        Returns:
            WorktreeState with path and metadata.

        Raises:
            RuntimeError: If max worktrees exceeded or git operation fails.
        """
        if len(self.active_worktrees) >= self.config.max_worktrees:
            raise RuntimeError(
                f"Max worktrees ({self.config.max_worktrees}) reached. "
                "Clean up abandoned worktrees first."
            )

        base = base_branch or self.config.base_branch
        worktree_id = str(uuid4())[:8]
        session_id: str | None = None
        if managed_dir:
            session_id = managed_session_id or (
                f"{self._managed_session_slug(name)}-{str(uuid4())[:8]}"
            )
            session = self._lifecycle.ensure_managed_worktree(
                managed_dir=managed_dir,
                base_branch=base,
                agent=managed_agent or agent_id or "coordination",
                session_id=session_id,
                force_new=force_new,
                reconcile=reconcile,
                strategy=strategy,
            )
            branch_name = session.branch
            worktree_path = session.path
        else:
            branch_name = f"{self.config.branch_prefix}/{name}-{worktree_id}"
            dir_name = branch_name.replace("/", "-")
            worktree_path = self._worktree_dir / dir_name

            self._worktree_dir.mkdir(parents=True, exist_ok=True)

            result = self._lifecycle.create_worktree(
                worktree_path=worktree_path,
                ref=base,
                branch=branch_name,
                git_runner=self._run_git,
            )
            if not result.success:
                raise RuntimeError(f"Failed to create worktree: {result.stderr.strip()}")

        # Get the initial commit SHA
        sha_result = self._run_git("rev-parse", "HEAD", cwd=worktree_path, check=False)
        initial_sha = sha_result.stdout.strip() if sha_result.returncode == 0 else None

        state = WorktreeState(
            worktree_id=worktree_id,
            branch_name=branch_name,
            path=worktree_path,
            track=track,
            base_branch=base,
            last_commit_sha=initial_sha,
            agent_id=agent_id,
            managed_dir=managed_dir,
            managed_session_id=session_id,
        )
        self._worktrees[worktree_id] = state

        logger.info(
            "worktree_created id=%s branch=%s path=%s track=%s managed=%s",
            worktree_id,
            branch_name,
            worktree_path,
            track,
            bool(managed_dir),
        )
        return state

    async def destroy(self, worktree_id: str, force: bool = False) -> bool:
        """Destroy a worktree and optionally its branch.

        Args:
            worktree_id: ID of the worktree to destroy.
            force: If True, force-remove even if there are changes.

        Returns:
            True if successfully removed.
        """
        state = self._worktrees.get(worktree_id)
        if not state:
            logger.warning("worktree_not_found id=%s", worktree_id)
            return False

        op_result = self._lifecycle.remove_worktree(
            worktree_path=state.path,
            force=force,
            git_runner=self._run_git,
        )
        if not op_result.success:
            if force and state.path.exists():
                # Fallback: manual removal
                shutil.rmtree(state.path, ignore_errors=True)
                self._run_git("worktree", "prune", check=False)
            else:
                logger.warning(
                    "worktree_remove_failed id=%s err=%s",
                    worktree_id,
                    op_result.stderr.strip(),
                )
                return False

        state.status = "destroyed"
        logger.info("worktree_destroyed id=%s branch=%s", worktree_id, state.branch_name)
        return True

    def record_activity(self, worktree_id: str) -> None:
        """Record agent activity in a worktree (heartbeat)."""
        state = self._worktrees.get(worktree_id)
        if state and state.status == "active":
            state.last_activity = datetime.now(timezone.utc)

    def check_for_new_commits(self, worktree_id: str) -> bool:
        """Check if there are new commits in a worktree since last check.

        Returns:
            True if new commits were found.
        """
        state = self._worktrees.get(worktree_id)
        if not state or not state.path.exists():
            return False

        result = self._run_git("rev-parse", "HEAD", cwd=state.path, check=False)
        if result.returncode != 0:
            return False

        current_sha = result.stdout.strip()
        if current_sha != state.last_commit_sha:
            state.last_commit_sha = current_sha
            state.last_activity = datetime.now(timezone.utc)
            state.commit_count += 1
            return True
        return False

    def get_stalled_worktrees(self) -> list[WorktreeState]:
        """Return worktrees that have had no activity for stall_timeout."""
        now = datetime.now(timezone.utc)
        stalled = []
        for state in self._worktrees.values():
            if state.status != "active":
                continue
            idle_seconds = (now - state.last_activity).total_seconds()
            if idle_seconds >= self.config.stall_timeout_seconds:
                stalled.append(state)
        return stalled

    def get_abandoned_worktrees(self) -> list[WorktreeState]:
        """Return worktrees idle longer than abandon_timeout."""
        now = datetime.now(timezone.utc)
        abandoned = []
        for state in self._worktrees.values():
            if state.status in ("destroyed",):
                continue
            idle_seconds = (now - state.last_activity).total_seconds()
            if idle_seconds >= self.config.abandon_timeout_seconds:
                abandoned.append(state)
        return abandoned

    async def mark_stalled(self, worktree_id: str) -> None:
        """Mark a worktree as stalled."""
        state = self._worktrees.get(worktree_id)
        if state:
            state.status = "stalled"
            logger.warning("worktree_stalled id=%s branch=%s", worktree_id, state.branch_name)

    async def mark_abandoned(self, worktree_id: str) -> None:
        """Mark a worktree as abandoned."""
        state = self._worktrees.get(worktree_id)
        if state:
            state.status = "abandoned"
            logger.warning("worktree_abandoned id=%s branch=%s", worktree_id, state.branch_name)

    async def cleanup_abandoned(self) -> int:
        """Destroy all abandoned worktrees. Returns count removed."""
        abandoned = self.get_abandoned_worktrees()
        removed = 0
        for state in abandoned:
            await self.mark_abandoned(state.worktree_id)
            if await self.destroy(state.worktree_id, force=True):
                removed += 1
        return removed

    def get_commits_ahead(self, worktree_id: str) -> int:
        """Return number of commits ahead of base branch."""
        state = self._worktrees.get(worktree_id)
        if not state:
            return 0
        result = self._run_git(
            "rev-list",
            "--count",
            f"{state.base_branch}..{state.branch_name}",
            check=False,
        )
        if result.returncode != 0:
            return 0
        return int(result.stdout.strip())

    def get_changed_files(self, worktree_id: str) -> list[str]:
        """Return files changed in this worktree relative to base."""
        state = self._worktrees.get(worktree_id)
        if not state:
            return []
        result = self._run_git(
            "diff",
            "--name-only",
            f"{state.base_branch}...{state.branch_name}",
            check=False,
        )
        if result.returncode != 0:
            return []
        return [f.strip() for f in result.stdout.split("\n") if f.strip()]

    def maintain_managed_sessions(
        self,
        *,
        base_branch: str | None = None,
        ttl_hours: int = 24,
        strategy: str = "merge",
        managed_dirs: list[str] | None = None,
        include_active: bool = False,
        reconcile_only: bool = True,
        delete_branches: bool = False,
    ) -> dict[str, Any]:
        """Run managed codex-auto lifecycle maintenance with shared service."""
        return self._lifecycle.maintain_managed_dirs(
            base_branch=base_branch or self.config.base_branch,
            ttl_hours=ttl_hours,
            strategy=strategy,
            managed_dirs=managed_dirs,
            include_active=include_active,
            reconcile_only=reconcile_only,
            delete_branches=delete_branches,
        )

    def summary(self) -> dict[str, int]:
        """Return a summary of worktree statuses."""
        counts: dict[str, int] = {}
        for state in self._worktrees.values():
            counts[state.status] = counts.get(state.status, 0) + 1
        return counts


__all__ = [
    "WorktreeManager",
    "WorktreeManagerConfig",
    "WorktreeState",
]
