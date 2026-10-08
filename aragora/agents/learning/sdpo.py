"""
SDPO - Self-Distillation Policy Optimization for Agent Calibration.

Based on research showing that agents can improve by:
1. Recording trajectories (inputs, outputs, outcomes)
2. Retrospectively evaluating which outputs led to good outcomes
3. Using this evaluation to refine future generation

Key insight: The same model can evaluate its past outputs better than
it could generate them originally (hindsight is 20/20).

Integration with Aragora:
- Track debate trajectories (proposals, critiques, syntheses)
- After debate completion, evaluate which contributions were most valuable
- Use these signals to improve calibration and generation quality

Usage:
    learner = SDPOLearner(config=SDPOConfig())

    # During debate
    trajectory = learner.start_trajectory(task="API design decision")
    trajectory.record_step(
        agent="proposer",
        action="propose",
        content="We should use REST because...",
        metadata={"confidence": 0.8},
    )
    # ... more steps ...

    # After debate completion
    trajectory.set_outcome(
        success=True,
        quality_score=0.85,
        feedback="Decision led to clean implementation",
    )

    # Learn from trajectory
    insights = await learner.evaluate_trajectory(trajectory)
    learner.update_calibration(insights)
"""

from __future__ import annotations

import json
import logging
import statistics
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class ActionType(str, Enum):
    """Types of actions in a trajectory."""

    PROPOSE = "propose"
    CRITIQUE = "critique"
    SYNTHESIZE = "synthesize"
    JUDGE = "judge"
    SEARCH = "search"
    REASON = "reason"
    OTHER = "other"


@dataclass
class TrajectoryStep:
    """A single step in a trajectory.

    Records what an agent did at a specific point, including
    the context, action taken, and any metadata like confidence.
    """

    id: str
    timestamp: datetime
    agent_name: str
    action_type: ActionType
    content: str
    context_summary: str = ""
    confidence: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)

    # Filled in during retrospective evaluation
    retrospective_score: float | None = None
    contribution_to_outcome: str | None = None


@dataclass
class TrajectoryOutcome:
    """Outcome of a completed trajectory."""

    success: bool
    quality_score: float  # 0.0 to 1.0
    feedback: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TrajectoryRecord:
    """Complete record of a decision-making trajectory.

    Tracks the full sequence of agent actions from task start
    to outcome, enabling retrospective analysis.
    """

    id: str
    task: str
    started_at: datetime
    steps: list[TrajectoryStep] = field(default_factory=list)
    outcome: TrajectoryOutcome | None = None
    completed_at: datetime | None = None

    def record_step(
        self,
        agent: str,
        action: ActionType | str,
        content: str,
        confidence: float = 0.5,
        context_summary: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> TrajectoryStep:
        """Record a new step in the trajectory.

        Args:
            agent: Name of the acting agent
            action: Type of action taken
            content: The actual content/output
            confidence: Agent's confidence in this action
            context_summary: Summary of context at this point
            metadata: Additional metadata

        Returns:
            The created TrajectoryStep
        """
        if isinstance(action, str):
            try:
                action = ActionType(action)
            except ValueError:
                action = ActionType.OTHER

        step = TrajectoryStep(
            id=str(uuid.uuid4()),
            timestamp=datetime.now(),
            agent_name=agent,
            action_type=action,
            content=content,
            context_summary=context_summary,
            confidence=confidence,
            metadata=metadata or {},
        )
        self.steps.append(step)
        return step

    def set_outcome(
        self,
        success: bool,
        quality_score: float,
        feedback: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Set the outcome of the trajectory.

        Args:
            success: Whether the trajectory achieved its goal
            quality_score: Quality rating (0.0 to 1.0)
            feedback: Human or automated feedback
            metadata: Additional outcome metadata
        """
        self.outcome = TrajectoryOutcome(
            success=success,
            quality_score=quality_score,
            feedback=feedback,
            metadata=metadata or {},
        )
        self.completed_at = datetime.now()

    @property
    def duration_seconds(self) -> float | None:
        """Calculate trajectory duration in seconds."""
        if not self.completed_at:
            return None
        return (self.completed_at - self.started_at).total_seconds()

    @property
    def is_complete(self) -> bool:
        """Check if trajectory has an outcome."""
        return self.outcome is not None


@dataclass
class CalibrationInsight:
    """Insight from retrospective evaluation.

    Captures what was learned about agent calibration from
    analyzing a trajectory.
    """

    agent_name: str
    action_type: ActionType
    original_confidence: float
    retrospective_score: float
    calibration_error: float  # How wrong was the confidence?
    lesson: str
    context_pattern: str = ""  # Pattern that triggered this lesson


@dataclass
class AgentCalibration:
    """Calibration data for a single agent.

    Tracks how well an agent's confidence matches actual quality
    and provides adjustment factors.
    """

    agent_name: str
    total_actions: int = 0
    mean_confidence: float = 0.5
    mean_quality: float = 0.5
    calibration_error: float = 0.0  # Avg |confidence - quality|
    overconfidence_bias: float = 0.0  # Positive = overconfident
    action_type_factors: dict[ActionType, float] = field(default_factory=dict)
    last_updated: datetime = field(default_factory=datetime.now)

    def get_adjustment_factor(self, action_type: ActionType) -> float:
        """Get confidence adjustment factor for an action type.

        Returns factor to multiply raw confidence by to get
        calibrated confidence.

        Args:
            action_type: Type of action

        Returns:
            Adjustment factor (typically 0.7 to 1.3)
        """
        base_factor = 1.0 - self.overconfidence_bias
        type_factor = self.action_type_factors.get(action_type, 1.0)
        return base_factor * type_factor

    @property
    def adjusted_confidence(self) -> float:
        """Convenience adjusted confidence based on overconfidence bias."""
        adjusted = self.mean_confidence * (1.0 - self.overconfidence_bias)
        return max(0.0, min(1.0, adjusted))


@dataclass
class SDPOConfig:
    """Configuration for SDPO learner.

    Attributes:
        buffer_size: Maximum trajectories to keep in buffer
        min_trajectories_for_update: Minimum trajectories before updating calibration
        learning_rate: How quickly to adjust calibration (0.0 to 1.0)
        retrospective_depth: How many steps back to evaluate
        enable_cross_trajectory: Learn patterns across trajectories
        storage_path: Optional path for persisting learnings
    """

    buffer_size: int = 100
    min_trajectories_for_update: int = 5
    learning_rate: float = 0.1
    retrospective_depth: int = 10
    enable_cross_trajectory: bool = True
    storage_path: Path | None = None


class RetrospectiveEvaluator(Protocol):
    """Protocol for retrospective evaluation of trajectory steps."""

    async def evaluate_step(
        self,
        step: TrajectoryStep,
        outcome: TrajectoryOutcome,
        full_trajectory: TrajectoryRecord,
    ) -> tuple[float, str]:
        """Evaluate how much a step contributed to the outcome.

        Args:
            step: The step to evaluate
            outcome: The final outcome
            full_trajectory: Complete trajectory for context

        Returns:
            Tuple of (contribution_score, explanation)
        """
        ...


class ExperienceBuffer:
    """Buffer for storing completed trajectories.

    Maintains a sliding window of recent trajectories for
    retrospective learning.
    """

    def __init__(self, max_size: int = 100):
        """Initialize the buffer.

        Args:
            max_size: Maximum number of trajectories to store
        """
        self.max_size = max_size
        self._buffer: deque[TrajectoryRecord] = deque(maxlen=max_size)

    def add(self, trajectory: TrajectoryRecord) -> None:
        """Add a completed trajectory to the buffer.

        Args:
            trajectory: Trajectory to add (must be complete)
        """
        if not trajectory.is_complete:
            logger.warning("Attempted to add incomplete trajectory to buffer")
            return
        self._buffer.append(trajectory)

    def get_recent(self, n: int = 10) -> list[TrajectoryRecord]:
        """Get the n most recent trajectories.

        Args:
            n: Number of trajectories to return

        Returns:
            List of recent trajectories
        """
        return list(self._buffer)[-n:]

    def get_by_task_pattern(self, pattern: str) -> list[TrajectoryRecord]:
        """Get trajectories matching a task pattern.

        Args:
            pattern: Substring to match in task description

        Returns:
            Matching trajectories
        """
        pattern_lower = pattern.lower()
        return [t for t in self._buffer if pattern_lower in t.task.lower()]

    def get_by_agent(self, agent_name: str) -> list[TrajectoryRecord]:
        """Get trajectories involving a specific agent.

        Args:
            agent_name: Agent name to filter by

        Returns:
            Trajectories with steps from this agent
        """
        return [t for t in self._buffer if any(s.agent_name == agent_name for s in t.steps)]

    def __len__(self) -> int:
        return len(self._buffer)

    def clear(self) -> None:
        """Clear all trajectories from buffer."""
        self._buffer.clear()


class DefaultRetrospectiveEvaluator:
    """Default implementation of retrospective evaluation.

    Uses heuristics to estimate step contribution to outcome.
    For production, implement with LLM-based evaluation.
    """

    async def evaluate_step(
        self,
        step: TrajectoryStep,
        outcome: TrajectoryOutcome,
        full_trajectory: TrajectoryRecord,
    ) -> tuple[float, str]:
        """Evaluate step contribution using heuristics.

        Args:
            step: Step to evaluate
            outcome: Final outcome
            full_trajectory: Complete trajectory

        Returns:
            (contribution_score, explanation)
        """
        # Base contribution starts with outcome quality
        base_score = outcome.quality_score

        # Adjust based on action type
        action_weights = {
            ActionType.PROPOSE: 0.3,
            ActionType.CRITIQUE: 0.25,
            ActionType.SYNTHESIZE: 0.3,
            ActionType.JUDGE: 0.15,
            ActionType.SEARCH: 0.1,
            ActionType.REASON: 0.2,
            ActionType.OTHER: 0.1,
        }
        action_weight = action_weights.get(step.action_type, 0.1)

        # Temporal factor: later steps had more information
        step_index = full_trajectory.steps.index(step)
        total_steps = len(full_trajectory.steps)
        temporal_factor = (step_index + 1) / total_steps

        # Content quality heuristics
        content_score = self._evaluate_content(step.content)

        # Combined score
        contribution = (
            0.4 * base_score + 0.2 * action_weight + 0.2 * temporal_factor + 0.2 * content_score
        )

        # Generate explanation
        explanation = self._generate_explanation(step, contribution, outcome.success)

        return contribution, explanation

    def _evaluate_content(self, content: str) -> float:
        """Evaluate content quality using heuristics."""
        if not content:
            return 0.0

        score = 0.5

        # Length factor
        words = content.split()
        if 20 <= len(words) <= 200:
            score += 0.2
        elif len(words) > 200:
            score += 0.1

        # Reasoning indicators
        reasoning_words = ["because", "therefore", "however", "considering"]
        if any(w in content.lower() for w in reasoning_words):
            score += 0.15

        # Structure (has sections/bullets)
        if "\n" in content:
            score += 0.1

        return min(1.0, score)

    def _generate_explanation(
        self,
        step: TrajectoryStep,
        contribution: float,
        success: bool,
    ) -> str:
        """Generate human-readable explanation."""
        quality = "high" if contribution > 0.7 else "moderate" if contribution > 0.4 else "low"
        outcome_word = "successful" if success else "unsuccessful"

        return (
            f"{step.agent_name}'s {step.action_type.value} had {quality} contribution "
            f"to the {outcome_word} outcome. "
            f"Original confidence: {step.confidence:.2f}, "
            f"Retrospective score: {contribution:.2f}."
        )


class SDPOLearner:
    """Self-Distillation Policy Optimization learner.

    Learns from retrospective evaluation of trajectories to
    improve agent calibration over time.

    Example:
        learner = SDPOLearner()

        # Track a debate trajectory
        trajectory = learner.start_trajectory("Should we use microservices?")
        trajectory.record_step(
            agent="claude",
            action=ActionType.PROPOSE,
            content="Microservices offer better scalability...",
            confidence=0.85,
        )
        # ... more steps ...
        trajectory.set_outcome(success=True, quality_score=0.9)

        # Learn from it
        insights = await learner.evaluate_trajectory(trajectory)
        print(f"Learned {len(insights)} insights")

        # Apply to future confidence estimates
        calibrated = learner.calibrate_confidence(
            agent="claude",
            action=ActionType.PROPOSE,
            raw_confidence=0.8,
        )
    """

    def __init__(
        self,
        config: SDPOConfig | None = None,
        evaluator: RetrospectiveEvaluator | None = None,
    ):
        """Initialize the SDPO learner.

        Args:
            config: Configuration options
            evaluator: Custom retrospective evaluator
        """
        self.config = config or SDPOConfig()
        self.evaluator = evaluator or DefaultRetrospectiveEvaluator()
        self.buffer = ExperienceBuffer(max_size=self.config.buffer_size)
        self.calibrations: dict[str, AgentCalibration] = {}
        self._active_trajectories: dict[str, TrajectoryRecord] = {}

    def start_trajectory(self, task: str) -> TrajectoryRecord:
        """Start tracking a new trajectory.

        Args:
            task: Description of the task/decision

        Returns:
            New TrajectoryRecord for recording steps
        """
        trajectory = TrajectoryRecord(
            id=str(uuid.uuid4()),
            task=task,
            started_at=datetime.now(),
        )
        self._active_trajectories[trajectory.id] = trajectory
        return trajectory

    def complete_trajectory(
        self,
        trajectory_id: str,
        success: bool,
        quality_score: float,
        feedback: str = "",
    ) -> TrajectoryRecord | None:
        """Complete an active trajectory with outcome.

        Args:
            trajectory_id: ID of the trajectory
            success: Whether it was successful
            quality_score: Quality rating
            feedback: Optional feedback

        Returns:
            Completed trajectory, or None if not found
        """
        trajectory = self._active_trajectories.pop(trajectory_id, None)
        if not trajectory:
            logger.warning("Trajectory not found: %s", trajectory_id)
            return None

        trajectory.set_outcome(
            success=success,
            quality_score=quality_score,
            feedback=feedback,
        )
        self.buffer.add(trajectory)
        return trajectory

    def get_trajectory(self, trajectory_id: str) -> TrajectoryRecord | None:
        """Retrieve a trajectory by ID from active set or buffer."""
        if trajectory_id in self._active_trajectories:
            return self._active_trajectories[trajectory_id]
        for traj in self.buffer.get_recent(self.buffer.max_size):
            if traj.id == trajectory_id:
                return traj
        return None

    async def evaluate_trajectory(
        self,
        trajectory: TrajectoryRecord,
    ) -> list[CalibrationInsight]:
        """Retrospectively evaluate a trajectory.

        Analyzes each step's contribution to the outcome and
        generates calibration insights.

        Args:
            trajectory: Completed trajectory to evaluate

        Returns:
            List of CalibrationInsight objects
        """
        if not trajectory.is_complete:
            logger.warning("Cannot evaluate incomplete trajectory")
            return []

        insights = []
        outcome = trajectory.outcome
        if outcome is None:
            logger.warning("Cannot evaluate trajectory without an outcome")
            return []

        # Evaluate each step
        for step in trajectory.steps[-self.config.retrospective_depth :]:
            score, explanation = await self.evaluator.evaluate_step(step, outcome, trajectory)

            # Update step with retrospective data
            step.retrospective_score = score
            step.contribution_to_outcome = explanation

            # Generate insight
            calibration_error = abs(step.confidence - score)
            insight = CalibrationInsight(
                agent_name=step.agent_name,
                action_type=step.action_type,
                original_confidence=step.confidence,
                retrospective_score=score,
                calibration_error=calibration_error,
                lesson=explanation,
                context_pattern=trajectory.task[:50],
            )
            insights.append(insight)

        return insights

    def update_calibration(
        self,
        insights: list[CalibrationInsight],
    ) -> None:
        """Update calibration based on insights.

        Args:
            insights: List of calibration insights
        """
        # Group insights by agent
        agent_insights: dict[str, list[CalibrationInsight]] = {}
        for insight in insights:
            if insight.agent_name not in agent_insights:
                agent_insights[insight.agent_name] = []
            agent_insights[insight.agent_name].append(insight)

        # Update each agent's calibration
        for agent_name, agent_data in agent_insights.items():
            self._update_agent_calibration(agent_name, agent_data)

    def _update_agent_calibration(
        self,
        agent_name: str,
        insights: list[CalibrationInsight],
    ) -> None:
        """Update calibration for a single agent.

        Args:
            agent_name: Name of the agent
            insights: Insights for this agent
        """
        if agent_name not in self.calibrations:
            self.calibrations[agent_name] = AgentCalibration(agent_name=agent_name)

        cal = self.calibrations[agent_name]
        lr = self.config.learning_rate

        # Calculate aggregate statistics
        confidences = [i.original_confidence for i in insights]
        scores = [i.retrospective_score for i in insights]
        errors = [i.calibration_error for i in insights]

        if not confidences:
            return

        # Update running statistics with exponential smoothing
        new_mean_conf = statistics.mean(confidences)
        new_mean_qual = statistics.mean(scores)
        new_error = statistics.mean(errors)

        cal.mean_confidence = (1 - lr) * cal.mean_confidence + lr * new_mean_conf
        cal.mean_quality = (1 - lr) * cal.mean_quality + lr * new_mean_qual
        cal.calibration_error = (1 - lr) * cal.calibration_error + lr * new_error

        # Calculate overconfidence bias (positive = overconfident)
        confidence_diffs = [c - s for c, s in zip(confidences, scores)]
        if confidence_diffs:
            bias = statistics.mean(confidence_diffs)
            cal.overconfidence_bias = (1 - lr) * cal.overconfidence_bias + lr * bias

        # Update action-type-specific factors
        action_data: dict[ActionType, list[float]] = {}
        for insight in insights:
            if insight.action_type not in action_data:
                action_data[insight.action_type] = []
            # Factor = retrospective / confidence (how much to scale)
            if insight.original_confidence > 0.1:
                factor = insight.retrospective_score / insight.original_confidence
                action_data[insight.action_type].append(factor)

        for action_type, factors in action_data.items():
            if factors:
                new_factor = statistics.mean(factors)
                old_factor = cal.action_type_factors.get(action_type, 1.0)
                cal.action_type_factors[action_type] = (1 - lr) * old_factor + lr * new_factor

        cal.total_actions += len(insights)
        cal.last_updated = datetime.now()

    def calibrate_confidence(
        self,
        agent: str,
        action: ActionType,
        raw_confidence: float,
    ) -> float:
        """Get calibrated confidence for an agent action.

        Args:
            agent: Agent name
            action: Type of action
            raw_confidence: Original confidence estimate

        Returns:
            Calibrated confidence (0.0 to 1.0)
        """
        cal = self.calibrations.get(agent)
        if not cal:
            return raw_confidence

        factor = cal.get_adjustment_factor(action)
        calibrated = raw_confidence * factor

        # Clamp to valid range
        return max(0.0, min(1.0, calibrated))

    def get_agent_summary(self, agent_name: str) -> dict[str, Any]:
        """Get summary of an agent's calibration state.

        Args:
            agent_name: Name of the agent

        Returns:
            Dictionary with calibration summary
        """
        cal = self.calibrations.get(agent_name)
        if not cal:
            return {"agent": agent_name, "status": "no_data"}

        return {
            "agent": agent_name,
            "total_actions": cal.total_actions,
            "mean_confidence": cal.mean_confidence,
            "mean_quality": cal.mean_quality,
            "calibration_error": cal.calibration_error,
            "overconfidence_bias": cal.overconfidence_bias,
            "is_overconfident": cal.overconfidence_bias > 0.1,
            "is_underconfident": cal.overconfidence_bias < -0.1,
            "action_type_factors": {k.value: v for k, v in cal.action_type_factors.items()},
            "last_updated": cal.last_updated.isoformat(),
        }

    async def batch_update(self, min_trajectories: int | None = None) -> int:
        """Run batch update on buffered trajectories.

        Args:
            min_trajectories: Minimum trajectories required (uses config default)

        Returns:
            Number of trajectories processed
        """
        min_t = min_trajectories or self.config.min_trajectories_for_update

        if len(self.buffer) < min_t:
            logger.info(
                "Not enough trajectories for batch update (%s < %s)", len(self.buffer), min_t
            )
            return 0

        # Evaluate recent trajectories
        recent = self.buffer.get_recent(min_t)
        all_insights = []

        for trajectory in recent:
            insights = await self.evaluate_trajectory(trajectory)
            all_insights.extend(insights)

        # Update calibration
        self.update_calibration(all_insights)

        return len(recent)

    def save(self, path: Path) -> None:
        """Save learner state to disk.

        Args:
            path: Directory to save to
        """
        path.mkdir(parents=True, exist_ok=True)

        # Save calibrations
        cal_data = {}
        for name, cal in self.calibrations.items():
            cal_data[name] = {
                "agent_name": cal.agent_name,
                "total_actions": cal.total_actions,
                "mean_confidence": cal.mean_confidence,
                "mean_quality": cal.mean_quality,
                "calibration_error": cal.calibration_error,
                "overconfidence_bias": cal.overconfidence_bias,
                "action_type_factors": {k.value: v for k, v in cal.action_type_factors.items()},
                "last_updated": cal.last_updated.isoformat(),
            }

        with open(path / "calibrations.json", "w") as f:
            json.dump(cal_data, f, indent=2)

    def load(self, path: Path) -> None:
        """Load learner state from disk.

        Args:
            path: Directory to load from
        """
        cal_file = path / "calibrations.json"
        if not cal_file.exists():
            return

        with open(cal_file) as f:
            cal_data = json.load(f)

        for name, data in cal_data.items():
            cal = AgentCalibration(
                agent_name=data["agent_name"],
                total_actions=data["total_actions"],
                mean_confidence=data["mean_confidence"],
                mean_quality=data["mean_quality"],
                calibration_error=data["calibration_error"],
                overconfidence_bias=data["overconfidence_bias"],
                last_updated=datetime.fromisoformat(data["last_updated"]),
            )
            for action_str, factor in data.get("action_type_factors", {}).items():
                try:
                    action_type = ActionType(action_str)
                    cal.action_type_factors[action_type] = factor
                except ValueError as e:
                    logger.debug("load encountered an error: %s", e)
            self.calibrations[name] = cal
