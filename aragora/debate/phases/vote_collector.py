"""
Vote collection orchestration for consensus phase.

Extracted from consensus_phase.py to reduce complexity.
Handles the mechanics of collecting votes from agents with timeout protection.

Key responsibilities:
- Parallel vote collection from all agents
- Timeout protection (per-agent and overall)
- Error tracking for unanimity mode
- Vote grouping for similar choices
- Success callbacks (hooks, recording, position tracking)
- RLM-inspired early termination when clear majority is reached

Usage:
    collector = VoteCollector(
        vote_with_agent=arena._vote_with_agent,
        with_timeout=arena._with_timeout,
        ...
    )
    votes = await collector.collect_votes(ctx)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

from aragora.debate.bias_mitigation import (
    generate_permutations,
    average_permutation_votes,
)
from aragora.debate.config.defaults import DEBATE_DEFAULTS
from aragora.debate.phases._phase_invariant import require_phase_result

if TYPE_CHECKING:
    from aragora.core import Agent, Vote
    from aragora.debate.context import DebateContext

logger = logging.getLogger(__name__)

# Timeout constants - sourced from centralized defaults
AGENT_TIMEOUT_SECONDS = DEBATE_DEFAULTS.agent_timeout_seconds
# Vote collection timeout: 3x the round timeout to allow for parallel collection
VOTE_COLLECTION_TIMEOUT = DEBATE_DEFAULTS.round_timeout_seconds * 2

# RLM Early Termination Configuration - sourced from centralized defaults
# Minimum fraction of votes needed for early termination
RLM_EARLY_TERMINATION_THRESHOLD = DEBATE_DEFAULTS.early_stop_threshold
# Minimum lead over second choice to trigger early termination (as fraction of total agents)
RLM_MAJORITY_LEAD_THRESHOLD = 0.25  # No equivalent in defaults, keep as local constant


def get_complexity_governor() -> Any:
    """Get the global complexity governor instance."""
    from aragora.debate.complexity_governor import get_complexity_governor as _get_governor

    return _get_governor()


class _VoteTaskOwner:
    """Own vote tasks until each is consumed or safely detached exactly once."""

    def __init__(self, tasks: list[asyncio.Task[Any]]):
        self._tasks = tuple(tasks)
        self._order = {task: index for index, task in enumerate(tasks)}
        self._classifications: dict[asyncio.Task[Any], str] = {}
        self._loop = asyncio.get_running_loop()

    def classification(self, task: asyncio.Task[Any]) -> str | None:
        """Return the task's terminal ownership classification, if assigned."""
        return self._classifications.get(task)

    def _report_detached_failure(
        self,
        task: asyncio.Task[Any],
        error: BaseException,
    ) -> None:
        if isinstance(error, Exception):
            logger.warning(
                "detached_vote_task_failed error=%s: %s",
                type(error).__name__,
                error,
            )
            return
        self._loop.call_exception_handler(
            {
                "message": "Detached vote task raised a control-flow exception",
                "exception": error,
                "task": task,
            }
        )

    def _retrieve_detached_result(self, task: asyncio.Task[Any]) -> None:
        try:
            result = task.result()
        except BaseException as error:  # noqa: BLE001 - retrieve every off-path result
            if isinstance(error, asyncio.CancelledError):
                return
            self._report_detached_failure(task, error)
            return

        if isinstance(result, tuple) and len(result) == 2:
            vote_result = result[1]
            if isinstance(vote_result, BaseException) and not isinstance(vote_result, Exception):
                self._report_detached_failure(task, vote_result)

    def _detach(self, task: asyncio.Task[Any]) -> None:
        if task in self._classifications:
            return
        self._classifications[task] = "detached"
        task.add_done_callback(self._retrieve_detached_result)

    def consume(
        self,
        task: asyncio.Task[Any],
        consumer: Callable[[asyncio.Task[Any]], None],
    ) -> None:
        """Claim and synchronously consume one completed task once."""
        if task in self._classifications:
            return
        self._classifications[task] = "consumed"
        consumer(task)

    def settle(
        self,
        consumer: Callable[[asyncio.Task[Any]], None],
        *,
        propagate: bool,
    ) -> None:
        """Drain completed tasks, then cancel and observe all unfinished tasks."""
        first_error: BaseException | None = None

        def consume_or_record(task: asyncio.Task[Any]) -> None:
            nonlocal first_error
            try:
                self.consume(task, consumer)
            except BaseException as error:  # noqa: BLE001 - ownership must finish first
                if propagate and first_error is None:
                    first_error = error
                else:
                    self._report_detached_failure(task, error)

        # Preserve work that was already complete at the decision boundary.
        for task in self._tasks:
            if task not in self._classifications and task.done():
                consume_or_record(task)

        # A failed cancel can mean completion won the race; re-check before
        # detaching so that result is classified as completed work.
        for task in self._tasks:
            if task in self._classifications:
                continue
            if task.cancel():
                self._detach(task)
            elif task.done():
                consume_or_record(task)
            else:
                self._detach(task)

        if first_error is not None:
            raise first_error

    async def run(
        self,
        consumer: Callable[[asyncio.Task[Any]], None],
        should_stop: Callable[[], bool] | None = None,
    ) -> bool:
        """Consume completions until exhaustion or a caller-defined stop boundary."""
        pending = set(self._tasks)
        try:
            while pending:
                done, pending = await asyncio.wait(
                    pending,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in sorted(done, key=self._order.__getitem__):
                    self.consume(task, consumer)
                    if should_stop is not None and should_stop():
                        self.settle(consumer, propagate=True)
                        return True
            return False
        except asyncio.CancelledError:
            self.settle(consumer, propagate=False)
            raise
        except BaseException:  # noqa: BLE001 - make sibling tasks safe before propagation
            self.settle(consumer, propagate=False)
            raise


@dataclass
class VoteCollectorConfig:
    """Configuration for VoteCollector."""

    # Required callback for voting
    vote_with_agent: Callable | None = None

    # Timeout wrapper
    with_timeout: Callable | None = None

    # Notifications
    notify_spectator: Callable | None = None

    # Hooks
    hooks: dict = field(default_factory=dict)

    # Recording
    recorder: Any | None = None
    position_tracker: Any | None = None

    # Vote grouping
    group_similar_votes: Callable | None = None

    # Timeouts
    vote_collection_timeout: float = VOTE_COLLECTION_TIMEOUT
    agent_timeout: float = AGENT_TIMEOUT_SECONDS

    # RLM Early Termination
    # Enable early termination when clear majority reached
    enable_rlm_early_termination: bool = True
    # Minimum fraction of votes collected before checking for early termination
    rlm_early_termination_threshold: float = RLM_EARLY_TERMINATION_THRESHOLD
    # Minimum lead (as fraction of total agents) for early termination
    rlm_majority_lead_threshold: float = RLM_MAJORITY_LEAD_THRESHOLD

    # Position Bias Mitigation (Agent-as-a-Judge)
    # Shuffle proposal order and average votes across permutations
    enable_position_shuffling: bool = False
    # Number of proposal permutations to vote on
    position_shuffling_permutations: int = 3
    # Random seed for reproducibility (None = random)
    position_shuffling_seed: int | None = None


class VoteCollector:
    """
    Orchestrates vote collection from debate agents.

    Handles:
    - Parallel vote collection with timeout protection
    - Error tracking for unanimity mode
    - Vote success callbacks (hooks, recording, position tracking)
    - Vote grouping for similar choices
    - RLM-inspired early termination when clear majority is reached
    """

    def __init__(self, config: VoteCollectorConfig):
        """Initialize vote collector with configuration.

        Args:
            config: VoteCollectorConfig with callbacks and settings
        """
        self.config = config
        self._vote_with_agent = config.vote_with_agent
        self._with_timeout = config.with_timeout
        self._notify_spectator = config.notify_spectator
        self.hooks = config.hooks
        self.recorder = config.recorder
        self.position_tracker = config.position_tracker
        self._group_similar_votes = config.group_similar_votes
        self.VOTE_COLLECTION_TIMEOUT = config.vote_collection_timeout

    def _check_clear_majority(
        self,
        votes: list[Vote],
        total_agents: int,
    ) -> tuple[bool, str | None]:
        """
        Check if a clear majority has been reached for RLM early termination.

        RLM-inspired optimization: Stop collecting votes once a clear winner
        is determined, avoiding unnecessary waiting for slower agents.

        A clear majority requires:
        1. At least rlm_early_termination_threshold (default 75%) of votes collected
        2. Leading choice has > 50% of total agents
        3. Lead over second choice >= rlm_majority_lead_threshold (default 25%)

        Args:
            votes: List of votes collected so far
            total_agents: Total number of agents in the debate

        Returns:
            Tuple of (has_clear_majority, winning_choice or None)
        """
        if not self.config.enable_rlm_early_termination:
            return False, None

        if not votes or total_agents == 0:
            return False, None

        # Check minimum vote threshold
        votes_collected = len(votes)
        min_votes_needed = int(total_agents * self.config.rlm_early_termination_threshold)
        if votes_collected < min_votes_needed:
            return False, None

        # Count votes by choice
        vote_counts: dict[str, int] = {}
        for vote in votes:
            if hasattr(vote, "choice") and vote.choice:
                vote_counts[vote.choice] = vote_counts.get(vote.choice, 0) + 1

        if not vote_counts:
            return False, None

        # Sort choices by count
        sorted_choices = sorted(vote_counts.items(), key=lambda x: x[1], reverse=True)
        leader, leader_count = sorted_choices[0]

        # Check if leader has majority of total agents (not just votes collected)
        if leader_count <= total_agents / 2:
            return False, None

        # Check lead over second choice
        second_count = sorted_choices[1][1] if len(sorted_choices) > 1 else 0
        lead = leader_count - second_count
        min_lead = int(total_agents * self.config.rlm_majority_lead_threshold)

        if lead >= min_lead:
            logger.info(
                "rlm_early_termination_majority leader=%s votes=%s/%s lead=%s total_agents=%s",
                leader,
                leader_count,
                votes_collected,
                lead,
                total_agents,
            )
            return True, leader

        return False, None

    async def _collect_single_permutation_votes(
        self,
        ctx: DebateContext,
        proposals: dict[str, str],
        permutation_idx: int,
    ) -> list[Vote]:
        """Collect votes for a single proposal permutation.

        Args:
            ctx: The debate context with agents
            proposals: Shuffled proposals dict for this permutation
            permutation_idx: Index of this permutation (for logging)

        Returns:
            List of Vote objects from agents
        """
        votes: list[Vote] = []
        task = ctx.env.task if ctx.env else ""
        vote_with_agent = self._vote_with_agent
        if vote_with_agent is None:
            return votes
        with_timeout = self._with_timeout

        async def cast_vote(agent: Agent) -> tuple[Any, Any]:
            """Cast a vote for a single agent."""
            logger.debug("agent_voting_permutation agent=%s perm=%s", agent.name, permutation_idx)
            try:
                timeout = get_complexity_governor().get_scaled_timeout(
                    float(self.config.agent_timeout)
                )
                if with_timeout:
                    vote_result = await with_timeout(
                        vote_with_agent(agent, proposals, task),
                        agent.name,
                        timeout_seconds=timeout,
                    )
                else:
                    vote_result = await vote_with_agent(agent, proposals, task)
                return (agent, vote_result)
            except (ValueError, KeyError, TypeError) as e:  # noqa: BLE001
                logger.warning(
                    "vote_exception_permutation agent=%s perm=%s error=%s: %s",
                    agent.name,
                    permutation_idx,
                    type(e).__name__,
                    e,
                )
                return (agent, e)

        vote_tasks = [asyncio.create_task(cast_vote(agent)) for agent in ctx.agents]
        owner = _VoteTaskOwner(vote_tasks)

        def consume_vote(completed_task: asyncio.Task[Any]) -> None:
            try:
                agent, vote_result = completed_task.result()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - phase isolation
                logger.error(
                    "task_exception phase=vote_permutation perm=%s error=%s", permutation_idx, e
                )
                return

            if isinstance(vote_result, BaseException) and not isinstance(vote_result, Exception):
                raise vote_result

            if vote_result is None or isinstance(vote_result, Exception):
                if isinstance(vote_result, Exception):
                    logger.error(
                        "vote_error_permutation agent=%s error=%s", agent.name, vote_result
                    )
            else:
                votes.append(vote_result)

        await owner.run(consume_vote)

        return votes

    async def _collect_votes_with_shuffling(self, ctx: DebateContext) -> list[Vote]:
        """Collect votes using position shuffling to mitigate position bias.

        Generates multiple permutations of the proposal order, collects votes
        on each permutation, and averages the results to reduce the effect
        of position bias in agent voting.

        Args:
            ctx: The debate context with agents and proposals

        Returns:
            List of averaged Vote objects
        """
        if not ctx.proposals:
            return []

        num_permutations = self.config.position_shuffling_permutations
        seed = self.config.position_shuffling_seed

        logger.info(
            "position_shuffling_start permutations=%s proposals=%s seed=%s",
            num_permutations,
            len(ctx.proposals),
            seed,
        )

        # Generate permutations
        permutations = generate_permutations(
            ctx.proposals,
            num_permutations=num_permutations,
            base_seed=seed,
        )

        # Collect votes on each permutation
        votes_by_agent: dict[str, list[Vote]] = {}

        for perm_idx, shuffled_proposals in enumerate(permutations):
            perm_votes = await self._collect_single_permutation_votes(
                ctx, shuffled_proposals, perm_idx
            )

            for vote in perm_votes:
                agent_name = vote.agent if hasattr(vote, "agent") else "unknown"
                if agent_name not in votes_by_agent:
                    votes_by_agent[agent_name] = []
                votes_by_agent[agent_name].append(vote)

            logger.debug(
                "position_shuffling_permutation_done perm=%s votes=%s", perm_idx, len(perm_votes)
            )

        # Average votes across permutations
        averaged_votes = average_permutation_votes(votes_by_agent, ctx.proposals)

        logger.info(
            "position_shuffling_complete permutations=%s agents_voted=%s averaged_votes=%s",
            num_permutations,
            len(votes_by_agent),
            len(averaged_votes),
        )

        # Handle success callbacks for averaged votes
        for vote in averaged_votes:
            averaged_agent_name = vote.agent if hasattr(vote, "agent") else None
            agent = next((a for a in ctx.agents if a.name == averaged_agent_name), None)
            if agent:
                self._handle_vote_success(ctx, agent, vote)

        return averaged_votes

    async def collect_votes(self, ctx: DebateContext) -> list[Vote]:
        """Collect votes from all agents with outer timeout protection.

        Uses VOTE_COLLECTION_TIMEOUT to prevent total vote collection time from
        exceeding reasonable bounds (N agents * per-agent timeout could be very long).
        If timeout is reached, returns partial votes collected so far.

        When position shuffling is enabled, collects votes on multiple proposal
        permutations and averages results to mitigate position bias.

        Args:
            ctx: The debate context with agents and proposals

        Returns:
            List of Vote objects from agents that successfully voted
        """
        if not self._vote_with_agent:
            logger.warning("No vote_with_agent callback, skipping votes")
            return []

        # Use position shuffling if enabled (Agent-as-a-Judge bias mitigation)
        if self.config.enable_position_shuffling:
            logger.info("position_shuffling_enabled - using multi-permutation voting")
            try:
                return await asyncio.wait_for(
                    self._collect_votes_with_shuffling(ctx),
                    timeout=self.VOTE_COLLECTION_TIMEOUT
                    * self.config.position_shuffling_permutations,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "position_shuffling_timeout timeout=%ss",
                    self.VOTE_COLLECTION_TIMEOUT * self.config.position_shuffling_permutations,
                )
                return []

        votes: list[Vote] = []
        task = ctx.env.task if ctx.env else ""
        vote_with_agent = self._vote_with_agent
        if vote_with_agent is None:
            return votes
        with_timeout = self._with_timeout

        async def cast_vote(agent: Agent) -> tuple[Any, Any]:
            """Cast a vote for a single agent with timeout protection."""
            logger.debug("agent_voting agent=%s", agent.name)
            try:
                timeout = get_complexity_governor().get_scaled_timeout(
                    float(self.config.agent_timeout)
                )
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
            """Collect votes from all agents concurrently with RLM early termination."""
            total_agents = len(ctx.agents)
            vote_tasks = [asyncio.create_task(cast_vote(agent)) for agent in ctx.agents]
            owner = _VoteTaskOwner(vote_tasks)
            early_leader: str | None = None

            def consume_vote(completed_task: asyncio.Task[Any]) -> None:
                try:
                    agent, vote_result = completed_task.result()
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001 - phase isolation
                    logger.error("task_exception phase=vote error=%s", e)
                    return

                if isinstance(vote_result, BaseException) and not isinstance(
                    vote_result, Exception
                ):
                    raise vote_result

                if vote_result is None or isinstance(vote_result, Exception):
                    if isinstance(vote_result, Exception):
                        logger.error("vote_error agent=%s error=%s", agent.name, vote_result)
                    else:
                        logger.error(
                            "vote_error agent=%s error=vote returned None",
                            agent.name,
                            extra={
                                "triage_diag_code": "vote_none",
                                "triage_diag_severity": "degraded",
                            },
                        )
                else:
                    votes.append(vote_result)
                    self._handle_vote_success(ctx, agent, vote_result)

            def should_stop() -> bool:
                nonlocal early_leader
                has_majority, leader = self._check_clear_majority(votes, total_agents)
                if has_majority:
                    early_leader = leader
                return has_majority

            early_terminated = await owner.run(consume_vote, should_stop)

            if early_terminated:
                if self._notify_spectator:
                    self._notify_spectator(
                        "rlm_early_termination",
                        details=(
                            f"Clear majority for '{early_leader}' "
                            f"({len(votes)}/{total_agents} votes)"
                        ),
                        metric=len(votes) / total_agents,
                        agent="system",
                    )

                if "on_rlm_early_termination" in self.hooks:
                    self.hooks["on_rlm_early_termination"](
                        leader=early_leader,
                        votes_collected=len(votes),
                        total_agents=total_agents,
                    )

                logger.info(
                    "vote_collection_early_terminated collected=%s total_agents=%s",
                    len(votes),
                    total_agents,
                )

        # Apply outer timeout to prevent N*agent_timeout runaway
        try:
            await asyncio.wait_for(collect_all_votes(), timeout=self.VOTE_COLLECTION_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning(
                "vote_collection_timeout collected=%s expected=%s timeout=%ss",
                len(votes),
                len(ctx.agents),
                self.VOTE_COLLECTION_TIMEOUT,
            )
            # Return partial votes - better than nothing

        return votes

    async def collect_votes_with_errors(self, ctx: DebateContext) -> tuple[list[Vote], int]:
        """Collect votes with error tracking for unanimity mode.

        Used for unanimity mode where we need to track errors.
        Uses VOTE_COLLECTION_TIMEOUT to prevent runaway collection time.

        Args:
            ctx: The debate context with agents and proposals

        Returns:
            Tuple of (votes list, error count)
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

        async def cast_vote(agent: Agent) -> tuple[Any, Any]:
            """Cast a vote for unanimous consensus with timeout protection."""
            logger.debug("agent_voting_unanimous agent=%s", agent.name)
            try:
                timeout = get_complexity_governor().get_scaled_timeout(
                    float(self.config.agent_timeout)
                )
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
            """Collect votes from all agents with error counting for unanimity checks."""
            nonlocal voting_errors
            vote_tasks = [asyncio.create_task(cast_vote(agent)) for agent in ctx.agents]
            owner = _VoteTaskOwner(vote_tasks)

            def consume_vote(completed_task: asyncio.Task[Any]) -> None:
                nonlocal voting_errors
                try:
                    agent, vote_result = completed_task.result()
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001 - phase isolation
                    logger.error("task_exception phase=unanimous_vote error=%s", e)
                    voting_errors += 1
                    return

                if isinstance(vote_result, BaseException) and not isinstance(
                    vote_result, Exception
                ):
                    raise vote_result

                if vote_result is None or isinstance(vote_result, Exception):
                    if isinstance(vote_result, Exception):
                        logger.error(
                            "vote_error_unanimous agent=%s error=%s", agent.name, vote_result
                        )
                    else:
                        logger.error(
                            "vote_error_unanimous agent=%s error=vote returned None",
                            agent.name,
                            extra={
                                "triage_diag_code": "vote_none",
                                "triage_diag_severity": "degraded",
                            },
                        )
                    voting_errors += 1
                else:
                    votes.append(vote_result)
                    self._handle_vote_success(ctx, agent, vote_result, unanimous=True)

            await owner.run(consume_vote)

        # Apply outer timeout to prevent N*agent_timeout runaway
        try:
            await asyncio.wait_for(collect_all_votes(), timeout=self.VOTE_COLLECTION_TIMEOUT)
        except asyncio.TimeoutError:
            # Treat timeout as errors for missing votes
            missing = len(ctx.agents) - len(votes) - voting_errors
            voting_errors += missing
            logger.warning(
                "vote_collection_timeout_unanimous collected=%s errors=%s expected=%s timeout=%ss",
                len(votes),
                voting_errors,
                len(ctx.agents),
                self.VOTE_COLLECTION_TIMEOUT,
            )

        return votes, voting_errors

    def _handle_vote_success(
        self,
        ctx: DebateContext,
        agent: Agent,
        vote: Vote,
        unanimous: bool = False,
    ) -> None:
        """Handle successful vote: notifications, hooks, recording.

        Args:
            ctx: The debate context
            agent: The agent that voted
            vote: The Vote object
            unanimous: Whether this is for unanimous consensus mode
        """
        result = require_phase_result(ctx)

        logger.debug(
            f"vote_cast{'_unanimous' if unanimous else ''} agent={agent.name} "
            f"choice={vote.choice} confidence={vote.confidence:.0%}"
        )

        # Notify spectator
        if self._notify_spectator:
            self._notify_spectator(
                "vote",
                agent=agent.name,
                details=f"Voted for {vote.choice}",
                metric=vote.confidence,
            )

        # Emit vote hook
        if "on_vote" in self.hooks:
            self.hooks["on_vote"](agent.name, vote.choice, vote.confidence)

        # Record vote
        if self.recorder:
            try:
                self.recorder.record_vote(agent.name, vote.choice, vote.reasoning)
            except (RuntimeError, AttributeError, TypeError) as e:  # noqa: BLE001
                logger.debug("Recorder error for vote: %s", e)

        # Record position for truth-grounded personas
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
            votes: List of Vote objects

        Returns:
            Tuple of (vote_groups dict, choice_mapping dict)
            - vote_groups: canonical choice -> list of variant choices
            - choice_mapping: variant choice -> canonical choice
        """
        if not self._group_similar_votes:
            # No grouping, identity mapping
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


# =============================================================================
# Factory function
# =============================================================================


def create_vote_collector(
    vote_with_agent: Callable | None = None,
    with_timeout: Callable | None = None,
    notify_spectator: Callable | None = None,
    hooks: dict | None = None,
    recorder: Any | None = None,
    position_tracker: Any | None = None,
    group_similar_votes: Callable | None = None,
    vote_collection_timeout: float = VOTE_COLLECTION_TIMEOUT,
    agent_timeout: float = AGENT_TIMEOUT_SECONDS,
    enable_rlm_early_termination: bool = True,
    rlm_early_termination_threshold: float = RLM_EARLY_TERMINATION_THRESHOLD,
    rlm_majority_lead_threshold: float = RLM_MAJORITY_LEAD_THRESHOLD,
    enable_position_shuffling: bool = False,
    position_shuffling_permutations: int = 3,
    position_shuffling_seed: int | None = None,
) -> VoteCollector:
    """Create a VoteCollector with the given configuration.

    Args:
        vote_with_agent: Callback to vote with an agent
        with_timeout: Timeout wrapper function
        notify_spectator: Spectator notification callback
        hooks: Dict of phase hooks
        recorder: Vote recorder instance
        position_tracker: Position tracker instance
        group_similar_votes: Vote grouping callback
        vote_collection_timeout: Overall timeout for vote collection
        agent_timeout: Per-agent voting timeout
        enable_rlm_early_termination: Enable RLM early termination when majority reached
        rlm_early_termination_threshold: Min fraction of votes before checking majority
        rlm_majority_lead_threshold: Min lead (fraction) to trigger early termination
        enable_position_shuffling: Enable position bias mitigation via shuffling
        position_shuffling_permutations: Number of permutations to vote on
        position_shuffling_seed: Random seed for reproducibility

    Returns:
        Configured VoteCollector instance
    """
    config = VoteCollectorConfig(
        vote_with_agent=vote_with_agent,
        with_timeout=with_timeout,
        notify_spectator=notify_spectator,
        hooks=hooks or {},
        recorder=recorder,
        position_tracker=position_tracker,
        group_similar_votes=group_similar_votes,
        vote_collection_timeout=vote_collection_timeout,
        agent_timeout=agent_timeout,
        enable_rlm_early_termination=enable_rlm_early_termination,
        rlm_early_termination_threshold=rlm_early_termination_threshold,
        rlm_majority_lead_threshold=rlm_majority_lead_threshold,
        enable_position_shuffling=enable_position_shuffling,
        position_shuffling_permutations=position_shuffling_permutations,
        position_shuffling_seed=position_shuffling_seed,
    )
    return VoteCollector(config)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "VoteCollector",
    "VoteCollectorConfig",
    "create_vote_collector",
    "VOTE_COLLECTION_TIMEOUT",
    "AGENT_TIMEOUT_SECONDS",
    "RLM_EARLY_TERMINATION_THRESHOLD",
    "RLM_MAJORITY_LEAD_THRESHOLD",
]
