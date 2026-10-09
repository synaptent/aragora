"""
Agent Auto-Scaling for Control Plane.

Provides dynamic agent capacity management based on:
- Queue depth and wait times
- Agent health and utilization
- P99 latency thresholds
- Provider-specific capacity limits

Usage:
    from aragora.control_plane.auto_scaling import (
        AutoScaler,
        ScalingPolicy,
        ScalingDecision,
    )

    scaler = AutoScaler(
        registry=agent_registry,
        scheduler=task_scheduler,
        policy=ScalingPolicy.default(),
    )

    # Start auto-scaling loop
    await scaler.start()

    # Or evaluate manually
    decision = await scaler.evaluate()
    if decision.should_scale:
        await scaler.apply(decision)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

from aragora.observability import get_logger

if TYPE_CHECKING:
    from aragora.control_plane.registry import AgentRegistry
    from aragora.control_plane.scheduler import TaskScheduler
    from aragora.control_plane.health import HealthMonitor

logger = get_logger(__name__)


class ScalingDirection(Enum):
    """Direction of scaling action."""

    SCALE_UP = "scale_up"
    SCALE_DOWN = "scale_down"
    NONE = "none"


class ScalingReason(Enum):
    """Reason for scaling decision."""

    QUEUE_DEPTH = "queue_depth"
    LATENCY = "latency"
    UTILIZATION = "utilization"
    AGENT_EXHAUSTION = "agent_exhaustion"
    IDLE_AGENTS = "idle_agents"
    COST_OPTIMIZATION = "cost_optimization"
    MANUAL = "manual"


@dataclass
class ScalingPolicy:
    """Configuration for auto-scaling behavior."""

    # Scale-up thresholds
    queue_depth_threshold: int = 10  # Scale up if queue > N tasks
    latency_p99_threshold_ms: float = 5000.0  # Scale up if p99 > 5s
    utilization_threshold: float = 0.8  # Scale up if utilization > 80%
    agent_exhaustion_threshold: float = 0.9  # Scale up if 90% agents busy

    # Scale-down thresholds
    idle_time_threshold_seconds: float = 300.0  # Scale down after 5 min idle
    min_utilization_for_scale_down: float = 0.3  # Scale down if < 30% utilization
    queue_empty_duration_seconds: float = 180.0  # Scale down after 3 min empty queue

    # Capacity limits
    min_agents: int = 1
    max_agents: int = 20
    max_agents_per_provider: dict[str, int] = field(
        default_factory=lambda: {
            "anthropic": 10,
            "openai": 10,
            "openrouter": 15,
            "mistral": 5,
        }
    )

    # Scaling behavior
    scale_up_increment: int = 2  # Add N agents at a time
    scale_down_increment: int = 1  # Remove N agents at a time
    cooldown_seconds: float = 60.0  # Wait between scaling actions
    evaluation_interval_seconds: float = 30.0  # How often to evaluate

    # Provider preferences for scaling
    scale_up_provider_priority: list[str] = field(
        default_factory=lambda: ["anthropic", "openai", "mistral", "openrouter"]
    )
    scale_down_provider_priority: list[str] = field(
        default_factory=lambda: ["openrouter", "mistral", "openai", "anthropic"]
    )

    @classmethod
    def default(cls) -> ScalingPolicy:
        """Create default scaling policy."""
        return cls()

    @classmethod
    def aggressive(cls) -> ScalingPolicy:
        """Create aggressive scaling policy (faster reactions)."""
        return cls(
            queue_depth_threshold=5,
            latency_p99_threshold_ms=2000.0,
            utilization_threshold=0.7,
            scale_up_increment=3,
            cooldown_seconds=30.0,
            evaluation_interval_seconds=15.0,
        )

    @classmethod
    def conservative(cls) -> ScalingPolicy:
        """Create conservative scaling policy (slower reactions, cost-focused)."""
        return cls(
            queue_depth_threshold=20,
            latency_p99_threshold_ms=10000.0,
            utilization_threshold=0.9,
            scale_up_increment=1,
            cooldown_seconds=120.0,
            idle_time_threshold_seconds=600.0,
        )


@dataclass
class ScalingMetrics:
    """Current metrics used for scaling decisions."""

    queue_depth: int = 0
    pending_tasks: int = 0
    running_tasks: int = 0
    total_agents: int = 0
    available_agents: int = 0
    busy_agents: int = 0
    utilization: float = 0.0  # busy / total
    latency_p99_ms: float = 0.0
    avg_wait_time_seconds: float = 0.0
    queue_empty_duration_seconds: float = 0.0
    agents_by_provider: dict[str, int] = field(default_factory=dict)

    @property
    def agent_exhaustion_ratio(self) -> float:
        """Calculate ratio of busy agents to total agents."""
        if self.total_agents == 0:
            return 1.0  # No agents = exhausted
        return self.busy_agents / self.total_agents


@dataclass
class ScalingDecision:
    """Result of scaling evaluation."""

    direction: ScalingDirection
    reason: ScalingReason
    recommended_delta: int  # Positive for scale-up, negative for scale-down
    target_provider: str | None = None
    confidence: float = 0.0  # 0-1, how confident in this decision
    metrics: ScalingMetrics | None = None
    explanation: str = ""

    @property
    def should_scale(self) -> bool:
        """Check if scaling action is recommended."""
        return self.direction != ScalingDirection.NONE and self.recommended_delta != 0


# Type for scale-up/down callbacks
ScalingCallback = Callable[[ScalingDecision], "asyncio.Future[bool]"]


class AutoScaler:
    """
    Manages dynamic agent scaling based on workload.

    Monitors queue depth, latency, and agent utilization to make
    scaling decisions. Integrates with agent registry and scheduler.
    """

    def __init__(
        self,
        registry: AgentRegistry | None = None,
        scheduler: TaskScheduler | None = None,
        health_monitor: HealthMonitor | None = None,
        policy: ScalingPolicy | None = None,
        scale_up_callback: ScalingCallback | None = None,
        scale_down_callback: ScalingCallback | None = None,
    ):
        """
        Initialize the auto-scaler.

        Args:
            registry: AgentRegistry for agent information
            scheduler: TaskScheduler for queue information
            health_monitor: HealthMonitor for agent health
            policy: Scaling policy configuration
            scale_up_callback: Callback to provision new agents
            scale_down_callback: Callback to deprovision agents
        """
        self._registry = registry
        self._scheduler = scheduler
        self._health_monitor = health_monitor
        self._policy = policy or ScalingPolicy.default()
        self._scale_up_callback = scale_up_callback
        self._scale_down_callback = scale_down_callback

        # State tracking
        self._last_scale_time: float = 0.0
        self._last_evaluation_time: float = 0.0
        self._queue_empty_since: float | None = None
        self._scaling_history: list[dict[str, Any]] = []
        self._max_history = 100

        # Background task
        self._running = False
        self._task: asyncio.Task | None = None

        # Metrics tracking
        self._latency_samples: list[float] = []
        self._max_latency_samples = 100

    async def start(self) -> None:
        """Start the auto-scaling loop."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._scaling_loop())
        logger.info("Auto-scaler started", policy=self._policy.__class__.__name__)

    async def stop(self) -> None:
        """Stop the auto-scaling loop."""
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass  # Expected when stopping — task was intentionally cancelled
            self._task = None

        logger.info("Auto-scaler stopped")

    async def _scaling_loop(self) -> None:
        """Background loop that evaluates scaling decisions."""
        while self._running:
            try:
                await asyncio.sleep(self._policy.evaluation_interval_seconds)

                # Evaluate current state
                decision = await self.evaluate()

                # Apply if needed and cooldown passed
                if decision.should_scale and self._cooldown_passed():
                    await self.apply(decision)

            except asyncio.CancelledError:
                break
            except (RuntimeError, ValueError, OSError):
                logger.error("Error in scaling loop iteration", exc_info=True)

    def _cooldown_passed(self) -> bool:
        """Check if cooldown period has passed since last scaling action."""
        return (time.time() - self._last_scale_time) >= self._policy.cooldown_seconds

    async def evaluate(self) -> ScalingDecision:
        """
        Evaluate current state and decide on scaling action.

        Returns:
            ScalingDecision with recommended action
        """
        self._last_evaluation_time = time.time()

        # Collect current metrics
        metrics = await self._collect_metrics()

        # Check for scale-up conditions (in priority order)
        decision = self._check_scale_up(metrics)
        if decision.should_scale:
            return decision

        # Check for scale-down conditions
        decision = self._check_scale_down(metrics)
        if decision.should_scale:
            return decision

        # No scaling needed
        return ScalingDecision(
            direction=ScalingDirection.NONE,
            reason=ScalingReason.MANUAL,
            recommended_delta=0,
            metrics=metrics,
            explanation="No scaling action needed",
        )

    async def _collect_metrics(self) -> ScalingMetrics:
        """Collect current metrics for scaling decisions."""
        metrics = ScalingMetrics()

        # Get scheduler stats
        if self._scheduler:
            try:
                stats = await self._scheduler.get_stats()
                metrics.queue_depth = stats.get("pending_tasks", 0)
                metrics.pending_tasks = stats.get("pending_tasks", 0)
                metrics.running_tasks = stats.get("running_tasks", 0)
            except (OSError, ConnectionError, RuntimeError) as e:
                logger.warning("Failed to get scheduler stats: %s", e)

        # Get registry stats
        if self._registry:
            try:
                stats = await self._registry.get_stats()
                metrics.total_agents = stats.get("total_agents", 0)
                metrics.available_agents = stats.get("available_agents", 0)
                metrics.busy_agents = stats.get("busy_agents", 0)
                metrics.agents_by_provider = stats.get("by_provider", {})

                if metrics.total_agents > 0:
                    metrics.utilization = metrics.busy_agents / metrics.total_agents
            except (OSError, ConnectionError, RuntimeError) as e:
                logger.warning("Failed to get registry stats: %s", e)

        # Calculate p99 latency from samples
        if self._latency_samples:
            sorted_samples = sorted(self._latency_samples)
            p99_index = int(len(sorted_samples) * 0.99)
            metrics.latency_p99_ms = sorted_samples[min(p99_index, len(sorted_samples) - 1)]

        # Track queue empty duration
        if metrics.queue_depth == 0:
            if self._queue_empty_since is None:
                self._queue_empty_since = time.time()
            metrics.queue_empty_duration_seconds = time.time() - self._queue_empty_since
        else:
            self._queue_empty_since = None
            metrics.queue_empty_duration_seconds = 0.0

        return metrics

    def _check_scale_up(self, metrics: ScalingMetrics) -> ScalingDecision:
        """Check if scale-up is needed."""
        policy = self._policy

        # Already at max capacity?
        if metrics.total_agents >= policy.max_agents:
            return ScalingDecision(
                direction=ScalingDirection.NONE,
                reason=ScalingReason.MANUAL,
                recommended_delta=0,
                metrics=metrics,
                explanation=f"Already at max capacity ({policy.max_agents} agents)",
            )

        # Check agent exhaustion (highest priority)
        if metrics.agent_exhaustion_ratio >= policy.agent_exhaustion_threshold:
            delta = min(
                policy.scale_up_increment,
                policy.max_agents - metrics.total_agents,
            )
            provider = self._select_provider_for_scale_up(metrics)

            return ScalingDecision(
                direction=ScalingDirection.SCALE_UP,
                reason=ScalingReason.AGENT_EXHAUSTION,
                recommended_delta=delta,
                target_provider=provider,
                confidence=0.9,
                metrics=metrics,
                explanation=f"Agent exhaustion at {metrics.agent_exhaustion_ratio:.1%}",
            )

        # Check queue depth
        if metrics.queue_depth > policy.queue_depth_threshold:
            delta = min(
                policy.scale_up_increment,
                policy.max_agents - metrics.total_agents,
            )
            provider = self._select_provider_for_scale_up(metrics)

            return ScalingDecision(
                direction=ScalingDirection.SCALE_UP,
                reason=ScalingReason.QUEUE_DEPTH,
                recommended_delta=delta,
                target_provider=provider,
                confidence=0.8,
                metrics=metrics,
                explanation=f"Queue depth {metrics.queue_depth} > threshold {policy.queue_depth_threshold}",
            )

        # Check latency
        if metrics.latency_p99_ms > policy.latency_p99_threshold_ms:
            delta = min(
                policy.scale_up_increment,
                policy.max_agents - metrics.total_agents,
            )
            provider = self._select_provider_for_scale_up(metrics)

            return ScalingDecision(
                direction=ScalingDirection.SCALE_UP,
                reason=ScalingReason.LATENCY,
                recommended_delta=delta,
                target_provider=provider,
                confidence=0.7,
                metrics=metrics,
                explanation=f"P99 latency {metrics.latency_p99_ms:.0f}ms > threshold {policy.latency_p99_threshold_ms:.0f}ms",
            )

        # Check utilization
        if metrics.utilization > policy.utilization_threshold:
            delta = min(
                policy.scale_up_increment,
                policy.max_agents - metrics.total_agents,
            )
            provider = self._select_provider_for_scale_up(metrics)

            return ScalingDecision(
                direction=ScalingDirection.SCALE_UP,
                reason=ScalingReason.UTILIZATION,
                recommended_delta=delta,
                target_provider=provider,
                confidence=0.6,
                metrics=metrics,
                explanation=f"Utilization {metrics.utilization:.1%} > threshold {policy.utilization_threshold:.1%}",
            )

        # No scale-up needed
        return ScalingDecision(
            direction=ScalingDirection.NONE,
            reason=ScalingReason.MANUAL,
            recommended_delta=0,
            metrics=metrics,
        )

    def _check_scale_down(self, metrics: ScalingMetrics) -> ScalingDecision:
        """Check if scale-down is needed."""
        policy = self._policy

        # Already at min capacity?
        if metrics.total_agents <= policy.min_agents:
            return ScalingDecision(
                direction=ScalingDirection.NONE,
                reason=ScalingReason.MANUAL,
                recommended_delta=0,
                metrics=metrics,
                explanation=f"Already at min capacity ({policy.min_agents} agents)",
            )

        # Check idle agents (queue empty for a while)
        if metrics.queue_empty_duration_seconds > policy.queue_empty_duration_seconds:
            delta = min(
                policy.scale_down_increment,
                metrics.total_agents - policy.min_agents,
            )
            provider = self._select_provider_for_scale_down(metrics)

            return ScalingDecision(
                direction=ScalingDirection.SCALE_DOWN,
                reason=ScalingReason.IDLE_AGENTS,
                recommended_delta=-delta,
                target_provider=provider,
                confidence=0.8,
                metrics=metrics,
                explanation=f"Queue empty for {metrics.queue_empty_duration_seconds:.0f}s",
            )

        # Check low utilization
        if metrics.utilization < policy.min_utilization_for_scale_down:
            delta = min(
                policy.scale_down_increment,
                metrics.total_agents - policy.min_agents,
            )
            provider = self._select_provider_for_scale_down(metrics)

            return ScalingDecision(
                direction=ScalingDirection.SCALE_DOWN,
                reason=ScalingReason.COST_OPTIMIZATION,
                recommended_delta=-delta,
                target_provider=provider,
                confidence=0.6,
                metrics=metrics,
                explanation=f"Low utilization {metrics.utilization:.1%} < threshold {policy.min_utilization_for_scale_down:.1%}",
            )

        # No scale-down needed
        return ScalingDecision(
            direction=ScalingDirection.NONE,
            reason=ScalingReason.MANUAL,
            recommended_delta=0,
            metrics=metrics,
        )

    def _select_provider_for_scale_up(self, metrics: ScalingMetrics) -> str | None:
        """Select which provider to scale up."""
        for provider in self._policy.scale_up_provider_priority:
            current = metrics.agents_by_provider.get(provider, 0)
            max_for_provider = self._policy.max_agents_per_provider.get(provider, 5)

            if current < max_for_provider:
                return provider

        return None

    def _select_provider_for_scale_down(self, metrics: ScalingMetrics) -> str | None:
        """Select which provider to scale down."""
        for provider in self._policy.scale_down_provider_priority:
            current = metrics.agents_by_provider.get(provider, 0)

            if current > 0:
                return provider

        return None

    async def apply(self, decision: ScalingDecision) -> bool:
        """
        Apply a scaling decision.

        Args:
            decision: ScalingDecision to apply

        Returns:
            True if scaling was applied successfully
        """
        if not decision.should_scale:
            return True

        logger.info(
            "Applying scaling decision",
            direction=decision.direction.value,
            delta=decision.recommended_delta,
            provider=decision.target_provider,
            reason=decision.reason.value,
        )

        success = False

        try:
            if decision.direction == ScalingDirection.SCALE_UP:
                if self._scale_up_callback:
                    success = await self._scale_up_callback(decision)
                else:
                    logger.warning("No scale-up callback configured")
                    success = True  # Assume success for simulation

            elif decision.direction == ScalingDirection.SCALE_DOWN:
                if self._scale_down_callback:
                    success = await self._scale_down_callback(decision)
                else:
                    logger.warning("No scale-down callback configured")
                    success = True  # Assume success for simulation

            if success:
                self._last_scale_time = time.time()
                self._record_scaling_action(decision)

        except (RuntimeError, ValueError, OSError) as e:
            logger.error("Failed to apply scaling decision: %s", e)
            success = False

        return success

    def _record_scaling_action(self, decision: ScalingDecision) -> None:
        """Record scaling action for history."""
        self._scaling_history.append(
            {
                "timestamp": time.time(),
                "direction": decision.direction.value,
                "reason": decision.reason.value,
                "delta": decision.recommended_delta,
                "provider": decision.target_provider,
                "confidence": decision.confidence,
            }
        )

        # Trim history
        if len(self._scaling_history) > self._max_history:
            self._scaling_history = self._scaling_history[-self._max_history :]

    def record_latency(self, latency_ms: float) -> None:
        """Record a latency sample for p99 calculation."""
        self._latency_samples.append(latency_ms)

        # Trim samples
        if len(self._latency_samples) > self._max_latency_samples:
            self._latency_samples = self._latency_samples[-self._max_latency_samples :]

    def get_stats(self) -> dict[str, Any]:
        """Get auto-scaler statistics."""
        return {
            "running": self._running,
            "last_scale_time": self._last_scale_time,
            "last_evaluation_time": self._last_evaluation_time,
            "cooldown_remaining": max(
                0,
                self._policy.cooldown_seconds - (time.time() - self._last_scale_time),
            ),
            "scaling_history": self._scaling_history[-10:],
            "total_scaling_actions": len(self._scaling_history),
            "policy": {
                "queue_depth_threshold": self._policy.queue_depth_threshold,
                "latency_p99_threshold_ms": self._policy.latency_p99_threshold_ms,
                "utilization_threshold": self._policy.utilization_threshold,
                "min_agents": self._policy.min_agents,
                "max_agents": self._policy.max_agents,
            },
        }

    @property
    def policy(self) -> ScalingPolicy:
        """Get the current scaling policy."""
        return self._policy

    def set_policy(self, policy: ScalingPolicy) -> None:
        """Update the scaling policy."""
        self._policy = policy
        logger.info("Scaling policy updated")


# Module-level singleton
_auto_scaler: AutoScaler | None = None


def get_auto_scaler() -> AutoScaler | None:
    """Get the global auto-scaler instance."""
    return _auto_scaler


def set_auto_scaler(scaler: AutoScaler) -> None:
    """Set the global auto-scaler instance."""
    global _auto_scaler
    _auto_scaler = scaler


def init_auto_scaler(
    registry: AgentRegistry | None = None,
    scheduler: TaskScheduler | None = None,
    health_monitor: HealthMonitor | None = None,
    policy: ScalingPolicy | None = None,
) -> AutoScaler:
    """Initialize and set the global auto-scaler."""
    scaler = AutoScaler(
        registry=registry,
        scheduler=scheduler,
        health_monitor=health_monitor,
        policy=policy,
    )
    set_auto_scaler(scaler)
    return scaler


__all__ = [
    "ScalingDirection",
    "ScalingReason",
    "ScalingPolicy",
    "ScalingMetrics",
    "ScalingDecision",
    "AutoScaler",
    "get_auto_scaler",
    "set_auto_scaler",
    "init_auto_scaler",
]
