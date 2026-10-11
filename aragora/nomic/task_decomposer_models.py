"""Data models for task decomposition: subtasks, file conflicts, oracle results,
decomposition quality and the decomposition result.

Import them from ``aragora.nomic.task_decomposer``, which re-exports every name here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _sanitize_file_scope_entries(values: list[Any]) -> list[str]:
    from aragora.swarm.spec import SwarmSpec

    return [
        normalized for path in values if (normalized := SwarmSpec.sanitize_file_scope_entry(path))
    ]


@dataclass
class SubTask:
    """A subtask extracted from a larger task.

    Supports hierarchical goal trees via parent_id/depth:
    - parent_id: ID of the parent subtask (None for root-level)
    - depth: Nesting level (0 = root, 1 = child of root, etc.)
    - children: Populated by TaskDecomposition.build_tree()
    """

    id: str
    title: str
    description: str
    dependencies: list[str] = field(default_factory=list)
    estimated_complexity: str = "low"  # low, medium, high
    file_scope: list[str] = field(default_factory=list)
    success_criteria: dict[str, Any] = field(default_factory=dict)
    """Measurable success criteria, e.g. {"test_pass_rate": ">0.95", "lint_errors": "==0"}.
    Keys map to MetricSnapshot fields. Values are targets like ">0.9", "==0", "<=10"."""
    parent_id: str | None = None
    depth: int = 0
    children: list[SubTask] = field(default_factory=list)


@dataclass
class FileConflict:
    """A file-scope conflict between two sibling subtasks.

    Indicates that both subtasks list the same file in their file_scope,
    meaning they cannot safely execute in parallel without coordination.
    """

    file_path: str
    subtask_ids: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        return f"FileConflict({self.file_path!r}, subtasks={self.subtask_ids})"


@dataclass
class OracleResult:
    """Result of oracle validation on a subtask's file scope.

    Oracle checks are lightweight pre-execution validations:
    - Python syntax check via ast.parse
    - File existence and readability
    """

    valid: bool
    errors: list[str] = field(default_factory=list)
    checked_files: list[str] = field(default_factory=list)


@dataclass
class DecompositionQuality:
    """Quality score for a set of decomposed subtasks.

    Factors:
    - score: overall quality 0.0-1.0 (higher is better)
    - file_conflicts: number of file-scope overlaps between sibling subtasks
    - avg_scope_size: average number of files per subtask
    - coverage_ratio: fraction of original goal's file scope covered by subtasks
    """

    score: float
    file_conflicts: int
    avg_scope_size: float
    coverage_ratio: float


@dataclass
class TaskDecomposition:
    """Result of task decomposition analysis.

    Supports both flat (subtasks list) and hierarchical (tree) views.
    Call build_tree() to populate children on SubTask objects.
    """

    original_task: str
    complexity_score: int  # 1-10
    complexity_level: str  # low, medium, high
    should_decompose: bool
    subtasks: list[SubTask] = field(default_factory=list)
    rationale: str = ""
    recommend_debate: bool = False
    """Set to True when the goal is abstract (high complexity, no file hints)
    and would benefit from debate-based decomposition. Callers can check this
    to decide whether to use ``analyze_with_debate()`` instead of heuristic."""

    def build_tree(self) -> list[SubTask]:
        """Build hierarchical tree from flat subtask list using parent_id.

        Returns root-level subtasks with children populated recursively.
        The flat subtasks list is not modified.
        """
        by_id: dict[str, SubTask] = {s.id: s for s in self.subtasks}
        roots: list[SubTask] = []
        for subtask in self.subtasks:
            subtask.children = []  # Reset before building
        for subtask in self.subtasks:
            if subtask.parent_id and subtask.parent_id in by_id:
                by_id[subtask.parent_id].children.append(subtask)
            else:
                roots.append(subtask)
        return roots

    def get_roots(self) -> list[SubTask]:
        """Get root-level subtasks (parent_id is None)."""
        return [s for s in self.subtasks if s.parent_id is None]

    def get_children(self, parent_id: str) -> list[SubTask]:
        """Get direct children of a subtask."""
        return [s for s in self.subtasks if s.parent_id == parent_id]

    def max_depth(self) -> int:
        """Get maximum depth in the goal tree."""
        return max((s.depth for s in self.subtasks), default=0)

    def flatten_tree(self, roots: list[SubTask] | None = None) -> list[SubTask]:
        """Flatten a tree back into an ordered list (depth-first)."""
        if roots is None:
            roots = self.build_tree()
        result: list[SubTask] = []
        for root in roots:
            result.append(root)
            result.extend(self.flatten_tree(root.children))
        return result


__all__ = [
    "DecompositionQuality",
    "FileConflict",
    "OracleResult",
    "SubTask",
    "TaskDecomposition",
]
