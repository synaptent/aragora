"""Conflict resolver with Arena-based debate for multi-agent coordination.

Wraps :class:`SemanticConflictDetector` and :class:`GitReconciler` to detect
overlapping changes between branches, then runs an Arena debate when semantic
conflicts (same function modified differently) are found.

Trivial conflicts (import order, whitespace) are auto-resolved.  Semantic
conflicts get a 2-round debate where agents present their change rationale
and a neutral judge picks the winner or proposes a synthesis.

Usage::

    from aragora.coordination.resolver import ConflictResolver

    resolver = ConflictResolver(repo_path=Path("."))
    result = await resolver.resolve("branch-a", "branch-b")
    # result.resolution in ("auto_merged", "debate_resolved", "needs_human")
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from aragora.coordination.reconciler import GitReconciler

logger = logging.getLogger(__name__)

_COORD_DIR = ".aragora_coordination"
_DECISIONS_DIR = "decisions"


class Resolution(str, Enum):
    """Outcome of a conflict resolution attempt."""

    NO_CONFLICT = "no_conflict"
    AUTO_MERGED = "auto_merged"
    DEBATE_RESOLVED = "debate_resolved"
    NEEDS_HUMAN = "needs_human"
    ERROR = "error"


@dataclass
class ResolutionResult:
    """Full result of a conflict resolution attempt."""

    resolution: Resolution
    branch_a: str
    branch_b: str
    conflicting_files: list[str] = field(default_factory=list)
    merge_order: str = ""  # "a_first", "b_first", or ""
    debate_summary: str = ""
    receipt_path: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["resolution"] = self.resolution.value
        return d


class ConflictResolver:
    """Resolves merge conflicts between agent branches using Arena debates.

    Layers:
    1. Fast: GitReconciler.detect_conflicts() — textual conflict classification
    2. Deep: SemanticConflictDetector.detect() — AST-aware analysis
    3. Debate: Arena 2-round debate for semantic conflicts

    Only semantic conflicts (confidence > 0.7) trigger a debate.
    Everything else is auto-resolved or passed through.
    """

    def __init__(
        self,
        repo_path: Path | None = None,
        *,
        enable_debate: bool = True,
        debate_rounds: int = 2,
        confidence_threshold: float = 0.7,
    ):
        self.repo_path = (repo_path or Path.cwd()).resolve()
        self._decisions_dir = self.repo_path / _COORD_DIR / _DECISIONS_DIR
        self._enable_debate = enable_debate
        self._debate_rounds = debate_rounds
        self._confidence_threshold = confidence_threshold

    def _ensure_dir(self) -> Path:
        self._decisions_dir.mkdir(parents=True, exist_ok=True)
        return self._decisions_dir

    def _get_reconciler(self) -> GitReconciler:
        """Lazy import to avoid pulling in subprocess machinery at module load."""
        from aragora.coordination.reconciler import GitReconciler

        return GitReconciler(repo_path=self.repo_path)

    def _get_semantic_detector(self) -> Any:
        """Lazy import SemanticConflictDetector. Returns None if unavailable."""
        try:
            from aragora.nomic.semantic_conflict_detector import SemanticConflictDetector

            return SemanticConflictDetector(self.repo_path, enable_debate=False)
        except ImportError:
            logger.debug("SemanticConflictDetector not available")
            return None

    def detect(self, branch_a: str, branch_b: str) -> dict[str, Any]:
        """Detect conflicts between two branches without resolving.

        Returns:
            Dict with "textual" (ConflictInfo list) and "semantic" (SemanticConflict list).
        """
        reconciler = self._get_reconciler()
        textual = reconciler.detect_conflicts(branch_a, branch_b)

        semantic: list[Any] = []
        detector = self._get_semantic_detector()
        if detector:
            try:
                semantic = detector.detect([branch_a, branch_b])
            except (RuntimeError, ValueError, OSError) as exc:
                logger.debug("semantic_detection_failed: %s", exc)

        return {
            "textual": textual,
            "semantic": semantic,
        }

    async def resolve(
        self,
        branch_a: str,
        branch_b: str,
        *,
        context: dict[str, str] | None = None,
    ) -> ResolutionResult:
        """Attempt to resolve conflicts between two branches.

        Args:
            branch_a: First branch name.
            branch_b: Second branch name.
            context: Optional dict with extra context (agent intents, etc.)

        Returns:
            ResolutionResult with outcome and optional debate receipt.
        """
        conflicts = self.detect(branch_a, branch_b)
        textual = conflicts["textual"]
        semantic = conflicts["semantic"]

        # No conflicts at all
        if not textual and not semantic:
            return ResolutionResult(
                resolution=Resolution.NO_CONFLICT,
                branch_a=branch_a,
                branch_b=branch_b,
            )

        # Only trivial textual conflicts — auto-resolve
        all_auto = all(getattr(c, "auto_resolvable", False) for c in textual)
        high_confidence_semantic = [
            s for s in semantic if getattr(s, "confidence", 0) > self._confidence_threshold
        ]

        if all_auto and not high_confidence_semantic:
            return ResolutionResult(
                resolution=Resolution.AUTO_MERGED,
                branch_a=branch_a,
                branch_b=branch_b,
                conflicting_files=[getattr(c, "file_path", "") for c in textual],
            )

        # Semantic conflicts — try debate
        if self._enable_debate and high_confidence_semantic:
            debate_result = await self._run_debate(
                branch_a, branch_b, high_confidence_semantic, context
            )
            if debate_result is not None:
                return debate_result

        # Fallback: needs human review
        all_files = [getattr(c, "file_path", "") for c in textual]
        all_files.extend(f for s in semantic for f in getattr(s, "affected_files", []))
        return ResolutionResult(
            resolution=Resolution.NEEDS_HUMAN,
            branch_a=branch_a,
            branch_b=branch_b,
            conflicting_files=list(dict.fromkeys(all_files)),
        )

    async def _run_debate(
        self,
        branch_a: str,
        branch_b: str,
        semantic_conflicts: list[Any],
        context: dict[str, str] | None,
    ) -> ResolutionResult | None:
        """Run an Arena debate to resolve semantic conflicts.

        Returns None if Arena is unavailable or debate fails.
        """
        try:
            from aragora.debate.orchestrator import Arena
            from aragora.debate.orchestrator import DebateProtocol
            from aragora.debate.orchestrator import Environment
        except ImportError:
            logger.debug("Arena not available for conflict debate")
            return None

        # Build debate task description
        conflict_descriptions = []
        affected_files: list[str] = []
        for sc in semantic_conflicts:
            desc = getattr(sc, "description", str(sc))
            conflict_descriptions.append(desc)
            affected_files.extend(getattr(sc, "affected_files", []))

        affected_files = list(dict.fromkeys(affected_files))

        task_text = (
            f"Two agent branches conflict and need resolution.\n\n"
            f"Branch A: {branch_a}\n"
            f"Branch B: {branch_b}\n\n"
            f"Conflicting files: {', '.join(affected_files)}\n\n"
            f"Conflicts:\n" + "\n".join(f"- {d}" for d in conflict_descriptions)
        )

        if context:
            task_text += "\n\nAgent context:\n" + "\n".join(
                f"- {k}: {v}" for k, v in context.items()
            )

        task_text += (
            "\n\nDetermine: (1) Which branch should merge first? "
            "(2) How should the conflicting changes be reconciled? "
            "(3) Provide specific merge instructions."
        )

        try:
            env = Environment(task=task_text)
            protocol = DebateProtocol(
                rounds=self._debate_rounds,
                consensus="majority",
            )

            # Use minimal agent set — this is an internal coordination debate
            arena = Arena(env, agents=[], protocol=protocol)
            result = await arena.run()

            # Extract resolution from debate result
            synthesis = getattr(result, "synthesis", "") or ""
            merge_order = ""
            if "branch a" in synthesis.lower() and "first" in synthesis.lower():
                merge_order = "a_first"
            elif "branch b" in synthesis.lower() and "first" in synthesis.lower():
                merge_order = "b_first"

            # Store decision receipt
            receipt_path = self._store_receipt(branch_a, branch_b, affected_files, synthesis)

            return ResolutionResult(
                resolution=Resolution.DEBATE_RESOLVED,
                branch_a=branch_a,
                branch_b=branch_b,
                conflicting_files=affected_files,
                merge_order=merge_order,
                debate_summary=synthesis[:500],
                receipt_path=str(receipt_path),
            )

        except (RuntimeError, ValueError, TypeError, OSError) as exc:
            logger.warning("debate_failed branches=%s/%s: %s", branch_a, branch_b, exc)
            return None

    def _store_receipt(
        self,
        branch_a: str,
        branch_b: str,
        files: list[str],
        synthesis: str,
    ) -> Path:
        """Store a decision receipt as JSON."""
        d = self._ensure_dir()
        receipt_id = str(uuid4())[:12]
        receipt = {
            "receipt_id": receipt_id,
            "branch_a": branch_a,
            "branch_b": branch_b,
            "conflicting_files": files,
            "synthesis": synthesis,
            "timestamp": time.time(),
        }
        path = d / f"{receipt_id}.json"
        path.write_text(json.dumps(receipt, default=str), encoding="utf-8")
        logger.info("decision_receipt stored=%s", path)
        return path


__all__ = [
    "ConflictResolver",
    "Resolution",
    "ResolutionResult",
]
