"""Oracle-driven validation and quality scoring for task decompositions.

``TaskDecomposer`` (``aragora.nomic.task_decomposer``) inherits these methods: they check
that sibling subtasks do not share files, run lightweight existence and syntax checks on a
subtask's file scope, and score a decomposition for independence, granularity and coverage.
Import the decomposer from ``aragora.nomic.task_decomposer``.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys

from aragora.nomic.task_decomposer_models import (
    DecompositionQuality,
    FileConflict,
    OracleResult,
    SubTask,
)

# The facade's logger name, so log filters and caplog assertions keyed on
# "aragora.nomic.task_decomposer" still see records from the moved methods.
logger = logging.getLogger("aragora.nomic.task_decomposer")


class TaskDecomposerValidationMixin:
    """File-independence, oracle and quality checks inherited by ``TaskDecomposer``."""

    # =========================================================================
    # Oracle-driven validation (Tier 3)
    # =========================================================================

    def validate_file_independence(self, subtasks: list[SubTask]) -> list[FileConflict]:
        """Check that no two sibling subtasks share the same file in their file_scope.

        When subtasks share files, they cannot safely execute in parallel.
        This method detects overlaps and returns a list of conflicts so the
        caller can merge conflicting subtasks or mark them as sequential.

        Args:
            subtasks: List of subtasks to check for file overlaps.

        Returns:
            List of FileConflict objects describing which files overlap
            and which subtasks are involved. Empty list means all subtasks
            are file-independent and safe for parallel execution.
        """
        # Build a mapping from file -> list of subtask IDs that reference it
        file_to_subtasks: dict[str, list[str]] = {}
        for subtask in subtasks:
            for file_path in subtask.file_scope:
                normalized = file_path.rstrip("/")
                if normalized not in file_to_subtasks:
                    file_to_subtasks[normalized] = []
                file_to_subtasks[normalized].append(subtask.id)

        # Collect conflicts (files referenced by 2+ subtasks)
        conflicts: list[FileConflict] = []
        for file_path, subtask_ids in file_to_subtasks.items():
            if len(subtask_ids) > 1:
                conflicts.append(FileConflict(file_path=file_path, subtask_ids=list(subtask_ids)))

        if conflicts:
            logger.info(
                "file_independence_conflicts count=%d files=%s",
                len(conflicts),
                [c.file_path for c in conflicts],
            )
        else:
            logger.debug(
                "file_independence_ok subtasks=%d all_independent",
                len(subtasks),
            )

        return conflicts

    def validate_with_oracle(
        self,
        subtask: SubTask,
        worktree_path: str | None = None,
    ) -> OracleResult:
        """Run lightweight oracle checks on a subtask's file scope.

        Validates that the files referenced in the subtask's file_scope are
        coherent before agent execution begins. Checks include:
        - File existence and readability
        - Python syntax validation via ``ast.parse``

        This is an optional enhancement -- failures here indicate the task
        scope may reference non-existent or malformed files, but do not
        block execution.

        Args:
            subtask: The subtask whose file_scope to validate.
            worktree_path: Optional worktree root to resolve files against.
                If not provided, files are checked relative to cwd.

        Returns:
            OracleResult with validation status, errors, and checked files.
        """
        errors: list[str] = []
        checked_files: list[str] = []
        base_path = worktree_path or os.getcwd()

        for file_path in subtask.file_scope:
            # Skip directory-only scopes (e.g. "aragora/debate/")
            if file_path.endswith("/"):
                continue

            full_path = os.path.join(base_path, file_path)
            checked_files.append(file_path)

            # Check existence and readability
            if not os.path.isfile(full_path):
                errors.append(f"File not found: {file_path}")
                continue

            if not os.access(full_path, os.R_OK):
                errors.append(f"File not readable: {file_path}")
                continue

            # Python syntax check
            if file_path.endswith(".py"):
                try:
                    result = subprocess.run(  # noqa: S603 -- subprocess with fixed args, no shell
                        [
                            sys.executable,
                            "-c",
                            f"import ast; ast.parse(open({full_path!r}).read())",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if result.returncode != 0:
                        stderr = result.stderr.strip()
                        errors.append(f"Syntax error in {file_path}: {stderr[:200]}")
                except subprocess.TimeoutExpired:
                    errors.append(f"Syntax check timed out: {file_path}")
                except OSError as e:
                    errors.append(f"Syntax check failed for {file_path}: {e}")

        valid = len(errors) == 0
        if not valid:
            logger.info(
                "oracle_validation_failed subtask=%s errors=%d: %s",
                subtask.id,
                len(errors),
                errors[:3],
            )
        else:
            logger.debug(
                "oracle_validation_passed subtask=%s checked=%d files",
                subtask.id,
                len(checked_files),
            )

        return OracleResult(valid=valid, errors=errors, checked_files=checked_files)

    def score_decomposition(
        self,
        subtasks: list[SubTask],
        original_file_scope: list[str] | None = None,
    ) -> DecompositionQuality:
        """Score the quality of a decomposition.

        Evaluates the subtask set on three dimensions:
        - **File independence** (no overlaps): penalizes shared files
        - **Granularity** (1-5 files per task): rewards focused subtasks
        - **Coverage** (union of scopes covers original goal): rewards completeness

        Args:
            subtasks: List of subtasks to score.
            original_file_scope: Optional list of files from the original goal.
                Used to compute coverage_ratio. If not provided, coverage
                is estimated from the subtask union.

        Returns:
            DecompositionQuality with score (0.0-1.0) and component metrics.
        """
        if not subtasks:
            return DecompositionQuality(
                score=0.0, file_conflicts=0, avg_scope_size=0.0, coverage_ratio=0.0
            )

        # File independence score
        conflicts = self.validate_file_independence(subtasks)
        file_conflicts = len(conflicts)
        # Penalize: 0 conflicts = 1.0, each conflict reduces by 0.15
        independence_score = max(0.0, 1.0 - file_conflicts * 0.15)

        # Granularity score: ideal is 1-5 files per subtask
        scope_sizes = [len(s.file_scope) for s in subtasks]
        avg_scope_size = sum(scope_sizes) / len(scope_sizes) if scope_sizes else 0.0
        # Score: 1-5 files = 1.0, 0 files = 0.5 (no scope defined), >5 = decreasing
        if avg_scope_size == 0:
            granularity_score = 0.5  # No file scope defined is neutral
        elif 1 <= avg_scope_size <= 5:
            granularity_score = 1.0
        elif avg_scope_size > 5:
            # Use a steeper drop for oversized scopes so broad subtasks are
            # materially penalized in the combined quality score.
            granularity_score = max(0.1, 1.0 - (avg_scope_size - 5) * 0.15)
        else:
            granularity_score = 0.5

        # Coverage score
        all_subtask_files: set[str] = set()
        for s in subtasks:
            all_subtask_files.update(f.rstrip("/") for f in s.file_scope)

        if original_file_scope:
            original_set = {f.rstrip("/") for f in original_file_scope}
            if original_set:
                covered = all_subtask_files & original_set
                coverage_ratio = len(covered) / len(original_set)
            else:
                coverage_ratio = 1.0
        else:
            # Without an original scope, use subtask count as proxy
            # More subtasks with files = better coverage
            has_scope = sum(1 for s in subtasks if s.file_scope)
            coverage_ratio = has_scope / len(subtasks) if subtasks else 0.0

        # Weighted combination
        score = independence_score * 0.4 + granularity_score * 0.3 + coverage_ratio * 0.3

        logger.info(
            "decomposition_quality score=%.2f independence=%.2f granularity=%.2f "
            "coverage=%.2f conflicts=%d avg_scope=%.1f",
            score,
            independence_score,
            granularity_score,
            coverage_ratio,
            file_conflicts,
            avg_scope_size,
        )

        return DecompositionQuality(
            score=round(score, 3),
            file_conflicts=file_conflicts,
            avg_scope_size=round(avg_scope_size, 2),
            coverage_ratio=round(coverage_ratio, 3),
        )
