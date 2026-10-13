"""
Relationship Tracker to Bias Mitigation Bridge.

Bridges relationship data from RelationshipTracker into the BiasMitigation system,
enabling detection and mitigation of echo chamber effects in agent selection.

This closes the loop between:
1. RelationshipTracker: Tracks alliances, rivalries, agreement patterns
2. BiasMitigation: Detects and mitigates various biases in debate voting

By connecting them, we enable:
- Echo chamber detection (agents who always agree)
- Alliance bias mitigation (down-weight votes from allied agents)
- Diversity enforcement (prefer teams with varied relationships)
- Groupthink prevention

Usage:
    from aragora.debate.relationship_bias_bridge import RelationshipBiasBridge

    bridge = RelationshipBiasBridge(
        relationship_tracker=tracker,
        echo_chamber_threshold=0.8,
    )

    # Check team for echo chamber risk
    risk = bridge.compute_team_echo_risk(["claude", "gemini", "gpt-4"])

    # Get vote weight adjustments based on relationships
    weights = bridge.compute_relationship_weights(votes, proposals)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from itertools import combinations
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.core import Vote
    from aragora.ranking.relationships import RelationshipTracker, RelationshipMetrics

logger = logging.getLogger(__name__)


@dataclass
class EchoChamberRisk:
    """Assessment of echo chamber risk for a team."""

    team: list[str]
    overall_risk: float  # 0-1, higher = more echo chamber risk
    high_alliance_pairs: list[tuple[str, str]]  # Pairs with alliance_score > threshold
    agreement_stats: dict[str, float]  # Pair -> agreement_rate
    recommendation: str  # "safe", "caution", "high_risk"


@dataclass
class RelationshipBiasBridgeConfig:
    """Configuration for the relationship-bias bridge."""

    # Echo chamber detection threshold
    echo_chamber_alliance_threshold: float = 0.7

    # Minimum agreement rate to flag as potential echo chamber
    echo_chamber_agreement_threshold: float = 0.8

    # Weight penalty for votes from highly-allied agents
    alliance_vote_penalty: float = 0.3

    # Minimum debates before considering relationship
    min_debates_for_relationship: int = 5

    # Risk thresholds
    high_risk_threshold: float = 0.6  # Team risk score for "high_risk"
    caution_threshold: float = 0.3  # Team risk score for "caution"

    # Whether to apply vote weight adjustments
    apply_vote_adjustments: bool = True

    # Diversity bonus for teams with varied relationships
    diversity_bonus: float = 0.1


@dataclass
class RelationshipBiasBridge:
    """Bridges RelationshipTracker into BiasMitigation decisions.

    Key integration points:
    1. Detects echo chamber patterns from high-agreement pairs
    2. Computes vote weight adjustments for allied agents
    3. Assesses team composition for groupthink risk
    4. Provides diversity recommendations for team selection
    """

    relationship_tracker: RelationshipTracker | None = None
    config: RelationshipBiasBridgeConfig = field(default_factory=RelationshipBiasBridgeConfig)

    # Cache for relationship metrics
    _metrics_cache: dict[tuple[str, str], RelationshipMetrics] = field(
        default_factory=dict, repr=False
    )

    def compute_team_echo_risk(self, team: list[str]) -> EchoChamberRisk:
        """Assess echo chamber risk for a team.

        Args:
            team: List of agent names on the team

        Returns:
            EchoChamberRisk assessment
        """
        if len(team) < 2:
            return EchoChamberRisk(
                team=team,
                overall_risk=0.0,
                high_alliance_pairs=[],
                agreement_stats={},
                recommendation="safe",
            )

        high_alliance_pairs: list[tuple[str, str]] = []
        agreement_stats: dict[str, float] = {}
        total_risk = 0.0
        pair_count = 0

        # Check all pairs
        for agent_a, agent_b in combinations(team, 2):
            metrics = self._get_relationship_metrics(agent_a, agent_b)

            if metrics is None:
                continue

            if metrics.debate_count < self.config.min_debates_for_relationship:
                continue

            pair_key = f"{agent_a}:{agent_b}"
            agreement_stats[pair_key] = metrics.agreement_rate

            # Check alliance threshold
            if metrics.alliance_score > self.config.echo_chamber_alliance_threshold:
                high_alliance_pairs.append((agent_a, agent_b))

            # Check agreement threshold
            if metrics.agreement_rate > self.config.echo_chamber_agreement_threshold:
                high_alliance_pairs.append((agent_a, agent_b))

            # Accumulate risk
            # Risk = average of (alliance_score + agreement_rate) / 2
            pair_risk = (metrics.alliance_score + metrics.agreement_rate) / 2
            total_risk += pair_risk
            pair_count += 1

        # Calculate overall risk
        if pair_count > 0:
            overall_risk = total_risk / pair_count
        else:
            overall_risk = 0.0

        # Amplify risk if many high-alliance pairs
        alliance_ratio = len(high_alliance_pairs) / max(1, pair_count)
        overall_risk = min(1.0, overall_risk + alliance_ratio * 0.2)

        # Determine recommendation
        if overall_risk >= self.config.high_risk_threshold:
            recommendation = "high_risk"
        elif overall_risk >= self.config.caution_threshold:
            recommendation = "caution"
        else:
            recommendation = "safe"

        # Remove duplicates from high_alliance_pairs
        high_alliance_pairs = list(set(high_alliance_pairs))

        logger.debug(
            "team_echo_risk team=%s risk=%.2f high_alliance_pairs=%s recommendation=%s",
            team,
            overall_risk,
            len(high_alliance_pairs),
            recommendation,
        )

        return EchoChamberRisk(
            team=team,
            overall_risk=overall_risk,
            high_alliance_pairs=high_alliance_pairs,
            agreement_stats=agreement_stats,
            recommendation=recommendation,
        )

    def compute_vote_weight_adjustments(
        self,
        votes: list[Vote],
        proposals: dict[str, str],
    ) -> dict[str, float]:
        """Compute vote weight adjustments based on relationships.

        Reduces weight of votes from agents with high alliance scores
        with the agent they're voting for.

        Args:
            votes: List of votes
            proposals: Dict of agent_name -> proposal

        Returns:
            Dict of voter_name -> weight adjustment (multiplier)
        """
        if not self.config.apply_vote_adjustments:
            return {v.agent: 1.0 for v in votes}

        adjustments: dict[str, float] = {}

        for vote in votes:
            voter = vote.agent
            choice = vote.choice

            # Check if choice is an agent name
            if choice not in proposals:
                adjustments[voter] = 1.0
                continue

            # Get relationship between voter and chosen agent
            metrics = self._get_relationship_metrics(voter, choice)

            if metrics is None:
                adjustments[voter] = 1.0
                continue

            if metrics.debate_count < self.config.min_debates_for_relationship:
                adjustments[voter] = 1.0
                continue

            # Penalize votes for highly-allied agents
            if metrics.alliance_score > self.config.echo_chamber_alliance_threshold:
                penalty = metrics.alliance_score * self.config.alliance_vote_penalty
                adjustments[voter] = 1.0 - penalty
                logger.debug(
                    "alliance_vote_penalty voter=%s choice=%s alliance=%.2f penalty=%.2f",
                    voter,
                    choice,
                    metrics.alliance_score,
                    penalty,
                )
            else:
                adjustments[voter] = 1.0

        return adjustments

    def get_diverse_team_candidates(
        self,
        available_agents: list[str],
        team_size: int,
        required_agents: list[str] | None = None,
    ) -> list[list[str]]:
        """Suggest diverse team compositions.

        Prefers teams with lower echo chamber risk.

        Args:
            available_agents: All available agent names
            team_size: Desired team size
            required_agents: Agents that must be on the team

        Returns:
            List of team candidates sorted by diversity (most diverse first)
        """
        required = set(required_agents or [])

        if len(required) >= team_size:
            return [list(required)[:team_size]]

        # Generate candidate teams
        remaining = [a for a in available_agents if a not in required]
        slots_to_fill = team_size - len(required)

        if slots_to_fill > len(remaining):
            # Not enough agents
            return [list(required) + remaining]

        # Generate all combinations
        candidates: list[tuple[float, list[str]]] = []

        for combo in combinations(remaining, slots_to_fill):
            team = list(required) + list(combo)
            risk = self.compute_team_echo_risk(team)
            candidates.append((risk.overall_risk, team))

        # Sort by risk (ascending) and return teams
        candidates.sort(key=lambda x: x[0])

        return [team for _, team in candidates[:10]]  # Return top 10

    def get_echo_chamber_pairs(
        self,
        agents: list[str] | None = None,
    ) -> list[tuple[str, str, float]]:
        """Get all agent pairs that form potential echo chambers.

        Args:
            agents: Optional list to filter. If None, uses all cached relationships.

        Returns:
            List of (agent_a, agent_b, combined_risk) tuples
        """
        echo_pairs: list[tuple[str, str, float]] = []

        if agents:
            # Check specific pairs
            for agent_a, agent_b in combinations(agents, 2):
                metrics = self._get_relationship_metrics(agent_a, agent_b)
                if metrics and metrics.debate_count >= self.config.min_debates_for_relationship:
                    combined_risk = (metrics.alliance_score + metrics.agreement_rate) / 2
                    if combined_risk > self.config.caution_threshold:
                        echo_pairs.append((agent_a, agent_b, combined_risk))
        else:
            # Use cached metrics
            for (agent_a, agent_b), metrics in self._metrics_cache.items():
                if metrics.debate_count >= self.config.min_debates_for_relationship:
                    combined_risk = (metrics.alliance_score + metrics.agreement_rate) / 2
                    if combined_risk > self.config.caution_threshold:
                        echo_pairs.append((agent_a, agent_b, combined_risk))

        # Sort by risk descending
        echo_pairs.sort(key=lambda x: x[2], reverse=True)

        return echo_pairs

    def _get_relationship_metrics(
        self,
        agent_a: str,
        agent_b: str,
    ) -> RelationshipMetrics | None:
        """Get relationship metrics, using cache.

        Args:
            agent_a: First agent
            agent_b: Second agent

        Returns:
            RelationshipMetrics if available
        """
        # Normalize key order
        if agent_a > agent_b:
            agent_a, agent_b = agent_b, agent_a

        cache_key = (agent_a, agent_b)

        if cache_key in self._metrics_cache:
            return self._metrics_cache[cache_key]

        if self.relationship_tracker is None:
            return None

        metrics = self.relationship_tracker.compute_metrics(agent_a, agent_b)
        self._metrics_cache[cache_key] = metrics

        return metrics

    def compute_diversity_score(self, team: list[str]) -> float:
        """Compute a diversity score for a team.

        Higher score = more diverse relationships.

        Args:
            team: List of agent names

        Returns:
            Diversity score (0-1, higher = more diverse)
        """
        if len(team) < 2:
            return 1.0  # Single agent is maximally "diverse"

        total_diversity = 0.0
        pair_count = 0

        for agent_a, agent_b in combinations(team, 2):
            metrics = self._get_relationship_metrics(agent_a, agent_b)

            if metrics is None or metrics.debate_count < self.config.min_debates_for_relationship:
                # Unknown relationship = moderate diversity
                total_diversity += 0.5
            else:
                # Diversity = 1 - agreement_rate (different opinions = diverse)
                pair_diversity = 1 - metrics.agreement_rate

                # Rival pairs are more diverse than allied pairs
                if metrics.rivalry_score > metrics.alliance_score:
                    pair_diversity = min(1.0, pair_diversity + 0.1)

                total_diversity += pair_diversity

            pair_count += 1

        return total_diversity / pair_count if pair_count > 0 else 0.5

    def refresh_cache(self, agents: list[str]) -> int:
        """Refresh relationship cache for a set of agents.

        Args:
            agents: List of agent names to cache

        Returns:
            Number of relationships cached
        """
        cached = 0
        for agent_a, agent_b in combinations(agents, 2):
            metrics = self._get_relationship_metrics(agent_a, agent_b)
            if metrics:
                cached += 1

        logger.debug("relationship_cache_refreshed cached=%s", cached)
        return cached

    def clear_cache(self) -> None:
        """Clear the relationship metrics cache."""
        self._metrics_cache.clear()

    def get_stats(self) -> dict[str, Any]:
        """Get bridge statistics.

        Returns:
            Dict with bridge metrics
        """
        echo_pairs = self.get_echo_chamber_pairs()

        return {
            "relationships_cached": len(self._metrics_cache),
            "echo_chamber_pairs": len(echo_pairs),
            "apply_vote_adjustments": self.config.apply_vote_adjustments,
            "echo_threshold_alliance": self.config.echo_chamber_alliance_threshold,
            "echo_threshold_agreement": self.config.echo_chamber_agreement_threshold,
        }


def create_relationship_bias_bridge(
    relationship_tracker: RelationshipTracker | None = None,
    **config_kwargs: Any,
) -> RelationshipBiasBridge:
    """Create and configure a RelationshipBiasBridge.

    Args:
        relationship_tracker: RelationshipTracker instance
        **config_kwargs: Additional configuration options

    Returns:
        Configured RelationshipBiasBridge instance
    """
    config = RelationshipBiasBridgeConfig(**config_kwargs)
    return RelationshipBiasBridge(
        relationship_tracker=relationship_tracker,
        config=config,
    )


__all__ = [
    "RelationshipBiasBridge",
    "RelationshipBiasBridgeConfig",
    "EchoChamberRisk",
    "create_relationship_bias_bridge",
]
