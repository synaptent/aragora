"""
Voting phase logic extracted from Arena.

Provides utilities for:
- Vote collection and aggregation
- Semantic vote grouping (preventing artificial disagreement)
- Weighted vote counting (reputation, calibration, consistency)
- Vote result analysis
- Consensus strength calculation
"""

from __future__ import annotations

__all__ = [
    "WeightSource",
    "WeightedVoteResult",
    "VoteWeightCalculator",
    "VotingPhase",
]

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol
from collections.abc import Callable

if TYPE_CHECKING:
    from aragora.core import Vote
    from aragora.debate.convergence import SimilarityBackend
    from aragora.debate.protocol import DebateProtocol

logger = logging.getLogger(__name__)


class WeightSource(Protocol):
    """Protocol for weight providers."""

    def get_weight(self, agent_name: str) -> float:
        """Return weight for agent (typically 0.5-1.5 range)."""
        ...


@dataclass
class WeightedVoteResult:
    """Result of weighted vote counting."""

    winner: str | None = None
    vote_counts: dict[str, float] = field(default_factory=dict)
    total_weighted_votes: float = 0.0
    confidence: float = 0.0
    consensus_reached: bool = False
    consensus_strength: str = "none"  # "unanimous", "strong", "medium", "weak", "none"
    consensus_variance: float = 0.0
    choice_mapping: dict[str, str] = field(default_factory=dict)  # variant -> canonical


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
        reputation_source: Callable[[str], float] | None = None,
        reliability_weights: dict[str, float] | None = None,
        consistency_source: Callable[[str], float] | None = None,
        calibration_source: Callable[[str], float] | None = None,
    ):
        """Initialize weight calculator.

        Args:
            reputation_source: Function returning reputation weight (0.5-1.5)
            reliability_weights: Pre-computed reliability weights dict
            consistency_source: Function returning consistency score (0-1)
            calibration_source: Function returning calibration weight (0.5-1.5)
        """
        self._reputation_source = reputation_source
        self._reliability_weights = reliability_weights or {}
        self._consistency_source = consistency_source
        self._calibration_source = calibration_source
        self._cache: dict[str, float] = {}

    def compute_weight(self, agent_name: str) -> float:
        """Compute combined weight for an agent.

        Returns:
            Combined weight (product of all source weights)
        """
        if agent_name in self._cache:
            return self._cache[agent_name]

        weight = 1.0

        # Reputation weight (0.5-1.5)
        if self._reputation_source:
            try:
                weight *= self._reputation_source(agent_name)
            except (ValueError, KeyError, TypeError, RuntimeError) as e:  # noqa: BLE001
                logger.debug("Reputation weight error for %s: %s", agent_name, e)

        # Reliability weight (0-1 multiplier)
        if agent_name in self._reliability_weights:
            weight *= self._reliability_weights[agent_name]

        # Consistency weight (map 0-1 score to 0.5-1.0 multiplier)
        if self._consistency_source:
            try:
                consistency_score = self._consistency_source(agent_name)
                consistency_weight = 0.5 + (consistency_score * 0.5)
                weight *= consistency_weight
            except (ValueError, KeyError, TypeError, RuntimeError) as e:  # noqa: BLE001
                logger.debug("Consistency weight error for %s: %s", agent_name, e)

        # Calibration weight (0.5-1.5)
        if self._calibration_source:
            try:
                weight *= self._calibration_source(agent_name)
            except (ValueError, KeyError, TypeError, RuntimeError) as e:  # noqa: BLE001
                logger.debug("Calibration weight error for %s: %s", agent_name, e)

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


class VotingPhase:
    """Handles vote collection and aggregation logic.

    This class can be used as a mixin or standalone utility for
    managing the voting phase of a debate.
    """

    def __init__(
        self,
        protocol: DebateProtocol,
        similarity_backend: SimilarityBackend | None = None,
    ):
        """Initialize voting phase.

        Args:
            protocol: Debate protocol with voting configuration
            similarity_backend: Optional similarity backend for vote grouping
        """
        self.protocol = protocol
        self._similarity_backend = similarity_backend

    def group_similar_votes(self, votes: list[Vote]) -> dict[str, list[str]]:
        """Group semantically similar vote choices.

        This prevents artificial disagreement when agents vote for the
        same thing using different wording (e.g., "Vector DB" vs "Use vector database").

        Args:
            votes: List of Vote objects

        Returns:
            Dict mapping canonical choice -> list of original choices that map to it
        """
        if not self.protocol.vote_grouping or not votes:
            return {}

        # Get similarity backend (lazy load if needed)
        if self._similarity_backend is None:
            from aragora.debate.convergence import get_similarity_backend

            self._similarity_backend = get_similarity_backend("auto")
        backend = self._similarity_backend

        # Extract unique choices
        choices = list(set(v.choice for v in votes if v.choice))
        if len(choices) < 2:
            return {}

        # Build groups using union-find approach (optimized)
        groups: dict[str, list[str]] = {}  # canonical -> [choices]
        assigned: dict[str, str] = {}  # choice -> canonical

        # Track unassigned for O(n) filtering instead of O(n²) checks
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
            for other in unassigned:
                similarity = backend.compute_similarity(choice, other)
                if similarity >= self.protocol.vote_grouping_threshold:
                    groups[choice].append(other)
                    assigned[other] = choice
                    to_assign.append(other)

            # Remove newly assigned from unassigned set
            for item in to_assign:
                unassigned.remove(item)

        # Only return groups with multiple members (merges occurred)
        return {k: v for k, v in groups.items() if len(v) > 1}

    def apply_vote_grouping(self, votes: list[Vote], groups: dict[str, list[str]]) -> list[Vote]:
        """Apply vote grouping to normalize vote choices.

        Args:
            votes: Original votes
            groups: Grouping map from group_similar_votes()

        Returns:
            Votes with normalized choices
        """
        if not groups:
            return votes

        # Build reverse mapping: original -> canonical
        reverse_map: dict[str, str] = {}
        for canonical, members in groups.items():
            for member in members:
                reverse_map[member] = canonical

        # Create normalized votes
        normalized = []
        for vote in votes:
            if vote.choice in reverse_map:
                # Create copy with normalized choice
                normalized.append(
                    type(vote)(
                        agent=vote.agent,
                        choice=reverse_map[vote.choice],
                        reasoning=vote.reasoning,
                        confidence=vote.confidence,
                    )
                )
            else:
                normalized.append(vote)

        return normalized

    def compute_vote_distribution(self, votes: list[Vote]) -> dict[str, dict[str, Any]]:
        """Compute vote distribution statistics.

        Args:
            votes: List of votes

        Returns:
            Dict with choice -> {count, percentage, voters, avg_confidence}
        """
        if not votes:
            return {}

        from collections import Counter

        # Count votes per choice
        choice_counts = Counter(v.choice for v in votes if v.choice)
        total = sum(choice_counts.values())

        # Build detailed distribution
        distribution: dict[str, dict[str, Any]] = {}
        for choice, count in choice_counts.items():
            choice_votes = [v for v in votes if v.choice == choice]
            confidences = [
                v.confidence
                for v in choice_votes
                if hasattr(v, "confidence") and v.confidence is not None
            ]

            distribution[choice] = {
                "count": count,
                "percentage": (count / total * 100) if total > 0 else 0,
                "voters": [v.agent for v in choice_votes],
                "avg_confidence": sum(confidences) / len(confidences) if confidences else None,
            }

        return distribution

    def determine_winner(
        self,
        votes: list[Vote],
        require_majority: bool = False,
        min_margin: float = 0.0,
    ) -> str | None:
        """Determine the winning choice from votes.

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

    def count_weighted_votes(
        self,
        votes: list[Vote],
        weight_calculator: VoteWeightCalculator | None = None,
        user_votes: list[dict[str, Any] | None] | None = None,
        user_vote_weight: float = 0.5,
        user_vote_multiplier: Callable[[int, Any], float] | None = None,
    ) -> WeightedVoteResult:
        """Count votes with optional weighting.

        Args:
            votes: List of Vote objects
            weight_calculator: Optional calculator for agent vote weights
            user_votes: Optional list of user vote dicts with 'choice' and optional 'intensity'
            user_vote_weight: Base weight for user votes (default 0.5)
            user_vote_multiplier: Optional function(intensity, protocol) -> multiplier

        Returns:
            WeightedVoteResult with counts, winner, and consensus info
        """
        result = WeightedVoteResult()

        if not votes:
            return result

        # Group similar votes first
        vote_groups = self.group_similar_votes(votes)

        # Build choice mapping (variant -> canonical)
        for canonical, variants in vote_groups.items():
            for variant in variants:
                result.choice_mapping[variant] = canonical

        if vote_groups:
            logger.debug("vote_grouping_merged groups=%s", vote_groups)

        # Count votes with weights
        vote_counts: defaultdict[str, float] = defaultdict(float)
        total_weighted = 0.0

        for vote in votes:
            if isinstance(vote, Exception):
                continue

            canonical = result.choice_mapping.get(vote.choice, vote.choice)
            weight = 1.0
            if weight_calculator:
                weight = weight_calculator.compute_weight(vote.agent)

            vote_counts[canonical] += weight
            total_weighted += weight

        # Add user votes if provided
        if user_votes:
            for user_vote in user_votes:
                if user_vote is None:
                    continue
                choice = user_vote.get("choice", "")
                if choice:
                    canonical = result.choice_mapping.get(choice, choice)
                    weight = user_vote_weight
                    if user_vote_multiplier:
                        intensity = user_vote.get("intensity", 5)
                        weight *= user_vote_multiplier(intensity, self.protocol)
                    vote_counts[canonical] += weight
                    total_weighted += weight
                    logger.debug(
                        f"user_vote user={user_vote.get('user_id', 'anon')} "
                        f"choice={choice} weight={weight:.2f}"
                    )

        result.vote_counts = dict(vote_counts)
        result.total_weighted_votes = total_weighted

        # Determine winner
        if vote_counts and total_weighted > 0:
            winner, count = max(vote_counts.items(), key=lambda x: x[1])
            result.winner = winner
            result.confidence = count / total_weighted

            # Calculate consensus strength
            strength_info = self.compute_consensus_strength(vote_counts, total_weighted)
            result.consensus_strength = strength_info["strength"]
            result.consensus_variance = strength_info["variance"]

        return result

    def compute_consensus_strength(
        self,
        vote_counts: Counter | dict[str, float],
        total_votes: float,
    ) -> dict[str, Any]:
        """Compute consensus strength from vote distribution.

        Args:
            vote_counts: Counter or dict of choice -> vote count
            total_votes: Total number of weighted votes

        Returns:
            Dict with 'strength' (str) and 'variance' (float)
        """
        if not vote_counts:
            return {"strength": "none", "variance": 0.0}

        counts = list(vote_counts.values())

        if len(counts) == 1:
            return {"strength": "unanimous", "variance": 0.0}

        # Calculate variance
        mean = sum(counts) / len(counts)
        variance = sum((c - mean) ** 2 for c in counts) / len(counts)

        # Classify strength based on variance
        if variance < 1:
            strength = "strong"
        elif variance < 2:
            strength = "medium"
        else:
            strength = "weak"

        return {"strength": strength, "variance": variance}

    def check_unanimous(
        self,
        votes: list[Vote],
        voting_errors: int = 0,
    ) -> WeightedVoteResult:
        """Check for unanimous consensus (no weighting).

        In unanimous mode, all votes are equal and any dissent or error
        prevents consensus.

        Args:
            votes: List of Vote objects
            voting_errors: Number of voting errors (count as dissent)

        Returns:
            WeightedVoteResult with unanimous consensus check
        """
        result = WeightedVoteResult()

        if not votes:
            return result

        # Group similar votes
        vote_groups = self.group_similar_votes(votes)
        for canonical, variants in vote_groups.items():
            for variant in variants:
                result.choice_mapping[variant] = canonical

        # Count votes (unweighted)
        vote_counts: Counter = Counter()
        for vote in votes:
            if isinstance(vote, Exception):
                continue
            canonical = result.choice_mapping.get(vote.choice, vote.choice)
            vote_counts[canonical] += 1

        result.vote_counts = dict(vote_counts)

        # Total includes errors (they count as dissent)
        total_voters = len([v for v in votes if not isinstance(v, Exception)]) + voting_errors
        result.total_weighted_votes = float(total_voters)

        most_common = vote_counts.most_common(1)
        if most_common and total_voters > 0:
            winner, count = most_common[0]
            unanimity_ratio = count / total_voters

            result.winner = winner
            result.confidence = unanimity_ratio

            if unanimity_ratio >= 1.0:
                result.consensus_reached = True
                result.consensus_strength = "unanimous"
                result.consensus_variance = 0.0
                logger.info(
                    "consensus_unanimous winner=%s votes=%s/%s", winner, count, total_voters
                )
            else:
                result.consensus_reached = False
                result.consensus_strength = "none"
                logger.info(
                    f"consensus_not_unanimous best={winner} "
                    f"ratio={unanimity_ratio:.0%} votes={count}/{total_voters}"
                )

        return result
