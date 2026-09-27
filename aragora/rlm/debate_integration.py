"""
Debate-RLM Training Integration.

Connects debate outcomes to the RLM training loop, enabling
learning from real debate experiences.

Usage:
    from aragora.rlm.debate_integration import (
        DebateTrajectoryCollector,
        get_debate_trajectory_collector,
    )

    # Get the global collector
    collector = get_debate_trajectory_collector()

    # Record a debate outcome
    collector.record_debate_outcome(
        debate_id="debate_001",
        task="Design a caching system",
        consensus_reached=True,
        confidence=0.85,
        messages=debate_messages,
    )

    # Get training trajectories
    trajectories = collector.get_trajectories(limit=100)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from collections.abc import Callable
from datetime import datetime, timezone

from aragora.rlm.training.buffer import ExperienceBuffer, Step, Trajectory

if TYPE_CHECKING:
    from aragora.core_types import Message
    from aragora.debate.context import DebateContext

logger = logging.getLogger(__name__)

# Global collector instance
_global_collector: DebateTrajectoryCollector | None = None


@dataclass
class DebateOutcome:
    """Outcome data from a completed debate."""

    debate_id: str
    task: str
    consensus_reached: bool
    confidence: float
    winner: str | None = None
    final_answer: str = ""
    num_rounds: int = 0
    num_messages: int = 0
    agents: list[str] = field(default_factory=list)
    domain: str = "general"

    def __post_init__(self) -> None:
        # Preserve normalization for deserializers that explicitly pass null.
        if self.agents is None:
            self.agents = []


class DebateTrajectoryCollector:
    """
    Collects trajectories from debate outcomes for RLM training.

    Converts debate sessions into training trajectories that can be
    used by the RLM trainer to improve context management strategies.
    """

    def __init__(
        self,
        buffer: ExperienceBuffer | None = None,
        max_trajectories: int = 10000,
    ) -> None:
        """
        Initialize the collector.

        Args:
            buffer: Optional experience buffer (creates new if not provided)
            max_trajectories: Maximum trajectories to keep in buffer
        """
        self.buffer = buffer or ExperienceBuffer(max_size=max_trajectories)
        self._debate_count = 0
        self._successful_debates = 0
        self._in_progress: dict[str, Trajectory] = {}  # debate_id -> trajectory being built

    def record_debate_outcome(
        self,
        debate_id: str,
        task: str,
        consensus_reached: bool,
        confidence: float,
        messages: list[Message] | None = None,
        winner: str | None = None,
        final_answer: str = "",
        num_rounds: int = 0,
        agents: list[str] | None = None,
        domain: str = "general",
    ) -> Trajectory:
        """
        Record a debate outcome as a training trajectory.

        Args:
            debate_id: Unique identifier for the debate
            task: The debate task/question
            consensus_reached: Whether consensus was reached
            confidence: Confidence in the final answer
            messages: Optional list of debate messages
            winner: Winning proposal/agent if applicable
            final_answer: The final answer from the debate
            num_rounds: Number of debate rounds
            agents: List of participating agent names
            domain: Debate domain for categorization

        Returns:
            Created trajectory
        """
        outcome = DebateOutcome(
            debate_id=debate_id,
            task=task,
            consensus_reached=consensus_reached,
            confidence=confidence,
            winner=winner,
            final_answer=final_answer,
            num_rounds=num_rounds,
            num_messages=len(messages) if messages else 0,
            agents=agents or [],
            domain=domain,
        )

        trajectory = self._create_trajectory(outcome, messages)

        # Merge any per-round steps recorded via record_round()
        in_progress = self._in_progress.pop(debate_id, None)
        if in_progress and in_progress.steps:
            # Prepend per-round steps before the final outcome steps
            trajectory.steps = in_progress.steps + trajectory.steps

        self.buffer.add(trajectory)

        self._debate_count += 1
        if consensus_reached:
            self._successful_debates += 1

        logger.debug(
            f"Recorded debate trajectory: id={debate_id}, "
            f"consensus={consensus_reached}, confidence={confidence:.2f}"
        )

        return trajectory

    def record_from_context(self, ctx: DebateContext) -> Trajectory | None:
        """
        Record a trajectory directly from a DebateContext.

        Convenience method that extracts all relevant data from the context.

        Args:
            ctx: The completed debate context

        Returns:
            Created trajectory, or None if context has no result
        """
        if not ctx.result:
            return None

        result = ctx.result
        messages: list[Message] | None = ctx.context_messages if ctx.context_messages else None
        return self.record_debate_outcome(
            debate_id=ctx.debate_id,
            task=ctx.env.task if ctx.env else "",
            consensus_reached=result.consensus_reached,
            confidence=result.confidence,
            messages=messages,
            winner=result.winner,
            final_answer=result.final_answer or "",
            num_rounds=len(ctx.context_messages) // max(len(ctx.agents), 1) if ctx.agents else 0,
            agents=[a.name for a in ctx.agents] if ctx.agents else [],
            domain=ctx.domain or "general",
        )

    def record_round(
        self,
        debate_id: str,
        round_num: int,
        proposals: list[dict[str, str]],
        critiques: list[dict[str, str]],
        convergence_similarity: float = 0.0,
    ) -> None:
        """Record per-round proposals and critiques for richer training data.

        Builds an in-progress trajectory round by round. Call
        ``record_debate_outcome`` to finalize it.

        Args:
            debate_id: Unique identifier for the debate.
            round_num: Zero-based round number.
            proposals: List of ``{"agent": name, "content": text}`` dicts.
            critiques: List of ``{"agent": name, "content": text}`` dicts.
            convergence_similarity: Semantic similarity score for this round.
        """
        if not debate_id:
            return

        if debate_id not in self._in_progress:
            self._in_progress[debate_id] = Trajectory(
                trajectory_id=debate_id,
                query="",
                strategy="debate",
                source_type="debate",
            )

        trajectory = self._in_progress[debate_id]

        for proposal in proposals:
            step = Step(
                state={
                    "round": round_num,
                    "phase": "proposal",
                    "convergence": convergence_similarity,
                },
                action=proposal.get("content", "")[:500],
                action_type="proposal",
                observation=proposal.get("agent", ""),
            )
            trajectory.add_step(step)

        for critique in critiques:
            step = Step(
                state={
                    "round": round_num,
                    "phase": "critique",
                    "convergence": convergence_similarity,
                },
                action=critique.get("content", "")[:500],
                action_type="critique",
                observation=critique.get("agent", ""),
            )
            trajectory.add_step(step)

        logger.debug(
            "Recorded round %d for debate %s: %d proposals, %d critiques",
            round_num,
            debate_id,
            len(proposals),
            len(critiques),
        )

    def _create_trajectory(
        self,
        outcome: DebateOutcome,
        messages: list[Message] | None = None,
    ) -> Trajectory:
        """
        Create a training trajectory from a debate outcome.

        Args:
            outcome: The debate outcome data
            messages: Optional list of debate messages

        Returns:
            Trajectory suitable for RLM training
        """
        trajectory = Trajectory(
            trajectory_id=outcome.debate_id,
            query=outcome.task,
            strategy="debate",
            final_answer=outcome.final_answer,
            is_terminal=True,
            outcome={
                "consensus_reached": outcome.consensus_reached,
                "confidence": outcome.confidence,
                "winner": outcome.winner,
                "num_rounds": outcome.num_rounds,
                "agents": outcome.agents,
                "domain": outcome.domain,
            },
            stats={
                "total_messages": outcome.num_messages,
                "agents": len(outcome.agents),
                "rounds": outcome.num_rounds,
            },
            source_type="debate",
        )

        # Convert messages to steps
        if messages:
            for i, msg in enumerate(messages):
                step = Step(
                    state={
                        "round": i // max(len(outcome.agents), 1),
                        "agent_index": i % max(len(outcome.agents), 1),
                    },
                    action=getattr(msg, "content", str(msg))[:500],
                    action_type="message",
                    observation="",  # Response to this message
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
                trajectory.add_step(step)

        # Finalize trajectory with outcome
        trajectory.finalize(
            answer=outcome.final_answer,
            outcome={
                "consensus_reached": outcome.consensus_reached,
                "confidence": outcome.confidence,
                "winner": outcome.winner,
                "success": outcome.consensus_reached,
            },
        )

        return trajectory

    def get_trajectories(self, limit: int | None = None) -> list[Trajectory]:
        """
        Get trajectories for training.

        Args:
            limit: Maximum number of trajectories to return

        Returns:
            List of trajectories
        """
        return self.buffer.sample(limit or len(self.buffer))

    def get_stats(self) -> dict[str, Any]:
        """Get collector statistics."""
        return {
            "total_debates": self._debate_count,
            "successful_debates": self._successful_debates,
            "success_rate": (
                self._successful_debates / self._debate_count if self._debate_count > 0 else 0.0
            ),
            "buffer_size": len(self.buffer),
            "buffer_capacity": self.buffer.max_size,
        }

    def clear(self) -> None:
        """Clear all collected trajectories."""
        self.buffer.clear()
        self._debate_count = 0
        self._successful_debates = 0


def get_debate_trajectory_collector() -> DebateTrajectoryCollector:
    """
    Get the global debate trajectory collector.

    Creates the collector on first call.

    Returns:
        Global DebateTrajectoryCollector instance
    """
    global _global_collector
    if _global_collector is None:
        _global_collector = DebateTrajectoryCollector()
    return _global_collector


def reset_debate_trajectory_collector() -> None:
    """Reset the global collector."""
    global _global_collector
    if _global_collector:
        _global_collector.clear()
    _global_collector = None


def create_training_hook() -> Callable[..., Any]:
    """
    Create a post-debate hook for automatic trajectory collection.

    Returns a hook function that can be registered with Arena.

    Usage:
        from aragora.rlm.debate_integration import create_training_hook

        arena = Arena(
            ...,
            event_hooks={
                "on_debate_complete": create_training_hook(),
            },
        )
    """

    def on_debate_complete(result: Any, ctx: Any = None) -> None:
        """Hook that records debate outcomes for RLM training."""
        try:
            collector = get_debate_trajectory_collector()

            if ctx is not None:
                collector.record_from_context(ctx)
            elif hasattr(result, "debate_id"):
                # Fallback: construct from result
                collector.record_debate_outcome(
                    debate_id=getattr(result, "debate_id", "unknown"),
                    task=getattr(result, "task", ""),
                    consensus_reached=getattr(result, "consensus_reached", False),
                    confidence=getattr(result, "confidence", 0.0),
                    winner=getattr(result, "winner", None),
                    final_answer=getattr(result, "final_answer", ""),
                )
        except (RuntimeError, ValueError, AttributeError, TypeError) as e:
            logger.debug("Failed to record debate trajectory: %s", e)

    return on_debate_complete


__all__ = [
    "DebateTrajectoryCollector",
    "DebateOutcome",
    "get_debate_trajectory_collector",
    "reset_debate_trajectory_collector",
    "create_training_hook",
]
