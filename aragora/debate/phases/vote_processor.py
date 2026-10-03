"""Vote collection and processing for consensus phase.

This module extracts vote-related operations from ConsensusPhase:
- Vote collection (parallel with timeout)
- Vote grouping and mapping
- Weight computation
- Calibration adjustments
- User vote integration
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

from aragora.config import AGENT_TIMEOUT_SECONDS
from aragora.debate.complexity_governor import get_complexity_governor
from aragora.debate.phases._phase_invariant import require_phase_result
from aragora.debate.phases.weight_calculator import WeightCalculator

if TYPE_CHECKING:
    from aragora.core import Agent, Vote
    from aragora.debate.context import DebateContext

logger = logging.getLogger(__name__)

# Default timeout for collecting all votes (prevents N*agent_timeout runaway)
DEFAULT_VOTE_COLLECTION_TIMEOUT = 180.0


class VoteProcessor:
    """Handles vote collection, processing, and aggregation.

    Extracted from ConsensusPhase to improve modularity and testability.
    """

    def __init__(
        self,
        *,
        # Dependencies
        memory: Any = None,
        elo_system: Any = None,
        flip_detector: Any = None,
        position_tracker: Any = None,
        calibration_tracker: Any = None,
        recorder: Any = None,
        agent_weights: dict[str, float] | None = None,
        hooks: dict[str, Callable[..., Any] | None] | None = None,
        user_votes: list[dict[str, Any] | None] | None = None,
        protocol: Any = None,
        # Callbacks
        vote_with_agent: Callable[..., Any] | None = None,
        with_timeout: Callable[..., Any] | None = None,
        group_similar_votes: Callable[..., Any] | None = None,
        get_calibration_weight: Callable[..., Any] | None = None,
        notify_spectator: Callable[..., Any] | None = None,
        drain_user_events: Callable[..., Any] | None = None,
        user_vote_multiplier: Callable[..., Any] | None = None,
        # Config
        vote_collection_timeout: float = DEFAULT_VOTE_COLLECTION_TIMEOUT,
    ) -> None:
        """Initialize the vote processor.

        Args:
            memory: Memory system for retrieving agent history
            elo_system: ELO rating system
            flip_detector: Flip detection for consistency weighting
            position_tracker: Position tracking for truth-grounded personas
            calibration_tracker: Calibration tracking for confidence adjustment
            recorder: Vote recorder
            agent_weights: Pre-computed agent weights
            hooks: Event hooks dictionary
            user_votes: List of user votes to include
            protocol: Debate protocol
            vote_with_agent: Callback to request vote from agent
            with_timeout: Timeout wrapper callback
            group_similar_votes: Vote grouping callback
            get_calibration_weight: Calibration weight callback
            notify_spectator: Spectator notification callback
            drain_user_events: User event drain callback
            user_vote_multiplier: User vote multiplier callback
            vote_collection_timeout: Timeout for collecting all votes
        """
        self.memory = memory
        self.elo_system = elo_system
        self.flip_detector = flip_detector
        self.position_tracker = position_tracker
        self.calibration_tracker = calibration_tracker
        self.recorder = recorder
        self.agent_weights = agent_weights or {}
        self.hooks = hooks or {}
        self.user_votes = user_votes or []
        self.protocol = protocol

        self._vote_with_agent = vote_with_agent
        self._with_timeout = with_timeout
        self._group_similar_votes = group_similar_votes
        self._get_calibration_weight = get_calibration_weight
        self._notify_spectator = notify_spectator
        self._drain_user_events = drain_user_events
        self._user_vote_multiplier = user_vote_multiplier

        self.vote_collection_timeout = vote_collection_timeout

    async def collect_votes(self, ctx: DebateContext) -> list[Vote]:
        """Collect votes from all agents with outer timeout protection.

        Uses VOTE_COLLECTION_TIMEOUT to prevent total vote collection time from
        exceeding reasonable bounds (N agents * per-agent timeout could be very long).
        If timeout is reached, returns partial votes collected so far.

        Args:
            ctx: The debate context

        Returns:
            List of collected votes (may be partial if timeout reached)
        """
        if not self._vote_with_agent:
            logger.warning("No vote_with_agent callback, skipping votes")
            return []

        votes: list[Vote] = []
        task = ctx.env.task if ctx.env else ""
        vote_with_agent = self._vote_with_agent
        if vote_with_agent is None:
            return votes
        with_timeout = self._with_timeout

        async def cast_vote(agent: Agent) -> tuple[Agent, Any]:
            """Cast a vote for a single agent with timeout protection."""
            logger.debug("agent_voting agent=%s", agent.name)
            try:
                base_timeout = getattr(agent, "timeout", AGENT_TIMEOUT_SECONDS)
                timeout = get_complexity_governor().get_scaled_timeout(float(base_timeout))
                if with_timeout:
                    vote_result = await with_timeout(
                        vote_with_agent(agent, ctx.proposals, task),
                        agent.name,
                        timeout_seconds=timeout,
                    )
                else:
                    vote_result = await vote_with_agent(agent, ctx.proposals, task)
                return (agent, vote_result)
            except (ValueError, KeyError, TypeError) as e:  # noqa: BLE001
                logger.warning(
                    "vote_exception agent=%s error=%s: %s", agent.name, type(e).__name__, e
                )
                return (agent, e)

        async def collect_all_votes() -> None:
            """Collect votes from all agents concurrently."""
            vote_tasks = [asyncio.create_task(cast_vote(agent)) for agent in ctx.agents]

            for completed_task in asyncio.as_completed(vote_tasks):
                try:
                    agent, vote_result = await completed_task
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001 - phase isolation
                    logger.error("task_exception phase=vote error=%s", e)
                    continue

                if vote_result is None or isinstance(vote_result, Exception):
                    if isinstance(vote_result, Exception):
                        logger.error("vote_error agent=%s error=%s", agent.name, vote_result)
                    else:
                        logger.error("vote_error agent=%s error=vote returned None", agent.name)
                else:
                    votes.append(vote_result)
                    self._handle_vote_success(ctx, agent, vote_result)

        try:
            await asyncio.wait_for(collect_all_votes(), timeout=self.vote_collection_timeout)
        except asyncio.TimeoutError:
            logger.warning(
                "vote_collection_timeout collected=%s expected=%s timeout=%ss",
                len(votes),
                len(ctx.agents),
                self.vote_collection_timeout,
            )

        return votes

    async def collect_votes_with_errors(self, ctx: DebateContext) -> tuple[list[Vote], int]:
        """Collect votes with error tracking.

        Used for unanimity mode where we need to track errors.

        Args:
            ctx: The debate context

        Returns:
            Tuple of (votes, error_count)
        """
        if not self._vote_with_agent:
            return [], 0

        votes: list[Vote] = []
        voting_errors = 0
        task = ctx.env.task if ctx.env else ""
        vote_with_agent = self._vote_with_agent
        if vote_with_agent is None:
            return votes, voting_errors
        with_timeout = self._with_timeout

        async def cast_vote(agent: Agent) -> tuple[Agent, Any]:
            """Cast a vote for unanimous consensus with timeout protection."""
            logger.debug("agent_voting_unanimous agent=%s", agent.name)
            try:
                base_timeout = getattr(agent, "timeout", AGENT_TIMEOUT_SECONDS)
                timeout = get_complexity_governor().get_scaled_timeout(float(base_timeout))
                if with_timeout:
                    vote_result = await with_timeout(
                        vote_with_agent(agent, ctx.proposals, task),
                        agent.name,
                        timeout_seconds=timeout,
                    )
                else:
                    vote_result = await vote_with_agent(agent, ctx.proposals, task)
                return (agent, vote_result)
            except (ValueError, KeyError, TypeError) as e:  # noqa: BLE001
                logger.warning(
                    "vote_exception_unanimous agent=%s error=%s: %s",
                    agent.name,
                    type(e).__name__,
                    e,
                )
                return (agent, e)

        async def collect_all_votes() -> None:
            """Collect votes from all agents with error counting."""
            nonlocal voting_errors
            vote_tasks = [asyncio.create_task(cast_vote(agent)) for agent in ctx.agents]

            for completed_task in asyncio.as_completed(vote_tasks):
                try:
                    agent, vote_result = await completed_task
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001 - phase isolation
                    logger.error("task_exception phase=unanimous_vote error=%s", e)
                    voting_errors += 1
                    continue

                if vote_result is None or isinstance(vote_result, Exception):
                    if isinstance(vote_result, Exception):
                        logger.error(
                            "vote_error_unanimous agent=%s error=%s", agent.name, vote_result
                        )
                    else:
                        logger.error(
                            "vote_error_unanimous agent=%s error=vote returned None", agent.name
                        )
                    voting_errors += 1
                else:
                    votes.append(vote_result)
                    self._handle_vote_success(ctx, agent, vote_result, unanimous=True)

        try:
            await asyncio.wait_for(collect_all_votes(), timeout=self.vote_collection_timeout)
        except asyncio.TimeoutError:
            missing = len(ctx.agents) - len(votes) - voting_errors
            voting_errors += missing
            logger.warning(
                "vote_collection_timeout_unanimous collected=%s errors=%s expected=%s timeout=%ss",
                len(votes),
                voting_errors,
                len(ctx.agents),
                self.vote_collection_timeout,
            )

        return votes, voting_errors

    def _handle_vote_success(
        self,
        ctx: DebateContext,
        agent: Agent,
        vote: Vote,
        unanimous: bool = False,
    ) -> None:
        """Handle successful vote: notifications, hooks, recording."""
        result = require_phase_result(ctx)

        logger.debug(
            f"vote_cast{'_unanimous' if unanimous else ''} agent={agent.name} "
            f"choice={vote.choice} confidence={vote.confidence:.0%}"
        )

        if self._notify_spectator:
            self._notify_spectator(
                "vote",
                agent=agent.name,
                details=f"Voted for {vote.choice}",
                metric=vote.confidence,
            )

        on_vote = self.hooks.get("on_vote")
        if on_vote:
            on_vote(agent.name, vote.choice, vote.confidence)

        if self.recorder:
            try:
                self.recorder.record_vote(agent.name, vote.choice, vote.reasoning)
            except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
                logger.debug("Recorder error for vote: %s", e)

        if self.position_tracker:
            try:
                debate_id = (
                    result.id if hasattr(result, "id") else (ctx.env.task[:50] if ctx.env else "")
                )
                self.position_tracker.record_position(
                    debate_id=debate_id,
                    agent_name=agent.name,
                    position_type="vote",
                    position_text=vote.choice,
                    round_num=result.rounds_used,
                    confidence=vote.confidence,
                )
            except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
                logger.debug("Position tracking error for vote: %s", e)

    def compute_vote_groups(self, votes: list[Vote]) -> tuple[dict[str, list[str]], dict[str, str]]:
        """Group similar votes and create choice mapping.

        Args:
            votes: List of votes to group

        Returns:
            Tuple of (vote_groups, choice_mapping)
        """
        if not self._group_similar_votes:
            choices = set(v.choice for v in votes if not isinstance(v, Exception))
            return {c: [c] for c in choices}, {c: c for c in choices}

        vote_groups = self._group_similar_votes(votes)

        choice_mapping: dict[str, str] = {}
        for canonical, variants in vote_groups.items():
            for variant in variants:
                choice_mapping[variant] = canonical

        if vote_groups:
            logger.debug("vote_grouping_merged groups=%s", vote_groups)

        return vote_groups, choice_mapping

    def compute_vote_weights(
        self, agents: list[Agent], domain: str = "general"
    ) -> dict[str, float]:
        """Pre-compute vote weights for all agents.

        Args:
            agents: List of agents
            domain: Debate domain for domain-specific ELO weighting

        Returns:
            Dictionary mapping agent names to weights
        """
        calculator = WeightCalculator(
            memory=self.memory,
            elo_system=self.elo_system,
            flip_detector=self.flip_detector,
            agent_weights=self.agent_weights,
            calibration_tracker=self.calibration_tracker,
            get_calibration_weight=self._get_calibration_weight,
            domain=domain,
        )
        return calculator.compute_weights(agents)

    def apply_calibration_to_votes(
        self,
        votes: list[Vote],
        ctx: DebateContext,
    ) -> list[Vote]:
        """Apply calibration adjustments to vote confidences.

        Adjusts each vote's confidence based on the agent's historical
        calibration performance.

        Args:
            votes: List of votes to adjust
            ctx: Debate context

        Returns:
            List of votes with adjusted confidences
        """
        if not self.calibration_tracker:
            return votes

        from aragora.agents.calibration import adjust_agent_confidence

        adjusted_votes: list[Any] = []
        for vote in votes:
            if isinstance(vote, Exception):
                adjusted_votes.append(vote)
                continue

            try:
                summary = self.calibration_tracker.get_calibration_summary(vote.agent)
                original_conf = vote.confidence
                adjusted_conf = adjust_agent_confidence(original_conf, summary)

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
            except (ValueError, KeyError, TypeError, RuntimeError) as e:  # noqa: BLE001
                logger.debug("Calibration adjustment failed for %s: %s", vote.agent, e)
                adjusted_votes.append(vote)

        return adjusted_votes

    def count_weighted_votes(
        self,
        votes: list[Vote],
        choice_mapping: dict[str, str],
        vote_weight_cache: dict[str, float],
    ) -> tuple[dict[str, float], float]:
        """Count weighted votes.

        Args:
            votes: List of votes
            choice_mapping: Mapping from vote choices to canonical choices
            vote_weight_cache: Pre-computed agent weights

        Returns:
            Tuple of (vote_counts, total_weighted)
        """
        vote_counts: dict[str, float] = defaultdict(float)
        total_weighted = 0.0

        for v in votes:
            if not isinstance(v, Exception):
                canonical = choice_mapping.get(v.choice, v.choice)
                weight = vote_weight_cache.get(v.agent, 1.0)
                vote_counts[canonical] += weight
                total_weighted += weight

        return dict(vote_counts), total_weighted

    def add_user_votes(
        self,
        vote_counts: dict[str, float],
        total_weighted: float,
        choice_mapping: dict[str, str],
    ) -> tuple[dict[str, float], float]:
        """Add user votes to counts.

        Args:
            vote_counts: Current vote counts
            total_weighted: Current total weighted votes
            choice_mapping: Mapping from vote choices to canonical choices

        Returns:
            Updated (vote_counts, total_weighted)
        """
        if self._drain_user_events:
            self._drain_user_events()

        base_user_weight = getattr(self.protocol, "user_vote_weight", 0.5)

        for user_vote in self.user_votes:
            if user_vote is None:
                continue
            choice = user_vote.get("choice", "")
            if choice:
                canonical = choice_mapping.get(choice, choice)
                intensity = user_vote.get("intensity", 5)

                if self._user_vote_multiplier:
                    intensity_multiplier = self._user_vote_multiplier(intensity, self.protocol)
                else:
                    intensity_multiplier = 1.0

                final_weight = base_user_weight * intensity_multiplier
                vote_counts[canonical] = vote_counts.get(canonical, 0.0) + final_weight
                total_weighted += final_weight

                logger.debug(
                    f"user_vote user={user_vote.get('user_id', 'anonymous')} "
                    f"choice={choice} intensity={intensity} weight={final_weight:.2f}"
                )

        return vote_counts, total_weighted

    def normalize_choice_to_agent(
        self,
        choice: str,
        agents: list[Agent],
        proposals: dict[str, str],
    ) -> str:
        """Normalize a vote choice to an agent name.

        Handles various formats:
        - Direct agent name: "claude-cli"
        - Quoted agent name: '"claude-cli"'
        - Proposal reference: "Proposal from claude-cli"
        - Partial match: "claude" -> "claude-cli"

        Args:
            choice: The vote choice to normalize
            agents: List of available agents
            proposals: Dictionary of proposals by agent name

        Returns:
            Normalized agent name or original choice if no match
        """
        choice_lower = choice.lower().strip().strip("\"'")
        agent_names = [a.name for a in agents]

        # Direct match
        for name in agent_names:
            if choice_lower == name.lower():
                return name

        # Proposal reference
        for name in agent_names:
            if f"proposal from {name.lower()}" in choice_lower:
                return name

        # Partial match
        for name in agent_names:
            if name.lower() in choice_lower or choice_lower in name.lower():
                return name

        # Check proposals
        for name, proposal in proposals.items():
            if choice_lower in proposal.lower():
                return name

        return choice


__all__ = ["VoteProcessor", "DEFAULT_VOTE_COLLECTION_TIMEOUT"]
