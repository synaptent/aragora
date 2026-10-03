"""
Calibration Tracker to Cost Optimizer Bridge.

Bridges calibration data from CalibrationTracker into cost optimization decisions,
enabling cost-efficient agent selection based on prediction reliability.

This closes the loop between:
1. CalibrationTracker: Tracks prediction accuracy and confidence calibration
2. CostTracker: Monitors and optimizes token/API costs

By connecting them, we enable:
- Selecting well-calibrated agents for cost-critical tasks
- Avoiding overconfident agents that require more verification rounds
- Cost prediction based on calibration quality
- Budget-aware agent selection

Usage:
    from aragora.billing.calibration_cost_bridge import CalibrationCostBridge

    bridge = CalibrationCostBridge(
        calibration_tracker=tracker,
        cost_tracker=cost_tracker,
    )

    # Get cost efficiency score for an agent
    score = bridge.get_cost_efficiency_score("claude")

    # Recommend agent for cost-optimized task
    agent = bridge.recommend_cost_efficient_agent(available_agents)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from aragora.billing.cost_tracker import CostTracker

logger = logging.getLogger(__name__)


class CalibrationSummary(Protocol):
    """Structural calibration result consumed by billing."""

    total_predictions: int
    ece: float
    accuracy: float
    is_overconfident: bool
    is_underconfident: bool


class CalibrationTracker(Protocol):
    """Structural calibration tracker consumed by billing."""

    def get_calibration_summary(self, agent_name: str) -> CalibrationSummary | None: ...

    def get_all_agents(self) -> list[str]: ...


@dataclass
class AgentCostEfficiency:
    """Cost efficiency assessment for an agent."""

    agent_name: str
    calibration_score: float = 0.0  # 0-1, based on ECE (lower ECE = higher score)
    accuracy_score: float = 0.0  # 0-1, prediction accuracy
    cost_per_call: Decimal = Decimal("0")  # Average cost per API call
    efficiency_score: float = 0.0  # Combined score
    confidence_reliability: float = 0.0  # How trustworthy confidence is
    is_overconfident: bool = False
    is_underconfident: bool = False
    recommendation: str = ""  # "efficient", "moderate", "costly"


@dataclass
class CalibrationCostBridgeConfig:
    """Configuration for the calibration-cost bridge."""

    # Minimum predictions before using calibration data
    min_predictions_for_scoring: int = 20

    # Weight for calibration in efficiency score
    calibration_weight: float = 0.4

    # Weight for accuracy in efficiency score
    accuracy_weight: float = 0.3

    # Weight for cost efficiency in efficiency score
    cost_weight: float = 0.3

    # ECE threshold for "well-calibrated"
    well_calibrated_ece_threshold: float = 0.1

    # Cost multiplier for overconfident agents (expect more rounds)
    overconfident_cost_multiplier: float = 1.3

    # Cost multiplier for underconfident agents (unnecessary caution)
    underconfident_cost_multiplier: float = 1.1

    # Efficiency thresholds
    efficient_threshold: float = 0.7
    moderate_threshold: float = 0.4


@dataclass
class CalibrationCostBridge:
    """Bridges CalibrationTracker into cost optimization decisions.

    Key integration points:
    1. Uses calibration quality to predict actual costs
    2. Adjusts cost estimates based on confidence reliability
    3. Recommends cost-efficient agents for budget-conscious tasks
    4. Predicts verification rounds needed based on calibration
    """

    calibration_tracker: CalibrationTracker | None = None
    cost_tracker: CostTracker | None = None
    config: CalibrationCostBridgeConfig = field(default_factory=CalibrationCostBridgeConfig)

    # Cached efficiency data
    _efficiency_cache: dict[str, AgentCostEfficiency] = field(default_factory=dict, repr=False)
    _cache_timestamp: datetime | None = field(default=None, repr=False)
    _cache_ttl_seconds: int = 300  # 5 minutes

    def compute_cost_efficiency(self, agent_name: str) -> AgentCostEfficiency:
        """Compute cost efficiency for an agent.

        Args:
            agent_name: Name of the agent

        Returns:
            AgentCostEfficiency assessment
        """
        result = AgentCostEfficiency(agent_name=agent_name)

        # Get calibration data
        calibration_summary = self._get_calibration_summary(agent_name)

        if calibration_summary is None:
            result.recommendation = "unknown"
            return result

        if calibration_summary.total_predictions < self.config.min_predictions_for_scoring:
            result.recommendation = "insufficient_data"
            return result

        # Compute calibration score (lower ECE = better)
        # ECE typically 0-0.3, we invert to 0-1 score
        ece = calibration_summary.ece
        result.calibration_score = max(0.0, 1.0 - ece * 3.33)  # 0.3 ECE -> 0 score

        # Accuracy score
        result.accuracy_score = calibration_summary.accuracy

        # Confidence reliability (based on calibration direction)
        result.is_overconfident = calibration_summary.is_overconfident
        result.is_underconfident = calibration_summary.is_underconfident

        if not result.is_overconfident and not result.is_underconfident:
            result.confidence_reliability = 1.0 - ece
        elif result.is_overconfident:
            # Overconfident = confidence > accuracy
            result.confidence_reliability = max(0.3, 0.7 - ece)
        else:
            # Underconfident = accuracy > confidence (less problematic)
            result.confidence_reliability = max(0.5, 0.85 - ece)

        # Get average cost per call
        result.cost_per_call = self._get_avg_cost(agent_name)

        # Compute combined efficiency score
        result.efficiency_score = (
            result.calibration_score * self.config.calibration_weight
            + result.accuracy_score * self.config.accuracy_weight
            + self._cost_score(result.cost_per_call) * self.config.cost_weight
        )

        # Apply penalties for miscalibration
        if result.is_overconfident:
            result.efficiency_score *= 0.85  # 15% penalty
        elif result.is_underconfident:
            result.efficiency_score *= 0.95  # 5% penalty

        # Determine recommendation
        if result.efficiency_score >= self.config.efficient_threshold:
            result.recommendation = "efficient"
        elif result.efficiency_score >= self.config.moderate_threshold:
            result.recommendation = "moderate"
        else:
            result.recommendation = "costly"

        # Cache result
        self._efficiency_cache[agent_name] = result
        self._cache_timestamp = datetime.now()

        logger.debug(
            f"cost_efficiency_computed agent={agent_name} "
            f"efficiency={result.efficiency_score:.2f} "
            f"calibration={result.calibration_score:.2f} "
            f"recommendation={result.recommendation}"
        )

        return result

    def _get_calibration_summary(self, agent_name: str) -> CalibrationSummary | None:
        """Get calibration summary from tracker."""
        if self.calibration_tracker is None:
            return None

        try:
            return self.calibration_tracker.get_calibration_summary(agent_name)
        except (ValueError, KeyError, TypeError, RuntimeError, AttributeError) as e:
            logger.warning("Failed to get calibration for %s: %s", agent_name, e)
            return None

    def _get_avg_cost(self, agent_name: str) -> Decimal:
        """Get average cost per call for an agent."""
        if self.cost_tracker is None:
            return Decimal("0")

        # Try to get from workspace stats
        # Note: This is a simplified approach; real implementation would
        # need to track per-agent costs more precisely
        try:
            # Get from any workspace that has this agent
            for workspace_id, stats in self.cost_tracker._workspace_stats.items():
                by_agent = stats.get("by_agent", {})
                if agent_name in by_agent:
                    total_cost = by_agent[agent_name]
                    # Estimate calls (rough approximation)
                    api_calls = stats.get("api_calls", 1)
                    return total_cost / max(1, api_calls)
        except (KeyError, TypeError, ValueError, ZeroDivisionError, AttributeError) as e:
            logger.debug("Could not get cost for %s: %s", agent_name, e)

        return Decimal("0")

    def _cost_score(self, cost: Decimal) -> float:
        """Convert cost to a 0-1 score (lower cost = higher score)."""
        if cost <= 0:
            return 0.5  # Unknown cost = neutral

        # Assume typical call costs $0.001-$0.10
        # $0.001 = score 1.0, $0.10 = score 0.0
        cost_float = float(cost)
        if cost_float <= 0.001:
            return 1.0
        elif cost_float >= 0.10:
            return 0.0
        else:
            return 1.0 - (cost_float - 0.001) / 0.099

    def estimate_task_cost(
        self,
        agent_name: str,
        base_cost: Decimal,
        rounds: int = 3,
    ) -> Decimal:
        """Estimate total cost for a task based on calibration.

        Well-calibrated agents likely need fewer verification rounds.
        Overconfident agents may need more rounds due to errors.

        Args:
            agent_name: Name of the agent
            base_cost: Base cost per round
            rounds: Expected number of rounds

        Returns:
            Estimated total cost
        """
        efficiency = self.compute_cost_efficiency(agent_name)

        multiplier = Decimal("1.0")

        if efficiency.is_overconfident:
            # Expect more rounds due to overconfidence errors
            multiplier = Decimal(str(self.config.overconfident_cost_multiplier))
        elif efficiency.is_underconfident:
            # Slight overhead from unnecessary caution
            multiplier = Decimal(str(self.config.underconfident_cost_multiplier))
        elif efficiency.confidence_reliability > 0.8:
            # Well-calibrated: might need fewer rounds
            multiplier = Decimal("0.9")

        return base_cost * rounds * multiplier

    def recommend_cost_efficient_agent(
        self,
        available_agents: list[str],
        min_accuracy: float = 0.7,
    ) -> str | None:
        """Recommend the most cost-efficient agent.

        Args:
            available_agents: List of available agent names
            min_accuracy: Minimum required accuracy

        Returns:
            Name of recommended agent, or None if none meet criteria
        """
        candidates: list[tuple[str, float]] = []

        for agent_name in available_agents:
            efficiency = self.compute_cost_efficiency(agent_name)

            if efficiency.recommendation == "insufficient_data":
                continue

            if efficiency.accuracy_score < min_accuracy:
                continue

            candidates.append((agent_name, efficiency.efficiency_score))

        if not candidates:
            return None

        # Sort by efficiency (descending)
        candidates.sort(key=lambda x: x[1], reverse=True)

        recommended = candidates[0][0]
        logger.info(
            "cost_efficient_agent_recommended agent=%s from %s candidates",
            recommended,
            len(available_agents),
        )

        return recommended

    def rank_agents_by_cost_efficiency(
        self,
        available_agents: list[str],
    ) -> list[tuple[str, float]]:
        """Rank agents by cost efficiency.

        Args:
            available_agents: List of available agent names

        Returns:
            List of (agent_name, efficiency_score) sorted by efficiency
        """
        rankings: list[tuple[str, float]] = []

        for agent_name in available_agents:
            efficiency = self.compute_cost_efficiency(agent_name)
            rankings.append((agent_name, efficiency.efficiency_score))

        rankings.sort(key=lambda x: x[1], reverse=True)
        return rankings

    def get_budget_aware_selection(
        self,
        available_agents: list[str],
        budget_remaining: Decimal,
        estimated_rounds: int = 3,
    ) -> list[str]:
        """Get agents that fit within budget constraints.

        Args:
            available_agents: List of available agent names
            budget_remaining: Remaining budget in USD
            estimated_rounds: Expected debate rounds

        Returns:
            List of agents that fit budget, sorted by efficiency
        """
        candidates: list[tuple[str, float, Decimal]] = []

        for agent_name in available_agents:
            efficiency = self.compute_cost_efficiency(agent_name)

            # Estimate cost
            base_cost = efficiency.cost_per_call or Decimal("0.01")
            estimated_cost = self.estimate_task_cost(agent_name, base_cost, estimated_rounds)

            if estimated_cost <= budget_remaining:
                candidates.append((agent_name, efficiency.efficiency_score, estimated_cost))

        # Sort by efficiency
        candidates.sort(key=lambda x: x[1], reverse=True)

        return [agent for agent, _, _ in candidates]

    def get_overconfident_agents(
        self,
        available_agents: list[str] | None = None,
    ) -> list[str]:
        """Get list of overconfident agents (may incur extra costs).

        Args:
            available_agents: Optional filter list

        Returns:
            List of overconfident agent names
        """
        if self.calibration_tracker is None:
            return []

        agents = available_agents or self.calibration_tracker.get_all_agents()
        overconfident = []

        for agent_name in agents:
            summary = self._get_calibration_summary(agent_name)
            if summary and summary.is_overconfident:
                overconfident.append(agent_name)

        return overconfident

    def get_well_calibrated_agents(
        self,
        available_agents: list[str] | None = None,
    ) -> list[str]:
        """Get list of well-calibrated agents (cost-efficient).

        Args:
            available_agents: Optional filter list

        Returns:
            List of well-calibrated agent names
        """
        if self.calibration_tracker is None:
            return []

        agents = available_agents or self.calibration_tracker.get_all_agents()
        well_calibrated = []

        for agent_name in agents:
            summary = self._get_calibration_summary(agent_name)
            if summary and summary.ece < self.config.well_calibrated_ece_threshold:
                well_calibrated.append(agent_name)

        return well_calibrated

    def get_efficiency(self, agent_name: str) -> AgentCostEfficiency | None:
        """Get cached efficiency data for an agent.

        Args:
            agent_name: Name of the agent

        Returns:
            AgentCostEfficiency if cached
        """
        # Check cache validity
        if self._cache_timestamp:
            elapsed = (datetime.now() - self._cache_timestamp).total_seconds()
            if elapsed > self._cache_ttl_seconds:
                self._efficiency_cache.clear()
                return None

        return self._efficiency_cache.get(agent_name)

    def refresh_cache(self, agents: list[str] | None = None) -> int:
        """Refresh efficiency cache for agents.

        Args:
            agents: List of agents to refresh, or None for all

        Returns:
            Number of agents refreshed
        """
        if agents is None and self.calibration_tracker:
            agents = self.calibration_tracker.get_all_agents()

        if not agents:
            return 0

        refreshed = 0
        for agent_name in agents:
            self.compute_cost_efficiency(agent_name)
            refreshed += 1

        return refreshed

    def get_stats(self) -> dict[str, Any]:
        """Get bridge statistics.

        Returns:
            Dict with bridge metrics
        """
        well_calibrated = self.get_well_calibrated_agents()
        overconfident = self.get_overconfident_agents()

        return {
            "agents_cached": len(self._efficiency_cache),
            "cache_valid": self._cache_timestamp is not None,
            "well_calibrated_agents": len(well_calibrated),
            "overconfident_agents": len(overconfident),
            "calibration_tracker_attached": self.calibration_tracker is not None,
            "cost_tracker_attached": self.cost_tracker is not None,
        }


def create_calibration_cost_bridge(
    calibration_tracker: CalibrationTracker | None = None,
    cost_tracker: CostTracker | None = None,
    **config_kwargs: Any,
) -> CalibrationCostBridge:
    """Create and configure a CalibrationCostBridge.

    Args:
        calibration_tracker: CalibrationTracker instance
        cost_tracker: CostTracker instance
        **config_kwargs: Additional configuration options

    Returns:
        Configured CalibrationCostBridge instance
    """
    config = CalibrationCostBridgeConfig(**config_kwargs)
    return CalibrationCostBridge(
        calibration_tracker=calibration_tracker,
        cost_tracker=cost_tracker,
        config=config,
    )


__all__ = [
    "CalibrationCostBridge",
    "CalibrationCostBridgeConfig",
    "AgentCostEfficiency",
    "create_calibration_cost_bridge",
]
