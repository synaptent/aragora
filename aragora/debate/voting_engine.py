"""
Unified Voting Engine.

Consolidates voting implementations from:
- debate/phases/voting.py (VotingPhase, VoteWeightCalculator, WeightedVoteResult)
- debate/phases/vote_aggregator.py (VoteAggregator, AggregatedVotes)
- debate/consensus.py (VoteType, ConsensusVote)

This module provides a single, cohesive API for:
- Vote collection and validation
- Semantic vote grouping (preventing artificial disagreement)
- Weighted vote counting (reputation, calibration, consistency)
- User vote integration
- Consensus strength calculation
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol
from collections.abc import Callable

if TYPE_CHECKING:
    from aragora.core import Vote
    from aragora.debate.convergence import SimilarityBackend
    from aragora.protocols.debate import DebateProtocol

logger = logging.getLogger(__name__)

__all__ = [
    # Enums and Types
    "VoteType",
    "ConsensusStrength",
    # Data classes
    "VoteResult",
    "WeightConfig",
    # Protocols
    "WeightSource",
    # Main class
    "VotingEngine",
    # Utilities
    "VoteWeightCalculator",
]

# =============================================================================
# Core Types (from consensus.py, preserved as canonical)
# =============================================================================


class VoteType(Enum):
    """Types of votes."""

    AGREE = "agree"
    DISAGREE = "disagree"
    ABSTAIN = "abstain"
    CONDITIONAL = "conditional"  # Agree with reservations


class ConsensusStrength(Enum):
    """Strength classification for consensus."""

    UNANIMOUS = "unanimous"  # All votes agree
    STRONG = "strong"  # Variance < 1
    MEDIUM = "medium"  # Variance < 2
    WEAK = "weak"  # Variance >= 2
    NONE = "none"  # No votes or no clear winner


# =============================================================================
# Weight Configuration
# =============================================================================


class WeightSource(Protocol):
    """Protocol for vote weight providers."""

    def get_weight(self, agent_name: str) -> float:
        """Return weight for agent (typically 0.5-1.5 range)."""
        ...


@dataclass
class WeightConfig:
    """Configuration for vote weighting.

    Allows fine-grained control over weight sources and their contribution.
    """

    # Base weight for all votes
    base_weight: float = 1.0

    # Weight multiplier ranges
    min_weight: float = 0.1  # Minimum allowed weight
    max_weight: float = 3.0  # Maximum allowed weight

    # User vote settings
    user_vote_weight: float = 0.5  # Base weight for user votes
    user_intensity_multiplier: Callable[[int, Any], float] | None = None

    # Weight source contributions (0.0 = disabled, 1.0 = full contribution)
    reputation_contribution: float = 1.0
    reliability_contribution: float = 1.0
    consistency_contribution: float = 1.0
    calibration_contribution: float = 1.0


# =============================================================================
# Vote Result (unified from WeightedVoteResult and AggregatedVotes)
# =============================================================================


@dataclass
class VoteResult:
    """Unified result of vote counting.

    Consolidates WeightedVoteResult and AggregatedVotes into a single class.
    Provides all the information needed for consensus determination.
    """

    # Winner and counts
    winner: str | None = None
    vote_counts: dict[str, float] = field(default_factory=dict)
    total_weighted_votes: float = 0.0

    # Confidence and consensus
    confidence: float = 0.0
    consensus_reached: bool = False
    consensus_strength: ConsensusStrength = ConsensusStrength.NONE
    consensus_variance: float = 0.0

    # Vote grouping (for semantic similarity merging)
    choice_mapping: dict[str, str] = field(default_factory=dict)  # variant -> canonical
    vote_groups: dict[str, list[str]] = field(default_factory=dict)  # canonical -> [variants]

    # Statistics
    total_votes: int = 0
    agent_votes_count: int = 0
    user_votes_count: int = 0
    error_count: int = 0

    # Raw data for auditing
    votes_by_agent: dict[str, str] = field(default_factory=dict)  # agent -> choice
    weights_by_agent: dict[str, float] = field(default_factory=dict)  # agent -> weight

    def get_vote_distribution(self) -> dict[str, float]:
        """Get vote distribution as percentages."""
        if self.total_weighted_votes <= 0:
            return {}
        return {
            choice: count / self.total_weighted_votes for choice, count in self.vote_counts.items()
        }

    def get_runner_up(self) -> tuple[str, float] | None:
        """Get the runner-up choice and its count."""
        sorted_counts = sorted(self.vote_counts.items(), key=lambda x: x[1], reverse=True)
        if len(sorted_counts) >= 2:
            return sorted_counts[1]
        return None

    def get_margin(self) -> float:
        """Get margin of victory (0-1)."""
        if not self.winner or self.total_weighted_votes <= 0:
            return 0.0
        runner_up = self.get_runner_up()
        if not runner_up:
            return 1.0
        winner_pct = self.vote_counts.get(self.winner, 0) / self.total_weighted_votes
        runner_up_pct = runner_up[1] / self.total_weighted_votes
        return winner_pct - runner_up_pct


# =============================================================================
# Vote Weight Calculator
# =============================================================================


class VoteWeightCalculator:
    """Calculates vote weights from multiple sources.

    Combines weights from:
    - Reputation (from memory/history)
    - Reliability (from capability probing)
    - Consistency (from FlipDetector)
    - Calibration (from ELO system)

    Each weight source contributes a multiplier, typically in range 0.5-1.5.
    """

    def __init__(
        self,
        config: WeightConfig | None = None,
        reputation_source: Callable[[str], float] | None = None,
        reliability_weights: dict[str, float] | None = None,
        consistency_source: Callable[[str], float] | None = None,
        calibration_source: Callable[[str], float] | None = None,
    ):
        """Initialize weight calculator.

        Args:
            config: Weight configuration
            reputation_source: Function returning reputation weight (0.5-1.5)
            reliability_weights: Pre-computed reliability weights dict
            consistency_source: Function returning consistency score (0-1)
            calibration_source: Function returning calibration weight (0.5-1.5)
        """
        self.config = config or WeightConfig()
        self._reputation_source = reputation_source
        self._reliability_weights = reliability_weights or {}
        self._consistency_source = consistency_source
        self._calibration_source = calibration_source
        self._cache: dict[str, float] = {}

    def compute_weight(self, agent_name: str) -> float:
        """Compute combined weight for an agent.

        Returns:
            Combined weight (product of all source weights, clamped to config bounds)
        """
        if agent_name in self._cache:
            return self._cache[agent_name]

        weight = self.config.base_weight

        # Reputation weight (0.5-1.5)
        if self._reputation_source and self.config.reputation_contribution > 0:
            try:
                rep_weight = self._reputation_source(agent_name)
                # Apply contribution factor
                rep_weight = 1.0 + (rep_weight - 1.0) * self.config.reputation_contribution
                weight *= rep_weight
            except (TypeError, ValueError, AttributeError, KeyError, RuntimeError) as e:
                logger.debug("Reputation weight error for %s: %s", agent_name, e)

        # Reliability weight (0-1 multiplier)
        if agent_name in self._reliability_weights and self.config.reliability_contribution > 0:
            rel_weight = self._reliability_weights[agent_name]
            rel_weight = 1.0 + (rel_weight - 1.0) * self.config.reliability_contribution
            weight *= rel_weight

        # Consistency weight (map 0-1 score to 0.5-1.0 multiplier)
        if self._consistency_source and self.config.consistency_contribution > 0:
            try:
                consistency_score = self._consistency_source(agent_name)
                consistency_weight = 0.5 + (consistency_score * 0.5)
                consistency_weight = (
                    1.0 + (consistency_weight - 1.0) * self.config.consistency_contribution
                )
                weight *= consistency_weight
            except (TypeError, ValueError, AttributeError, KeyError, RuntimeError) as e:
                logger.debug("Consistency weight error for %s: %s", agent_name, e)

        # Calibration weight (0.5-1.5)
        if self._calibration_source and self.config.calibration_contribution > 0:
            try:
                cal_weight = self._calibration_source(agent_name)
                cal_weight = 1.0 + (cal_weight - 1.0) * self.config.calibration_contribution
                weight *= cal_weight
            except (TypeError, ValueError, AttributeError, KeyError, RuntimeError) as e:
                logger.debug("Calibration weight error for %s: %s", agent_name, e)

        # Clamp to configured bounds
        weight = max(self.config.min_weight, min(self.config.max_weight, weight))

        self._cache[agent_name] = weight
        return weight

    def compute_weights_batch(self, agent_names: list[str]) -> dict[str, float]:
        """Compute weights for multiple agents.

        Returns:
            Dict mapping agent name to weight
        """
        return {name: self.compute_weight(name) for name in agent_names}

    def clear_cache(self) -> None:
        """Clear the weight cache."""
        self._cache.clear()


# =============================================================================
# Unified Voting Engine
# =============================================================================


class VotingEngine:
    """Unified voting engine for debate consensus.

    Consolidates functionality from VotingPhase and VoteAggregator into
    a single, cohesive API. Supports:

    - Vote collection and validation
    - Semantic vote grouping (preventing artificial disagreement)
    - Weighted vote counting (reputation, calibration, consistency)
    - User vote integration
    - Multiple consensus modes (majority, unanimous, weighted)

    Usage:
        engine = VotingEngine(protocol=protocol)

        # Configure weight calculator (optional)
        engine.set_weight_calculator(VoteWeightCalculator(
            reputation_source=memory.get_reputation,
            calibration_source=elo.get_calibration,
        ))

        # Count votes
        result = engine.count_votes(votes, user_votes=user_votes)

        # Check consensus
        if result.consensus_reached:
            print(f"Winner: {result.winner} ({result.consensus_strength.value})")
    """

    def __init__(
        self,
        protocol: DebateProtocol | None = None,
        similarity_backend: SimilarityBackend | None = None,
        weight_config: WeightConfig | None = None,
    ):
        """Initialize voting engine.

        Args:
            protocol: Debate protocol with voting configuration
            similarity_backend: Optional similarity backend for vote grouping
            weight_config: Configuration for vote weighting
        """
        self.protocol = protocol
        self._similarity_backend = similarity_backend
        self._weight_config = weight_config or WeightConfig()
        self._weight_calculator: VoteWeightCalculator | None = None

    def set_weight_calculator(self, calculator: VoteWeightCalculator) -> None:
        """Set the weight calculator for weighted voting."""
        self._weight_calculator = calculator

    # -------------------------------------------------------------------------
    # Vote Grouping
    # -------------------------------------------------------------------------

    def group_similar_votes(self, votes: list[Vote]) -> dict[str, list[str]]:
        """Group semantically similar vote choices.

        This prevents artificial disagreement when agents vote for the
        same thing using different wording (e.g., "Vector DB" vs "Use vector database").

        Args:
            votes: List of Vote objects

        Returns:
            Dict mapping canonical choice -> list of original choices that map to it
        """
        # Check if grouping is enabled
        if self.protocol and not self.protocol.vote_grouping:
            return {}

        if not votes:
            return {}

        # Get similarity backend (lazy load if needed)
        if self._similarity_backend is None:
            from aragora.debate.convergence import get_similarity_backend

            self._similarity_backend = get_similarity_backend("auto")
        backend = self._similarity_backend

        # Extract unique choices
        choices = list(set(v.choice for v in votes if hasattr(v, "choice") and v.choice))
        if len(choices) < 2:
            return {}

        # Get grouping threshold
        threshold = 0.8
        if self.protocol and hasattr(self.protocol, "vote_grouping_threshold"):
            threshold = self.protocol.vote_grouping_threshold

        # Build groups using union-find approach (optimized)
        groups: dict[str, list[str]] = {}
        assigned: dict[str, str] = {}
        unassigned = set(choices)

        for choice in choices:
            if choice not in unassigned:
                continue

            # Start a new group with this choice as canonical
            groups[choice] = [choice]
            assigned[choice] = choice
            unassigned.remove(choice)

            # Check only remaining unassigned choices for similarity
            to_assign = []
            for other in list(unassigned):
                # Skip contradictory choices (e.g., "Accept" vs "Reject")
                if backend.is_contradictory(choice, other):
                    logger.debug("vote_grouping_skip_contradiction: '%s' vs '%s'", choice, other)
                    continue

                similarity = backend.compute_similarity(choice, other)
                if similarity >= threshold:
                    groups[choice].append(other)
                    assigned[other] = choice
                    to_assign.append(other)

            # Remove newly assigned from unassigned set
            for item in to_assign:
                unassigned.discard(item)

        # Only return groups with multiple members (merges occurred)
        return {k: v for k, v in groups.items() if len(v) > 1}

    def _build_choice_mapping(
        self, votes: list[Vote]
    ) -> tuple[dict[str, list[str]], dict[str, str]]:
        """Build vote groups and choice mapping.

        Returns:
            Tuple of (vote_groups, choice_mapping)
        """
        vote_groups = self.group_similar_votes(votes)

        # Build choice mapping from groups
        choice_mapping: dict[str, str] = {}
        for canonical, variants in vote_groups.items():
            for variant in variants:
                choice_mapping[variant] = canonical

        if vote_groups:
            logger.debug("vote_grouping_merged groups=%s", vote_groups)

        return vote_groups, choice_mapping

    # -------------------------------------------------------------------------
    # Vote Counting
    # -------------------------------------------------------------------------

    def count_votes(
        self,
        votes: list[Vote],
        user_votes: list[dict[str, Any]] | None = None,
        require_majority: bool = False,
        min_margin: float = 0.0,
    ) -> VoteResult:
        """Count votes with optional weighting.

        This is the main entry point for vote counting. It handles:
        - Vote grouping (semantic similarity)
        - Agent vote weighting
        - User vote integration
        - Consensus determination

        Args:
            votes: List of Vote objects from agents
            user_votes: Optional list of user vote dicts with 'choice' and 'intensity'
            require_majority: If True, winner must have >50% of votes
            min_margin: Minimum margin of victory (0-1)

        Returns:
            VoteResult with counts, winner, and consensus info
        """
        result = VoteResult()
        user_votes = user_votes or []

        # Handle empty votes
        valid_votes = [v for v in votes if not isinstance(v, Exception)]
        error_count = len(votes) - len(valid_votes)
        result.error_count = error_count

        if not valid_votes and not user_votes:
            return result

        # Step 1: Group similar votes
        vote_groups, choice_mapping = self._build_choice_mapping(valid_votes)
        result.vote_groups = vote_groups
        result.choice_mapping = choice_mapping

        # Step 2: Count agent votes with weights
        vote_counts: dict[str, float] = {}
        total_weighted = 0.0

        for vote in valid_votes:
            if not hasattr(vote, "choice") or not hasattr(vote, "agent"):
                continue

            canonical = choice_mapping.get(vote.choice, vote.choice)
            weight = 1.0
            if self._weight_calculator:
                weight = self._weight_calculator.compute_weight(vote.agent)

            vote_counts[canonical] = vote_counts.get(canonical, 0.0) + weight
            total_weighted += weight

            # Track raw data for auditing
            result.votes_by_agent[vote.agent] = vote.choice
            result.weights_by_agent[vote.agent] = weight

        result.agent_votes_count = len(valid_votes)

        # Step 3: Add user votes
        for user_vote in user_votes:
            choice = user_vote.get("choice", "")
            if not choice:
                continue

            canonical = choice_mapping.get(choice, choice)
            weight = self._weight_config.user_vote_weight

            # Apply intensity multiplier if configured
            if self._weight_config.user_intensity_multiplier:
                try:
                    intensity = user_vote.get("intensity", 5)
                    weight *= self._weight_config.user_intensity_multiplier(
                        intensity, self.protocol
                    )
                except (TypeError, ValueError, AttributeError, KeyError, RuntimeError) as e:
                    logger.warning("User vote multiplier failed: %s", e)

            vote_counts[canonical] = vote_counts.get(canonical, 0.0) + weight
            total_weighted += weight
            result.user_votes_count += 1

            logger.debug(
                "user_vote user=%s choice=%s weight=%.2f",
                user_vote.get("user_id", "anon"),
                choice,
                weight,
            )

        # Store results
        result.vote_counts = dict(vote_counts)
        result.total_weighted_votes = total_weighted
        result.total_votes = result.agent_votes_count + result.user_votes_count

        # Step 4: Determine winner and consensus
        if vote_counts and total_weighted > 0:
            # Get winner (highest vote count)
            winner = max(vote_counts, key=lambda k: vote_counts.get(k) or 0)
            count = vote_counts[winner]
            result.winner = winner
            result.confidence = count / total_weighted

            # Check requirements
            if require_majority and result.confidence <= 0.5:
                result.winner = None
            elif min_margin > 0:
                margin = result.get_margin()
                if margin < min_margin:
                    result.winner = None

            # Calculate consensus strength
            result.consensus_strength, result.consensus_variance = self._compute_consensus_strength(
                vote_counts
            )

            # Set consensus reached flag
            result.consensus_reached = result.winner is not None and result.consensus_strength in (
                ConsensusStrength.UNANIMOUS,
                ConsensusStrength.STRONG,
                ConsensusStrength.MEDIUM,
            )

        return result

    def count_unweighted(
        self,
        votes: list[Vote],
        voting_errors: int = 0,
    ) -> VoteResult:
        """Count votes without weighting (for unanimous mode).

        In unanimous mode, all votes are equal and any dissent or error
        prevents consensus.

        Args:
            votes: List of Vote objects
            voting_errors: Number of voting errors (count as dissent)

        Returns:
            VoteResult with unanimous consensus check
        """
        result = VoteResult()
        result.error_count = voting_errors

        valid_votes = [v for v in votes if not isinstance(v, Exception)]
        if not valid_votes:
            return result

        # Group similar votes
        vote_groups, choice_mapping = self._build_choice_mapping(valid_votes)
        result.vote_groups = vote_groups
        result.choice_mapping = choice_mapping

        # Count votes (unweighted)
        vote_counts: Counter = Counter()
        for vote in valid_votes:
            if not hasattr(vote, "choice"):
                continue
            canonical = choice_mapping.get(vote.choice, vote.choice)
            vote_counts[canonical] += 1
            result.votes_by_agent[vote.agent] = vote.choice

        result.vote_counts = dict(vote_counts)

        # Total includes errors (they count as dissent)
        total_voters = len(valid_votes) + voting_errors
        result.total_weighted_votes = float(total_voters)
        result.total_votes = total_voters
        result.agent_votes_count = len(valid_votes)

        if vote_counts and total_voters > 0:
            winner, count = vote_counts.most_common(1)[0]
            unanimity_ratio = count / total_voters

            result.winner = winner
            result.confidence = unanimity_ratio

            if unanimity_ratio >= 1.0:
                result.consensus_reached = True
                result.consensus_strength = ConsensusStrength.UNANIMOUS
                result.consensus_variance = 0.0
                logger.info(
                    "consensus_unanimous winner=%s votes=%s/%s", winner, count, total_voters
                )
            else:
                result.consensus_reached = False
                result.consensus_strength = ConsensusStrength.NONE
                logger.info(
                    "consensus_not_unanimous best=%s ratio=%.0f%% votes=%s/%s",
                    winner,
                    unanimity_ratio * 100,
                    count,
                    total_voters,
                )

        return result

    # -------------------------------------------------------------------------
    # Consensus Analysis
    # -------------------------------------------------------------------------

    def _compute_consensus_strength(
        self,
        vote_counts: Counter | dict[str, float],
    ) -> tuple[ConsensusStrength, float]:
        """Compute consensus strength from vote distribution.

        Args:
            vote_counts: Counter or dict of choice -> vote count

        Returns:
            Tuple of (strength enum, variance)
        """
        if not vote_counts:
            return ConsensusStrength.NONE, 0.0

        counts = list(vote_counts.values())

        if len(counts) == 1:
            return ConsensusStrength.UNANIMOUS, 0.0

        # Calculate variance
        mean = sum(counts) / len(counts)
        variance = sum((c - mean) ** 2 for c in counts) / len(counts)

        # Classify strength based on variance
        if variance < 1:
            strength = ConsensusStrength.STRONG
        elif variance < 2:
            strength = ConsensusStrength.MEDIUM
        else:
            strength = ConsensusStrength.WEAK

        return strength, variance

    def compute_vote_distribution(self, votes: list[Vote]) -> dict[str, dict[str, Any]]:
        """Compute vote distribution statistics.

        Args:
            votes: List of votes

        Returns:
            Dict with choice -> {count, percentage, voters, avg_confidence}
        """
        valid_votes = [v for v in votes if not isinstance(v, Exception)]
        if not valid_votes:
            return {}

        # Count votes per choice
        choice_counts = Counter(v.choice for v in valid_votes if hasattr(v, "choice") and v.choice)
        total = sum(choice_counts.values())

        # Build detailed distribution
        distribution: dict[str, dict[str, Any]] = {}
        for choice, count in choice_counts.items():
            choice_votes = [v for v in valid_votes if hasattr(v, "choice") and v.choice == choice]
            confidences = [
                v.confidence
                for v in choice_votes
                if hasattr(v, "confidence") and v.confidence is not None
            ]

            distribution[choice] = {
                "count": count,
                "percentage": (count / total * 100) if total > 0 else 0,
                "voters": [v.agent for v in choice_votes if hasattr(v, "agent")],
                "avg_confidence": sum(confidences) / len(confidences) if confidences else None,
            }

        return distribution

    def determine_winner(
        self,
        votes: list[Vote],
        require_majority: bool = False,
        min_margin: float = 0.0,
    ) -> str | None:
        """Determine the winning choice from votes (quick check, no weighting).

        Args:
            votes: List of votes
            require_majority: If True, winner must have >50% of votes
            min_margin: Minimum margin of victory (0-1)

        Returns:
            Winning choice, or None if no clear winner
        """
        distribution = self.compute_vote_distribution(votes)
        if not distribution:
            return None

        # Sort by count descending
        sorted_choices = sorted(distribution.items(), key=lambda x: x[1]["count"], reverse=True)

        if len(sorted_choices) == 0:
            return None

        winner, winner_stats = sorted_choices[0]

        # Check majority requirement
        if require_majority and winner_stats["percentage"] <= 50:
            return None

        # Check margin requirement
        if len(sorted_choices) > 1 and min_margin > 0:
            runner_up_pct = sorted_choices[1][1]["percentage"]
            margin = (winner_stats["percentage"] - runner_up_pct) / 100
            if margin < min_margin:
                return None

        return winner
