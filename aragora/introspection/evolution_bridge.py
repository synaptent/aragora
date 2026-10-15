"""Bridge from Agent Introspection to Genesis Evolution.

Closes the introspection-to-agent-improvement loop: reads agent
self-awareness data (performance per round, influence scores, proposal
quality) and routes targeted improvement recommendations to the
ImprovementQueue.  Optionally feeds Genesis breeding configs so that
underperforming agent genomes can be evolved.

This module is **purely additive** -- it does not modify any existing
introspection or genesis code.  All external imports are lazy so that
missing subsystems degrade gracefully.

Usage::

    from aragora.introspection.evolution_bridge import IntrospectionEvolutionBridge

    bridge = IntrospectionEvolutionBridge()
    recommendations = bridge.analyze(tracker.get_all_summaries())
    bridge.route_to_queue(recommendations)
    bridge.feed_genesis(recommendations)  # optional
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from aragora.introspection.active import AgentPerformanceSummary
    from aragora.introspection.types import IntrospectionSnapshot
    from aragora.learning.improvement_goal_queue import ImprovementQueue


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class EvolutionRecommendation:
    """A single improvement recommendation derived from introspection data.

    Attributes:
        agent_name: Name of the agent this recommendation targets.
        recommendation: Human-readable recommendation string.
        severity: ``"low"``, ``"medium"``, or ``"high"``.
        metric_name: Which metric triggered this recommendation.
        metric_value: Current value of the triggering metric.
        threshold: Threshold that was breached.
        source: Always ``"introspection"`` for provenance tracking.
        timestamp: Unix timestamp when the recommendation was generated.
        context: Arbitrary extra context (e.g. round history snippets).
    """

    agent_name: str
    recommendation: str
    severity: str = "medium"
    metric_name: str = ""
    metric_value: float = 0.0
    threshold: float = 0.0
    source: str = "introspection"
    timestamp: float = field(default_factory=time.time)
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dictionary."""
        return {
            "agent_name": self.agent_name,
            "recommendation": self.recommendation,
            "severity": self.severity,
            "metric_name": self.metric_name,
            "metric_value": self.metric_value,
            "threshold": self.threshold,
            "source": self.source,
            "timestamp": self.timestamp,
            "context": self.context,
        }


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

# Agents performing below these thresholds trigger recommendations.
_DEFAULT_THRESHOLDS: dict[str, float] = {
    "proposal_acceptance_rate": 0.25,
    "critique_effectiveness": 0.20,
    "average_influence": 0.15,
    "influence_drop_pct": 0.30,
    "reputation_score": 0.25,
    "calibration_score": 0.30,
}

# Minimum rounds/proposals/critiques before an agent is evaluated.
_MIN_ROUNDS = 2
_MIN_PROPOSALS = 3
_MIN_CRITIQUES = 3
_MIN_DEBATES_FOR_SNAPSHOT = 3


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------


class IntrospectionEvolutionBridge:
    """Reads introspection data and produces evolution recommendations.

    The bridge works with two data sources:

    1. **Active summaries** (``AgentPerformanceSummary``) -- live, per-round
       data from the current or recent debate.
    2. **Historical snapshots** (``IntrospectionSnapshot``) -- aggregated
       reputation/calibration data loaded at debate start.

    Parameters:
        thresholds: Override default thresholds for recommendation triggers.
        queue: Optional pre-built ``ImprovementQueue`` instance.  If not
            provided, one is lazily constructed on first ``route_to_queue``
            call.
    """

    def __init__(
        self,
        thresholds: dict[str, float] | None = None,
        queue: ImprovementQueue | None = None,
    ) -> None:
        self._thresholds = {**_DEFAULT_THRESHOLDS, **(thresholds or {})}
        self._queue = queue

    # --- Public API --------------------------------------------------------

    def analyze_summaries(
        self,
        summaries: dict[str, AgentPerformanceSummary],
    ) -> list[EvolutionRecommendation]:
        """Analyze active introspection summaries and produce recommendations.

        High-performing agents are silently skipped.  Only agents that
        breach one or more thresholds generate recommendations.

        Args:
            summaries: Mapping of agent_name -> AgentPerformanceSummary.

        Returns:
            List of recommendations (may be empty).
        """
        recommendations: list[EvolutionRecommendation] = []
        for agent_name, summary in summaries.items():
            recommendations.extend(self._evaluate_summary(agent_name, summary))
        return recommendations

    def analyze_snapshots(
        self,
        snapshots: dict[str, IntrospectionSnapshot],
    ) -> list[EvolutionRecommendation]:
        """Analyze historical introspection snapshots and produce recommendations.

        Args:
            snapshots: Mapping of agent_name -> IntrospectionSnapshot.

        Returns:
            List of recommendations (may be empty).
        """
        recommendations: list[EvolutionRecommendation] = []
        for agent_name, snapshot in snapshots.items():
            recommendations.extend(self._evaluate_snapshot(agent_name, snapshot))
        return recommendations

    def analyze(
        self,
        summaries: dict[str, AgentPerformanceSummary] | None = None,
        snapshots: dict[str, IntrospectionSnapshot] | None = None,
    ) -> list[EvolutionRecommendation]:
        """Convenience: analyze both summaries and snapshots in one call."""
        results: list[EvolutionRecommendation] = []
        if summaries:
            results.extend(self.analyze_summaries(summaries))
        if snapshots:
            results.extend(self.analyze_snapshots(snapshots))
        return results

    def route_to_queue(
        self,
        recommendations: list[EvolutionRecommendation],
    ) -> int:
        """Push recommendations into the ImprovementQueue.

        Returns the number of goals successfully pushed.  Gracefully
        handles missing ``ImprovementQueue`` (returns 0).
        """
        if not recommendations:
            return 0

        queue = self._get_queue()
        if queue is None:
            logger.debug("ImprovementQueue unavailable; skipping route_to_queue")
            return 0

        pushed = 0
        for rec in recommendations:
            try:
                # Lazy import to avoid circular dependencies
                from aragora.learning.improvement_goal_queue import ImprovementGoal

                priority = self._severity_to_priority(rec.severity)
                goal = ImprovementGoal(
                    goal=rec.recommendation,
                    source=rec.source,
                    priority=priority,
                    context={
                        "agent_name": rec.agent_name,
                        "metric_name": rec.metric_name,
                        "metric_value": rec.metric_value,
                        "threshold": rec.threshold,
                        "severity": rec.severity,
                        **rec.context,
                    },
                )
                queue.push(goal)
                pushed += 1
            except (ImportError, RuntimeError, OSError, TypeError, ValueError) as exc:
                logger.debug("Failed to push recommendation to queue: %s", exc)

        logger.info(
            "evolution_bridge routed %d/%d recommendations to ImprovementQueue",
            pushed,
            len(recommendations),
        )
        return pushed

    def feed_genesis(
        self,
        recommendations: list[EvolutionRecommendation],
    ) -> int:
        """Optionally adjust Genesis breeding configs from recommendations.

        For each underperforming agent that has a genome in the Genesis
        population, we lower its fitness score so that ``natural_selection``
        deprioritizes it and ``evolve_population`` breeds replacements.

        Returns the number of genomes whose fitness was adjusted.
        """
        if not recommendations:
            return 0

        try:
            from aragora.genesis.breeding import PopulationManager
        except ImportError:
            logger.debug("Genesis module unavailable; skipping feed_genesis")
            return 0

        adjusted = 0
        try:
            manager = PopulationManager()
        except (RuntimeError, OSError, TypeError, ValueError) as exc:
            logger.debug("Could not initialize PopulationManager: %s", exc)
            return 0

        for rec in recommendations:
            if rec.severity not in ("high", "medium"):
                continue
            try:
                genome = manager.genome_store.get_by_name(rec.agent_name)
                if genome is None:
                    continue

                # Lower fitness proportional to severity
                delta = -0.1 if rec.severity == "high" else -0.05
                manager.update_fitness(genome.genome_id, fitness_delta=delta)
                adjusted += 1

                logger.debug(
                    "evolution_bridge adjusted fitness for %s (genome=%s) by %+.2f",
                    rec.agent_name,
                    genome.genome_id,
                    delta,
                )
            except (RuntimeError, OSError, TypeError, ValueError, AttributeError, KeyError) as exc:
                logger.debug(
                    "Failed to adjust genesis fitness for %s: %s",
                    rec.agent_name,
                    exc,
                )

        if adjusted > 0:
            logger.info(
                "evolution_bridge adjusted genesis fitness for %d agents",
                adjusted,
            )
        return adjusted

    # --- Private helpers ---------------------------------------------------

    def _evaluate_summary(
        self,
        agent_name: str,
        summary: AgentPerformanceSummary,
    ) -> list[EvolutionRecommendation]:
        """Evaluate a single agent's active performance summary."""
        recs: list[EvolutionRecommendation] = []

        if summary.rounds_completed < _MIN_ROUNDS:
            return recs

        # 1. Low proposal acceptance rate
        if summary.total_proposals >= _MIN_PROPOSALS:
            rate = summary.proposal_acceptance_rate
            threshold = self._thresholds["proposal_acceptance_rate"]
            if rate < threshold:
                pct = int(rate * 100)
                recs.append(
                    EvolutionRecommendation(
                        agent_name=agent_name,
                        recommendation=(
                            f"Agent {agent_name} has {pct}% proposal acceptance "
                            f"-- consider prompt tuning"
                        ),
                        severity="high" if rate < threshold / 2 else "medium",
                        metric_name="proposal_acceptance_rate",
                        metric_value=rate,
                        threshold=threshold,
                        context={
                            "total_proposals": summary.total_proposals,
                            "total_accepted": summary.total_accepted,
                        },
                    )
                )

        # 2. Low critique effectiveness
        if summary.total_critiques >= _MIN_CRITIQUES:
            eff = summary.critique_effectiveness
            threshold = self._thresholds["critique_effectiveness"]
            if eff < threshold:
                pct = int(eff * 100)
                recs.append(
                    EvolutionRecommendation(
                        agent_name=agent_name,
                        recommendation=(
                            f"Agent {agent_name} has {pct}% critique effectiveness "
                            f"-- critiques rarely lead to changes"
                        ),
                        severity="medium",
                        metric_name="critique_effectiveness",
                        metric_value=eff,
                        threshold=threshold,
                        context={
                            "total_critiques": summary.total_critiques,
                            "total_effective": summary.total_critiques_effective,
                        },
                    )
                )

        # 3. Low influence
        avg_inf = summary.average_influence
        threshold = self._thresholds["average_influence"]
        if avg_inf < threshold:
            recs.append(
                EvolutionRecommendation(
                    agent_name=agent_name,
                    recommendation=(
                        f"Agent {agent_name}'s average influence is {avg_inf:.2f} "
                        f"-- arguments have limited impact on outcomes"
                    ),
                    severity="medium",
                    metric_name="average_influence",
                    metric_value=avg_inf,
                    threshold=threshold,
                )
            )

        # 4. Influence drop across rounds
        recs.extend(self._check_influence_drop(agent_name, summary))

        return recs

    def _check_influence_drop(
        self,
        agent_name: str,
        summary: AgentPerformanceSummary,
    ) -> list[EvolutionRecommendation]:
        """Detect declining influence over the round history."""
        recs: list[EvolutionRecommendation] = []
        history = summary.round_history

        if len(history) < 4:
            return recs

        # Compare first half vs second half average influence
        mid = len(history) // 2
        first_half = [r.argument_influence for r in history[:mid]]
        second_half = [r.argument_influence for r in history[mid:]]

        avg_first = sum(first_half) / len(first_half) if first_half else 0.0
        avg_second = sum(second_half) / len(second_half) if second_half else 0.0

        if avg_first > 0:
            drop_pct = (avg_first - avg_second) / avg_first
            threshold = self._thresholds["influence_drop_pct"]
            if drop_pct >= threshold:
                pct = int(drop_pct * 100)
                recs.append(
                    EvolutionRecommendation(
                        agent_name=agent_name,
                        recommendation=(
                            f"Agent {agent_name}'s influence dropped {pct}% "
                            f"over the last {len(history)} rounds -- investigate"
                        ),
                        severity="high",
                        metric_name="influence_drop_pct",
                        metric_value=drop_pct,
                        threshold=threshold,
                        context={
                            "first_half_avg": round(avg_first, 4),
                            "second_half_avg": round(avg_second, 4),
                            "rounds": len(history),
                        },
                    )
                )

        return recs

    def _evaluate_snapshot(
        self,
        agent_name: str,
        snapshot: IntrospectionSnapshot,
    ) -> list[EvolutionRecommendation]:
        """Evaluate a single agent's historical introspection snapshot."""
        recs: list[EvolutionRecommendation] = []

        if snapshot.debate_count < _MIN_DEBATES_FOR_SNAPSHOT:
            return recs

        # 1. Low reputation
        threshold = self._thresholds["reputation_score"]
        if snapshot.reputation_score < threshold:
            pct = int(snapshot.reputation_score * 100)
            recs.append(
                EvolutionRecommendation(
                    agent_name=agent_name,
                    recommendation=(
                        f"Agent {agent_name} has {pct}% reputation score "
                        f"across {snapshot.debate_count} debates -- "
                        f"persistent underperformance"
                    ),
                    severity="high",
                    metric_name="reputation_score",
                    metric_value=snapshot.reputation_score,
                    threshold=threshold,
                    context={"debate_count": snapshot.debate_count},
                )
            )

        # 2. Low proposal acceptance (historical)
        if snapshot.proposals_made >= _MIN_PROPOSALS:
            rate = snapshot.proposal_acceptance_rate
            pa_threshold = self._thresholds["proposal_acceptance_rate"]
            if rate < pa_threshold:
                pct = int(rate * 100)
                recs.append(
                    EvolutionRecommendation(
                        agent_name=agent_name,
                        recommendation=(
                            f"Agent {agent_name} has {pct}% historical proposal "
                            f"acceptance -- consider prompt tuning"
                        ),
                        severity="medium",
                        metric_name="proposal_acceptance_rate",
                        metric_value=rate,
                        threshold=pa_threshold,
                        context={
                            "proposals_made": snapshot.proposals_made,
                            "proposals_accepted": snapshot.proposals_accepted,
                        },
                    )
                )

        # 3. Low calibration
        cal_threshold = self._thresholds["calibration_score"]
        if snapshot.calibration_score < cal_threshold:
            recs.append(
                EvolutionRecommendation(
                    agent_name=agent_name,
                    recommendation=(
                        f"Agent {agent_name} has calibration score "
                        f"{snapshot.calibration_score:.2f} ({snapshot.calibration_label}) "
                        f"-- prediction accuracy needs improvement"
                    ),
                    severity="medium",
                    metric_name="calibration_score",
                    metric_value=snapshot.calibration_score,
                    threshold=cal_threshold,
                )
            )

        return recs

    def _get_queue(self) -> ImprovementQueue | None:
        """Lazily resolve or create the ImprovementQueue."""
        if self._queue is not None:
            return self._queue

        try:
            from aragora.learning.improvement_goal_queue import ImprovementQueue

            self._queue = ImprovementQueue()
            return self._queue
        except (ImportError, RuntimeError, OSError) as exc:
            logger.debug("Could not create ImprovementQueue: %s", exc)
            return None

    @staticmethod
    def _severity_to_priority(severity: str) -> float:
        """Map severity to ImprovementGoal priority (0.0-1.0, higher = more urgent)."""
        return {"high": 0.85, "medium": 0.65, "low": 0.40}.get(severity, 0.50)


__all__ = [
    "EvolutionRecommendation",
    "IntrospectionEvolutionBridge",
]
