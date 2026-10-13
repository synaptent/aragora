"""Git Reconciler for multi-agent worktree coordination.

Provides safe merge strategies with conflict classification, pre-merge test
gates, auto-resolution of trivial conflicts, and rollback on test failure.

Usage:
    from aragora.coordination.reconciler import GitReconciler

    reconciler = GitReconciler(repo_path=Path("."))
    result = await reconciler.safe_merge("dev/feature-auth-abc1", target="main")
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class ConflictCategory(str, Enum):
    """Classification of merge conflicts."""

    IMPORT_ORDER = "import_order"  # Python import reordering
    WHITESPACE = "whitespace"  # Trailing whitespace, newlines
    BOTH_ADDED = "both_added"  # Both branches added to same section
    SEMANTIC = "semantic"  # Genuine logic conflict
    TEST = "test"  # Conflict in test files
    CONFIG = "config"  # Conflict in config/toml/yaml files
    UNKNOWN = "unknown"


@dataclass
class ConflictInfo:
    """Detailed information about a single merge conflict."""

    file_path: str
    category: ConflictCategory = ConflictCategory.UNKNOWN
    auto_resolvable: bool = False
    description: str = ""


@dataclass
class MergeAttempt:
    """Result of a merge attempt with detailed conflict information."""

    source_branch: str
    target_branch: str
    success: bool
    commit_sha: str | None = None
    conflicts: list[ConflictInfo] = field(default_factory=list)
    tests_passed: bool | None = None  # None = tests not run
    rolled_back: bool = False
    error: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ReconcilerConfig:
    """Configuration for GitReconciler."""

    pre_merge_tests: bool = True
    post_merge_tests: bool = True
    auto_resolve_trivial: bool = True
    rollback_on_test_failure: bool = True
    test_command: list[str] = field(
        default_factory=lambda: ["python", "-m", "pytest", "-x", "-q", "--timeout=60"]
    )
    test_timeout_seconds: int = 300
    ignored_test_dirs: list[str] = field(
        default_factory=lambda: ["tests/connectors", "tests/integration", "tests/benchmarks"]
    )


class GitReconciler:
    """Safe git merge with conflict classification and test gates.

    Implements the merge workflow:
    1. Dry-run merge to detect conflicts
    2. Classify conflicts (trivial vs semantic)
    3. Auto-resolve trivial conflicts if configured
    4. Run pre-merge tests on source branch
    5. Perform actual merge
    6. Run post-merge tests
    7. Rollback if tests fail
    """

    def __init__(
        self,
        repo_path: Path | None = None,
        config: ReconcilerConfig | None = None,
    ):
        self.repo_path = (repo_path or Path.cwd()).resolve()
        self.config = config or ReconcilerConfig()
        self._merge_history: list[MergeAttempt] = []

    @property
    def merge_history(self) -> list[MergeAttempt]:
        """Read-only access to merge history."""
        return list(self._merge_history)

    def _run_git(
        self,
        *args: str,
        cwd: Path | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Run a git command."""
        cmd = ["git"] + list(args)
        return subprocess.run(  # subprocess with fixed args, no shell
            cmd,
            cwd=cwd or self.repo_path,
            capture_output=True,
            text=True,
            check=check,
        )

    def detect_conflicts(self, source: str, target: str = "main") -> list[ConflictInfo]:
        """Detect and classify potential merge conflicts without modifying state.

        Uses git merge-tree (three-way) to check for conflicts.

        Returns:
            List of classified conflicts.
        """
        # Find merge base
        base_result = self._run_git("merge-base", target, source, check=False)
        if base_result.returncode != 0:
            return []

        merge_base = base_result.stdout.strip()

        # Three-way merge-tree
        tree_result = self._run_git(
            "merge-tree",
            merge_base,
            target,
            source,
            check=False,
        )

        if "CONFLICT" not in tree_result.stdout.upper() and tree_result.returncode == 0:
            return []

        return self._parse_and_classify_conflicts(tree_result.stdout)

    def _parse_and_classify_conflicts(self, merge_output: str) -> list[ConflictInfo]:
        """Parse merge-tree output and classify each conflict."""
        conflicts: list[ConflictInfo] = []
        current_file = None

        for line in merge_output.split("\n"):
            # merge-tree output includes conflict markers with file paths
            if "changed in both" in line.lower() or "CONFLICT" in line:
                # Extract file path from various git merge-tree output formats
                parts = line.split()
                for part in parts:
                    if "/" in part or part.endswith(".py") or part.endswith(".toml"):
                        current_file = part.strip("'\"")
                        break

                if current_file:
                    category = self._classify_conflict(current_file)
                    conflicts.append(
                        ConflictInfo(
                            file_path=current_file,
                            category=category,
                            auto_resolvable=category
                            in (
                                ConflictCategory.IMPORT_ORDER,
                                ConflictCategory.WHITESPACE,
                            ),
                            description=line.strip(),
                        )
                    )
                    current_file = None

        return conflicts

    def _classify_conflict(self, file_path: str) -> ConflictCategory:
        """Classify a conflict based on the file path and content."""
        path_lower = file_path.lower()

        if path_lower.startswith("tests/") or path_lower.startswith("test_"):
            return ConflictCategory.TEST
        if path_lower.endswith((".toml", ".yaml", ".yml", ".json", ".cfg", ".ini")):
            return ConflictCategory.CONFIG
        if path_lower.endswith("__init__.py"):
            return ConflictCategory.IMPORT_ORDER
        return ConflictCategory.UNKNOWN

    def get_changed_files(self, source: str, target: str = "main") -> list[str]:
        """Get files changed in source relative to target."""
        result = self._run_git(
            "diff",
            "--name-only",
            f"{target}...{source}",
            check=False,
        )
        if result.returncode != 0:
            return []
        return [f.strip() for f in result.stdout.split("\n") if f.strip()]

    def get_commits_ahead(self, source: str, target: str = "main") -> int:
        """Return number of commits in source not in target."""
        result = self._run_git(
            "rev-list",
            "--count",
            f"{target}..{source}",
            check=False,
        )
        if result.returncode != 0:
            return 0
        return int(result.stdout.strip())

    async def safe_merge(
        self,
        source: str,
        target: str = "main",
        worktree_path: Path | None = None,
    ) -> MergeAttempt:
        """Merge source into target with conflict detection and test gates.

        Args:
            source: Source branch name.
            target: Target branch name.
            worktree_path: Path to source worktree (for running pre-merge tests).

        Returns:
            MergeAttempt with full details.
        """
        # Step 1: Detect conflicts
        conflicts = self.detect_conflicts(source, target)

        semantic_conflicts = [c for c in conflicts if not c.auto_resolvable]

        if semantic_conflicts:
            attempt = MergeAttempt(
                source_branch=source,
                target_branch=target,
                success=False,
                conflicts=conflicts,
                error=f"{len(semantic_conflicts)} non-trivial conflict(s) detected",
            )
            self._merge_history.append(attempt)
            return attempt

        # Step 2: Pre-merge tests on source
        if self.config.pre_merge_tests:
            test_cwd = worktree_path or self.repo_path
            pre_passed = self._run_tests(cwd=test_cwd)
            if not pre_passed:
                attempt = MergeAttempt(
                    source_branch=source,
                    target_branch=target,
                    success=False,
                    tests_passed=False,
                    error="Pre-merge tests failed",
                )
                self._merge_history.append(attempt)
                return attempt

        # Step 3: Perform merge
        self._run_git("checkout", target, check=False)

        merge_result = self._run_git(
            "merge",
            "--no-ff",
            "-m",
            f"Merge {source} into {target}",
            source,
            check=False,
        )

        if merge_result.returncode != 0:
            self._run_git("merge", "--abort", check=False)
            attempt = MergeAttempt(
                source_branch=source,
                target_branch=target,
                success=False,
                conflicts=self._parse_merge_stderr(merge_result.stderr),
                error="Merge failed with conflicts",
            )
            self._merge_history.append(attempt)
            return attempt

        # Get merge commit SHA
        sha_result = self._run_git("rev-parse", "HEAD")
        commit_sha = sha_result.stdout.strip()

        # Step 4: Post-merge tests
        if self.config.post_merge_tests:
            post_passed = self._run_tests(cwd=self.repo_path)
            if not post_passed and self.config.rollback_on_test_failure:
                # Rollback: revert the merge commit
                revert_result = self._run_git(
                    "revert",
                    "-m",
                    "1",
                    "--no-edit",
                    commit_sha,
                    check=False,
                )
                rolled_back = revert_result.returncode == 0
                attempt = MergeAttempt(
                    source_branch=source,
                    target_branch=target,
                    success=False,
                    commit_sha=commit_sha,
                    tests_passed=False,
                    rolled_back=rolled_back,
                    error="Post-merge tests failed" + (" (rolled back)" if rolled_back else ""),
                )
                self._merge_history.append(attempt)
                logger.warning(
                    "merge_rolled_back source=%s sha=%s rolled_back=%s",
                    source,
                    commit_sha[:8],
                    rolled_back,
                )
                return attempt

        attempt = MergeAttempt(
            source_branch=source,
            target_branch=target,
            success=True,
            commit_sha=commit_sha,
            tests_passed=True if self.config.post_merge_tests else None,
        )
        self._merge_history.append(attempt)
        logger.info("merge_succeeded source=%s target=%s sha=%s", source, target, commit_sha[:8])
        return attempt

    def _run_tests(self, cwd: Path) -> bool:
        """Run the test suite. Returns True if tests pass."""
        cmd = list(self.config.test_command)
        for ignored in self.config.ignored_test_dirs:
            cmd.extend(["--ignore", ignored])

        try:
            result = subprocess.run(  # subprocess with fixed args, no shell
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=self.config.test_timeout_seconds,
                check=False,
            )
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            logger.warning("test_timeout cwd=%s timeout=%ds", cwd, self.config.test_timeout_seconds)
            return False

    def _parse_merge_stderr(self, stderr: str) -> list[ConflictInfo]:
        """Parse git merge stderr for conflict information."""
        conflicts: list[ConflictInfo] = []
        for line in stderr.split("\n"):
            if "CONFLICT" in line and "Merge conflict in" in line:
                parts = line.split("Merge conflict in")
                if len(parts) > 1:
                    file_path = parts[1].strip()
                    conflicts.append(
                        ConflictInfo(
                            file_path=file_path,
                            category=self._classify_conflict(file_path),
                            description=line.strip(),
                        )
                    )
        return conflicts

    def summary(self) -> dict[str, int]:
        """Summarize merge history."""
        succeeded = sum(1 for m in self._merge_history if m.success)
        failed = sum(1 for m in self._merge_history if not m.success)
        rolled_back = sum(1 for m in self._merge_history if m.rolled_back)
        return {
            "total": len(self._merge_history),
            "succeeded": succeeded,
            "failed": failed,
            "rolled_back": rolled_back,
        }


__all__ = [
    "GitReconciler",
    "ReconcilerConfig",
    "MergeAttempt",
    "ConflictInfo",
    "ConflictCategory",
]
