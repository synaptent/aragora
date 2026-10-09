"""
Byzantine Fault-Tolerant Consensus Protocol.

Adapted from claude-flow (MIT License)
Pattern: PBFT-style consensus for critical decisions with fault tolerance
Original: https://github.com/ruvnet/claude-flow

Aragora adaptations:
- Integration with existing ConsensusProof and DebateResult
- Async implementation for LLM agent voting
- Configurable fault tolerance threshold
- View change support for leader failures

This implements a simplified Practical Byzantine Fault Tolerance (PBFT)
protocol adapted for multi-agent debates. It tolerates up to f faulty
(adversarial or hallucinating) agents where n >= 3f + 1.

Usage:
    protocol = ByzantineConsensus(agents, fault_tolerance=0.33)

    # Propose a value
    result = await protocol.propose("Final recommendation", proposer_agent)

    # Check if consensus was reached
    if result.success:
        print(f"Consensus: {result.value}")
    else:
        print(f"Failed: {result.failure_reason}")
"""

from __future__ import annotations

__all__ = [
    "ByzantineConsensus",
    "ByzantineConsensusConfig",
    "ByzantineConsensusResult",
    "ByzantineMessage",
    "ByzantinePhase",
    "ViewChangeReason",
]

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING
from collections.abc import Sequence

from aragora.debate.config.defaults import DEBATE_DEFAULTS

if TYPE_CHECKING:
    from aragora.core import Agent

logger = logging.getLogger(__name__)


class ByzantinePhase(str, Enum):
    """Phases of PBFT consensus."""

    PRE_PREPARE = "pre_prepare"  # Leader proposes
    PREPARE = "prepare"  # Nodes validate and broadcast
    COMMIT = "commit"  # Nodes commit to value
    REPLY = "reply"  # Final confirmation
    VIEW_CHANGE = "view_change"  # Leader failure recovery


class ViewChangeReason(str, Enum):
    """Reasons for triggering a view change."""

    LEADER_TIMEOUT = "leader_timeout"
    LEADER_FAILURE = "leader_failure"
    INVALID_PROPOSAL = "invalid_proposal"
    CONSENSUS_STALL = "consensus_stall"


@dataclass
class ByzantineMessage:
    """A message in the Byzantine consensus protocol."""

    phase: ByzantinePhase
    view: int
    sequence: int
    sender: str
    proposal_hash: str
    proposal: str | None = None  # Only included in PRE_PREPARE
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def compute_hash(self) -> str:
        """Compute message hash for verification."""
        content = f"{self.phase.value}:{self.view}:{self.sequence}:{self.proposal_hash}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]


@dataclass
class ByzantineConsensusConfig:
    """Configuration for Byzantine consensus."""

    # Fault tolerance: f < n/3 faulty nodes tolerated
    max_faulty_fraction: float = 0.33

    # Timeouts
    phase_timeout_seconds: float = 30.0
    view_change_timeout_seconds: float = 60.0

    # Minimum agents required (3f + 1, so min 4 for f=1)
    min_agents: int = DEBATE_DEFAULTS.byzantine_min_agents

    # Retry settings
    max_view_changes: int = 3
    max_retries_per_phase: int = 2


@dataclass
class ByzantineConsensusResult:
    """Result of Byzantine consensus attempt."""

    success: bool
    value: str | None = None
    confidence: float = 0.0
    view: int = 0
    sequence: int = 0
    commit_count: int = 0
    total_agents: int = 0
    failure_reason: str | None = None
    duration_seconds: float = 0.0
    agent_votes: dict[str, str] = field(default_factory=dict)  # agent -> vote hash

    @property
    def agreement_ratio(self) -> float:
        """Ratio of agents that committed."""
        return self.commit_count / self.total_agents if self.total_agents > 0 else 0.0


@dataclass
class ByzantineConsensus:
    """
    PBFT-style Byzantine Fault-Tolerant Consensus Protocol.

    Implements a simplified version of PBFT adapted for LLM agents:
    1. PRE_PREPARE: Leader proposes a value
    2. PREPARE: Agents validate and signal readiness
    3. COMMIT: Agents commit if 2f+1 prepare messages received
    4. REPLY: Final value is confirmed

    Tolerates up to f faulty agents where n >= 3f + 1.
    """

    agents: Sequence[Agent]
    config: ByzantineConsensusConfig = field(default_factory=ByzantineConsensusConfig)

    # State
    _current_view: int = field(default=0, init=False)
    _sequence: int = field(default=0, init=False)
    _prepare_votes: dict[str, set[str]] = field(default_factory=dict, init=False)
    _commit_votes: dict[str, set[str]] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        """Validate configuration."""
        if len(self.agents) < self.config.min_agents:
            logger.warning(
                "Byzantine consensus requires at least %s agents, got %s. Consensus may be unreliable.",
                self.config.min_agents,
                len(self.agents),
            )

    @property
    def n(self) -> int:
        """Total number of agents."""
        return len(self.agents)

    @property
    def f(self) -> int:
        """Maximum number of faulty agents tolerated."""
        return (self.n - 1) // 3

    @property
    def quorum_size(self) -> int:
        """Number of agents needed for quorum (2f + 1)."""
        return 2 * self.f + 1

    @property
    def leader(self) -> Agent:
        """Current leader (rotating by view number)."""
        return self.agents[self._current_view % self.n]

    async def propose(
        self,
        proposal: str,
        proposer: Agent | None = None,
        task: str = "",
    ) -> ByzantineConsensusResult:
        """
        Initiate Byzantine consensus on a proposal.

        Args:
            proposal: The value to reach consensus on
            proposer: Agent making the proposal (uses leader if not specified)
            task: Task context for the proposal

        Returns:
            ByzantineConsensusResult with success status and agreed value
        """
        start_time = time.time()
        self._sequence += 1

        # Use specified proposer or current leader
        leader = proposer or self.leader

        logger.info(
            "byzantine_consensus_start view=%s sequence=%s leader=%s n=%s f=%s",
            self._current_view,
            self._sequence,
            leader.name,
            self.n,
            self.f,
        )

        view_changes = 0
        while view_changes <= self.config.max_view_changes:
            try:
                # Phase 1: PRE-PREPARE
                proposal_hash = self._compute_proposal_hash(proposal)
                pre_prepare = ByzantineMessage(
                    phase=ByzantinePhase.PRE_PREPARE,
                    view=self._current_view,
                    sequence=self._sequence,
                    sender=leader.name,
                    proposal_hash=proposal_hash,
                    proposal=proposal,
                )

                # Phase 2: PREPARE
                prepare_votes = await self._collect_prepare_votes(pre_prepare, task)
                if len(prepare_votes) < self.quorum_size:
                    logger.warning(
                        "Prepare phase failed: %s/%s", len(prepare_votes), self.quorum_size
                    )
                    raise ConsensusFailure("Prepare phase did not reach quorum")

                # Phase 3: COMMIT
                commit_votes = await self._collect_commit_votes(pre_prepare, prepare_votes, task)
                if len(commit_votes) < self.quorum_size:
                    logger.warning(
                        "Commit phase failed: %s/%s", len(commit_votes), self.quorum_size
                    )
                    raise ConsensusFailure("Commit phase did not reach quorum")

                # Success!
                duration = time.time() - start_time
                confidence = len(commit_votes) / self.n

                logger.info(
                    "byzantine_consensus_success view=%s commits=%s confidence=%.2f",
                    self._current_view,
                    len(commit_votes),
                    confidence,
                )

                return ByzantineConsensusResult(
                    success=True,
                    value=proposal,
                    confidence=confidence,
                    view=self._current_view,
                    sequence=self._sequence,
                    commit_count=len(commit_votes),
                    total_agents=self.n,
                    duration_seconds=duration,
                    agent_votes=dict.fromkeys(commit_votes, proposal_hash),
                )

            except ConsensusFailure as e:
                logger.warning("Consensus failed: %s, initiating view change", e)
                view_changes += 1
                self._current_view += 1

            except asyncio.TimeoutError:
                logger.warning("Consensus timeout, initiating view change")
                view_changes += 1
                self._current_view += 1

        # All view changes exhausted
        duration = time.time() - start_time
        return ByzantineConsensusResult(
            success=False,
            failure_reason=f"Consensus failed after {view_changes} view changes",
            view=self._current_view,
            sequence=self._sequence,
            total_agents=self.n,
            duration_seconds=duration,
        )

    async def _collect_prepare_votes(
        self,
        pre_prepare: ByzantineMessage,
        task: str,
    ) -> set[str]:
        """
        Collect prepare votes from agents.

        Each agent validates the proposal and indicates readiness.
        """
        self._prepare_votes[pre_prepare.proposal_hash] = set()

        async def get_prepare_vote(agent: Agent) -> str | None:
            try:
                prompt = self._build_prepare_prompt(pre_prepare, task)
                response = await asyncio.wait_for(
                    agent.generate(prompt),
                    timeout=self.config.phase_timeout_seconds,
                )

                # Parse vote from response
                if self._parse_agreement(response):
                    return agent.name
                return None

            except asyncio.TimeoutError:
                logger.warning("Prepare timeout for %s", agent.name)
                return None
            except (RuntimeError, ValueError, TypeError, OSError, ConnectionError) as e:
                logger.warning("Prepare error for %s: %s", agent.name, e)
                return None

        # Collect votes in parallel
        tasks = [get_prepare_vote(agent) for agent in self.agents]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, str):
                self._prepare_votes[pre_prepare.proposal_hash].add(result)

        return self._prepare_votes[pre_prepare.proposal_hash]

    async def _collect_commit_votes(
        self,
        pre_prepare: ByzantineMessage,
        prepare_votes: set[str],
        task: str,
    ) -> set[str]:
        """
        Collect commit votes from agents.

        Agents commit if they've seen 2f+1 prepare messages.
        """
        self._commit_votes[pre_prepare.proposal_hash] = set()

        async def get_commit_vote(agent: Agent) -> str | None:
            try:
                prompt = self._build_commit_prompt(pre_prepare, prepare_votes, task)
                response = await asyncio.wait_for(
                    agent.generate(prompt),
                    timeout=self.config.phase_timeout_seconds,
                )

                # Parse vote from response
                if self._parse_agreement(response):
                    return agent.name
                return None

            except asyncio.TimeoutError:
                logger.warning("Commit timeout for %s", agent.name)
                return None
            except (RuntimeError, ValueError, TypeError, OSError, ConnectionError) as e:
                logger.warning("Commit error for %s: %s", agent.name, e)
                return None

        # Only agents who prepared should commit
        prepared_agents = [a for a in self.agents if a.name in prepare_votes]
        tasks = [get_commit_vote(agent) for agent in prepared_agents]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, str):
                self._commit_votes[pre_prepare.proposal_hash].add(result)

        return self._commit_votes[pre_prepare.proposal_hash]

    def _build_prepare_prompt(self, pre_prepare: ByzantineMessage, task: str) -> str:
        """Build prompt for prepare phase."""
        return f"""You are participating in a Byzantine fault-tolerant consensus protocol.

TASK CONTEXT:
{task}

PROPOSAL (View {pre_prepare.view}, Sequence {pre_prepare.sequence}):
{pre_prepare.proposal}

Proposal Hash: {pre_prepare.proposal_hash}
Leader: {pre_prepare.sender}

PREPARE PHASE INSTRUCTIONS:
Evaluate this proposal and indicate whether you are prepared to commit to it.
Consider:
1. Is the proposal well-formed and addresses the task?
2. Does it represent a reasonable solution?
3. Would you be willing to commit to this as the final answer?

Respond with:
PREPARE: YES or NO
REASONING: [Your brief reasoning]"""

    def _build_commit_prompt(
        self,
        pre_prepare: ByzantineMessage,
        prepare_votes: set[str],
        task: str,
    ) -> str:
        """Build prompt for commit phase."""
        return f"""You are participating in a Byzantine fault-tolerant consensus protocol.

TASK CONTEXT:
{task}

PROPOSAL (View {pre_prepare.view}, Sequence {pre_prepare.sequence}):
{pre_prepare.proposal}

PREPARE PHASE COMPLETE:
{len(prepare_votes)} agents have prepared (quorum: {self.quorum_size})
Prepared agents: {", ".join(sorted(prepare_votes))}

COMMIT PHASE INSTRUCTIONS:
Given that a quorum of agents has prepared, decide whether to commit to this proposal.
Once committed, this becomes the final consensus value.

Respond with:
COMMIT: YES or NO
REASONING: [Your brief reasoning]"""

    def _parse_agreement(self, response: str) -> bool:
        """Parse agreement from agent response."""
        response_upper = response.upper()

        # Check for explicit YES
        if "PREPARE: YES" in response_upper or "COMMIT: YES" in response_upper:
            return True

        # Check for explicit NO
        if "PREPARE: NO" in response_upper or "COMMIT: NO" in response_upper:
            return False

        # Fallback: look for agreement indicators
        agreement_words = ["agree", "accept", "approve", "confirm", "yes"]
        disagreement_words = ["disagree", "reject", "deny", "refuse", "no"]

        agreement_count = sum(1 for w in agreement_words if w in response.lower())
        disagreement_count = sum(1 for w in disagreement_words if w in response.lower())

        return agreement_count > disagreement_count

    def _compute_proposal_hash(self, proposal: str) -> str:
        """Compute deterministic hash of proposal."""
        return hashlib.sha256(proposal.encode()).hexdigest()[:16]


class ConsensusFailure(Exception):
    """Exception raised when consensus fails."""

    pass


async def verify_with_byzantine_consensus(
    proposal: str,
    agents: Sequence[Agent],
    task: str = "",
    fault_tolerance: float = 0.33,
) -> ByzantineConsensusResult:
    """
    Convenience function to verify a proposal with Byzantine consensus.

    Args:
        proposal: Value to verify
        agents: Agents to participate in consensus
        task: Task context
        fault_tolerance: Maximum fraction of faulty agents (default 1/3)

    Returns:
        ByzantineConsensusResult
    """
    config = ByzantineConsensusConfig(max_faulty_fraction=fault_tolerance)
    protocol = ByzantineConsensus(agents=agents, config=config)
    return await protocol.propose(proposal, task=task)
