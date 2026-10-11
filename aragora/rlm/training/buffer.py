"""
Experience buffer for RLM training.

Provides trajectory storage and sampling for RL training of context
management strategies.

Usage:
    from aragora.rlm.training.buffer import ExperienceBuffer, Trajectory

    buffer = ExperienceBuffer(max_size=10000)
    buffer.add(trajectory)
    batch = buffer.sample(batch_size=32)
"""

from __future__ import annotations

import logging
import random
from collections import deque
from dataclasses import dataclass, field
from typing import Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class Step:
    """
    Single step in a trajectory.

    Represents one interaction with the RLM REPL environment.
    """

    # State representation
    state: dict[str, Any] = field(default_factory=dict)

    # Action taken (code executed, strategy chosen, etc.)
    action: str = ""
    action_type: str = "code"  # code, strategy, final

    # Environment response
    observation: str = ""

    # Intermediate metrics
    tokens_examined: int = 0
    sub_calls: int = 0

    # Timing
    timestamp: str = ""
    duration_seconds: float = 0.0

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class Trajectory:
    """
    Complete trajectory of an RLM query session.

    Stores the sequence of steps from query to final answer,
    along with outcome information for reward computation.
    """

    # Identity
    trajectory_id: str = ""
    query: str = ""
    strategy: str = "auto"

    # Steps in the trajectory
    steps: list[Step] = field(default_factory=list)

    # Final outcome
    final_answer: str = ""
    outcome: dict[str, Any] = field(default_factory=dict)
    is_terminal: bool = False

    # Aggregate statistics
    stats: dict[str, Any] = field(default_factory=dict)

    # Metadata
    created_at: str = ""
    context_tokens: int = 0
    source_type: str = "text"

    def __post_init__(self) -> None:
        if not self.trajectory_id:
            import uuid

            self.trajectory_id = str(uuid.uuid4())[:12]
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def add_step(self, step: Step) -> None:
        """Add a step to the trajectory."""
        self.steps.append(step)

    def finalize(
        self,
        answer: str,
        outcome: dict[str, Any],
        stats: dict[str, Any] | None = None,
    ) -> None:
        """
        Finalize the trajectory with final answer and outcome.

        Args:
            answer: Final answer produced
            outcome: Outcome dictionary (consensus_reached, quality_score, etc.)
            stats: Optional aggregate statistics
        """
        self.final_answer = answer
        self.outcome = outcome
        self.is_terminal = True

        # Compute aggregate stats if not provided
        if stats:
            self.stats = stats
        else:
            self.stats = self._compute_stats()

    def _compute_stats(self) -> dict[str, Any]:
        """Compute aggregate statistics from steps."""
        total_tokens = sum(s.tokens_examined for s in self.steps)
        total_sub_calls = sum(s.sub_calls for s in self.steps)
        total_duration = sum(s.duration_seconds for s in self.steps)

        return {
            "total_steps": len(self.steps),
            "total_tokens_examined": total_tokens,
            "sub_calls_made": total_sub_calls,
            "total_duration": total_duration,
            "strategy": self.strategy,
        }

    def to_dict(self) -> dict[str, Any]:
        """Convert trajectory to dictionary for serialization."""
        return {
            "trajectory_id": self.trajectory_id,
            "query": self.query,
            "strategy": self.strategy,
            "steps": [
                {
                    "action": s.action,
                    "action_type": s.action_type,
                    "observation": s.observation[:500],
                    "tokens_examined": s.tokens_examined,
                    "sub_calls": s.sub_calls,
                    "duration_seconds": s.duration_seconds,
                }
                for s in self.steps
            ],
            "final_answer": self.final_answer[:1000],
            "outcome": self.outcome,
            "stats": self.stats,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Trajectory:
        """Create trajectory from dictionary."""
        trajectory = cls(
            trajectory_id=data.get("trajectory_id", ""),
            query=data.get("query", ""),
            strategy=data.get("strategy", "auto"),
            final_answer=data.get("final_answer", ""),
            outcome=data.get("outcome", {}),
            stats=data.get("stats", {}),
            created_at=data.get("created_at", ""),
        )

        for step_data in data.get("steps", []):
            trajectory.add_step(
                Step(
                    action=step_data.get("action", ""),
                    action_type=step_data.get("action_type", "code"),
                    observation=step_data.get("observation", ""),
                    tokens_examined=step_data.get("tokens_examined", 0),
                    sub_calls=step_data.get("sub_calls", 0),
                    duration_seconds=step_data.get("duration_seconds", 0.0),
                )
            )

        trajectory.is_terminal = bool(data.get("outcome"))
        return trajectory


class ExperienceBuffer:
    """
    Experience replay buffer for storing trajectories.

    Supports:
    - FIFO eviction when capacity is reached
    - Random sampling for training
    - Priority-based sampling (optional)
    - Persistence to disk
    """

    def __init__(
        self,
        max_size: int = 10000,
        priority_alpha: float = 0.0,  # 0 = uniform, >0 = prioritized
    ):
        """
        Initialize experience buffer.

        Args:
            max_size: Maximum number of trajectories to store
            priority_alpha: Priority exponent (0 for uniform sampling)
        """
        self.max_size = max_size
        self.priority_alpha = priority_alpha
        self._buffer: deque[Trajectory] = deque(maxlen=max_size)
        self._priorities: deque[float] = deque(maxlen=max_size)

    def __len__(self) -> int:
        return len(self._buffer)

    def add(self, trajectory: Trajectory, priority: float = 1.0) -> None:
        """
        Add a trajectory to the buffer.

        Args:
            trajectory: Trajectory to add
            priority: Initial priority (for prioritized sampling)
        """
        if not trajectory.is_terminal:
            logger.warning("Adding non-terminal trajectory %s", trajectory.trajectory_id)

        self._buffer.append(trajectory)
        self._priorities.append(priority)

    def sample(self, batch_size: int) -> list[Trajectory]:
        """
        Sample a batch of trajectories.

        Args:
            batch_size: Number of trajectories to sample

        Returns:
            List of sampled trajectories
        """
        if len(self._buffer) == 0:
            return []

        batch_size = min(batch_size, len(self._buffer))

        if self.priority_alpha == 0:
            # Uniform sampling
            indices = random.sample(range(len(self._buffer)), batch_size)
        else:
            # Prioritized sampling
            priorities = [p**self.priority_alpha for p in self._priorities]
            total_priority = sum(priorities)
            probs = [p / total_priority for p in priorities]
            indices = random.choices(
                range(len(self._buffer)),
                weights=probs,
                k=batch_size,
            )

        return [self._buffer[i] for i in indices]

    def sample_by_outcome(
        self,
        batch_size: int,
        success_only: bool = False,
        failure_only: bool = False,
    ) -> list[Trajectory]:
        """
        Sample trajectories filtered by outcome.

        Args:
            batch_size: Number of trajectories to sample
            success_only: Only sample successful trajectories
            failure_only: Only sample failed trajectories

        Returns:
            List of filtered trajectories
        """
        filtered = []
        for t in self._buffer:
            if success_only and not t.outcome.get("success", False):
                continue
            if failure_only and t.outcome.get("success", False):
                continue
            filtered.append(t)

        if not filtered:
            return []

        batch_size = min(batch_size, len(filtered))
        return random.sample(filtered, batch_size)

    def sample_by_strategy(
        self,
        strategy: str,
        batch_size: int,
    ) -> list[Trajectory]:
        """
        Sample trajectories that used a specific strategy.

        Args:
            strategy: Strategy to filter by
            batch_size: Number of trajectories to sample

        Returns:
            List of filtered trajectories
        """
        filtered = [t for t in self._buffer if t.strategy == strategy]

        if not filtered:
            return []

        batch_size = min(batch_size, len(filtered))
        return random.sample(filtered, batch_size)

    def update_priority(self, trajectory_id: str, new_priority: float) -> None:
        """Update priority for a trajectory."""
        for i, t in enumerate(self._buffer):
            if t.trajectory_id == trajectory_id:
                self._priorities[i] = new_priority
                break

    def get_stats(self) -> dict[str, Any]:
        """Get buffer statistics."""
        if not self._buffer:
            return {
                "size": 0,
                "success_rate": 0.0,
                "avg_steps": 0.0,
                "strategies": {},
            }

        success_count = sum(1 for t in self._buffer if t.outcome.get("success", False))
        avg_steps = sum(len(t.steps) for t in self._buffer) / len(self._buffer)

        strategy_counts: dict[str, int] = {}
        for t in self._buffer:
            strategy_counts[t.strategy] = strategy_counts.get(t.strategy, 0) + 1

        return {
            "size": len(self._buffer),
            "success_rate": success_count / len(self._buffer),
            "avg_steps": avg_steps,
            "strategies": strategy_counts,
        }

    def clear(self) -> None:
        """Clear the buffer."""
        self._buffer.clear()
        self._priorities.clear()

    def save(self, filepath: str) -> None:
        """
        Save buffer to disk.

        Args:
            filepath: Path to save file (JSON)
        """
        import json

        data = {
            "max_size": self.max_size,
            "priority_alpha": self.priority_alpha,
            "trajectories": [t.to_dict() for t in self._buffer],
            "priorities": list(self._priorities),
        }

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

        logger.info("Saved %s trajectories to %s", len(self._buffer), filepath)

    @classmethod
    def load(cls, filepath: str) -> ExperienceBuffer:
        """
        Load buffer from disk.

        Args:
            filepath: Path to load file

        Returns:
            Loaded ExperienceBuffer
        """
        import json

        with open(filepath) as f:
            data = json.load(f)

        buffer = cls(
            max_size=data.get("max_size", 10000),
            priority_alpha=data.get("priority_alpha", 0.0),
        )

        for t_data, priority in zip(
            data.get("trajectories", []),
            data.get("priorities", [1.0] * len(data.get("trajectories", []))),
        ):
            trajectory = Trajectory.from_dict(t_data)
            buffer.add(trajectory, priority)

        logger.info("Loaded %s trajectories from %s", len(buffer), filepath)
        return buffer


__all__ = [
    "Step",
    "Trajectory",
    "ExperienceBuffer",
]
