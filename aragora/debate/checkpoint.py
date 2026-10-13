"""
Incremental Consensus Checkpointing.

Enables pause/resume for long-running debates:
- Durable checkpoints at configurable intervals
- Resume from last checkpoint on crash/timeout
- Async human participation (review + intervene + resume)
- Distributed debates across sessions

Key concepts:
- DebateCheckpoint: Full state snapshot at a point in time
- CheckpointStore: Persistence layer (file, S3, git)
- CheckpointManager: Orchestrates checkpointing lifecycle
- ResumedDebate: Context for continuing from checkpoint
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from collections.abc import Callable

# Git-safe ID pattern: alphanumeric, dash, underscore only (no path traversal or special chars)
SAFE_CHECKPOINT_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$")

logger = logging.getLogger(__name__)

from aragora.core import Critique, Message, Vote


class CheckpointStatus(Enum):
    """Status of a checkpoint."""

    CREATING = "creating"
    COMPLETE = "complete"
    RESUMING = "resuming"
    CORRUPTED = "corrupted"
    EXPIRED = "expired"


@dataclass
class AgentState:
    """Serialized state of an agent at checkpoint time."""

    agent_name: str
    agent_model: str
    agent_role: str
    system_prompt: str
    stance: str
    memory_snapshot: dict | None = None


@dataclass
class DebateCheckpoint:
    """
    Complete state snapshot for debate resumption.

    Captures everything needed to continue a debate from
    exactly where it left off.
    """

    checkpoint_id: str
    debate_id: str
    task: str

    # Progress
    current_round: int
    total_rounds: int
    phase: str  # "proposal", "critique", "vote", "synthesis"

    # Message history
    messages: list[dict]  # Serialized Message objects
    critiques: list[dict]  # Serialized Critique objects
    votes: list[dict]  # Serialized Vote objects

    # Agent states
    agent_states: list[AgentState]

    # Consensus state
    current_consensus: str | None = None
    consensus_confidence: float = 0.0
    convergence_status: str = ""

    # Claims kernel state (if using)
    claims_kernel_state: dict | None = None

    # Belief network state (if using)
    belief_network_state: dict | None = None

    # Continuum memory state (if using)
    continuum_memory_state: dict | None = None

    # Metadata
    status: CheckpointStatus = CheckpointStatus.COMPLETE
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    expires_at: str | None = None
    checksum: str = ""

    # Resumption info
    resume_count: int = 0
    last_resumed_at: str | None = None
    resumed_by: str | None = None  # User/system that resumed

    # Human intervention
    pending_intervention: bool = False
    intervention_notes: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.checksum:
            self.checksum = self._compute_checksum()

    def _compute_checksum(self) -> str:
        """Compute checksum for integrity verification."""
        data = f"{self.debate_id}:{self.current_round}:{len(self.messages)}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    def verify_integrity(self) -> bool:
        """Verify checkpoint integrity."""
        return self.checksum == self._compute_checksum()

    def to_dict(self) -> dict:
        return {
            "checkpoint_id": self.checkpoint_id,
            "debate_id": self.debate_id,
            "task": self.task,
            "current_round": self.current_round,
            "total_rounds": self.total_rounds,
            "phase": self.phase,
            "messages": self.messages,
            "critiques": self.critiques,
            "votes": self.votes,
            "agent_states": [
                {
                    "agent_name": s.agent_name,
                    "agent_model": s.agent_model,
                    "agent_role": s.agent_role,
                    "system_prompt": s.system_prompt,
                    "stance": s.stance,
                    "memory_snapshot": s.memory_snapshot,
                }
                for s in self.agent_states
            ],
            "current_consensus": self.current_consensus,
            "consensus_confidence": self.consensus_confidence,
            "convergence_status": self.convergence_status,
            "claims_kernel_state": self.claims_kernel_state,
            "belief_network_state": self.belief_network_state,
            "continuum_memory_state": self.continuum_memory_state,
            "status": self.status.value,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "checksum": self.checksum,
            "resume_count": self.resume_count,
            "last_resumed_at": self.last_resumed_at,
            "resumed_by": self.resumed_by,
            "pending_intervention": self.pending_intervention,
            "intervention_notes": self.intervention_notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> DebateCheckpoint:
        return cls(
            checkpoint_id=data["checkpoint_id"],
            debate_id=data["debate_id"],
            task=data["task"],
            current_round=data["current_round"],
            total_rounds=data["total_rounds"],
            phase=data["phase"],
            messages=data["messages"],
            critiques=data["critiques"],
            votes=data["votes"],
            agent_states=[
                AgentState(
                    agent_name=s["agent_name"],
                    agent_model=s["agent_model"],
                    agent_role=s["agent_role"],
                    system_prompt=s["system_prompt"],
                    stance=s["stance"],
                    memory_snapshot=s.get("memory_snapshot"),
                )
                for s in data["agent_states"]
            ],
            current_consensus=data.get("current_consensus"),
            consensus_confidence=data.get("consensus_confidence", 0.0),
            convergence_status=data.get("convergence_status", ""),
            claims_kernel_state=data.get("claims_kernel_state"),
            belief_network_state=data.get("belief_network_state"),
            continuum_memory_state=data.get("continuum_memory_state"),
            status=CheckpointStatus(data.get("status", "complete")),
            created_at=data["created_at"],
            expires_at=data.get("expires_at"),
            checksum=data["checksum"],
            resume_count=data.get("resume_count", 0),
            last_resumed_at=data.get("last_resumed_at"),
            resumed_by=data.get("resumed_by"),
            pending_intervention=data.get("pending_intervention", False),
            intervention_notes=data.get("intervention_notes", []),
        )


@dataclass
class ResumedDebate:
    """Context for a debate resumed from checkpoint."""

    checkpoint: DebateCheckpoint
    original_debate_id: str
    resumed_at: str
    resumed_by: str

    # Restored state
    messages: list[Message]
    votes: list[Vote]

    # Reconciliation
    context_drift_detected: bool = False
    drift_notes: list[str] = field(default_factory=list)


class CheckpointStore(ABC):
    """Abstract base for checkpoint persistence."""

    @abstractmethod
    async def save(self, checkpoint: DebateCheckpoint) -> str:
        """Save checkpoint, return storage path."""
        raise NotImplementedError("Subclasses must implement save")

    @abstractmethod
    async def load(self, checkpoint_id: str) -> DebateCheckpoint | None:
        """Load checkpoint by ID."""
        raise NotImplementedError("Subclasses must implement load")

    @abstractmethod
    async def list_checkpoints(
        self,
        debate_id: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """List available checkpoints."""
        raise NotImplementedError("Subclasses must implement list_checkpoints")

    @abstractmethod
    async def delete(self, checkpoint_id: str) -> bool:
        """Delete a checkpoint."""
        raise NotImplementedError("Subclasses must implement delete")


@dataclass
class CheckpointConfig:
    """Configuration for checkpointing behavior."""

    interval_rounds: int = 1  # Checkpoint every N rounds
    interval_seconds: float = 300.0  # Or every N seconds
    max_checkpoints: int = 10  # Keep at most N checkpoints per debate
    expiry_hours: float = 72.0  # Delete checkpoints after N hours
    compress: bool = True
    auto_cleanup: bool = True
    # Gastown-inspired continuous mode
    continuous_mode: bool = False  # Commit after every round
    enable_recovery_narrator: bool = True  # Generate recovery summaries
    glacial_tier_sync: bool = False  # Sync to ContinuumMemory glacial tier


class CheckpointManager:
    """
    Manages checkpoint lifecycle for debates.

    Handles creation, storage, resumption, and cleanup.

    Enhanced with Gastown-inspired features:
    - Continuous mode: commit after every round for crash resilience
    - Recovery narrator: generate context summaries for debate resumption
    - Glacial tier sync: persist to ContinuumMemory for long-term storage
    """

    def __init__(
        self,
        store: CheckpointStore | None = None,
        config: CheckpointConfig | None = None,
        webhook: CheckpointWebhook | None = None,
    ):
        self.store = store or FileCheckpointStore()
        self.config = config or CheckpointConfig()
        self.webhook = webhook

        self._last_checkpoint_time: dict[str, datetime] = {}
        self._checkpoint_count: dict[str, int] = {}

        # Initialize recovery narrator for GitCheckpointStore
        self._recovery_narrator: RecoveryNarrator | None = None
        if isinstance(self.store, GitCheckpointStore) and self.config.enable_recovery_narrator:
            self._recovery_narrator = RecoveryNarrator(self.store)

    @property
    def recovery_narrator(self) -> RecoveryNarrator | None:
        """Get the recovery narrator (only available with GitCheckpointStore)."""
        return self._recovery_narrator

    async def get_recovery_context(self, debate_id: str, agent_name: str) -> str | None:
        """Get recovery context for resuming a debate.

        Returns a prompt injection with debate history summary.
        """
        if self._recovery_narrator:
            return await self._recovery_narrator.get_resumption_prompt(debate_id, agent_name)
        return None

    def close(self) -> None:
        """Close checkpoint storage resources and clear transient state."""
        store = getattr(self, "store", None)
        if store is not None and hasattr(store, "close"):
            store.close()
        self._last_checkpoint_time.clear()
        self._checkpoint_count.clear()

    def should_checkpoint(
        self,
        debate_id: str,
        current_round: int,
    ) -> bool:
        """Determine if a checkpoint should be created."""
        # Check round interval
        if current_round % self.config.interval_rounds == 0:
            return True

        # Check time interval
        last_time = self._last_checkpoint_time.get(debate_id)
        if last_time:
            elapsed = (datetime.now() - last_time).total_seconds()
            if elapsed >= self.config.interval_seconds:
                return True

        return False

    async def create_checkpoint(
        self,
        debate_id: str,
        task: str,
        current_round: int,
        total_rounds: int,
        phase: str,
        messages: list[Message],
        critiques: list[Critique],
        votes: list[Vote],
        agents: list,  # Agent objects
        current_consensus: str | None = None,
        claims_kernel_state: dict | None = None,
        belief_network_state: dict | None = None,
        continuum_memory_state: dict | None = None,
    ) -> DebateCheckpoint:
        """Create and save a checkpoint."""
        checkpoint_id = f"cp-{debate_id[:8]}-{current_round:03d}-{uuid.uuid4().hex[:4]}"

        # Serialize messages
        messages_dict = [
            {
                "role": m.role,
                "agent": m.agent,
                "content": m.content,
                "timestamp": (
                    m.timestamp.isoformat()
                    if hasattr(m.timestamp, "isoformat")
                    else str(m.timestamp)
                ),
                "round": m.round,
            }
            for m in messages
        ]

        # Serialize critiques
        critiques_dict = [
            {
                "agent": c.agent,
                "target_agent": c.target_agent,
                "target_content": c.target_content,
                "issues": c.issues,
                "suggestions": c.suggestions,
                "severity": c.severity,
                "reasoning": c.reasoning,
            }
            for c in critiques
        ]

        # Serialize votes
        votes_dict = [
            {
                "agent": v.agent,
                "choice": v.choice,
                "confidence": v.confidence,
                "reasoning": v.reasoning,
                "continue_debate": v.continue_debate,
            }
            for v in votes
        ]

        # Serialize agent states
        agent_states = [
            AgentState(
                agent_name=a.name,
                agent_model=a.model,
                agent_role=a.role,
                system_prompt=getattr(a, "system_prompt", ""),
                stance=getattr(a, "stance", "neutral"),
            )
            for a in agents
        ]

        # Calculate expiry
        expiry = None
        if self.config.expiry_hours > 0:
            expiry = (datetime.now() + timedelta(hours=self.config.expiry_hours)).isoformat()

        checkpoint = DebateCheckpoint(
            checkpoint_id=checkpoint_id,
            debate_id=debate_id,
            task=task,
            current_round=current_round,
            total_rounds=total_rounds,
            phase=phase,
            messages=messages_dict,
            critiques=critiques_dict,
            votes=votes_dict,
            agent_states=agent_states,
            current_consensus=current_consensus,
            claims_kernel_state=claims_kernel_state,
            belief_network_state=belief_network_state,
            continuum_memory_state=continuum_memory_state,
            expires_at=expiry,
        )

        # Save
        await self.store.save(checkpoint)

        # Track
        self._last_checkpoint_time[debate_id] = datetime.now()
        self._checkpoint_count[debate_id] = self._checkpoint_count.get(debate_id, 0) + 1

        # Emit checkpoint event for UI narrator
        if self.webhook:
            await self.webhook.emit(
                "on_checkpoint",
                {
                    "checkpoint": checkpoint.to_dict(),
                    "debate_id": debate_id,
                    "round": current_round,
                },
            )

        # Cleanup old checkpoints if needed
        if self.config.auto_cleanup:
            await self._cleanup_old_checkpoints(debate_id)

        return checkpoint

    async def resume_from_checkpoint(
        self,
        checkpoint_id: str,
        resumed_by: str = "system",
    ) -> ResumedDebate | None:
        """Resume a debate from a checkpoint."""
        checkpoint = await self.store.load(checkpoint_id)

        if not checkpoint:
            return None

        if not checkpoint.verify_integrity():
            checkpoint.status = CheckpointStatus.CORRUPTED
            return None

        # Restore messages
        messages = [
            Message(
                role=m["role"],
                agent=m["agent"],
                content=m["content"],
                timestamp=(
                    datetime.fromisoformat(m["timestamp"])
                    if isinstance(m["timestamp"], str)
                    else m["timestamp"]
                ),
                round=m["round"],
            )
            for m in checkpoint.messages
        ]

        # Restore votes
        votes = [
            Vote(
                agent=v["agent"],
                choice=v["choice"],
                confidence=v["confidence"],
                reasoning=v["reasoning"],
                continue_debate=v.get("continue_debate", True),
            )
            for v in checkpoint.votes
        ]

        # Update checkpoint
        checkpoint.resume_count += 1
        checkpoint.last_resumed_at = datetime.now().isoformat()
        checkpoint.resumed_by = resumed_by
        checkpoint.status = CheckpointStatus.RESUMING

        await self.store.save(checkpoint)

        # Emit resume event for UI narrator
        if self.webhook:
            await self.webhook.emit(
                "on_resume",
                {
                    "checkpoint": checkpoint.to_dict(),
                    "debate_id": checkpoint.debate_id,
                    "round": checkpoint.current_round,
                    "resumed_by": resumed_by,
                },
            )

        return ResumedDebate(
            checkpoint=checkpoint,
            original_debate_id=checkpoint.debate_id,
            resumed_at=datetime.now().isoformat(),
            resumed_by=resumed_by,
            messages=messages,
            votes=votes,
        )

    async def add_intervention(
        self,
        checkpoint_id: str,
        note: str,
        by: str = "human",
    ) -> bool:
        """Add an intervention note to a checkpoint."""
        checkpoint = await self.store.load(checkpoint_id)

        if not checkpoint:
            return False

        checkpoint.pending_intervention = True
        checkpoint.intervention_notes.append(f"[{by}] {note}")

        await self.store.save(checkpoint)
        return True

    async def list_debates_with_checkpoints(self) -> list[dict]:
        """List all debates that have checkpoints."""
        all_checkpoints = await self.store.list_checkpoints()

        debates = {}
        for cp in all_checkpoints:
            debate_id = cp["debate_id"]
            if debate_id not in debates:
                debates[debate_id] = {
                    "debate_id": debate_id,
                    "task": cp["task"],
                    "checkpoint_count": 0,
                    "latest_checkpoint": None,
                    "latest_round": 0,
                }

            debates[debate_id]["checkpoint_count"] += 1
            if cp["current_round"] > debates[debate_id]["latest_round"]:
                debates[debate_id]["latest_round"] = cp["current_round"]
                debates[debate_id]["latest_checkpoint"] = cp["checkpoint_id"]

        return list(debates.values())

    async def save(self, checkpoint: DebateCheckpoint) -> str:
        """
        Save a checkpoint directly.

        This is a convenience method for checkpoint bridge integration.

        Args:
            checkpoint: Checkpoint to save

        Returns:
            Storage path or identifier
        """
        return await self.store.save(checkpoint)

    async def load(self, checkpoint_id: str) -> DebateCheckpoint | None:
        """
        Load a checkpoint directly.

        This is a convenience method for checkpoint bridge integration.

        Args:
            checkpoint_id: ID of checkpoint to load

        Returns:
            DebateCheckpoint if found, None otherwise
        """
        return await self.store.load(checkpoint_id)

    async def get_latest(self, debate_id: str) -> DebateCheckpoint | None:
        """
        Get the latest checkpoint for a debate.

        Args:
            debate_id: Debate identifier

        Returns:
            Latest checkpoint if found, None otherwise
        """
        checkpoints = await self.store.list_checkpoints(debate_id=debate_id, limit=1)

        if not checkpoints:
            return None

        # list_checkpoints returns dicts, sorted by created_at desc
        latest_id = checkpoints[0].get("checkpoint_id")
        if latest_id:
            return await self.store.load(latest_id)

        return None

    async def _cleanup_old_checkpoints(self, debate_id: str):
        """Remove old checkpoints beyond the limit."""
        checkpoints = await self.store.list_checkpoints(debate_id=debate_id)

        # Sort by creation time
        checkpoints.sort(key=lambda x: x["created_at"], reverse=True)

        # Delete extras
        for cp in checkpoints[self.config.max_checkpoints :]:
            await self.store.delete(cp["checkpoint_id"])


class CheckpointWebhook:
    """Webhook notifications for checkpoint events."""

    def __init__(self, webhook_url: str | None = None):
        self.webhook_url = webhook_url
        self.handlers: dict[str, list[Callable]] = {
            "on_checkpoint": [],
            "on_resume": [],
            "on_intervention": [],
        }

    def on_checkpoint(self, handler: Callable) -> Callable:
        """Register checkpoint creation handler."""
        self.handlers["on_checkpoint"].append(handler)
        return handler

    def on_resume(self, handler: Callable) -> Callable:
        """Register resume handler."""
        self.handlers["on_resume"].append(handler)
        return handler

    def on_intervention(self, handler: Callable) -> Callable:
        """Register intervention handler."""
        self.handlers["on_intervention"].append(handler)
        return handler

    async def emit(self, event: str, data: dict) -> None:
        """Emit event to all handlers."""
        for handler in self.handlers.get(event, []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(data)
                else:
                    handler(data)
            except (TypeError, ValueError, AttributeError) as e:
                logger.warning("Checkpoint webhook handler failed for event '%s': %s", event, e)
            except (RuntimeError, KeyError, OSError) as e:
                logger.exception(
                    "Unexpected error in checkpoint webhook handler for event '%s': %s", event, e
                )

        # Send to webhook if configured
        if self.webhook_url:
            await self._send_webhook(event, data)

    async def _send_webhook(self, event: str, data: dict):
        """Send webhook notification."""
        try:
            from aragora.observability.http_client_pool import get_http_pool

            pool = get_http_pool()
            async with pool.get_session("checkpoint_webhook") as client:
                await client.post(
                    self.webhook_url,
                    json={"event": event, "data": data},
                    timeout=10,
                )
        except ImportError as e:
            logger.debug("Webhook notification failed - http pool not available: %s", e)
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.debug("Webhook notification failed - connection error: %s", e)
        except (RuntimeError, ValueError, TypeError, AttributeError) as e:
            logger.warning("Unexpected webhook notification error: %s", e)


# Convenience function for quick checkpointing
async def checkpoint_debate(
    debate_id: str,
    task: str,
    round_num: int,
    total_rounds: int,
    phase: str,
    messages: list[Message],
    agents: list,
    store_path: str = ".checkpoints",
) -> DebateCheckpoint:
    """Quick checkpoint creation."""
    manager = CheckpointManager(
        store=FileCheckpointStore(store_path),
        config=CheckpointConfig(),
    )

    return await manager.create_checkpoint(
        debate_id=debate_id,
        task=task,
        current_round=round_num,
        total_rounds=total_rounds,
        phase=phase,
        messages=messages,
        critiques=[],
        votes=[],
        agents=agents,
    )


# Re-export backend implementations for backward compatibility
from aragora.debate.checkpoint_backends import (  # noqa: E402, F401
    DatabaseCheckpointStore,
    FileCheckpointStore,
    GitCheckpointStore,
    RecoveryNarrator,
    S3CheckpointStore,
)
