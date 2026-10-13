"""Branch Coordinator for parallel development.

Manages multiple development branches for parallel nomic loops,
handles conflict detection, and coordinates merges.

Usage:
    from aragora.nomic.branch_coordinator import BranchCoordinator

    coordinator = BranchCoordinator()

    # Create branches for parallel work
    branches = await coordinator.create_track_branches([
        TrackAssignment(track=Track.SME, goal="Improve dashboard"),
        TrackAssignment(track=Track.QA, goal="Add E2E tests"),
    ])

    # Run parallel work
    result = await coordinator.coordinate_parallel_work(branches)
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from collections.abc import Callable

from aragora.nomic.meta_planner import PrioritizedGoal, Track

logger = logging.getLogger(__name__)


@dataclass
class WorktreeInfo:
    """Metadata for a managed git worktree."""

    branch_name: str
    worktree_path: Path
    track: str | None = None
    created_at: datetime | None = None
    assignment_id: str | None = None


@dataclass
class TrackAssignment:
    """Assignment of a goal to a track for parallel execution."""

    goal: PrioritizedGoal
    branch_name: str | None = None
    worktree_path: Path | None = None
    status: str = "pending"  # pending, running, completed, failed, merged
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class ConflictReport:
    """Report of potential merge conflicts."""

    source_branch: str
    target_branch: str
    conflicting_files: list[str]
    severity: str  # low, medium, high
    resolution_hint: str = ""


@dataclass
class MergeResult:
    """Result of a merge operation."""

    source_branch: str
    target_branch: str
    success: bool
    commit_sha: str | None = None
    error: str | None = None
    conflicts: list[str] = field(default_factory=list)


@dataclass
class CoordinationResult:
    """Result of coordinating parallel work."""

    total_branches: int
    completed_branches: int
    failed_branches: int
    merged_branches: int
    assignments: list[TrackAssignment]
    duration_seconds: float
    success: bool
    summary: str = ""


@dataclass
class BranchCoordinatorConfig:
    """Configuration for BranchCoordinator."""

    base_branch: str = "main"
    branch_prefix: str = "dev"
    auto_merge_safe: bool = True
    require_tests_pass: bool = True
    max_parallel_branches: int = 3
    worktree_base_dir: Path | None = None  # Default: {repo}/.worktrees/
    use_worktrees: bool = True  # Use git worktree for isolation
    enable_semantic_conflicts: bool = False  # Enable AST-based semantic conflict detection


class BranchCoordinator:
    """Manages parallel development branches.

    Creates feature branches for each track/goal, runs nomic loops
    in parallel, and coordinates merges back to main.
    """

    def __init__(
        self,
        repo_path: Path | None = None,
        config: BranchCoordinatorConfig | None = None,
        on_conflict: Callable[[ConflictReport], None] | None = None,
        semantic_conflict_detector: Any | None = None,
    ):
        self.repo_path = repo_path or Path.cwd()
        self.config = config or BranchCoordinatorConfig()
        self.on_conflict = on_conflict
        self._active_branches: list[str] = []
        self._worktree_dir = self.config.worktree_base_dir or self.repo_path / ".worktrees"
        # Map branch name -> worktree path
        self._worktree_paths: dict[str, Path] = {}
        # Map branch name -> WorktreeInfo metadata
        self._active_worktrees: dict[str, WorktreeInfo] = {}
        # Semantic conflict detection (AST-based)
        self.semantic_conflict_detector = semantic_conflict_detector
        if self.config.enable_semantic_conflicts and semantic_conflict_detector is None:
            try:
                from aragora.nomic.semantic_conflict_detector import SemanticConflictDetector

                self.semantic_conflict_detector = SemanticConflictDetector(self.repo_path)
            except ImportError:
                logger.debug("SemanticConflictDetector not available")

    async def __aenter__(self) -> BranchCoordinator:
        """Enter async context manager."""
        return self

    async def __aexit__(
        self, exc_type: type | None, exc_val: BaseException | None, exc_tb: Any
    ) -> None:
        """Exit async context manager, cleaning up all worktrees."""
        self.cleanup_all_worktrees()

    def _run_git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        """Run a git command."""
        cmd = ["git"] + list(args)
        return subprocess.run(  # subprocess with fixed args, no shell
            cmd,
            cwd=self.repo_path,
            capture_output=True,
            text=True,
            check=check,
        )

    def _worktree_git(
        self,
        worktree_path: Path,
        *args: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        """Run a git command in a worktree directory."""
        cmd = ["git"] + list(args)
        return subprocess.run(  # subprocess with fixed args, no shell
            cmd,
            cwd=worktree_path,
            capture_output=True,
            text=True,
            check=check,
        )

    def get_current_branch(self) -> str:
        """Get the current branch name."""
        result = self._run_git("rev-parse", "--abbrev-ref", "HEAD")
        return result.stdout.strip()

    def branch_exists(self, branch_name: str) -> bool:
        """Check if a branch exists."""
        result = self._run_git(
            "rev-parse",
            "--verify",
            f"refs/heads/{branch_name}",
            check=False,
        )
        return result.returncode == 0

    def _ref_exists(self, ref: str) -> bool:
        """Check whether an arbitrary git ref resolves."""
        result = self._run_git("rev-parse", "--verify", ref, check=False)
        return result.returncode == 0

    def _resolve_base_ref(self, base: str) -> str:
        """Resolve the best available base ref for branch creation.

        CI checkouts often expose only ``origin/<branch>`` without creating a
        local branch. Prefer the requested base ref when present, then fall
        back to the matching remote-tracking ref.
        """
        if self._ref_exists(base):
            return base
        if "/" not in base:
            remote_ref = f"origin/{base}"
            if self._ref_exists(remote_ref):
                return remote_ref
        return base

    def get_worktree_path(self, branch_name: str) -> Path | None:
        """Get the worktree path for a branch.

        Args:
            branch_name: The branch name

        Returns:
            Path to the worktree directory, or None if not using worktrees
        """
        return self._worktree_paths.get(branch_name)

    def list_worktrees(self) -> list[WorktreeInfo]:
        """List all git worktrees with metadata.

        Parses ``git worktree list --porcelain`` and cross-references with
        tracked worktrees for enriched metadata.

        Returns:
            List of WorktreeInfo objects for each worktree.
        """
        result = self._run_git("worktree", "list", "--porcelain", check=False)
        if result.returncode != 0:
            return []

        worktrees: list[WorktreeInfo] = []
        current_path: Path | None = None
        current_branch: str | None = None

        for line in result.stdout.split("\n"):
            line = line.strip()
            if line.startswith("worktree "):
                current_path = Path(line[len("worktree ") :])
                current_branch = None
            elif line.startswith("branch refs/heads/"):
                current_branch = line[len("branch refs/heads/") :]
            elif line == "" and current_path is not None and current_branch is not None:
                tracked = self._active_worktrees.get(current_branch)
                if tracked:
                    worktrees.append(tracked)
                else:
                    worktrees.append(
                        WorktreeInfo(
                            branch_name=current_branch,
                            worktree_path=current_path,
                        )
                    )
                current_path = None
                current_branch = None

        # Handle last entry if output doesn't end with blank line
        if current_path is not None and current_branch is not None:
            tracked = self._active_worktrees.get(current_branch)
            if tracked:
                worktrees.append(tracked)
            else:
                worktrees.append(
                    WorktreeInfo(
                        branch_name=current_branch,
                        worktree_path=current_path,
                    )
                )

        return worktrees

    async def merge_worktree_back(
        self,
        branch: str,
        target: str | None = None,
        cleanup: bool = True,
    ) -> MergeResult:
        """Merge a worktree branch back to target and optionally clean up.

        Args:
            branch: Branch name to merge.
            target: Target branch (default: base_branch from config).
            cleanup: If True, remove the worktree after successful merge.

        Returns:
            MergeResult with merge status.
        """
        merge_result = await self.safe_merge(branch, target)
        if merge_result.success and cleanup:
            self._remove_worktree(branch)
            self._active_worktrees.pop(branch, None)
        return merge_result

    def cleanup_all_worktrees(self) -> int:
        """Remove all tracked worktrees and prune stale entries.

        Returns:
            Number of worktrees removed.
        """
        removed = 0
        for branch in list(self._worktree_paths):
            self._remove_worktree(branch)
            removed += 1
        self._active_worktrees.clear()
        self._run_git("worktree", "prune", check=False)
        return removed

    async def create_track_branch(
        self,
        track: Track,
        goal: str,
        base_branch: str | None = None,
    ) -> str:
        """Create a feature branch for a track.

        If worktrees are enabled, creates a git worktree for isolated parallel
        work. Otherwise falls back to git checkout.

        Args:
            track: Development track
            goal: Goal description (for branch naming)
            base_branch: Branch to base off of

        Returns:
            Branch name
        """
        base = base_branch or self.config.base_branch

        branch_name = self._generate_branch_name(track, goal)

        if self.config.use_worktrees:
            return await self._create_worktree_branch(branch_name, base)
        else:
            return await self._create_checkout_branch(branch_name, base)

    async def _create_worktree_branch(self, branch_name: str, base: str) -> str:
        """Create an isolated git worktree for a branch.

        Each branch gets its own working directory, allowing true parallel
        work without any checkout conflicts.
        """
        # Sanitize branch name for directory path (replace / with -)
        dir_name = branch_name.replace("/", "-")
        worktree_path = self._worktree_dir / dir_name
        self._worktree_dir.mkdir(parents=True, exist_ok=True)

        base_ref = self._resolve_base_ref(base)

        if self.branch_exists(branch_name):
            logger.warning("Branch %s already exists", branch_name)
            if worktree_path.exists():
                logger.info("Worktree already exists at %s", worktree_path)
            else:
                # Add worktree for existing branch
                self._run_git(
                    "worktree",
                    "add",
                    str(worktree_path),
                    branch_name,
                    check=False,
                )
        else:
            # Create new branch with worktree in one command
            self._run_git(
                "worktree",
                "add",
                "-b",
                branch_name,
                str(worktree_path),
                base_ref,
            )
            logger.info("Created worktree branch: %s at %s", branch_name, worktree_path)

        self._active_branches.append(branch_name)
        self._worktree_paths[branch_name] = worktree_path
        self._active_worktrees[branch_name] = WorktreeInfo(
            branch_name=branch_name,
            worktree_path=worktree_path,
            created_at=datetime.now(timezone.utc),
        )
        return branch_name

    async def _create_checkout_branch(self, branch_name: str, base: str) -> str:
        """Create a branch using traditional git checkout (legacy mode)."""
        base_ref = self._resolve_base_ref(base)
        # Ensure we're on base branch
        current = self.get_current_branch()
        if current != base:
            self._run_git("checkout", base_ref)
            self._run_git("pull", "--rebase", "origin", base, check=False)

        # Create and checkout new branch
        if self.branch_exists(branch_name):
            logger.warning("Branch %s already exists, using it", branch_name)
            self._run_git("checkout", branch_name)
        else:
            self._run_git("checkout", "-b", branch_name)
            logger.info("Created branch: %s", branch_name)

        self._active_branches.append(branch_name)
        return branch_name

    async def create_track_branches(
        self,
        assignments: list[TrackAssignment],
    ) -> list[TrackAssignment]:
        """Create branches for all track assignments.

        Args:
            assignments: List of track assignments

        Returns:
            Updated assignments with branch names and worktree paths
        """
        for assignment in assignments:
            branch = await self.create_track_branch(
                track=assignment.goal.track,
                goal=assignment.goal.description,
            )
            assignment.branch_name = branch
            assignment.worktree_path = self.get_worktree_path(branch)

        # Return to base branch (only needed in checkout mode)
        if not self.config.use_worktrees:
            self._run_git("checkout", self.config.base_branch, check=False)

        return assignments

    async def detect_conflicts(
        self,
        branches: list[str],
        target_branch: str | None = None,
    ) -> list[ConflictReport]:
        """Detect potential merge conflicts between branches.

        Args:
            branches: List of branch names to check
            target_branch: Target branch for merge (default: main)

        Returns:
            List of conflict reports
        """
        target = target_branch or self.config.base_branch
        conflicts = []

        for branch in branches:
            if not self.branch_exists(branch):
                continue

            # Get files changed in this branch
            changed_files = self._get_branch_files(branch, target)

            # Check against other branches
            for other_branch in branches:
                if other_branch == branch or not self.branch_exists(other_branch):
                    continue

                other_files = self._get_branch_files(other_branch, target)
                overlap = set(changed_files) & set(other_files)

                if overlap:
                    # Determine severity
                    if len(overlap) > 5:
                        severity = "high"
                    elif len(overlap) > 2:
                        severity = "medium"
                    else:
                        severity = "low"

                    conflicts.append(
                        ConflictReport(
                            source_branch=branch,
                            target_branch=other_branch,
                            conflicting_files=list(overlap),
                            severity=severity,
                            resolution_hint=self._generate_resolution_hint(list(overlap)),
                        )
                    )

        return conflicts

    def _get_branch_files(self, branch: str, base: str) -> list[str]:
        """Get files changed in a branch relative to base."""
        result = self._run_git(
            "diff",
            "--name-only",
            f"{base}...{branch}",
            check=False,
        )
        if result.returncode != 0:
            return []
        return [f.strip() for f in result.stdout.split("\n") if f.strip()]

    def _generate_resolution_hint(self, conflicting_files: list[str]) -> str:
        """Generate a hint for resolving conflicts."""
        if any("test" in f.lower() for f in conflicting_files):
            return "Consider merging test changes separately"
        if any(f.endswith(".py") for f in conflicting_files):
            return "Review Python module changes carefully"
        return "Manual review recommended"

    async def safe_merge(
        self,
        source: str,
        target: str | None = None,
        dry_run: bool = False,
    ) -> MergeResult:
        """Merge a branch if safe.

        Args:
            source: Source branch to merge
            target: Target branch (default: main)
            dry_run: If True, only check if merge is possible

        Returns:
            MergeResult with status
        """
        target = target or self.config.base_branch

        if not self.branch_exists(source):
            return MergeResult(
                source_branch=source,
                target_branch=target,
                success=False,
                error=f"Branch {source} does not exist",
            )

        # Checkout target branch. In multi-worktree setups this can fail when
        # the target branch is already checked out elsewhere; report cleanly
        # instead of raising so orchestration can continue.
        checkout_result = self._run_git("checkout", target, check=False)
        if checkout_result.returncode != 0:
            checkout_error = (checkout_result.stderr or checkout_result.stdout).strip()
            return MergeResult(
                source_branch=source,
                target_branch=target,
                success=False,
                error=f"Failed to checkout target branch {target}: {checkout_error}",
            )
        self._run_git("pull", "--rebase", "origin", target, check=False)

        if dry_run:
            # Check if merge would succeed
            result = self._run_git("merge", "--no-commit", "--no-ff", source, check=False)
            self._run_git("merge", "--abort", check=False)

            return MergeResult(
                source_branch=source,
                target_branch=target,
                success=result.returncode == 0,
                conflicts=(
                    self._parse_merge_conflicts(result.stderr) if result.returncode != 0 else []
                ),
            )

        # Perform actual merge
        result = self._run_git(
            "merge",
            "--no-ff",
            "-m",
            f"Merge {source} into {target}",
            source,
            check=False,
        )

        if result.returncode != 0:
            conflicts = self._parse_merge_conflicts(result.stderr)
            self._run_git("merge", "--abort", check=False)

            return MergeResult(
                source_branch=source,
                target_branch=target,
                success=False,
                error="Merge conflicts detected",
                conflicts=conflicts,
            )

        # Get commit SHA
        sha_result = self._run_git("rev-parse", "HEAD")
        commit_sha = sha_result.stdout.strip()

        logger.info("Merged %s into %s: %s", source, target, commit_sha[:8])

        return MergeResult(
            source_branch=source,
            target_branch=target,
            success=True,
            commit_sha=commit_sha,
        )

    def _parse_merge_conflicts(self, stderr: str) -> list[str]:
        """Parse conflicting files from git merge stderr."""
        conflicts = []
        for line in stderr.split("\n"):
            if "CONFLICT" in line and "Merge conflict in" in line:
                # Extract filename
                parts = line.split("Merge conflict in")
                if len(parts) > 1:
                    conflicts.append(parts[1].strip())
        return conflicts

    @staticmethod
    def _compute_waves(assignments: list[TrackAssignment]) -> list[list[TrackAssignment]]:
        """Topologically sort assignments into dependency waves.

        Wave 0: assignments with no dependencies (or no depends_on field on goal).
        Wave N: assignments whose dependencies are all in waves 0..N-1.

        Falls back to a single wave (all parallel) if no dependency data exists.
        """
        # Build id -> assignment map using goal.id
        by_id: dict[str, TrackAssignment] = {}
        for a in assignments:
            goal_id = getattr(a.goal, "id", None)
            if goal_id:
                by_id[goal_id] = a

        # Check if any assignment has dependencies (via goal.focus_areas used as dep hints)
        has_deps = any(
            getattr(a.goal, "dependencies", None) or getattr(a.goal, "depends_on", None)
            for a in assignments
        )
        if not has_deps:
            return [assignments]

        assigned: set[str] = set()
        waves: list[list[TrackAssignment]] = []
        remaining = list(assignments)

        for _ in range(len(assignments) + 1):
            if not remaining:
                break

            wave: list[TrackAssignment] = []
            still_remaining: list[TrackAssignment] = []

            for a in remaining:
                deps = (
                    getattr(a.goal, "dependencies", None)
                    or getattr(a.goal, "depends_on", None)
                    or []
                )
                unmet = [d for d in deps if d in by_id and d not in assigned]
                if not unmet:
                    wave.append(a)
                else:
                    still_remaining.append(a)

            if not wave:
                wave = still_remaining
                still_remaining = []

            waves.append(wave)
            for a in wave:
                goal_id = getattr(a.goal, "id", None)
                if goal_id:
                    assigned.add(goal_id)
            remaining = still_remaining

        return waves

    async def coordinate_parallel_work(
        self,
        assignments: list[TrackAssignment],
        run_nomic_fn: Callable[[TrackAssignment], Any] | None = None,
    ) -> CoordinationResult:
        """Run nomic loops in parallel on separate branches.

        Assignments are grouped into dependency waves. Tasks within a wave
        execute in parallel; waves execute sequentially.

        Args:
            assignments: Track assignments with goals
            run_nomic_fn: Function to run nomic loop on a branch

        Returns:
            CoordinationResult with status
        """
        start_time = datetime.now(timezone.utc)

        # Create branches for all assignments
        assignments = await self.create_track_branches(assignments)

        # Check for conflicts upfront
        branches = [a.branch_name for a in assignments if a.branch_name]
        conflicts = await self.detect_conflicts(branches)

        for conflict in conflicts:
            logger.warning(
                "potential_conflict source=%s target=%s files=%s",
                conflict.source_branch,
                conflict.target_branch,
                conflict.conflicting_files,
            )
            if self.on_conflict:
                self.on_conflict(conflict)

        # Semantic conflict detection (AST-based)
        if self.semantic_conflict_detector and branches:
            try:
                semantic_conflicts = self.semantic_conflict_detector.detect(
                    branches,
                    self.config.base_branch,
                )
                for sc in semantic_conflicts:
                    if sc.confidence > 0.7:
                        logger.warning(
                            "semantic_conflict type=%s confidence=%.2f files=%s: %s",
                            sc.conflict_type.value,
                            sc.confidence,
                            sc.affected_files,
                            sc.description[:100],
                        )
            except (RuntimeError, ValueError, OSError) as e:
                logger.debug("Semantic conflict detection failed: %s", e)

        # Group into dependency waves and execute wave-by-wave
        if run_nomic_fn:
            waves = self._compute_waves(assignments)
            logger.info(
                "coordinate_waves total=%d waves=%d",
                len(assignments),
                len(waves),
            )

            for wave_idx, wave in enumerate(waves):
                tasks = []
                for assignment in wave:
                    if assignment.branch_name:
                        task = asyncio.create_task(self._run_assignment(assignment, run_nomic_fn))
                        tasks.append(task)

                try:
                    await asyncio.gather(*tasks, return_exceptions=True)
                except BaseException:
                    self.cleanup_all_worktrees()
                    raise

                logger.info(
                    "wave_completed wave=%d/%d tasks=%d",
                    wave_idx + 1,
                    len(waves),
                    len(wave),
                )

        # Attempt to merge completed branches
        merged_count = 0
        if self.config.auto_merge_safe:
            for assignment in assignments:
                if assignment.status == "completed" and assignment.branch_name:
                    if self.config.require_tests_pass:
                        # Test-gated merge: pre/post tests + auto-revert
                        merge_result = await self.safe_merge_with_gate(
                            assignment.branch_name,
                            auto_revert=True,
                        )
                    else:
                        merge_result = await self.safe_merge(
                            assignment.branch_name,
                            dry_run=False,
                        )
                    if merge_result.success:
                        assignment.status = "merged"
                        merged_count += 1
                    else:
                        logger.warning(
                            "Could not auto-merge %s: %s",
                            assignment.branch_name,
                            merge_result.error,
                        )

        # Compute result
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        completed = sum(1 for a in assignments if a.status in ("completed", "merged"))
        failed = sum(1 for a in assignments if a.status == "failed")

        return CoordinationResult(
            total_branches=len(assignments),
            completed_branches=completed,
            failed_branches=failed,
            merged_branches=merged_count,
            assignments=assignments,
            duration_seconds=duration,
            success=failed == 0,
            summary=self._generate_summary(assignments),
        )

    async def _run_assignment(
        self,
        assignment: TrackAssignment,
        run_nomic_fn: Callable[[TrackAssignment], Any],
    ) -> None:
        """Run a single assignment on its branch.

        When worktrees are enabled, work happens in the worktree directory
        without needing to checkout/switch branches in the main repo.
        """
        if not assignment.branch_name:
            return

        assignment.status = "running"
        assignment.started_at = datetime.now(timezone.utc)

        try:
            if self.config.use_worktrees:
                # No checkout needed -- worktree is already on the branch
                worktree_path = self.get_worktree_path(assignment.branch_name)
                if worktree_path:
                    logger.info("Running assignment in worktree: %s", worktree_path)
            else:
                # Legacy: checkout the branch in main repo
                self._run_git("checkout", assignment.branch_name)

            # Run the nomic loop
            result = await run_nomic_fn(assignment)

            assignment.status = "completed"
            assignment.result = result

        except Exception as e:  # noqa: BLE001 - external callback; must not crash coordinator
            logger.warning("Assignment failed: %s", e)
            assignment.status = "failed"
            assignment.error = f"Failed: {type(e).__name__}"

        finally:
            assignment.completed_at = datetime.now(timezone.utc)
            if not self.config.use_worktrees:
                # Only need to switch back in checkout mode
                self._run_git("checkout", self.config.base_branch, check=False)

    def _generate_summary(self, assignments: list[TrackAssignment]) -> str:
        """Generate a summary of coordination result."""
        lines = ["Branch Coordination Summary:", ""]

        by_status: dict[str, list[str]] = {}
        for a in assignments:
            if a.status not in by_status:
                by_status[a.status] = []
            by_status[a.status].append(f"{a.goal.track.value}: {a.goal.description[:40]}")

        for status, items in by_status.items():
            icon = {"completed": "+", "merged": "++", "failed": "!", "running": "~"}.get(
                status, "-"
            )
            lines.append(f"{status.upper()}:")
            for item in items:
                lines.append(f"  {icon} {item}")
            lines.append("")

        return "\n".join(lines)

    def _slugify(self, text: str) -> str:
        """Convert text to a branch-name-friendly slug."""
        import re

        slug = text.lower()
        slug = re.sub(r"[^a-z0-9]+", "-", slug)
        slug = slug.strip("-")
        return slug

    def _generate_branch_name(self, track: Track, goal: str) -> str:
        """Generate a collision-resistant branch name for a track/goal pair."""
        goal_slug = self._slugify(goal)[:30] or "task"
        timestamp = datetime.now(timezone.utc).strftime("%m%d-%H%M%S")
        unique_suffix = uuid.uuid4().hex[:6]
        return f"{self.config.branch_prefix}/{track.value}-{goal_slug}-{timestamp}-{unique_suffix}"

    def cleanup_worktrees(self) -> int:
        """Remove all active worktrees and prune stale entries.

        Returns:
            Number of worktrees removed.
        """
        removed = 0
        for branch in list(self._worktree_paths):
            self._remove_worktree(branch)
            removed += 1
        # Prune any stale worktree entries that git still tracks
        self._run_git("worktree", "prune", check=False)
        return removed

    def cleanup_branches(self, branches: list[str] | None = None) -> int:
        """Delete merged or stale branches and their worktrees.

        Args:
            branches: Specific branches to clean up (default: all active)

        Returns:
            Number of branches deleted
        """
        branches = branches or list(self._active_branches)
        deleted = 0

        for branch in branches:
            if not self.branch_exists(branch):
                # Still try to remove worktree if it exists
                self._remove_worktree(branch)
                continue

            # Check if merged into main
            result = self._run_git(
                "branch",
                "--merged",
                self.config.base_branch,
                check=False,
            )
            merged_branches = result.stdout.strip().split("\n")

            if branch in merged_branches or f"  {branch}" in merged_branches:
                # Remove worktree first, then branch
                self._remove_worktree(branch)
                self._run_git("branch", "-d", branch, check=False)
                deleted += 1
                logger.info("Deleted merged branch: %s", branch)

        return deleted

    async def safe_merge_with_gate(
        self,
        source: str,
        target: str | None = None,
        test_paths: list[str] | None = None,
        auto_revert: bool = True,
        test_timeout: int = 300,
    ) -> MergeResult:
        """Merge a branch with test-gated verification.

        1. Dry-run merge check
        2. Run pre-merge tests on the source branch
        3. Actual merge (--no-ff)
        4. Run post-merge tests on target
        5. Auto-revert if post-merge tests fail

        Uses ``AutonomousOrchestrator._infer_test_paths`` as a fallback
        when *test_paths* is not provided.

        Args:
            source: Source branch to merge
            target: Target branch (default: base_branch from config)
            test_paths: Test paths to run pre/post merge
            auto_revert: Whether to auto-revert on post-merge test failure
            test_timeout: Maximum test execution time in seconds

        Returns:
            MergeResult with merge status
        """
        target = target or self.config.base_branch

        if not self.branch_exists(source):
            return MergeResult(
                source_branch=source,
                target_branch=target,
                success=False,
                error=f"Branch {source} does not exist",
            )

        # Infer test paths if not provided
        resolved_test_paths = test_paths
        if not resolved_test_paths:
            try:
                from aragora.nomic.autonomous_orchestrator import AutonomousOrchestrator

                changed_files = self._get_branch_files(source, target)
                resolved_test_paths = AutonomousOrchestrator._infer_test_paths(changed_files)
            except ImportError:
                logger.debug("AutonomousOrchestrator not available for test path inference")
                resolved_test_paths = []

        # Step 1: Dry-run merge check
        dry_result = await self.safe_merge(source, target, dry_run=True)
        if not dry_result.success:
            return MergeResult(
                source_branch=source,
                target_branch=target,
                success=False,
                error=dry_result.error or "Dry-run merge failed: conflicts detected",
                conflicts=dry_result.conflicts,
            )

        # Step 2: Pre-merge tests on source branch
        if resolved_test_paths:
            worktree_path = self._worktree_paths.get(source)
            cwd = worktree_path if worktree_path else self.repo_path
            cmd = ["python", "-m", "pytest"] + resolved_test_paths + ["--tb=short", "-q"]

            try:
                pre_result = await asyncio.wait_for(
                    asyncio.to_thread(
                        subprocess.run,
                        cmd,
                        capture_output=True,
                        text=True,
                        cwd=cwd,
                    ),
                    timeout=test_timeout,
                )
                if pre_result.returncode != 0:
                    return MergeResult(
                        source_branch=source,
                        target_branch=target,
                        success=False,
                        error="Pre-merge tests failed",
                    )
            except asyncio.TimeoutError:
                return MergeResult(
                    source_branch=source,
                    target_branch=target,
                    success=False,
                    error=f"Pre-merge tests timed out after {test_timeout}s",
                )

        # Step 3: Actual merge (--no-ff)
        checkout_result = self._run_git("checkout", target, check=False)
        if checkout_result.returncode != 0:
            checkout_error = (checkout_result.stderr or checkout_result.stdout).strip()
            return MergeResult(
                source_branch=source,
                target_branch=target,
                success=False,
                error=f"Failed to checkout target branch {target}: {checkout_error}",
            )
        self._run_git("pull", "--rebase", "origin", target, check=False)

        merge_proc = self._run_git(
            "merge",
            "--no-ff",
            "-m",
            f"Merge {source} into {target}",
            source,
            check=False,
        )

        if merge_proc.returncode != 0:
            conflicts = self._parse_merge_conflicts(merge_proc.stderr)
            self._run_git("merge", "--abort", check=False)
            return MergeResult(
                source_branch=source,
                target_branch=target,
                success=False,
                error="Merge failed",
                conflicts=conflicts,
            )

        sha_result = self._run_git("rev-parse", "HEAD")
        commit_sha = sha_result.stdout.strip()

        # Step 4: Post-merge tests on target
        if resolved_test_paths:
            cmd = ["python", "-m", "pytest"] + resolved_test_paths + ["--tb=short", "-q"]
            try:
                post_result = await asyncio.wait_for(
                    asyncio.to_thread(
                        subprocess.run,
                        cmd,
                        capture_output=True,
                        text=True,
                        cwd=self.repo_path,
                    ),
                    timeout=test_timeout,
                )
                post_passed = post_result.returncode == 0
            except asyncio.TimeoutError:
                post_passed = False

            # Step 5: Auto-revert if post-merge tests fail
            if not post_passed and auto_revert:
                revert_result = self._run_git(
                    "revert", "-m", "1", "--no-edit", commit_sha, check=False
                )
                revert_msg = " (reverted)" if revert_result.returncode == 0 else " (revert failed)"
                logger.warning(
                    "merge_gate_post_failed source=%s sha=%s%s",
                    source,
                    commit_sha[:8],
                    revert_msg,
                )
                return MergeResult(
                    source_branch=source,
                    target_branch=target,
                    success=False,
                    commit_sha=commit_sha,
                    error=f"Post-merge tests failed{revert_msg}",
                )
            elif not post_passed:
                logger.warning(
                    "merge_gate_post_failed source=%s sha=%s (no revert)",
                    source,
                    commit_sha[:8],
                )
                return MergeResult(
                    source_branch=source,
                    target_branch=target,
                    success=False,
                    commit_sha=commit_sha,
                    error="Post-merge tests failed",
                )

        logger.info("safe_merge_with_gate source=%s sha=%s", source, commit_sha[:8])
        return MergeResult(
            source_branch=source,
            target_branch=target,
            success=True,
            commit_sha=commit_sha,
        )

    def _remove_worktree(self, branch_name: str) -> None:
        """Remove a git worktree for a branch if it exists."""
        worktree_path = self._worktree_paths.pop(branch_name, None)
        self._active_worktrees.pop(branch_name, None)
        if worktree_path and worktree_path.exists():
            self._run_git("worktree", "remove", str(worktree_path), check=False)
            logger.info("Removed worktree: %s", worktree_path)
        elif branch_name in self._active_branches:
            # Try to remove by convention path
            dir_name = branch_name.replace("/", "-")
            fallback_path = self._worktree_dir / dir_name
            if fallback_path.exists():
                self._run_git("worktree", "remove", str(fallback_path), check=False)
                logger.info("Removed worktree (fallback): %s", fallback_path)


__all__ = [
    "BranchCoordinator",
    "BranchCoordinatorConfig",
    "TrackAssignment",
    "WorktreeInfo",
    "ConflictReport",
    "MergeResult",
    "CoordinationResult",
]
