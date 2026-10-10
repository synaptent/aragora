"""Agent outcome feedback and self-correction, inherited by ``AutonomousOrchestrator``.

Records outcomes in ELO and the Knowledge Mound, picks an alternative agent after a
failure, turns regressions into goals and applies self-correction priority adjustments.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone
from typing import Any

# Runtime imports, not TYPE_CHECKING ones: typing.get_type_hints() on the
# orchestrator classes and the methods below evaluates annotations here.
from aragora.nomic.feedback_loop import FeedbackLoop
from aragora.nomic.types import (
    DEFAULT_TRACK_CONFIGS,
    AgentAssignment,
    OrchestrationResult,
    Track,
    TrackConfig,
)
from aragora.observability import get_logger

# The facade's logger name, so log filters and caplog assertions keyed on
# "aragora.nomic.autonomous_orchestrator" still see records from these methods.
logger = get_logger("aragora.nomic.autonomous_orchestrator")


class AutonomousFeedbackMixin:
    """Outcome feedback and self-correction methods of ``AutonomousOrchestrator``."""

    # Set by AutonomousOrchestrator.__init__.
    track_configs: dict[Track, TrackConfig]
    feedback_loop: FeedbackLoop
    _self_correction: Any
    _orchestration_id: str | None

    async def _record_agent_outcome(
        self,
        assignment: AgentAssignment,
        success: bool,
        domain: str,
    ) -> None:
        """Record agent implementation performance in ELO and Knowledge Mound.

        This closes the self-improvement feedback loop: agents that succeed
        at implementation tasks get ELO boosts, agents that fail get penalties.
        Over time, the system learns which agents are best for which tracks.
        """
        agent_name = assignment.agent_type

        # Record in ELO system
        try:
            from aragora.ranking.elo import get_elo_store

            elo = get_elo_store()
            # Use a synthetic match: agent vs "baseline" where success = win
            elo.record_match(
                debate_id=f"impl-{assignment.subtask.id}",
                participants=[agent_name, "_baseline"],
                scores={agent_name: 1.0 if success else 0.0, "_baseline": 0.5},
                domain=domain,
            )
            logger.info(
                "agent_outcome_elo agent=%s success=%s domain=%s", agent_name, success, domain
            )
        except (ImportError, RuntimeError, TypeError, ValueError) as e:
            logger.debug("ELO recording failed for %s: %s", agent_name, e)

        # Record in Knowledge Mound
        try:
            from aragora.knowledge.mound.adapters.factory import get_adapter

            adapter = get_adapter("nomic_cycle")
            if adapter and hasattr(adapter, "record"):
                await adapter.record(
                    {
                        "type": "agent_implementation_outcome",
                        "agent": agent_name,
                        "track": domain,
                        "subtask_id": assignment.subtask.id,
                        "success": success,
                        "attempt": assignment.attempt_count,
                    }
                )
        except (ImportError, RuntimeError, TypeError, ValueError) as e:
            logger.debug("KM recording failed for %s: %s", agent_name, e)

    def _select_alternative_agent(self, assignment: AgentAssignment) -> str | None:
        """Select an alternative agent type for reassignment on failure.

        Picks the next available agent from the track's preferred list,
        skipping the current agent. Falls back to 'claude' as the most
        capable general-purpose agent.
        """
        config = self.track_configs.get(
            assignment.track,
            DEFAULT_TRACK_CONFIGS[Track.DEVELOPER],
        )
        candidates = [a for a in config.agent_types if a != assignment.agent_type]
        if candidates:
            return candidates[0]
        # Fallback: if current agent isn't claude, try claude
        if assignment.agent_type != "claude":
            return "claude"
        return None

    def _enqueue_regression_goals(
        self,
        comparison: Any,
        original_goal: str,
    ) -> None:
        """Convert detected regressions into improvement goals for next cycle.

        When OutcomeTracker detects a regression, this method generates
        targeted fix goals and pushes them to the ImprovementQueue so
        MetaPlanner picks them up automatically in the next planning cycle.
        """
        try:
            from aragora.nomic.feedback_orchestrator import ImprovementGoal, ImprovementQueue
        except ImportError:
            logger.debug("feedback_orchestrator unavailable for auto-replan")
            return

        try:
            queue = ImprovementQueue()
            metrics_delta = getattr(comparison, "metrics_delta", {}) or {}
            recommendation = getattr(comparison, "recommendation", "review")

            # Generate a goal for each regressed metric
            regressed = [(k, v) for k, v in metrics_delta.items() if v is not None]
            if not regressed:
                # No specific metrics — generate a generic regression-fix goal
                queue.push(
                    ImprovementGoal(
                        goal=f"Fix regression caused by: {original_goal}",
                        source="outcome_tracker_regression",
                        priority=0.9,  # High priority
                        context={
                            "recommendation": recommendation,
                            "original_goal": original_goal,
                            "auto_replan": True,
                        },
                    )
                )
                logger.info("auto_replan: queued generic regression-fix goal")
                return

            for metric_name, delta_value in regressed:
                priority = 0.95 if recommendation == "revert" else 0.8
                queue.push(
                    ImprovementGoal(
                        goal=(
                            f"Fix {metric_name} regression "
                            f"(delta={delta_value:+.3f}) "
                            f"after: {original_goal}"
                        ),
                        source="outcome_tracker_regression",
                        priority=priority,
                        context={
                            "regressed_metric": metric_name,
                            "delta": delta_value,
                            "recommendation": recommendation,
                            "original_goal": original_goal,
                            "auto_replan": True,
                        },
                    )
                )

            logger.info(
                "auto_replan: queued %d regression-fix goals (recommendation=%s)",
                len(regressed),
                recommendation,
            )

            # Emit spectate event for regression visibility
            if hasattr(self, "_emit_event"):
                self._emit_event(
                    "regression_detected",
                    goal=original_goal[:100],
                    recommendation=recommendation,
                    regressed_metrics=len(regressed),
                    goals_queued=len(regressed) or 1,
                )
        except (RuntimeError, OSError, ValueError) as e:
            logger.debug("auto_replan_failed: %s", e)

    def _apply_self_correction(
        self,
        assignments: list[AgentAssignment],
        result: OrchestrationResult,
    ) -> None:
        """Apply self-correction analysis from past outcomes.

        Converts completed assignments to outcome dicts, runs pattern
        analysis, computes priority adjustments and strategy recommendations,
        and stores them for the next orchestration cycle.
        """
        if self._self_correction is None:
            return

        try:
            # Convert assignments to outcome dicts for analysis
            outcomes: list[dict[str, Any]] = []
            for a in assignments:
                if a.status in ("completed", "failed"):
                    outcomes.append(
                        {
                            "track": a.track.value,
                            "success": a.status == "completed",
                            "agent": a.agent_type,
                            "description": a.subtask.title,
                            "timestamp": (
                                a.completed_at.isoformat()
                                if a.completed_at
                                else datetime.now(timezone.utc).isoformat()
                            ),
                        }
                    )

            if not outcomes:
                return

            # Analyze patterns across this cycle's outcomes
            report = self._self_correction.analyze_patterns(outcomes)

            # Compute priority adjustments for next cycle
            adjustments = self._self_correction.compute_priority_adjustments(report)
            if adjustments:
                # Store on the result for callers to inspect
                if result.after_metrics is None:
                    result.after_metrics = {}
                result.after_metrics["self_correction_adjustments"] = adjustments

            # Compute strategy recommendations
            recommendations = self._self_correction.recommend_strategy_change(report)
            if recommendations:
                if result.after_metrics is None:
                    result.after_metrics = {}
                result.after_metrics["self_correction_recommendations"] = [
                    {
                        "track": r.track,
                        "action": r.action_type,
                        "recommendation": r.recommendation,
                        "confidence": r.confidence,
                    }
                    for r in recommendations
                ]

            # Feed adjustments into MetaPlanner for next cycle
            self._store_priority_adjustments(adjustments)

            # Feed strategy recommendations into FeedbackLoop for next cycle
            if recommendations and self.feedback_loop is not None:
                self.feedback_loop.apply_strategy_recommendations(recommendations)

            logger.info(
                "self_correction_applied outcomes=%s adjustments=%s recommendations=%s",
                len(outcomes),
                len(adjustments),
                len(recommendations),
            )
        except (RuntimeError, ValueError, TypeError, AttributeError) as e:
            logger.debug("Self-correction analysis failed: %s", e)

    def _store_priority_adjustments(self, adjustments: dict[str, float]) -> None:
        """Store priority adjustments for the next MetaPlanner cycle.

        Persists to the Knowledge Mound so the MetaPlanner can query them
        when prioritizing work in the next orchestration cycle.
        """
        if not adjustments:
            return
        try:
            from aragora.knowledge.mound.adapters.factory import get_adapter

            adapter = get_adapter("nomic_cycle")
            if adapter and hasattr(adapter, "record"):
                import asyncio

                coro = adapter.record(
                    {
                        "type": "self_correction_adjustments",
                        "adjustments": adjustments,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "orchestration_id": self._orchestration_id,
                    }
                )
                # Fire-and-forget if we can't await
                if inspect.isawaitable(coro):
                    try:
                        asyncio.ensure_future(coro)
                    except RuntimeError:
                        pass
        except (ImportError, RuntimeError, TypeError, ValueError) as e:
            logger.debug("Failed to persist priority adjustments: %s", e)
