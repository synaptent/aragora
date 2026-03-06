"""Self-correcting improvement loop for the Nomic autonomous orchestrator.

Analyzes patterns across Nomic Loop cycles to adjust future behavior.
The engine learns from success/failure outcomes and produces actionable
recommendations: track priority adjustments, agent rotation, and
strategy changes.

Three correction mechanisms:
1. Track prioritization: boost successful tracks, deprioritize failing ones
2. Agent selection: prefer agents that contributed to successful outcomes
3. Strategy adaptation: switch approaches when patterns indicate failure

Usage:
    from aragora.nomic.self_correction import SelfCorrectionEngine

    engine = SelfCorrectionEngine()
    report = engine.analyze_patterns(outcomes)
    adjustments = engine.compute_priority_adjustments(report)
    recommendations = engine.recommend_strategy_change(report)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SelfCorrectionConfig:
    """Configuration for the self-correcting improvement loop."""

    enable_self_correction: bool = True
    min_cycles_for_pattern: int = 3  # Need at least N cycles before identifying patterns
    failure_repeat_threshold: int = 2  # Flag after N repeated failures on same track
    success_momentum_bonus: float = 0.1  # Boost priority for tracks with recent success
    failure_penalty: float = 0.15  # Reduce priority for tracks with repeated failure
    max_pattern_age_days: int = 30  # Ignore patterns older than this


@dataclass
class CorrectionReport:
    """Analysis of past improvement outcomes."""

    total_cycles: int
    overall_success_rate: float
    track_success_rates: dict[str, float]  # track -> rate
    track_streaks: dict[
        str, int
    ]  # track -> consecutive successes (positive) or failures (negative)
    agent_correlations: dict[str, float]  # agent -> correlation with success
    failing_patterns: list[str]  # Human-readable failure patterns


@dataclass
class StrategyRecommendation:
    """A recommended strategy change."""

    track: str
    recommendation: str
    reason: str
    confidence: float  # How confident we are in this recommendation (0.0-1.0)
    action_type: (
        str  # "deprioritize", "change_approach", "rotate_agent", "increase_scope", "decrease_scope"
    )


class SelfCorrectionEngine:
    """Analyzes Nomic Loop outcomes and adjusts future behavior.

    Implements three correction mechanisms:
    1. Track prioritization: boost successful tracks, deprioritize failing ones
    2. Agent selection: prefer agents that contributed to successful outcomes
    3. Strategy adaptation: switch approaches when patterns indicate failure
    """

    def __init__(
        self,
        config: SelfCorrectionConfig | None = None,
        km_bridge: Any | None = None,
    ):
        self.config = config or SelfCorrectionConfig()
        self._km_bridge = km_bridge

    def analyze_patterns(self, outcomes: list[dict[str, Any]]) -> CorrectionReport:
        """Analyze past outcomes to identify success/failure patterns.

        When a ``km_bridge`` is available, historical structured outcomes from
        the Knowledge Mound are merged with the supplied in-memory outcomes
        before analysis.

        Looks for:
        - Tracks that consistently succeed vs fail
        - Agents that correlate with success vs failure
        - Consecutive streaks (success or failure) per track
        - Goal types (refactor, feature, bugfix) that succeed vs fail

        Args:
            outcomes: List of outcome dicts. Each outcome should have at least:
                - track: str
                - success: bool
                Optional fields:
                - agent: str
                - goal_type: str (refactor, feature, bugfix)
                - timestamp: str (ISO format)
                - description: str

        Returns:
            CorrectionReport with analysis results.
        """
        # Merge historical patterns from KM bridge when available
        merged = list(outcomes)
        if self._km_bridge is not None:
            try:
                historical = self._km_bridge.retrieve_success_patterns(limit=50)
                for h in historical:
                    # Convert structured outcome format to analysis-compatible format
                    merged.append(
                        {
                            "track": h.get("track", "unknown"),
                            "success": h.get("success", False),
                            "agent": h.get("agent", ""),
                            "goal_type": h.get("goal_type", ""),
                            "timestamp": datetime.fromtimestamp(
                                h.get("timestamp", 0), tz=timezone.utc
                            ).isoformat()
                            if h.get("timestamp")
                            else None,
                        }
                    )
            except (RuntimeError, OSError, ValueError, TypeError, AttributeError) as exc:
                logger.debug("self_correction_km_merge_failed: %s", exc)

        if not merged:
            return CorrectionReport(
                total_cycles=0,
                overall_success_rate=0.0,
                track_success_rates={},
                track_streaks={},
                agent_correlations={},
                failing_patterns=[],
            )

        # Filter out stale outcomes
        filtered = self._filter_by_age(merged)

        total = len(filtered)
        successes = sum(1 for o in filtered if o.get("success"))
        overall_rate = successes / total if total > 0 else 0.0

        track_success_rates = self._compute_track_success_rates(filtered)
        track_streaks = self._compute_track_streaks(filtered)
        agent_correlations = self._compute_agent_correlations(filtered)
        failing_patterns = self._identify_failing_patterns(
            filtered, track_success_rates, track_streaks, agent_correlations
        )

        report = CorrectionReport(
            total_cycles=total,
            overall_success_rate=overall_rate,
            track_success_rates=track_success_rates,
            track_streaks=track_streaks,
            agent_correlations=agent_correlations,
            failing_patterns=failing_patterns,
        )

        logger.info(
            "self_correction_analysis total=%d success_rate=%.2f tracks=%d patterns=%d",
            total,
            overall_rate,
            len(track_success_rates),
            len(failing_patterns),
        )

        return report

    def compute_priority_adjustments(self, report: CorrectionReport) -> dict[str, float]:
        """Compute priority adjustments for each track based on patterns.

        Returns dict mapping track name to adjustment factor (1.0 = no change,
        >1.0 = boost, <1.0 = deprioritize).

        When there is insufficient data (fewer than min_cycles_for_pattern
        total cycles), all tracks get a neutral 1.0 adjustment.
        """
        adjustments: dict[str, float] = {}

        # Insufficient data: return neutral adjustments
        if report.total_cycles < self.config.min_cycles_for_pattern:
            for track in report.track_success_rates:
                adjustments[track] = 1.0
            return adjustments

        for track, rate in report.track_success_rates.items():
            adjustment = 1.0
            streak = report.track_streaks.get(track, 0)

            # Boost tracks with positive momentum (recent consecutive successes)
            if streak > 0:
                adjustment += self.config.success_momentum_bonus * min(streak, 5)

            # Penalize tracks with repeated failures
            if streak < 0 and abs(streak) >= self.config.failure_repeat_threshold:
                adjustment -= self.config.failure_penalty * min(abs(streak), 5)

            # Additional adjustment based on overall success rate for this track
            if rate > 0.7:
                adjustment += 0.05  # Minor boost for consistently successful tracks
            elif rate < 0.3:
                adjustment -= 0.05  # Minor penalty for consistently failing tracks

            # Clamp to reasonable range
            adjustment = max(0.1, min(2.0, adjustment))
            adjustments[track] = round(adjustment, 3)

        logger.info(
            "priority_adjustments %s",
            {k: f"{v:.3f}" for k, v in adjustments.items()},
        )

        return adjustments

    def recommend_strategy_change(self, report: CorrectionReport) -> list[StrategyRecommendation]:
        """Recommend strategy changes based on failure patterns.

        Produces actionable recommendations when patterns indicate systemic
        issues. Returns an empty list when data is insufficient or no
        concerning patterns are found.
        """
        recommendations: list[StrategyRecommendation] = []

        # Insufficient data: no recommendations
        if report.total_cycles < self.config.min_cycles_for_pattern:
            return recommendations

        # Check for consecutive failure streaks per track
        for track, streak in report.track_streaks.items():
            if streak < 0 and abs(streak) >= self.config.failure_repeat_threshold:
                consecutive_failures = abs(streak)
                recommendations.append(
                    StrategyRecommendation(
                        track=track,
                        recommendation=(
                            f"Switch to smaller incremental changes for track "
                            f"'{track}' after {consecutive_failures} consecutive failures."
                        ),
                        reason=(
                            f"Track '{track}' has failed {consecutive_failures} "
                            f"consecutive times. Large changes may be too risky."
                        ),
                        confidence=min(0.5 + 0.1 * consecutive_failures, 0.95),
                        action_type="decrease_scope",
                    )
                )

        # Check for agents that correlate strongly with failure
        for agent, correlation in report.agent_correlations.items():
            if correlation < 0.3:
                # Find which tracks this agent is failing on
                failing_tracks = [t for t, rate in report.track_success_rates.items() if rate < 0.5]
                track_str = ", ".join(failing_tracks[:3]) if failing_tracks else "multiple tracks"
                recommendations.append(
                    StrategyRecommendation(
                        track=track_str,
                        recommendation=(
                            f"Rotate agent '{agent}' to a different agent or pair "
                            f"with a stronger agent."
                        ),
                        reason=(
                            f"Agent '{agent}' has a success correlation of "
                            f"{correlation:.2f}, indicating it is involved in many "
                            f"failed outcomes."
                        ),
                        confidence=min(0.4 + (0.5 - correlation), 0.9),
                        action_type="rotate_agent",
                    )
                )

        # Check for tracks with very low success rates but positive streaks
        # (rare but possible: overall low rate but a recent success run)
        for track, rate in report.track_success_rates.items():
            streak = report.track_streaks.get(track, 0)
            if rate < 0.4 and streak > 0:
                recommendations.append(
                    StrategyRecommendation(
                        track=track,
                        recommendation=(
                            f"Increase scope for track '{track}' -- recent "
                            f"successes suggest the approach is improving."
                        ),
                        reason=(
                            f"Track '{track}' has a low overall rate ({rate:.0%}) "
                            f"but {streak} recent consecutive successes."
                        ),
                        confidence=0.4,
                        action_type="increase_scope",
                    )
                )

        # Check for tracks that should be deprioritized entirely
        for track, rate in report.track_success_rates.items():
            streak = report.track_streaks.get(track, 0)
            if rate < 0.2 and streak <= -3:
                recommendations.append(
                    StrategyRecommendation(
                        track=track,
                        recommendation=(
                            f"Deprioritize track '{track}' until root cause is investigated."
                        ),
                        reason=(
                            f"Track '{track}' has a {rate:.0%} success rate with "
                            f"{abs(streak)} consecutive failures. Continuing "
                            f"without intervention is wasteful."
                        ),
                        confidence=min(0.6 + 0.1 * abs(streak), 0.95),
                        action_type="deprioritize",
                    )
                )

        logger.info(
            "strategy_recommendations count=%d tracks=%s",
            len(recommendations),
            [r.track for r in recommendations],
        )

        return recommendations

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _filter_by_age(self, outcomes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Filter outcomes that are older than max_pattern_age_days."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.config.max_pattern_age_days)
        filtered: list[dict[str, Any]] = []

        for outcome in outcomes:
            ts_str = outcome.get("timestamp")
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str)
                    # Ensure timezone-aware comparison
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts < cutoff:
                        continue  # Too old, skip
                except (ValueError, TypeError):
                    pass  # If timestamp is invalid, include the outcome anyway
            filtered.append(outcome)

        return filtered

    def _compute_track_success_rates(self, outcomes: list[dict[str, Any]]) -> dict[str, float]:
        """Compute success rate for each track."""
        track_attempts: dict[str, int] = defaultdict(int)
        track_successes: dict[str, int] = defaultdict(int)

        for outcome in outcomes:
            track = outcome.get("track", "unknown")
            track_attempts[track] += 1
            if outcome.get("success"):
                track_successes[track] += 1

        return {
            track: track_successes[track] / count if count > 0 else 0.0
            for track, count in track_attempts.items()
        }

    def _compute_track_streaks(self, outcomes: list[dict[str, Any]]) -> dict[str, int]:
        """Compute consecutive success/failure streaks per track.

        Positive values indicate consecutive successes, negative values
        indicate consecutive failures. Counts from the most recent outcome
        backward (end of the list is most recent).
        """
        # Group outcomes by track, preserving order
        track_outcomes: dict[str, list[bool]] = defaultdict(list)
        for outcome in outcomes:
            track = outcome.get("track", "unknown")
            track_outcomes[track].append(bool(outcome.get("success")))

        streaks: dict[str, int] = {}
        for track, results in track_outcomes.items():
            if not results:
                streaks[track] = 0
                continue

            # Walk backwards from most recent
            last_result = results[-1]
            streak = 0
            for result in reversed(results):
                if result == last_result:
                    streak += 1
                else:
                    break

            # Negative for failures, positive for successes
            streaks[track] = streak if last_result else -streak

        return streaks

    def _compute_agent_correlations(self, outcomes: list[dict[str, Any]]) -> dict[str, float]:
        """Compute correlation between each agent and success.

        Returns a simple success rate per agent (0.0 = always fails,
        1.0 = always succeeds).
        """
        agent_attempts: dict[str, int] = defaultdict(int)
        agent_successes: dict[str, int] = defaultdict(int)

        for outcome in outcomes:
            agent = outcome.get("agent")
            if not agent:
                continue
            agent_attempts[agent] += 1
            if outcome.get("success"):
                agent_successes[agent] += 1

        return {
            agent: agent_successes[agent] / count if count > 0 else 0.0
            for agent, count in agent_attempts.items()
        }

    def _identify_failing_patterns(
        self,
        outcomes: list[dict[str, Any]],
        track_rates: dict[str, float],
        track_streaks: dict[str, int],
        agent_correlations: dict[str, float],
    ) -> list[str]:
        """Identify human-readable failure patterns."""
        patterns: list[str] = []

        # Pattern: tracks with consecutive failures
        for track, streak in track_streaks.items():
            if streak < 0 and abs(streak) >= self.config.failure_repeat_threshold:
                patterns.append(f"Track '{track}' has {abs(streak)} consecutive failures.")

        # Pattern: agents with low success correlation
        for agent, correlation in agent_correlations.items():
            if correlation < 0.3:
                patterns.append(
                    f"Agent '{agent}' has a {correlation:.0%} success rate across outcomes."
                )

        # Pattern: goal type failures
        goal_type_stats: dict[str, dict[str, int]] = defaultdict(
            lambda: {"attempts": 0, "successes": 0}
        )
        for outcome in outcomes:
            goal_type = outcome.get("goal_type")
            if goal_type:
                goal_type_stats[goal_type]["attempts"] += 1
                if outcome.get("success"):
                    goal_type_stats[goal_type]["successes"] += 1

        for goal_type, stats in goal_type_stats.items():
            if stats["attempts"] >= 2:
                rate = stats["successes"] / stats["attempts"]
                if rate < 0.3:
                    patterns.append(
                        f"Goal type '{goal_type}' has a {rate:.0%} success rate "
                        f"({stats['successes']}/{stats['attempts']})."
                    )

        return patterns


__all__ = [
    "SelfCorrectionConfig",
    "SelfCorrectionEngine",
    "CorrectionReport",
    "StrategyRecommendation",
]
