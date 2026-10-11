"""Outcome recording and self-correction re-ranking for ``MetaPlanner``.

``MetaPlanner`` (``aragora.nomic.meta_planner``) inherits these methods: they aggregate
executed-goal outcomes by track, hand them to the Knowledge Mound as a nomic cycle
outcome, and re-rank new goals with the self-correction engine's track adjustments
computed from recent cycles. Import the planner from ``aragora.nomic.meta_planner``.
"""

from __future__ import annotations

import logging
from typing import Any

from aragora.nomic.meta_planner_models import PrioritizedGoal

# The facade's logger name, so log filters and caplog assertions keyed on
# "aragora.nomic.meta_planner" still see records from the moved methods.
logger = logging.getLogger("aragora.nomic.meta_planner")


class MetaPlannerOutcomesMixin:
    """Outcome tracking and self-correction re-ranking inherited by ``MetaPlanner``."""

    def _apply_self_correction_adjustments(
        self,
        goals: list[PrioritizedGoal],
    ) -> list[PrioritizedGoal]:
        """Re-rank goals using self-correction engine priority adjustments.

        Queries the SelfCorrectionEngine for track-level adjustments and
        uses them to boost or demote goals. Higher adjustment = higher
        priority (lower number).
        """
        try:
            from aragora.nomic.self_correction import SelfCorrectionEngine

            engine = SelfCorrectionEngine()

            # Query past outcomes from Knowledge Mound
            past_outcomes = self._get_past_outcomes()
            if not past_outcomes:
                return goals

            report = engine.analyze_patterns(past_outcomes)
            adjustments = engine.compute_priority_adjustments(report)

            if not adjustments:
                return goals

            # Apply adjustments: multiply priority by inverse of adjustment
            # (higher adjustment = more important = lower priority number)
            for goal in goals:
                track_key = goal.track.value
                adj = adjustments.get(track_key, 1.0)
                # Adjusted priority: divide by adjustment factor so boosted
                # tracks get lower (higher priority) numbers
                goal.priority = max(1, round(goal.priority / adj))

            # Re-sort by adjusted priority
            goals.sort(key=lambda g: g.priority)

            # Re-assign sequential priority numbers
            for i, goal in enumerate(goals):
                goal.priority = i + 1

            logger.info(
                "self_correction_adjustments_applied tracks=%s",
                {g.track.value: adjustments.get(g.track.value, 1.0) for g in goals},
            )
        except (ImportError, RuntimeError, ValueError, TypeError) as e:
            logger.debug("Self-correction adjustments unavailable: %s", e)

        return goals

    def _get_past_outcomes(self) -> list[dict[str, Any]]:
        """Retrieve past orchestration outcomes for self-correction analysis."""
        try:
            from aragora.nomic.cycle_store import get_recent_cycles

            cycles = get_recent_cycles(n=20)
            outcomes: list[dict[str, Any]] = []
            for cycle in cycles:
                for contrib in getattr(cycle, "agent_contributions", []):
                    outcomes.append(
                        {
                            "track": getattr(contrib, "domain", "unknown"),
                            "success": getattr(contrib, "was_success", False),
                            "agent": getattr(contrib, "agent_name", "unknown"),
                            "timestamp": getattr(cycle, "timestamp", None),
                        }
                    )
            return outcomes
        except (ImportError, RuntimeError, TypeError, ValueError) as e:
            logger.debug("Past outcomes unavailable: %s", e)
            return []

    def record_outcome(
        self,
        goal_outcomes: list[dict[str, Any]],
        objective: str = "",
    ) -> dict[str, dict[str, Any]]:
        """Record improvement outcomes and log success rates by track.

        Closes the feedback loop: after goals are executed, this method
        aggregates results by Track and logs structured success rates so
        the next planning cycle can learn from what worked.

        Args:
            goal_outcomes: List of dicts with keys:
                - track: str (Track value like "sme", "qa", "core")
                - success: bool
                - description: str (optional)
                - error: str (optional, for failures)
            objective: The original planning objective

        Returns:
            Dict mapping track name to {attempted, succeeded, failed, rate}
        """
        track_stats: dict[str, dict[str, Any]] = {}

        for outcome in goal_outcomes:
            track = outcome.get("track", "unknown")
            if track not in track_stats:
                track_stats[track] = {
                    "attempted": 0,
                    "succeeded": 0,
                    "failed": 0,
                    "failures": [],
                }

            track_stats[track]["attempted"] += 1
            if outcome.get("success"):
                track_stats[track]["succeeded"] += 1
            else:
                track_stats[track]["failed"] += 1
                error = outcome.get("error", outcome.get("description", "unknown"))
                track_stats[track]["failures"].append(error)

        # Compute rates and log
        total_attempted = 0
        total_succeeded = 0
        for track, stats in track_stats.items():
            rate = stats["succeeded"] / stats["attempted"] if stats["attempted"] > 0 else 0.0
            stats["rate"] = rate
            total_attempted += stats["attempted"]
            total_succeeded += stats["succeeded"]

            logger.info(
                "meta_planner_track_outcome track=%s attempted=%d succeeded=%d failed=%d rate=%.2f",
                track,
                stats["attempted"],
                stats["succeeded"],
                stats["failed"],
                rate,
            )

        overall_rate = total_succeeded / total_attempted if total_attempted > 0 else 0.0
        logger.info(
            "meta_planner_outcome_summary objective=%s total_attempted=%d "
            "total_succeeded=%d overall_rate=%.2f tracks=%d",
            objective[:80] if objective else "unspecified",
            total_attempted,
            total_succeeded,
            overall_rate,
            len(track_stats),
        )

        # Persist to KM for cross-cycle learning
        self._persist_outcome_to_km(goal_outcomes, objective, track_stats)

        return track_stats

    def _persist_outcome_to_km(
        self,
        goal_outcomes: list[dict[str, Any]],
        objective: str,
        track_stats: dict[str, dict[str, Any]],
    ) -> None:
        """Persist outcomes to Knowledge Mound via NomicCycleAdapter."""
        try:
            from datetime import datetime, timezone

            from aragora.knowledge.mound.adapters.nomic_cycle_adapter import (
                CycleStatus,
                GoalOutcome,
                NomicCycleOutcome,
                get_nomic_cycle_adapter,
            )

            total = sum(s["attempted"] for s in track_stats.values())
            succeeded = sum(s["succeeded"] for s in track_stats.values())
            failed = sum(s["failed"] for s in track_stats.values())

            if total == 0:
                return

            if failed == 0:
                status = CycleStatus.SUCCESS
            elif succeeded == 0:
                status = CycleStatus.FAILED
            else:
                status = CycleStatus.PARTIAL

            now = datetime.now(timezone.utc)
            outcomes = []
            for o in goal_outcomes:
                outcomes.append(
                    GoalOutcome(
                        goal_id=o.get("goal_id", ""),
                        description=o.get("description", ""),
                        track=o.get("track", "unknown"),
                        status=CycleStatus.SUCCESS if o.get("success") else CycleStatus.FAILED,
                        error=o.get("error"),
                        learnings=o.get("learnings", []),
                    )
                )

            cycle = NomicCycleOutcome(
                cycle_id=f"meta_{now.strftime('%Y%m%d_%H%M%S')}",
                objective=objective,
                status=status,
                started_at=now,
                completed_at=now,
                goal_outcomes=outcomes,
                goals_attempted=total,
                goals_succeeded=succeeded,
                goals_failed=failed,
                tracks_affected=list(track_stats.keys()),
            )

            adapter = get_nomic_cycle_adapter()
            # Fire-and-forget: don't block on async KM write
            import asyncio

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(adapter.ingest_cycle_outcome(cycle))
            except RuntimeError:
                # No running loop - skip async persistence
                logger.debug("No event loop, skipping async KM persistence")

        except ImportError:
            logger.debug("NomicCycleAdapter not available, skipping KM persistence")
        except (ValueError, TypeError, OSError, AttributeError, KeyError) as e:
            logger.warning("Failed to persist outcome to KM: %s", e)
