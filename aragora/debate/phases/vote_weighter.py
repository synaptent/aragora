"""
Vote weighting for consensus phase.

Extracted from consensus_phase.py to improve maintainability and testability.
Handles calibration adjustments, weighted vote counting, and user vote integration.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

if TYPE_CHECKING:
    from aragora.core import Vote
    from aragora.debate.context import DebateContext
    from aragora.protocols.debate import DebateProtocol

logger = logging.getLogger(__name__)


@dataclass
class VoteWeighterConfig:
    """Configuration for vote weighting."""

    # Default user vote weight
    default_user_vote_weight: float = 0.5


@dataclass
class VoteWeighterDeps:
    """Dependencies for vote weighting operations."""

    # CalibrationTracker for confidence adjustments
    calibration_tracker: Any | None = None
    # Protocol for user vote weight config
    protocol: DebateProtocol | None = None
    # User votes list
    user_votes: list[dict] = field(default_factory=list)
    # Callback to drain user events
    drain_user_events: Callable[[], None] | None = None
    # Callback for user vote intensity multiplier
    user_vote_multiplier: Callable[[int, Any], float] | None = None


class VoteWeighter:
    """Handles vote weighting and calibration adjustments.

    Provides methods to:
    - Apply calibration adjustments to vote confidences
    - Count weighted votes with canonical choice mapping
    - Integrate user votes with intensity scaling

    Example:
        weighter = VoteWeighter(
            config=VoteWeighterConfig(),
            deps=VoteWeighterDeps(
                calibration_tracker=tracker,
                protocol=protocol,
                user_votes=user_votes,
            ),
        )
        adjusted = weighter.apply_calibration(votes, ctx)
        counts, total = weighter.count_weighted_votes(votes, mapping, weights)
    """

    def __init__(
        self,
        config: VoteWeighterConfig | None = None,
        deps: VoteWeighterDeps | None = None,
    ) -> None:
        """Initialize the vote weighter.

        Args:
            config: Weighting configuration.
            deps: Dependencies for calibration and user votes.
        """
        self.config = config or VoteWeighterConfig()
        self.deps = deps or VoteWeighterDeps()

    def apply_calibration_to_votes(
        self,
        votes: list[Vote],
        ctx: DebateContext,
    ) -> list[Vote]:
        """Apply calibration adjustments to vote confidences.

        Adjusts each vote's confidence based on the agent's historical
        calibration performance:
        - Overconfident agents have their confidence scaled down
        - Underconfident agents have their confidence scaled up
        - Well-calibrated agents are unchanged

        Args:
            votes: List of votes to adjust.
            ctx: Debate context.

        Returns:
            List of votes with adjusted confidences.
        """
        if not self.deps.calibration_tracker:
            return votes

        # Import here to avoid circular imports
        from aragora.agents.calibration import adjust_agent_confidence

        adjusted_votes: list[Any] = []
        for vote in votes:
            if isinstance(vote, Exception):
                adjusted_votes.append(vote)
                continue

            try:
                summary = self.deps.calibration_tracker.get_calibration_summary(vote.agent)
                original_conf = vote.confidence
                adjusted_conf = adjust_agent_confidence(original_conf, summary)

                # Create new vote with adjusted confidence
                if adjusted_conf != original_conf:
                    from aragora.core import Vote

                    adjusted_vote = Vote(
                        agent=vote.agent,
                        choice=vote.choice,
                        reasoning=vote.reasoning,
                        confidence=adjusted_conf,
                        continue_debate=vote.continue_debate,
                    )
                    adjusted_votes.append(adjusted_vote)
                    logger.debug(
                        "calibration_confidence_adjustment agent=%s "
                        "original=%.2f adjusted=%.2f bias=%s",
                        vote.agent,
                        original_conf,
                        adjusted_conf,
                        summary.bias_direction,
                    )
                else:
                    adjusted_votes.append(vote)
            except (ValueError, KeyError, TypeError) as e:  # noqa: BLE001
                logger.debug("Calibration adjustment failed for %s: %s", vote.agent, e)
                adjusted_votes.append(vote)

        return adjusted_votes

    def count_weighted_votes(
        self,
        votes: list[Vote],
        choice_mapping: dict[str, str],
        vote_weight_cache: dict[str, float],
    ) -> tuple[dict[str, float], float]:
        """Count weighted votes with canonical choice mapping.

        Args:
            votes: List of votes to count.
            choice_mapping: Mapping from vote choice to canonical form.
            vote_weight_cache: Pre-computed weights per agent.

        Returns:
            Tuple of (vote_counts, total_weighted) where vote_counts is a
            dict of canonical choices to weighted counts and total_weighted
            is the sum of all weights.
        """
        vote_counts: dict[str, float] = defaultdict(float)
        total_weighted = 0.0

        for v in votes:
            if not isinstance(v, Exception):
                canonical = choice_mapping.get(v.choice, v.choice)
                weight = vote_weight_cache.get(v.agent, 1.0)
                vote_counts[canonical] += weight
                total_weighted += weight

        return vote_counts, total_weighted

    def add_user_votes(
        self,
        vote_counts: dict[str, float],
        total_weighted: float,
        choice_mapping: dict[str, str],
    ) -> tuple[dict[str, float], float]:
        """Add user votes to counts with intensity scaling.

        Drains any pending user events, then adds each user vote to the
        counts with weight based on configured user_vote_weight and
        intensity multiplier.

        Args:
            vote_counts: Current vote counts to update.
            total_weighted: Current total weighted votes.
            choice_mapping: Mapping from vote choice to canonical form.

        Returns:
            Updated (vote_counts, total_weighted) tuple.
        """
        if self.deps.drain_user_events:
            self.deps.drain_user_events()

        base_user_weight = (
            getattr(self.deps.protocol, "user_vote_weight", None)
            or self.config.default_user_vote_weight
        )

        for user_vote in self.deps.user_votes:
            choice = user_vote.get("choice", "")
            if choice:
                canonical = choice_mapping.get(choice, choice)
                intensity = user_vote.get("intensity", 5)

                if self.deps.user_vote_multiplier:
                    intensity_multiplier = self.deps.user_vote_multiplier(
                        intensity, self.deps.protocol
                    )
                else:
                    intensity_multiplier = 1.0

                final_weight = base_user_weight * intensity_multiplier
                vote_counts[canonical] += final_weight
                total_weighted += final_weight

                logger.debug(
                    f"user_vote user={user_vote.get('user_id', 'anonymous')} "
                    f"choice={choice} intensity={intensity} weight={final_weight:.2f}"
                )

        return vote_counts, total_weighted

    def compute_vote_results(
        self,
        votes: list[Vote],
        choice_mapping: dict[str, str],
        vote_weight_cache: dict[str, float],
        include_user_votes: bool = True,
    ) -> tuple[dict[str, float], float]:
        """Compute full vote results with all weighting applied.

        Convenience method that combines counting and user vote integration.

        Args:
            votes: List of votes to process.
            choice_mapping: Mapping from vote choice to canonical form.
            vote_weight_cache: Pre-computed weights per agent.
            include_user_votes: Whether to include user votes.

        Returns:
            Tuple of (vote_counts, total_weighted).
        """
        vote_counts, total_weighted = self.count_weighted_votes(
            votes, choice_mapping, vote_weight_cache
        )

        if include_user_votes:
            vote_counts, total_weighted = self.add_user_votes(
                vote_counts, total_weighted, choice_mapping
            )

        return vote_counts, total_weighted
