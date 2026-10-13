"""Worktree Manager for parallel agent execution.

Manages git worktree lifecycle to provide file-level isolation for
concurrent agent work. Each agent gets its own worktree (working directory)
so multiple agents can edit files simultaneously without conflicts.

Wraps Gastown's HookRunner for worktree creation/removal and
BranchCoordinator for safe merges.

Usage:
    from aragora.nomic.worktree_manager import WorktreeManager

    manager = WorktreeManager(repo_path=Path("."))
    ctx = await manager.create_worktree_for_subtask(subtask, track, "claude")
    test_result = await manager.run_tests_in_worktree(ctx, ["tests/"])
    merge_result = await manager.merge_worktree(ctx)
    await manager.cleanup_worktree(ctx)
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class WorktreeContext:
    """Context for a single worktree-isolated agent execution."""

    subtask_id: str
    worktree_path: Path
    branch_name: str
    track: str
    agent_type: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "active"  # active | completed | failed | cleaned


@dataclass
class MergeGateConfig:
    """Configuration for test-gated merges."""

    pre_merge_test_paths: list[str] = field(default_factory=list)
    post_merge_test_paths: list[str] = field(default_factory=list)
    auto_revert: bool = True
    test_timeout: int = 300  # seconds
    require_pre_merge_pass: bool = True
    require_post_merge_pass: bool = True


@dataclass
class MergeGateResult:
    """Result of a test-gated merge operation."""

    success: bool
    pre_merge_passed: bool | None = None
    merge_succeeded: bool | None = None
    post_merge_passed: bool | None = None
    reverted: bool = False
    commit_sha: str | None = None
    error: str | None = None
    pre_merge_output: str = ""
    post_merge_output: str = ""


class WorktreeManager:
    """Manages git worktree lifecycle for parallel agent execution.

    Each subtask gets an isolated worktree with its own branch, allowing
    true parallel file edits. Tests run inside the worktree, and merges
    go through BranchCoordinator's safe_merge with dry-run checks.
    """

    def __init__(
        self,
        repo_path: Path,
        base_branch: str = "main",
        worktree_root: Path | None = None,
    ):
        self.repo_path = repo_path
        self.base_branch = base_branch
        self.worktree_root = worktree_root or (repo_path / ".worktrees")
        self._active_contexts: dict[str, WorktreeContext] = {}

        # Lazy imports to avoid hard dependencies
        self._hook_runner: Any | None = None
        self._branch_coordinator: Any | None = None

    def _get_hook_runner(self) -> Any:
        """Lazily import and create HookRunner."""
        if self._hook_runner is None:
            try:
                from aragora.extensions.gastown.hooks import HookRunner

                self._hook_runner = HookRunner()
            except ImportError:
                logger.debug("HookRunner unavailable, using subprocess fallback")
        return self._hook_runner

    def _get_branch_coordinator(self) -> Any:
        """Lazily import and create BranchCoordinator."""
        if self._branch_coordinator is None:
            try:
                from aragora.nomic.branch_coordinator import (
                    BranchCoordinator,
                    BranchCoordinatorConfig,
                )

                self._branch_coordinator = BranchCoordinator(
                    repo_path=self.repo_path,
                    config=BranchCoordinatorConfig(
                        base_branch=self.base_branch,
                        use_worktrees=False,  # We manage worktrees ourselves
                    ),
                )
            except ImportError:
                logger.debug("BranchCoordinator unavailable")
        return self._branch_coordinator

    def _run_git(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
        """Run a git command."""
        cmd = ["git"] + list(args)
        return subprocess.run(  # subprocess with fixed args, no shell
            cmd,
            cwd=cwd or self.repo_path,
            capture_output=True,
            text=True,
            check=False,
        )

    async def create_worktree_for_subtask(
        self,
        subtask: Any,
        track: Any,
        agent_type: str,
    ) -> WorktreeContext:
        """Create an isolated worktree for a subtask.

        Args:
            subtask: SubTask with id attribute
            track: Track enum with value attribute
            agent_type: Agent type string (e.g., "claude", "codex")

        Returns:
            WorktreeContext for the created worktree
        """
        track_value = track.value if hasattr(track, "value") else str(track)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        branch_name = f"dev/{track_value}-{subtask.id}-{timestamp}"

        # Sanitize for directory name
        dir_name = branch_name.replace("/", "-")
        worktree_path = self.worktree_root / dir_name

        # Ensure worktree root exists
        self.worktree_root.mkdir(parents=True, exist_ok=True)

        # Create branch from base
        self._run_git("branch", branch_name, self.base_branch)

        # Create worktree using HookRunner if available, else subprocess
        hook_runner = self._get_hook_runner()
        if hook_runner is not None:
            result = await hook_runner.create_worktree(
                repo_path=str(self.repo_path),
                worktree_path=str(worktree_path),
                branch=branch_name,
            )
            if not result.get("success"):
                raise RuntimeError(f"Failed to create worktree: {result.get('error', 'unknown')}")
        else:
            # Direct subprocess fallback
            result = await asyncio.to_thread(
                subprocess.run,
                ["git", "worktree", "add", str(worktree_path), branch_name],
                capture_output=True,
                text=True,
                cwd=self.repo_path,
            )
            if result.returncode != 0:
                raise RuntimeError(f"Failed to create worktree: {result.stderr or 'unknown error'}")

        ctx = WorktreeContext(
            subtask_id=subtask.id,
            worktree_path=worktree_path,
            branch_name=branch_name,
            track=track_value,
            agent_type=agent_type,
        )

        self._active_contexts[subtask.id] = ctx
        logger.info(
            "worktree_created subtask=%s branch=%s path=%s",
            subtask.id,
            branch_name,
            worktree_path,
        )
        return ctx

    async def run_tests_in_worktree(
        self,
        ctx: WorktreeContext,
        test_paths: list[str],
        timeout: int = 300,
    ) -> dict[str, Any]:
        """Run pytest inside a worktree.

        Args:
            ctx: WorktreeContext for the worktree
            test_paths: List of test file/directory paths
            timeout: Maximum test execution time in seconds

        Returns:
            Dict with success, output, exit_code, duration keys
        """
        if not test_paths:
            return {"success": True, "output": "No tests to run", "exit_code": 0, "duration": 0.0}

        cmd = ["python", "-m", "pytest"] + test_paths + ["--tb=short", "-q"]
        start = datetime.now(timezone.utc)

        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    subprocess.run,
                    cmd,
                    capture_output=True,
                    text=True,
                    cwd=ctx.worktree_path,
                ),
                timeout=timeout,
            )
            duration = (datetime.now(timezone.utc) - start).total_seconds()
            success = result.returncode == 0

            logger.info(
                "worktree_tests subtask=%s success=%s exit_code=%d duration=%.1fs",
                ctx.subtask_id,
                success,
                result.returncode,
                duration,
            )

            return {
                "success": success,
                "output": result.stdout + result.stderr,
                "exit_code": result.returncode,
                "duration": duration,
            }

        except asyncio.TimeoutError:
            duration = (datetime.now(timezone.utc) - start).total_seconds()
            logger.warning("worktree_tests_timeout subtask=%s timeout=%ds", ctx.subtask_id, timeout)
            return {
                "success": False,
                "output": f"Tests timed out after {timeout}s",
                "exit_code": -1,
                "duration": duration,
            }

    async def merge_worktree(
        self,
        ctx: WorktreeContext,
        require_tests_pass: bool = True,
        test_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        """Merge worktree branch back to base.

        Args:
            ctx: WorktreeContext for the worktree
            require_tests_pass: Whether to run tests before merging
            test_paths: Test paths to verify (if require_tests_pass)

        Returns:
            Dict with success, commit_sha, conflicts keys
        """
        # Run tests first if required
        if require_tests_pass and test_paths:
            test_result = await self.run_tests_in_worktree(ctx, test_paths)
            if not test_result["success"]:
                logger.warning("merge_aborted subtask=%s reason=tests_failed", ctx.subtask_id)
                return {
                    "success": False,
                    "error": "Tests failed, merge aborted",
                    "test_output": test_result["output"],
                }

        # Try merge via BranchCoordinator
        coordinator = self._get_branch_coordinator()
        if coordinator is not None:
            # Dry-run first
            dry_result = await coordinator.safe_merge(
                ctx.branch_name,
                self.base_branch,
                dry_run=True,
            )
            if not dry_result.success:
                logger.warning(
                    "merge_conflicts subtask=%s conflicts=%s",
                    ctx.subtask_id,
                    dry_result.conflicts,
                )
                return {
                    "success": False,
                    "conflicts": dry_result.conflicts,
                    "error": "Merge conflicts detected",
                }

            # Actual merge
            merge_result = await coordinator.safe_merge(
                ctx.branch_name,
                self.base_branch,
                dry_run=False,
            )
            ctx.status = "completed" if merge_result.success else "failed"
            return {
                "success": merge_result.success,
                "commit_sha": merge_result.commit_sha,
                "conflicts": merge_result.conflicts,
                "error": merge_result.error,
            }

        # Fallback: direct git merge
        self._run_git("checkout", self.base_branch)
        result = self._run_git(
            "merge",
            "--no-ff",
            "-m",
            f"Merge {ctx.branch_name} (subtask {ctx.subtask_id})",
            ctx.branch_name,
        )

        if result.returncode != 0:
            self._run_git("merge", "--abort")
            ctx.status = "failed"
            return {
                "success": False,
                "error": result.stderr or "Merge failed",
                "conflicts": [],
            }

        sha = self._run_git("rev-parse", "HEAD")
        ctx.status = "completed"
        return {
            "success": True,
            "commit_sha": sha.stdout.strip(),
            "conflicts": [],
        }

    async def merge_with_gate(
        self,
        ctx: WorktreeContext,
        gate_config: MergeGateConfig | None = None,
    ) -> MergeGateResult:
        """Merge worktree branch with pre/post test gates and auto-revert.

        Flow:
        1. Run pre-merge tests in worktree (ensures branch is clean)
        2. Merge branch to base (--no-ff)
        3. Run post-merge tests on base
        4. If post-merge fails and auto_revert: git revert HEAD --no-edit

        Args:
            ctx: WorktreeContext for the worktree to merge
            gate_config: Test gate configuration (uses defaults if None)

        Returns:
            MergeGateResult with detailed status of each phase
        """
        config = gate_config or MergeGateConfig()

        # Phase 1: Pre-merge tests in the worktree
        if config.require_pre_merge_pass and config.pre_merge_test_paths:
            pre_result = await self.run_tests_in_worktree(
                ctx,
                config.pre_merge_test_paths,
                timeout=config.test_timeout,
            )
            if not pre_result["success"]:
                logger.warning(
                    "merge_gate_pre_failed subtask=%s",
                    ctx.subtask_id,
                )
                return MergeGateResult(
                    success=False,
                    pre_merge_passed=False,
                    pre_merge_output=pre_result["output"],
                    error="Pre-merge tests failed",
                )
        else:
            pre_result = None

        # Phase 2: Merge branch to base (--no-ff)
        self._run_git("checkout", self.base_branch)
        merge_proc = self._run_git(
            "merge",
            "--no-ff",
            "-m",
            f"Merge {ctx.branch_name} (subtask {ctx.subtask_id})",
            ctx.branch_name,
        )

        if merge_proc.returncode != 0:
            self._run_git("merge", "--abort")
            ctx.status = "failed"
            return MergeGateResult(
                success=False,
                pre_merge_passed=True if pre_result else None,
                merge_succeeded=False,
                pre_merge_output=pre_result["output"] if pre_result else "",
                error=merge_proc.stderr or "Merge failed",
            )

        sha_proc = self._run_git("rev-parse", "HEAD")
        commit_sha = sha_proc.stdout.strip()

        # Phase 3: Post-merge tests on base
        if config.require_post_merge_pass and config.post_merge_test_paths:
            cmd = ["python", "-m", "pytest"] + config.post_merge_test_paths + ["--tb=short", "-q"]
            datetime.now(timezone.utc)
            try:
                post_proc = await asyncio.wait_for(
                    asyncio.to_thread(
                        subprocess.run,
                        cmd,
                        capture_output=True,
                        text=True,
                        cwd=self.repo_path,
                    ),
                    timeout=config.test_timeout,
                )
                post_output = post_proc.stdout + post_proc.stderr
                post_passed = post_proc.returncode == 0
            except asyncio.TimeoutError:
                post_output = f"Post-merge tests timed out after {config.test_timeout}s"
                post_passed = False

            if not post_passed:
                logger.warning(
                    "merge_gate_post_failed subtask=%s sha=%s",
                    ctx.subtask_id,
                    commit_sha[:8],
                )

                reverted = False
                if config.auto_revert:
                    reverted = self._revert_merge(commit_sha)
                    if reverted:
                        logger.info(
                            "merge_gate_reverted subtask=%s sha=%s",
                            ctx.subtask_id,
                            commit_sha[:8],
                        )

                ctx.status = "failed"
                return MergeGateResult(
                    success=False,
                    pre_merge_passed=True if pre_result else None,
                    merge_succeeded=True,
                    post_merge_passed=False,
                    reverted=reverted,
                    commit_sha=commit_sha,
                    pre_merge_output=pre_result["output"] if pre_result else "",
                    post_merge_output=post_output,
                    error="Post-merge tests failed",
                )
        else:
            post_output = ""

        ctx.status = "completed"
        logger.info(
            "merge_gate_success subtask=%s sha=%s",
            ctx.subtask_id,
            commit_sha[:8],
        )
        return MergeGateResult(
            success=True,
            pre_merge_passed=True if pre_result else None,
            merge_succeeded=True,
            post_merge_passed=True if config.post_merge_test_paths else None,
            commit_sha=commit_sha,
            pre_merge_output=pre_result["output"] if pre_result else "",
            post_merge_output=post_output,
        )

    def _revert_merge(self, commit_sha: str) -> bool:
        """Revert a merge commit. Returns True if successful."""
        # Use -m 1 to revert merge commits (select first parent)
        result = self._run_git("revert", "-m", "1", "--no-edit", commit_sha)
        return result.returncode == 0

    async def cleanup_worktree(self, ctx: WorktreeContext) -> bool:
        """Remove a worktree and optionally its branch.

        Always safe to call — idempotent. Should be called in finally blocks.

        Args:
            ctx: WorktreeContext to clean up

        Returns:
            True if cleanup succeeded
        """
        success = True

        # Remove worktree
        hook_runner = self._get_hook_runner()
        if hook_runner is not None:
            result = await hook_runner.remove_worktree(str(ctx.worktree_path))
            if not result.get("success"):
                logger.warning(
                    "worktree_cleanup_failed subtask=%s error=%s",
                    ctx.subtask_id,
                    result.get("error"),
                )
                success = False
        else:
            result = self._run_git("worktree", "remove", str(ctx.worktree_path))
            if result.returncode != 0:
                # Force remove as fallback
                result = self._run_git("worktree", "remove", "--force", str(ctx.worktree_path))
                if result.returncode != 0:
                    logger.warning(
                        "worktree_cleanup_failed subtask=%s error=%s",
                        ctx.subtask_id,
                        result.stderr,
                    )
                    success = False

        # Delete branch if merged
        if ctx.status == "completed":
            self._run_git("branch", "-d", ctx.branch_name)
        elif ctx.status in ("failed", "cleaned"):
            # Force delete unmerged branch
            self._run_git("branch", "-D", ctx.branch_name)

        ctx.status = "cleaned"
        self._active_contexts.pop(ctx.subtask_id, None)

        logger.info("worktree_cleaned subtask=%s", ctx.subtask_id)
        return success

    async def cleanup_all(self) -> int:
        """Emergency cleanup of all active worktrees.

        Returns:
            Number of worktrees cleaned up
        """
        count = 0
        for ctx in list(self._active_contexts.values()):
            if await self.cleanup_worktree(ctx):
                count += 1
        return count

    def list_active(self) -> list[WorktreeContext]:
        """List all active worktree contexts."""
        return list(self._active_contexts.values())


__all__ = [
    "MergeGateConfig",
    "MergeGateResult",
    "WorktreeContext",
    "WorktreeManager",
]
