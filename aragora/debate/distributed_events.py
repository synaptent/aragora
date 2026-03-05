"""
Distributed Debate Event Types.

Defines event types for cross-instance debate coordination,
extending the RegionalEventType enum.

These events flow through the RegionalEventBus to coordinate
debates across multiple Aragora instances.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
import time


class DistributedDebateEventType(str, Enum):
    """Event types for distributed debate coordination."""

    # Debate lifecycle
    DEBATE_CREATED = "debate.created"
    DEBATE_STARTED = "debate.started"
    DEBATE_PAUSED = "debate.paused"
    DEBATE_RESUMED = "debate.resumed"
    DEBATE_COMPLETED = "debate.completed"
    DEBATE_FAILED = "debate.failed"
    DEBATE_CANCELLED = "debate.cancelled"

    # Round events
    ROUND_STARTED = "round.started"
    ROUND_COMPLETED = "round.completed"

    # Agent participation
    AGENT_JOINED = "agent.joined"
    AGENT_LEFT = "agent.left"
    AGENT_PROPOSAL = "agent.proposal"
    AGENT_CRITIQUE = "agent.critique"
    AGENT_REVISION = "agent.revision"
    AGENT_VOTE = "agent.vote"

    # Consensus
    CONSENSUS_CHECK = "consensus.check"
    CONSENSUS_REACHED = "consensus.reached"
    CONSENSUS_FAILED = "consensus.failed"
    CONSENSUS_VOTE = "consensus.vote"

    # Coordination
    COORDINATOR_ELECTED = "coordinator.elected"
    COORDINATOR_HANDOFF = "coordinator.handoff"
    INSTANCE_JOINED = "instance.joined"
    INSTANCE_LEFT = "instance.left"

    # Sync
    STATE_SYNC_REQUEST = "state.sync_request"
    STATE_SYNC_RESPONSE = "state.sync_response"


@dataclass
class DistributedDebateEvent:
    """
    Event for distributed debate coordination.

    Uses timestamps for conflict-free ordering across instances.
    """

    event_type: DistributedDebateEventType
    debate_id: str
    source_instance: str
    timestamp: float = field(default_factory=time.time)
    round_number: int = 0
    agent_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "event_type": self.event_type.value,
            "debate_id": self.debate_id,
            "source_instance": self.source_instance,
            "timestamp": self.timestamp,
            "round_number": self.round_number,
            "agent_id": self.agent_id,
            "data": self.data,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DistributedDebateEvent:
        """Deserialize from dictionary."""
        return cls(
            event_type=DistributedDebateEventType(data["event_type"]),
            debate_id=data["debate_id"],
            source_instance=data["source_instance"],
            timestamp=data.get("timestamp", time.time()),
            round_number=data.get("round_number", 0),
            agent_id=data.get("agent_id"),
            data=data.get("data", {}),
            version=data.get("version", 1),
        )


@dataclass
class AgentProposal:
    """An agent's proposal in a distributed debate."""

    agent_id: str
    instance_id: str
    content: str
    round_number: int
    timestamp: float = field(default_factory=time.time)
    confidence: float = 0.0
    reasoning: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    # Trust-tier taint tracking (G2 security roadmap item)
    trust_tier: str = "standard"  # "untrusted" | "standard" | "vetted" | "system"
    taint_source: str | None = None  # e.g. "retrieved_context", "config_file"
    taint_evidence: list[str] = field(default_factory=list)  # evidence IDs

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "agent_id": self.agent_id,
            "instance_id": self.instance_id,
            "content": self.content,
            "round_number": self.round_number,
            "timestamp": self.timestamp,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "metadata": self.metadata,
            "trust_tier": self.trust_tier,
            "taint_source": self.taint_source,
            "taint_evidence": self.taint_evidence,
        }


@dataclass
class AgentCritique:
    """An agent's critique in a distributed debate."""

    agent_id: str
    instance_id: str
    target_agent_id: str
    content: str
    round_number: int
    timestamp: float = field(default_factory=time.time)
    rating: float = 0.0
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "agent_id": self.agent_id,
            "instance_id": self.instance_id,
            "target_agent_id": self.target_agent_id,
            "content": self.content,
            "round_number": self.round_number,
            "timestamp": self.timestamp,
            "rating": self.rating,
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
        }


@dataclass
class ConsensusVote:
    """A vote for consensus in a distributed debate."""

    agent_id: str
    instance_id: str
    proposal_agent_id: str
    vote: str  # "support", "oppose", "abstain"
    round_number: int
    timestamp: float = field(default_factory=time.time)
    confidence: float = 0.0
    reasoning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "agent_id": self.agent_id,
            "instance_id": self.instance_id,
            "proposal_agent_id": self.proposal_agent_id,
            "vote": self.vote,
            "round_number": self.round_number,
            "timestamp": self.timestamp,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
        }


@dataclass
class DistributedDebateState:
    """
    State of a distributed debate.

    Maintained by the coordinator and synced across instances.
    """

    debate_id: str
    task: str
    coordinator_instance: str
    status: str = "created"  # created, running, paused, completed, failed
    current_round: int = 0
    max_rounds: int = 5
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None

    # Participating instances and agents
    instances: dict[str, dict[str, Any]] = field(default_factory=dict)
    agents: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Round data
    proposals: list[AgentProposal] = field(default_factory=list)
    critiques: list[AgentCritique] = field(default_factory=list)
    votes: list[ConsensusVote] = field(default_factory=list)

    # Result
    consensus_reached: bool = False
    final_answer: str | None = None
    winning_agent: str | None = None
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "debate_id": self.debate_id,
            "task": self.task,
            "coordinator_instance": self.coordinator_instance,
            "status": self.status,
            "current_round": self.current_round,
            "max_rounds": self.max_rounds,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "instances": self.instances,
            "agents": self.agents,
            "proposals": [p.to_dict() for p in self.proposals],
            "critiques": [c.to_dict() for c in self.critiques],
            "votes": [v.to_dict() for v in self.votes],
            "consensus_reached": self.consensus_reached,
            "final_answer": self.final_answer,
            "winning_agent": self.winning_agent,
            "confidence": self.confidence,
        }
