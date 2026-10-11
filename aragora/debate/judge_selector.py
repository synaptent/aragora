"""
Judge Selection for Multi-Agent Debates.

Provides strategies for selecting judges to evaluate debate outcomes.
Extracted from Arena orchestrator for cleaner separation of concerns.

Single Judge Strategies:
- last: Use synthesizer or last agent (legacy)
- random: Random selection
- voted: Agents vote for judge
- elo_ranked: Highest ELO agent judges
- calibrated: Best composite score (ELO + calibration)
- crux_aware: Prefer historical dissenters on similar topics

Multi-Judge Panel:
- JudgePanel: Coordinates multiple judges with voting strategies
- JudgingStrategy: MAJORITY, SUPERMAJORITY, UNANIMOUS, WEIGHTED

Features:
- Circuit breaker awareness: filters unavailable agents before selection
- Fallback selection: provides ordered list of candidates for retry
- Panel voting: aggregate multiple judge opinions

Usage:
    # Single judge
    selector = JudgeSelector(agents, elo_system, protocol)
    judge = await selector.select_judge(proposals, context)

    # Multi-judge panel
    panel = JudgePanel(judges=judges, strategy=JudgingStrategy.MAJORITY)
    panel.record_vote("claude", JudgeVote.APPROVE, 0.9, "Well-reasoned")
    result = panel.get_result()
"""

from __future__ import annotations

import logging
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Protocol
from collections.abc import Awaitable, Callable, Sequence

if TYPE_CHECKING:
    from typing import Any

    from aragora.core import Agent, Message
    from aragora.memory.consensus import ConsensusMemory
    from aragora.ranking.elo import EloSystem
    from aragora.resilience import CircuitBreaker

logger = logging.getLogger(__name__)


class JudgeProtocol(Protocol):
    """Protocol for judge selection configuration."""

    @property
    def judge_selection(self) -> str:
        """Judge selection strategy: last, random, voted, elo_ranked, calibrated."""
        ...

    @property
    def judge_termination(self) -> bool:
        """Whether to allow judge-based early termination."""
        ...

    @property
    def min_rounds_before_judge_check(self) -> int:
        """Minimum rounds before judge can terminate."""
        ...


@dataclass
class JudgeScore:
    """Composite score for judge selection."""

    agent_name: str
    elo_score: float
    calibration_score: float
    composite_score: float


class JudgeScoringMixin:
    """Mixin providing scoring utilities for judge selection."""

    def __init__(self, elo_system: EloSystem | None = None):
        self._elo_system = elo_system

    def get_calibration_weight(self, agent_name: str) -> float:
        """Get agent weight based on calibration score (0.5-1.5 range).

        Uses calibration_score from ELO system to weight agent contributions.
        Agents with better calibration have higher weight.

        Returns:
            Weight between 0.5 (uncalibrated/poor) and 1.5 (perfect calibration)
        """
        if not self._elo_system:
            return 1.0

        try:
            rating = self._elo_system.get_rating(agent_name)
            cal_score = rating.calibration_score
            return 0.5 + cal_score
        except (AttributeError, TypeError, KeyError, ValueError, RuntimeError) as e:
            logger.debug("Calibration weight lookup failed for %s: %s", agent_name, e)
            return 1.0

    def compute_composite_score(self, agent_name: str) -> float:
        """Compute composite score for judge selection (ELO + calibration).

        Combines ELO ranking with calibration score for nuanced judge selection.

        Returns:
            Composite score (higher is better)
        """
        if not self._elo_system:
            return 0.0

        try:
            rating = self._elo_system.get_rating(agent_name)
            # Normalize ELO: 1000 is baseline, 500 is typical deviation
            elo_normalized = (rating.elo - 1000) / 500
            elo_normalized = max(0, elo_normalized)

            cal_score = rating.calibration_score

            # Weighted combination: 70% ELO, 30% calibration
            return (elo_normalized * 0.7) + (cal_score * 0.3)
        except (AttributeError, TypeError, KeyError, ValueError, RuntimeError) as e:
            logger.debug("Composite score calculation failed for %s: %s", agent_name, e)
            return 0.0

    def get_all_scores(self, agents: Sequence[Agent]) -> list[JudgeScore]:
        """Get scores for all agents.

        Args:
            agents: Agents to score

        Returns:
            List of JudgeScore objects sorted by composite score descending
        """
        # Batch fetch all ratings in single query
        ratings = {}
        if self._elo_system:
            agent_names = [a.name for a in agents]
            try:
                ratings = self._elo_system.get_ratings_batch(agent_names)
            except (AttributeError, TypeError, KeyError, ValueError, RuntimeError) as e:
                logger.debug("Batch rating lookup failed for %s: %s", agent_names, e)
                ratings = {}

        scores = []
        for agent in agents:
            elo_score = 0.0
            cal_score = 0.0

            rating = ratings.get(agent.name)
            if rating:
                elo_score = (rating.elo - 1000) / 500
                elo_score = max(0, elo_score)
                cal_score = rating.calibration_score

            composite = (elo_score * 0.7) + (cal_score * 0.3)
            scores.append(
                JudgeScore(
                    agent_name=agent.name,
                    elo_score=elo_score,
                    calibration_score=cal_score,
                    composite_score=composite,
                )
            )

        scores.sort(key=lambda x: x.composite_score, reverse=True)
        return scores


class JudgeSelectionStrategy(ABC):
    """Base class for judge selection strategies."""

    @abstractmethod
    async def select(
        self,
        agents: Sequence[Agent],
        proposals: dict[str, str],
        context: list[Message],
    ) -> Agent | None:
        """Select a judge from available agents.

        Args:
            agents: Available agents to select from
            proposals: Current proposals by agent name
            context: Debate context messages

        Returns:
            Selected judge agent
        """
        ...


class LastAgentStrategy(JudgeSelectionStrategy):
    """Legacy strategy: use synthesizer or last agent."""

    async def select(
        self,
        agents: Sequence[Agent],
        proposals: dict[str, str],
        context: list[Message],
    ) -> Agent | None:
        """Select synthesizer if available, else last agent."""
        synthesizers = [a for a in agents if getattr(a, "role", None) == "synthesizer"]
        if synthesizers:
            return synthesizers[0]
        return agents[-1] if agents else None


class RandomStrategy(JudgeSelectionStrategy):
    """Random selection from all agents."""

    async def select(
        self,
        agents: Sequence[Agent],
        proposals: dict[str, str],
        context: list[Message],
    ) -> Agent | None:
        """Select a random agent as judge."""
        return random.choice(list(agents)) if agents else None  # noqa: S311 -- non-security agent selection


class EloRankedStrategy(JudgeSelectionStrategy, JudgeScoringMixin):
    """Select highest ELO-rated agent as judge."""

    def __init__(self, elo_system: EloSystem | None = None):
        JudgeScoringMixin.__init__(self, elo_system)

    async def select(
        self,
        agents: Sequence[Agent],
        proposals: dict[str, str],
        context: list[Message],
    ) -> Agent | None:
        """Select agent with highest ELO rating."""
        if not self._elo_system or not agents:
            return random.choice(list(agents)) if agents else None  # noqa: S311 -- non-security agent selection

        agent_names = [a.name for a in agents]

        try:
            leaderboard = self._elo_system.get_leaderboard(limit=len(agent_names))
            for entry in leaderboard:
                entry_agent_name = getattr(entry, "agent_name", None)
                if not isinstance(entry_agent_name, str) or not entry_agent_name:
                    entry_agent_name = getattr(entry, "agent", None)
                if entry_agent_name in agent_names:
                    judge = next((a for a in agents if a.name == entry_agent_name), None)
                    if judge:
                        logger.debug("Selected %s (ELO: %s) as judge", entry_agent_name, entry.elo)
                        return judge
        except (AttributeError, TypeError, KeyError, ValueError, RuntimeError) as e:
            logger.warning("ELO query failed: %s; falling back to random", e)

        return random.choice(list(agents)) if agents else None  # noqa: S311 -- non-security agent selection


class CalibratedStrategy(JudgeSelectionStrategy, JudgeScoringMixin):
    """Select based on composite score (ELO + calibration)."""

    def __init__(self, elo_system: EloSystem | None = None):
        JudgeScoringMixin.__init__(self, elo_system)

    async def select(
        self,
        agents: Sequence[Agent],
        proposals: dict[str, str],
        context: list[Message],
    ) -> Agent | None:
        """Select agent with best composite score."""
        if not self._elo_system or not agents:
            return random.choice(list(agents)) if agents else None  # noqa: S311 -- non-security agent selection

        scores = self.get_all_scores(agents)
        if scores:
            best = scores[0]
            judge = next((a for a in agents if a.name == best.agent_name), None)
            if judge:
                logger.debug(
                    f"Selected {best.agent_name} (composite: {best.composite_score:.3f}) as judge"
                )
                return judge

        return random.choice(list(agents)) if agents else None  # noqa: S311 -- non-security agent selection


class CruxAwareStrategy(JudgeSelectionStrategy, JudgeScoringMixin):
    """Select judges who historically dissented on debate cruxes.

    This strategy aims to improve debate quality by selecting judges
    who have previously shown contrarian perspectives on similar topics.
    Dissenters often catch blind spots the majority misses.

    Falls back to CalibratedStrategy if no relevant historical data.
    """

    def __init__(
        self,
        elo_system: EloSystem | None = None,
        consensus_memory: ConsensusMemory | None = None,
    ):
        JudgeScoringMixin.__init__(self, elo_system)
        self._consensus_memory = consensus_memory

    async def select(
        self,
        agents: Sequence[Agent],
        proposals: dict[str, str],
        context: list[Message],
        cruxes: list[dict] | None = None,
    ) -> Agent | None:
        """Select agent who historically dissented on similar cruxes.

        Args:
            agents: Available agents
            proposals: Current proposals
            context: Debate messages
            cruxes: Optional list of identified cruxes for this debate

        Returns:
            Selected judge, preferring historical dissenters
        """
        if not agents:
            return None

        # Try to find historical dissenters if we have consensus memory and cruxes
        if self._consensus_memory and cruxes:
            dissenters = self._find_historical_dissenters(cruxes, agents)
            if dissenters:
                # Rank dissenters by ELO and pick best one
                ranked = self._rank_by_elo(dissenters)
                if ranked:
                    logger.info(
                        "crux_aware_judge selected=%s reason=historical_dissenter", ranked[0].name
                    )
                    return ranked[0]

        # Fall back to calibrated strategy
        if self._elo_system:
            scores = self.get_all_scores(agents)
            if scores:
                best = scores[0]
                judge = next((a for a in agents if a.name == best.agent_name), None)
                if judge:
                    logger.debug(
                        f"crux_aware_judge fallback={best.agent_name} "
                        f"composite={best.composite_score:.3f}"
                    )
                    return judge

        # Ultimate fallback: random
        import random

        return random.choice(list(agents))  # noqa: S311 -- non-security agent selection

    def _find_historical_dissenters(
        self,
        cruxes: list[dict],
        agents: Sequence[Agent],
    ) -> list[Agent]:
        """Find agents who historically dissented on similar topics.

        Args:
            cruxes: Cruxes identified in this debate
            agents: Available agents to filter

        Returns:
            Agents who have dissented on similar topics
        """
        if not self._consensus_memory:
            return []

        agent_names = {a.name for a in agents}
        dissenters = set()

        try:
            # Extract topic from first crux if available
            for crux in cruxes[:2]:  # Check first 2 cruxes
                claim = crux.get("claim", "") or str(crux)

                # Query for similar debates
                similar = self._consensus_memory.find_similar_debates(claim, limit=5)

                for debate in similar:
                    # Check if this agent dissented in similar debate
                    dissenting = getattr(debate, "dissenting_agents", [])
                    if hasattr(debate, "consensus") and hasattr(
                        debate.consensus, "dissenting_agents"
                    ):
                        dissenting = debate.consensus.dissenting_agents

                    for agent_name in dissenting:
                        if agent_name in agent_names:
                            dissenters.add(agent_name)

        except (AttributeError, TypeError, KeyError, ValueError, RuntimeError) as e:
            logger.debug("Historical dissent query failed: %s", e)

        # Convert names back to agent objects
        return [a for a in agents if a.name in dissenters]

    def _rank_by_elo(self, agents: Sequence[Agent]) -> list[Agent]:
        """Rank agents by ELO score descending.

        Args:
            agents: Agents to rank

        Returns:
            Agents sorted by ELO (highest first)
        """
        if not self._elo_system or not agents:
            return list(agents)

        try:
            agent_names = [a.name for a in agents]
            ratings = self._elo_system.get_ratings_batch(agent_names)

            ranked = sorted(
                agents,
                key=lambda a: ratings.get(a.name, type("", (), {"elo": 1000})()).elo,
                reverse=True,
            )
            return ranked
        except (AttributeError, TypeError, KeyError, ValueError, RuntimeError) as e:
            logger.debug("ELO ranking failed: %s", e)
            return list(agents)


class VotedStrategy(JudgeSelectionStrategy):
    """Agents vote on who should judge."""

    def __init__(
        self,
        generate_fn: Callable[[Agent, str, list[Message]], Awaitable[str]],
        build_vote_prompt_fn: Callable[[list[Agent], dict[str, str]], str],
        sanitize_fn: Callable[[str, str], str] | None = None,
    ):
        """
        Initialize voted strategy.

        Args:
            generate_fn: Async function to generate agent response
            build_vote_prompt_fn: Function to build vote prompt
            sanitize_fn: Optional function to sanitize output
        """
        self._generate = generate_fn
        self._build_prompt = build_vote_prompt_fn
        self._sanitize = sanitize_fn or (lambda x, _: x)

    async def select(
        self,
        agents: Sequence[Agent],
        proposals: dict[str, str],
        context: list[Message],
    ) -> Agent | None:
        """Have agents vote on who should judge."""
        if not agents:
            return None

        vote_counts: dict[str, int] = {}

        for agent in agents:
            other_agents = [a for a in agents if a.name != agent.name]
            if not other_agents:
                continue

            prompt = self._build_prompt(other_agents, proposals)

            try:
                raw_response = await self._generate(agent, prompt, context)
                response = self._sanitize(raw_response, agent.name)

                # Parse vote - look for agent names in response
                for other in other_agents:
                    if other.name.lower() in response.lower():
                        vote_counts[other.name] = vote_counts.get(other.name, 0) + 1
                        break
            except (
                RuntimeError,
                ValueError,
                TypeError,
                TimeoutError,
                ConnectionError,
                OSError,
            ) as e:
                logger.warning("Judge vote error for %s: %s", agent.name, e)

        # Select agent with most votes, random tiebreaker
        if vote_counts:
            max_votes = max(vote_counts.values())
            candidates = [name for name, count in vote_counts.items() if count == max_votes]
            winner_name = random.choice(candidates)  # noqa: S311 -- non-security random selection
            winner = next((a for a in agents if a.name == winner_name), None)
            if winner:
                return winner

        return random.choice(list(agents)) if agents else None  # noqa: S311 -- non-security agent selection


class JudgeSelector(JudgeScoringMixin):
    """
    Main judge selection coordinator.

    Provides unified interface for all judge selection strategies.
    Supports circuit breaker integration to filter unavailable agents
    and provides fallback candidate lists for retry scenarios.

    Usage:
        selector = JudgeSelector(
            agents=agents,
            elo_system=elo_system,
            judge_selection="calibrated",
        )
        judge = await selector.select_judge(proposals, context)

        # With circuit breaker (filters unavailable agents)
        selector = JudgeSelector(
            agents=agents,
            elo_system=elo_system,
            circuit_breaker=breaker,
        )

        # Get ordered fallback candidates
        candidates = await selector.get_judge_candidates(proposals, context)
    """

    def __init__(
        self,
        agents: Sequence[Agent],
        elo_system: EloSystem | None = None,
        judge_selection: str = "random",
        generate_fn: Callable | None = None,
        build_vote_prompt_fn: Callable | None = None,
        sanitize_fn: Callable | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        consensus_memory: ConsensusMemory | None = None,
    ):
        """
        Initialize the judge selector.

        Args:
            agents: Available agents
            elo_system: Optional ELO system for ranked selection
            judge_selection: Strategy name (last, random, voted, elo_ranked, calibrated, crux_aware)
            generate_fn: Agent generation function (required for voted strategy)
            build_vote_prompt_fn: Vote prompt builder (required for voted strategy)
            sanitize_fn: Output sanitizer function
            circuit_breaker: Optional circuit breaker for filtering unavailable agents
            consensus_memory: Optional ConsensusMemory for crux-aware selection
        """
        JudgeScoringMixin.__init__(self, elo_system)
        self._agents = list(agents)
        self._judge_selection = judge_selection
        self._generate_fn = generate_fn
        self._build_vote_prompt_fn = build_vote_prompt_fn
        self._sanitize_fn = sanitize_fn
        self._circuit_breaker = circuit_breaker
        self._consensus_memory = consensus_memory

        # Initialize strategies
        self._strategies: dict[str, JudgeSelectionStrategy] = {
            "last": LastAgentStrategy(),
            "random": RandomStrategy(),
            "elo_ranked": EloRankedStrategy(elo_system),
            "calibrated": CalibratedStrategy(elo_system),
            "crux_aware": CruxAwareStrategy(elo_system, consensus_memory),
        }

        # Add voted strategy if dependencies provided
        if generate_fn and build_vote_prompt_fn:
            self._strategies["voted"] = VotedStrategy(
                generate_fn=generate_fn,
                build_vote_prompt_fn=build_vote_prompt_fn,
                sanitize_fn=sanitize_fn,
            )

    def _filter_available_agents(self, agents: Sequence[Agent]) -> list[Agent]:
        """
        Filter agents by circuit breaker availability.

        Args:
            agents: Agents to filter

        Returns:
            List of agents with circuit breaker in closed/half-open state.
            Returns all agents if no circuit breaker configured.
        """
        if not self._circuit_breaker:
            return list(agents)

        available = []
        for agent in agents:
            if self._circuit_breaker.is_available(agent.name):
                available.append(agent)
            else:
                logger.debug("judge_filter_unavailable agent=%s", agent.name)

        if not available:
            # All agents unavailable - fall back to all agents with warning
            logger.warning("judge_selection_all_unavailable count=%s, using all", len(agents))
            return list(agents)

        logger.debug("judge_filter_result available=%s/%s", len(available), len(agents))
        return available

    async def select_judge(
        self,
        proposals: dict[str, str],
        context: list[Message],
    ) -> Agent | None:
        """
        Select a judge using the configured strategy.

        Filters unavailable agents (via circuit breaker) before selection.

        Args:
            proposals: Current proposals by agent name
            context: Debate context messages

        Returns:
            Selected judge agent, or None when no agents are configured
        """
        # Filter available agents first
        available_agents = self._filter_available_agents(self._agents)

        strategy = self._strategies.get(self._judge_selection)

        if not strategy:
            logger.warning("Unknown judge selection '%s', using random", self._judge_selection)
            strategy = self._strategies["random"]

        judge = await strategy.select(available_agents, proposals, context)

        if judge is None and available_agents:
            logger.warning("Judge selection returned None, falling back to random")
            judge = random.choice(available_agents)  # noqa: S311 -- non-security random selection

        return judge

    async def get_judge_candidates(
        self,
        proposals: dict[str, str],
        context: list[Message],
        max_candidates: int = 3,
    ) -> list[Agent]:
        """
        Get an ordered list of judge candidates for fallback selection.

        Returns candidates sorted by composite score (ELO + calibration),
        filtered by circuit breaker availability.

        Args:
            proposals: Current proposals by agent name
            context: Debate context messages
            max_candidates: Maximum number of candidates to return

        Returns:
            Ordered list of agent candidates (best first)
        """
        available_agents = self._filter_available_agents(self._agents)

        if not available_agents:
            return []

        # Get scores for all available agents
        scores = self.get_all_scores(available_agents)

        # Return agents in score order
        candidates = []
        for score in scores[:max_candidates]:
            agent = next((a for a in available_agents if a.name == score.agent_name), None)
            if agent:
                candidates.append(agent)

        # If we got no scores (no ELO system), use random shuffling
        if not candidates:
            candidates = list(available_agents)[:max_candidates]
            random.shuffle(candidates)

        logger.debug(
            "judge_candidates count=%s agents=%s", len(candidates), [a.name for a in candidates]
        )
        return candidates

    @classmethod
    def from_protocol(
        cls,
        protocol: JudgeProtocol,
        agents: Sequence[Agent],
        elo_system: EloSystem | None = None,
        generate_fn: Callable | None = None,
        build_vote_prompt_fn: Callable | None = None,
        sanitize_fn: Callable | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> JudgeSelector:
        """
        Create JudgeSelector from a debate protocol.

        Args:
            protocol: Protocol with judge_selection setting
            agents: Available agents
            elo_system: Optional ELO system
            generate_fn: Agent generation function
            build_vote_prompt_fn: Vote prompt builder
            sanitize_fn: Output sanitizer
            circuit_breaker: Optional circuit breaker for filtering

        Returns:
            Configured JudgeSelector
        """
        return cls(
            agents=agents,
            elo_system=elo_system,
            judge_selection=protocol.judge_selection,
            generate_fn=generate_fn,
            build_vote_prompt_fn=build_vote_prompt_fn,
            sanitize_fn=sanitize_fn,
            circuit_breaker=circuit_breaker,
        )


# =============================================================================
# Multi-Judge Panel System
# =============================================================================


class JudgingStrategy(Enum):
    """Strategy for aggregating multiple judge votes."""

    MAJORITY = "majority"  # Simple majority (>50%)
    SUPERMAJORITY = "supermajority"  # 2/3+ agreement
    UNANIMOUS = "unanimous"  # All judges must agree
    WEIGHTED = "weighted"  # Votes weighted by expertise/calibration


class JudgeVote(Enum):
    """A judge's vote on consensus validity."""

    APPROVE = "approve"  # Consensus is valid
    REJECT = "reject"  # Consensus should be rejected
    ABSTAIN = "abstain"  # Cannot evaluate


@dataclass
class JudgeVoteRecord:
    """Record of a judge's vote on consensus."""

    judge_name: str
    vote: JudgeVote
    confidence: float  # 0-1
    reasoning: str
    weight: float = 1.0  # For weighted voting
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: dict = field(default_factory=dict)


@dataclass
class JudgingResult:
    """Result of judge panel evaluation."""

    approved: bool
    strategy: JudgingStrategy
    votes: list[JudgeVoteRecord]
    approval_ratio: float
    weighted_approval: float
    confidence: float
    reasoning: str
    dissenting_judges: list[str] = field(default_factory=list)
    abstaining_judges: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "approved": self.approved,
            "strategy": self.strategy.value,
            "votes": [
                {
                    "judge": v.judge_name,
                    "vote": v.vote.value,
                    "confidence": v.confidence,
                    "reasoning": v.reasoning,
                    "weight": v.weight,
                }
                for v in self.votes
            ],
            "approval_ratio": self.approval_ratio,
            "weighted_approval": self.weighted_approval,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "dissenting_judges": self.dissenting_judges,
            "abstaining_judges": self.abstaining_judges,
        }


class JudgePanel:
    """
    Panel of judges that evaluates debate consensus.

    Coordinates judge voting and applies the selected judging strategy.
    Use this when you want multiple independent judges to evaluate
    debate outcomes for higher confidence in consensus validity.

    Example:
        # Create panel with 3 judges using weighted voting
        panel = JudgePanel(
            judges=selected_judges,
            strategy=JudgingStrategy.WEIGHTED,
            judge_weights={"claude": 1.2, "gpt4": 1.0, "gemini": 0.9}
        )

        # Record votes (typically from async judge evaluation)
        panel.record_vote("claude", JudgeVote.APPROVE, 0.9, "Well-reasoned argument")
        panel.record_vote("gpt4", JudgeVote.APPROVE, 0.8, "Sound logic")
        panel.record_vote("gemini", JudgeVote.REJECT, 0.7, "Missing edge case")

        # Get aggregated result
        result = panel.get_result()
        if result.approved:
            print(f"Consensus approved with {result.confidence:.0%} confidence")
    """

    def __init__(
        self,
        judges: list[Agent],
        strategy: JudgingStrategy = JudgingStrategy.MAJORITY,
        judge_weights: dict[str, float] | None = None,
    ):
        """
        Initialize judge panel.

        Args:
            judges: List of judge agents
            strategy: Voting strategy for consensus
            judge_weights: Optional per-judge weights (for weighted voting)
        """
        self.judges = judges
        self.strategy = strategy
        self.judge_weights = judge_weights or {}
        self.votes: list[JudgeVoteRecord] = []

    def record_vote(
        self,
        judge_name: str,
        vote: JudgeVote,
        confidence: float,
        reasoning: str,
        metadata: dict | None = None,
    ) -> JudgeVoteRecord:
        """
        Record a judge's vote.

        Args:
            judge_name: Name of the voting judge
            vote: The vote (approve/reject/abstain)
            confidence: Confidence level (0-1)
            reasoning: Explanation for the vote
            metadata: Optional additional data

        Returns:
            The recorded vote
        """
        weight = self.judge_weights.get(judge_name, 1.0)
        record = JudgeVoteRecord(
            judge_name=judge_name,
            vote=vote,
            confidence=confidence,
            reasoning=reasoning,
            weight=weight,
            metadata=metadata or {},
        )
        self.votes.append(record)
        logger.debug(
            f"judge_vote recorded judge={judge_name} vote={vote.value} "
            f"confidence={confidence:.2f} weight={weight:.2f}"
        )
        return record

    def get_result(self) -> JudgingResult:
        """
        Compute judging result based on recorded votes.

        Returns:
            JudgingResult with approval status and reasoning
        """
        if not self.votes:
            return JudgingResult(
                approved=False,
                strategy=self.strategy,
                votes=[],
                approval_ratio=0.0,
                weighted_approval=0.0,
                confidence=0.0,
                reasoning="No votes recorded",
            )

        # Categorize votes
        approvals = [v for v in self.votes if v.vote == JudgeVote.APPROVE]
        rejections = [v for v in self.votes if v.vote == JudgeVote.REJECT]
        abstentions = [v for v in self.votes if v.vote == JudgeVote.ABSTAIN]

        # Compute ratios (excluding abstentions)
        non_abstain = len(approvals) + len(rejections)
        approval_ratio = len(approvals) / non_abstain if non_abstain > 0 else 0.0

        # Compute weighted approval
        total_weight = sum(v.weight for v in self.votes if v.vote != JudgeVote.ABSTAIN)
        approve_weight = sum(v.weight for v in approvals)
        weighted_approval = approve_weight / total_weight if total_weight > 0 else 0.0

        # Apply strategy
        approved = self._apply_strategy(approval_ratio, weighted_approval, approvals, rejections)

        # Compute aggregate confidence
        if approvals:
            confidence = sum(v.confidence for v in approvals) / len(approvals)
        elif rejections:
            confidence = sum(v.confidence for v in rejections) / len(rejections)
        else:
            confidence = 0.0

        # Generate reasoning
        reasoning = self._generate_reasoning(approved, approvals, rejections, abstentions)

        result = JudgingResult(
            approved=approved,
            strategy=self.strategy,
            votes=self.votes.copy(),
            approval_ratio=approval_ratio,
            weighted_approval=weighted_approval,
            confidence=confidence,
            reasoning=reasoning,
            dissenting_judges=[v.judge_name for v in rejections],
            abstaining_judges=[v.judge_name for v in abstentions],
        )

        logger.info(
            f"judge_panel_result approved={approved} strategy={self.strategy.value} "
            f"ratio={approval_ratio:.2f} weighted={weighted_approval:.2f} "
            f"confidence={confidence:.2f}"
        )

        return result

    def _apply_strategy(
        self,
        approval_ratio: float,
        weighted_approval: float,
        approvals: list[JudgeVoteRecord],
        rejections: list[JudgeVoteRecord],
    ) -> bool:
        """Apply judging strategy to determine approval."""
        if self.strategy == JudgingStrategy.MAJORITY:
            return approval_ratio > 0.5

        elif self.strategy == JudgingStrategy.SUPERMAJORITY:
            return approval_ratio >= 2 / 3

        elif self.strategy == JudgingStrategy.UNANIMOUS:
            return len(rejections) == 0 and len(approvals) > 0

        elif self.strategy == JudgingStrategy.WEIGHTED:
            return weighted_approval > 0.5

        else:
            # Default to majority
            return approval_ratio > 0.5

    def _generate_reasoning(
        self,
        approved: bool,
        approvals: list[JudgeVoteRecord],
        rejections: list[JudgeVoteRecord],
        abstentions: list[JudgeVoteRecord],
    ) -> str:
        """Generate human-readable reasoning for the result."""
        parts = []

        if approved:
            parts.append(f"Consensus APPROVED by judge panel ({self.strategy.value} strategy).")
        else:
            parts.append(f"Consensus REJECTED by judge panel ({self.strategy.value} strategy).")

        parts.append(
            f"Votes: {len(approvals)} approve, {len(rejections)} reject, "
            f"{len(abstentions)} abstain."
        )

        if approvals:
            parts.append(f"Key approval reason: {approvals[0].reasoning[:100]}")

        if rejections:
            parts.append(f"Key rejection reason: {rejections[0].reasoning[:100]}")

        return " ".join(parts)

    def reset(self) -> None:
        """Clear recorded votes for reuse."""
        self.votes.clear()

    async def deliberate_and_vote(
        self,
        proposals: dict[str, str],
        task: str,
        context: list[Message],
        generate_fn: Callable,
        deliberation_rounds: int = 2,
        build_assessment_prompt: Callable | None = None,
        build_deliberation_prompt: Callable | None = None,
    ) -> JudgingResult:
        """
        Judges deliberate before final verdict (Agent-as-a-Judge bias mitigation).

        Instead of voting independently, judges:
        1. Share initial assessments
        2. Deliberate on each other's reasoning for N rounds
        3. Cast final votes after deliberation

        This process reduces individual biases by exposing judges to
        diverse perspectives before they commit to a verdict.

        Args:
            proposals: Proposals being judged
            task: The debate task/question
            context: Debate context messages
            generate_fn: Async function to generate agent responses
            deliberation_rounds: Number of deliberation rounds (default: 2)
            build_assessment_prompt: Optional custom prompt builder for assessments
            build_deliberation_prompt: Optional custom prompt builder for deliberation

        Returns:
            JudgingResult with votes informed by deliberation
        """
        logger.info(
            "judge_deliberation_start judges=%s rounds=%s", len(self.judges), deliberation_rounds
        )

        # Step 1: Collect initial assessments
        assessments = await self._collect_initial_assessments(
            proposals, task, context, generate_fn, build_assessment_prompt
        )

        if not assessments:
            return JudgingResult(
                approved=False,
                strategy=self.strategy,
                votes=[],
                approval_ratio=0.0,
                weighted_approval=0.0,
                confidence=0.0,
                reasoning="No assessments collected during deliberation",
            )

        # Step 2: Run deliberation rounds
        for round_num in range(deliberation_rounds):
            assessments = await self._run_deliberation_round(
                assessments,
                proposals,
                task,
                context,
                generate_fn,
                round_num,
                build_deliberation_prompt,
            )

        # Step 3: Collect final votes based on deliberation
        await self._collect_final_votes(assessments, proposals, task, context, generate_fn)

        # Return aggregated result
        return self.get_result()

    async def _collect_initial_assessments(
        self,
        proposals: dict[str, str],
        task: str,
        context: list[Message],
        generate_fn: Callable,
        build_prompt: Callable | None = None,
    ) -> dict[str, dict]:
        """Collect initial assessments from all judges.

        Args:
            proposals: Proposals to assess
            task: The debate task
            context: Debate context
            generate_fn: Agent generation function
            build_prompt: Optional custom prompt builder

        Returns:
            Dict mapping judge name to their assessment
        """
        assessments: dict[str, dict] = {}

        # Build assessment prompt
        if build_prompt:
            prompt = build_prompt(proposals, task)
        else:
            prompt = self._default_assessment_prompt(proposals, task)

        import asyncio

        async def get_assessment(judge: Agent) -> tuple[str, dict[str, Any] | None]:
            try:
                response = await generate_fn(judge, prompt, context)
                # Parse assessment (simple extraction)
                recommendation = (
                    "approve"
                    if "approve" in response.lower()
                    else ("reject" if "reject" in response.lower() else "abstain")
                )
                return judge.name, {
                    "judge": judge.name,
                    "reasoning": response[:500],
                    "recommendation": recommendation,
                    "confidence": 0.7,  # Default confidence
                }
            except (
                RuntimeError,
                ValueError,
                TypeError,
                TimeoutError,
                ConnectionError,
                OSError,
            ) as e:
                logger.warning("assessment_error judge=%s: %s", judge.name, e)
                return judge.name, None

        # Collect assessments in parallel
        tasks = [get_assessment(judge) for judge in self.judges]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, tuple):
                name, assessment = result
                if assessment is None:
                    continue
                assessments[name] = assessment
                logger.debug(
                    "judge_initial_assessment judge=%s recommendation=%s",
                    name,
                    assessment["recommendation"],
                )

        return assessments

    async def _run_deliberation_round(
        self,
        assessments: dict[str, dict],
        proposals: dict[str, str],
        task: str,
        context: list[Message],
        generate_fn: Callable,
        round_num: int,
        build_prompt: Callable | None = None,
    ) -> dict[str, dict]:
        """Run a deliberation round where judges respond to each other.

        Args:
            assessments: Current assessments from all judges
            proposals: Proposals being judged
            task: The debate task
            context: Debate context
            generate_fn: Agent generation function
            round_num: Current deliberation round (0-indexed)
            build_prompt: Optional custom prompt builder

        Returns:
            Updated assessments after deliberation
        """
        logger.debug("judge_deliberation_round=%s judges=%s", round_num, len(assessments))

        import asyncio

        async def deliberate(judge: Agent) -> tuple[str, dict[str, Any] | None]:
            try:
                # Build deliberation prompt with other judges' assessments
                other_assessments = {k: v for k, v in assessments.items() if k != judge.name}

                if build_prompt:
                    prompt = build_prompt(
                        assessments=other_assessments,
                        proposals=proposals,
                        task=task,
                        round_num=round_num,
                    )
                else:
                    prompt = self._default_deliberation_prompt(
                        other_assessments, proposals, task, round_num
                    )

                response = await generate_fn(judge, prompt, context)

                # Update recommendation based on deliberation
                recommendation = (
                    "approve"
                    if "approve" in response.lower()
                    else ("reject" if "reject" in response.lower() else "abstain")
                )

                # Check for confidence indicators
                confidence = 0.7
                if "strongly" in response.lower() or "confident" in response.lower():
                    confidence = 0.9
                elif "uncertain" in response.lower() or "unsure" in response.lower():
                    confidence = 0.5

                return judge.name, {
                    "judge": judge.name,
                    "reasoning": response[:500],
                    "recommendation": recommendation,
                    "confidence": confidence,
                    "deliberation_round": round_num,
                }
            except (
                RuntimeError,
                ValueError,
                TypeError,
                TimeoutError,
                ConnectionError,
                OSError,
            ) as e:
                logger.warning("deliberation_error judge=%s round=%s: %s", judge.name, round_num, e)
                # Keep previous assessment
                return judge.name, assessments.get(judge.name)

        # Run deliberation in parallel
        tasks = [deliberate(judge) for judge in self.judges if judge.name in assessments]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        updated: dict[str, dict] = {}
        for result in results:
            if isinstance(result, tuple):
                name, assessment = result
                if assessment is None:
                    continue
                updated[name] = assessment

        return updated

    async def _collect_final_votes(
        self,
        assessments: dict[str, dict],
        proposals: dict[str, str],
        task: str,
        context: list[Message],
        generate_fn: Callable,
    ) -> None:
        """Collect final votes from judges after deliberation.

        Args:
            assessments: Final assessments from all judges
            proposals: Proposals being judged
            task: The debate task
            context: Debate context
            generate_fn: Agent generation function
        """
        for judge_name, assessment in assessments.items():
            recommendation = assessment.get("recommendation", "abstain")
            confidence = assessment.get("confidence", 0.5)
            reasoning = assessment.get("reasoning", "No reasoning provided")

            # Convert recommendation to vote
            vote_map = {
                "approve": JudgeVote.APPROVE,
                "reject": JudgeVote.REJECT,
                "abstain": JudgeVote.ABSTAIN,
            }
            vote = vote_map.get(recommendation, JudgeVote.ABSTAIN)

            self.record_vote(
                judge_name=judge_name,
                vote=vote,
                confidence=confidence,
                reasoning=f"[After deliberation] {reasoning}",
                metadata={"deliberation": True},
            )

    def _default_assessment_prompt(self, proposals: dict[str, str], task: str) -> str:
        """Build default assessment prompt."""
        proposal_text = "\n\n".join(
            f"**{name}**: {text[:300]}..." for name, text in proposals.items()
        )

        return f"""You are a judge evaluating debate proposals.

TASK: {task}

PROPOSALS:
{proposal_text}

Provide your initial assessment:
1. Analyze the quality of each proposal
2. Consider reasoning clarity, evidence usage, and completeness
3. State your recommendation: APPROVE (accept best proposal) or REJECT (need more debate)
4. Explain your reasoning

Assessment:"""

    def _default_deliberation_prompt(
        self,
        other_assessments: dict[str, dict],
        proposals: dict[str, str],
        task: str,
        round_num: int,
    ) -> str:
        """Build default deliberation prompt."""
        other_views = "\n\n".join(
            f"**{name}**: Recommends {a['recommendation'].upper()}\n{a['reasoning'][:200]}..."
            for name, a in other_assessments.items()
        )

        return f"""You are a judge in deliberation round {round_num + 1}.

TASK: {task}

OTHER JUDGES' ASSESSMENTS:
{other_views}

Consider:
1. Do the other judges raise valid points you missed?
2. Are there flaws in their reasoning?
3. Has your view changed after seeing other perspectives?

After deliberation, state your updated recommendation: APPROVE or REJECT
Explain any changes in your reasoning.

Deliberation response:"""


def create_judge_panel(
    candidates: list[Agent],
    participants: list[Agent] | None = None,
    domain: str = "general",
    strategy: JudgingStrategy = JudgingStrategy.MAJORITY,
    count: int = 3,
    elo_system: EloSystem | None = None,
    exclude_participants: bool = True,
) -> JudgePanel:
    """
    Convenience function to create a judge panel from candidate agents.

    Selects judges based on ELO and calibration scores, excluding
    debate participants if specified.

    Args:
        candidates: Pool of potential judges
        participants: Debate participants to exclude
        domain: Debate domain (for logging)
        strategy: Judging strategy
        count: Number of judges to select
        elo_system: Optional ELO system for scoring
        exclude_participants: Whether to exclude participants from judging

    Returns:
        Configured JudgePanel ready for evaluation
    """
    # Filter out participants
    participant_names = set()
    if participants and exclude_participants:
        participant_names = {p.name for p in participants}

    available = [a for a in candidates if a.name not in participant_names]

    if not available:
        logger.warning("No eligible judges after filtering participants")
        available = candidates  # Fall back to all candidates

    # Score and rank by composite score if ELO system available
    if elo_system:
        scorer = JudgeScoringMixin(elo_system)
        scores = scorer.get_all_scores(available)

        # Select top candidates
        judge_names = [s.agent_name for s in scores[:count]]
        judges = [a for a in available if a.name in judge_names]

        # Build weights from calibration scores
        weights = {s.agent_name: 0.5 + s.calibration_score for s in scores[:count]}
    else:
        # Random selection without scoring
        judges = available[:count] if len(available) >= count else available
        weights = {}

    logger.info(
        "create_judge_panel domain=%s count=%s excluded=%s participants",
        domain,
        len(judges),
        len(participant_names),
    )

    return JudgePanel(judges=judges, strategy=strategy, judge_weights=weights)
