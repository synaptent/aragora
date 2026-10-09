"""
SOAR Curriculum Integration for Nomic Loop.

Provides curriculum-based learning when tasks fail, generating stepping stones
to help bridge capability gaps instead of just retrying or escalating.

Usage:
    from aragora.nomic.curriculum.integration import (
        CurriculumAwareFeedbackLoop,
        integrate_curriculum_with_orchestrator,
    )

    # Create enhanced feedback loop
    feedback_loop = CurriculumAwareFeedbackLoop(
        max_iterations=3,
        enable_curriculum=True,
    )

    # Or integrate with existing orchestrator
    orchestrator = AutonomousOrchestrator()
    integrate_curriculum_with_orchestrator(orchestrator)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from aragora.nomic.curriculum.soar_curriculum import (
    Curriculum,
    CurriculumPlanner,
    SkillProfile,
    SteppingStone,
    SteppingStoneGenerator,
    SteppingStoneResult,
)

if TYPE_CHECKING:
    from aragora.nomic.autonomous_orchestrator import (
        AgentAssignment,
        AutonomousOrchestrator,
    )

logger = logging.getLogger(__name__)


@dataclass
class CurriculumConfig:
    """Configuration for curriculum-based learning.

    Attributes:
        enable_curriculum: Whether to use curriculum for failures
        max_stepping_stones: Maximum stones before escalating
        min_failures_for_curriculum: Failures before creating curriculum
        stone_success_threshold: Success rate to try main task
        persist_curricula: Whether to save curricula for cross-cycle learning
        curriculum_storage_path: Where to persist curricula
    """

    enable_curriculum: bool = True
    max_stepping_stones: int = 5
    min_failures_for_curriculum: int = 2
    stone_success_threshold: float = 0.6
    persist_curricula: bool = True
    curriculum_storage_path: str = ".aragora_beads/curricula"


class CurriculumAwareFeedbackLoop:
    """Enhanced feedback loop that uses SOAR curriculum for learning.

    When a task fails multiple times, instead of just escalating to a human,
    this feedback loop:
    1. Analyzes the failure to understand capability gaps
    2. Generates a curriculum of stepping stones
    3. Has the system attempt the stepping stones
    4. Only returns to the main task when stepping stones succeed

    This enables gradual capability building instead of binary pass/fail.
    """

    def __init__(
        self,
        max_iterations: int = 3,
        config: CurriculumConfig | None = None,
        skill_profile: SkillProfile | None = None,
    ):
        """Initialize the curriculum-aware feedback loop.

        Args:
            max_iterations: Max iterations before curriculum kicks in
            config: Curriculum configuration
            skill_profile: Existing skill profile (for continuity)
        """
        self.max_iterations = max_iterations
        self.config = config or CurriculumConfig()
        self._iteration_counts: dict[str, int] = {}
        self._skill_profile = skill_profile or SkillProfile()

        # Curriculum state
        self._planner = CurriculumPlanner(
            generator=SteppingStoneGenerator(),
            storage_path=(
                None
                if not self.config.persist_curricula
                else __import__("pathlib").Path(self.config.curriculum_storage_path)
            ),
        )
        self._active_curricula: dict[str, Curriculum] = {}
        self._stone_results: dict[str, list[SteppingStoneResult]] = {}

    @property
    def skill_profile(self) -> SkillProfile:
        """Get the current skill profile."""
        return self._skill_profile

    async def analyze_failure(
        self,
        assignment: AgentAssignment,
        error_info: dict[str, Any],
    ) -> dict[str, Any]:
        """Analyze a failure and determine next steps.

        Enhanced to use curriculum-based learning when appropriate.

        Args:
            assignment: The failed assignment
            error_info: Information about the failure

        Returns:
            Action to take, which may include:
            - "stepping_stone": Attempt a stepping stone
            - "retry_main_task": Try the original task again
            - Standard actions: retry_implement, quick_fix, redesign, escalate
        """
        subtask_id = assignment.subtask.id
        self._iteration_counts[subtask_id] = self._iteration_counts.get(subtask_id, 0) + 1
        iteration = self._iteration_counts[subtask_id]

        # Check if we have an active curriculum
        if subtask_id in self._active_curricula:
            return await self._handle_curriculum_progress(assignment, error_info)

        # Standard handling for early failures
        if iteration < self.config.min_failures_for_curriculum:
            return self._standard_analysis(error_info)

        # At max iterations, consider curriculum
        if iteration >= self.max_iterations:
            if self.config.enable_curriculum:
                return await self._create_curriculum(assignment, error_info)
            else:
                return {
                    "action": "escalate",
                    "reason": f"Max iterations ({self.max_iterations}) reached",
                    "require_human": True,
                }

        return self._standard_analysis(error_info)

    async def _create_curriculum(
        self,
        assignment: AgentAssignment,
        error_info: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a curriculum of stepping stones for a difficult task.

        Args:
            assignment: The failed assignment
            error_info: Information about the failure

        Returns:
            Action dict with curriculum information
        """
        task = assignment.subtask.description
        subtask_id = assignment.subtask.id

        logger.info(
            "Creating curriculum for task '%s' after %s failures",
            task[:50],
            self._iteration_counts[subtask_id],
        )

        # Estimate current capability based on failure history
        # More failures = lower current level estimate
        failure_count = self._iteration_counts.get(subtask_id, 1)
        current_level = max(0.1, 0.6 - (failure_count * 0.1))

        try:
            curriculum = await self._planner.create_curriculum(
                target_task=task,
                current_level=current_level,
                target_level=0.8,
                num_stones=min(3, self.config.max_stepping_stones),
            )

            if not curriculum.stepping_stones:
                logger.warning("No stepping stones generated for task: %s", task[:50])
                return {
                    "action": "escalate",
                    "reason": "Could not generate stepping stones",
                    "require_human": True,
                }

            self._active_curricula[subtask_id] = curriculum
            self._stone_results[subtask_id] = []

            first_stone = curriculum.stepping_stones[0]
            logger.info(
                "Created curriculum with %s stepping stones. First stone: %s",
                len(curriculum.stepping_stones),
                first_stone.task[:50],
            )

            return {
                "action": "stepping_stone",
                "reason": "Created curriculum to build capabilities",
                "curriculum_id": curriculum.id,
                "stone": {
                    "id": first_stone.id,
                    "task": first_stone.task,
                    "difficulty": first_stone.difficulty,
                    "hints": first_stone.hints,
                    "validation": first_stone.validation_criteria,
                },
                "total_stones": len(curriculum.stepping_stones),
                "stone_number": 1,
            }

        except (RuntimeError, ValueError, OSError) as e:
            logger.exception("Failed to create curriculum: %s", e)
            return {
                "action": "escalate",
                "reason": f"Curriculum creation failed: {e}",
                "require_human": True,
            }

    async def _handle_curriculum_progress(
        self,
        assignment: AgentAssignment,
        error_info: dict[str, Any],
    ) -> dict[str, Any]:
        """Handle progress through an active curriculum.

        Args:
            assignment: Current assignment
            error_info: May contain stepping stone result

        Returns:
            Next action (another stone, retry main task, or escalate)
        """
        subtask_id = assignment.subtask.id
        curriculum = self._active_curricula[subtask_id]

        # Check if this is a stepping stone result
        stone_result = error_info.get("stone_result")
        if stone_result:
            result = SteppingStoneResult(
                stone_id=stone_result.get("stone_id", ""),
                success=stone_result.get("success", False),
                completion_score=stone_result.get("score", 0.5),
                time_taken=stone_result.get("time", 0.0),
                errors_encountered=stone_result.get("errors", []),
            )
            self._planner.record_result(curriculum.id, result)
            self._stone_results[subtask_id].append(result)

        # Check if we should try the main task
        if self._planner.should_attempt_target(curriculum.id):
            logger.info(
                "Curriculum complete with %.0f%% success rate. Returning to main task.",
                curriculum.success_rate * 100,
            )
            del self._active_curricula[subtask_id]
            return {
                "action": "retry_main_task",
                "reason": "Stepping stones completed successfully",
                "curriculum_success_rate": curriculum.success_rate,
            }

        # Get next action from curriculum
        next_action = self._planner.get_next_action(curriculum.id)

        if isinstance(next_action, SteppingStone):
            stone_idx = curriculum.current_index + 1
            total = len(curriculum.stepping_stones)
            logger.info("Next stepping stone (%s/%s): %s", stone_idx, total, next_action.task[:50])
            return {
                "action": "stepping_stone",
                "reason": "Continuing curriculum",
                "curriculum_id": curriculum.id,
                "stone": {
                    "id": next_action.id,
                    "task": next_action.task,
                    "difficulty": next_action.difficulty,
                    "hints": next_action.hints,
                    "validation": next_action.validation_criteria,
                },
                "total_stones": total,
                "stone_number": stone_idx,
                "success_rate": curriculum.success_rate,
            }

        if next_action == curriculum.target_task:
            logger.info("Curriculum says attempt target task")
            del self._active_curricula[subtask_id]
            return {
                "action": "retry_main_task",
                "reason": "Curriculum complete, attempting target",
                "curriculum_success_rate": curriculum.success_rate,
            }

        # Curriculum failed (insufficient success rate)
        logger.warning(
            "Curriculum failed with %.0f%% success rate. Escalating.", curriculum.success_rate * 100
        )
        del self._active_curricula[subtask_id]
        return {
            "action": "escalate",
            "reason": f"Curriculum completed but insufficient success rate ({curriculum.success_rate:.0%})",
            "require_human": True,
            "curriculum_results": [
                {"stone_id": r.stone_id, "success": r.success, "score": r.completion_score}
                for r in self._stone_results.get(subtask_id, [])
            ],
        }

    def _standard_analysis(self, error_info: dict[str, Any]) -> dict[str, Any]:
        """Standard failure analysis without curriculum.

        Args:
            error_info: Information about the failure

        Returns:
            Action to take
        """
        error_type = error_info.get("type", "unknown")
        error_message = error_info.get("message", "")

        # Test failures -> adjust implementation
        if error_type == "test_failure":
            return {
                "action": "retry_implement",
                "reason": "Test failures require implementation adjustment",
                "hints": self._extract_test_hints(error_message),
            }

        # Lint/type errors -> quick fix
        if error_type in ("lint_error", "type_error"):
            return {
                "action": "quick_fix",
                "reason": "Static analysis errors can be auto-fixed",
                "hints": error_message,
            }

        # Design issues -> revisit design
        if error_type == "design_issue":
            return {
                "action": "redesign",
                "reason": "Implementation revealed design flaws",
                "hints": error_info.get("suggestion", ""),
            }

        return {
            "action": "retry_implement",
            "reason": f"Unknown error type: {error_type}",
        }

    def _extract_test_hints(self, error_message: str) -> str:
        """Extract hints from test failure messages."""
        lines = error_message.split("\n")
        hints = []

        for line in lines:
            if "AssertionError" in line or "Expected" in line or "Actual" in line:
                hints.append(line.strip())

        return "\n".join(hints[:5]) if hints else "Review test output"

    def get_active_curriculum(self, subtask_id: str) -> Curriculum | None:
        """Get the active curriculum for a subtask, if any."""
        return self._active_curricula.get(subtask_id)

    def get_curriculum_summary(self) -> dict[str, Any]:
        """Get a summary of curriculum learning for this session.

        Returns a dict suitable for inclusion in NomicCycleOutcome's
        curriculum_outcome field for cross-cycle persistence.

        Returns:
            Dict with curriculum learning metrics and details
        """
        # Count curricula and stones
        curricula_created = (
            len(self._planner._curricula) if hasattr(self._planner, "_curricula") else 0
        )
        stones_attempted = 0
        stones_succeeded = 0
        skill_gaps: list[str] = []
        skills_improved: list[str] = []
        curriculum_results: dict[str, dict[str, Any]] = {}

        # Aggregate results from all stone results
        for subtask_id, results in self._stone_results.items():
            curriculum = self._active_curricula.get(subtask_id)
            curriculum_id = curriculum.id if curriculum else subtask_id

            for result in results:
                stones_attempted += 1
                if result.success:
                    stones_succeeded += 1

            if results:
                curriculum_results[curriculum_id] = {
                    "stones_attempted": len(results),
                    "stones_succeeded": sum(1 for r in results if r.success),
                    "avg_score": (
                        sum(r.completion_score for r in results) / len(results) if results else 0.0
                    ),
                }

        # Extract skill gaps from iteration counts (high iteration = skill gap)
        for subtask_id, count in self._iteration_counts.items():
            if count >= self.config.min_failures_for_curriculum:
                # This subtask had enough failures to indicate a gap
                curriculum = self._active_curricula.get(subtask_id)
                if curriculum:
                    skill_gaps.append(curriculum.target_task[:100])

        # Skills improved are tasks that completed after curriculum
        for subtask_id in self._stone_results:
            results = self._stone_results[subtask_id]
            if results and sum(1 for r in results if r.success) > 0:
                curriculum = self._active_curricula.get(subtask_id)
                if curriculum:
                    skills_improved.append(curriculum.target_task[:100])

        return {
            "curricula_created": curricula_created,
            "stones_attempted": stones_attempted,
            "stones_succeeded": stones_succeeded,
            "skill_gaps": skill_gaps,
            "skills_improved": skills_improved,
            "curriculum_results": curriculum_results,
        }


def integrate_curriculum_with_orchestrator(
    orchestrator: AutonomousOrchestrator,
    config: CurriculumConfig | None = None,
) -> None:
    """Integrate curriculum-based learning with an existing orchestrator.

    Replaces the orchestrator's feedback loop with a curriculum-aware one.

    Args:
        orchestrator: The orchestrator to enhance
        config: Optional curriculum configuration
    """
    orchestrator.feedback_loop = CurriculumAwareFeedbackLoop(  # type: ignore[assignment]
        max_iterations=orchestrator.feedback_loop.max_iterations,
        config=config,
    )
    logger.info("Integrated SOAR curriculum with autonomous orchestrator")


__all__ = [
    "CurriculumConfig",
    "CurriculumAwareFeedbackLoop",
    "integrate_curriculum_with_orchestrator",
]
