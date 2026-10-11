"""
Task Router - Intelligent routing of tasks to appropriate agents.

Routes tasks based on multiple strategies:
- Capability matching (which agents can handle the task)
- Cost optimization (minimize API costs)
- Latency optimization (fastest response time)
- Load balancing (distribute across available agents)

Security Model:
1. Sensitive tasks can be restricted to internal agents only
2. Routing decisions are logged for audit
3. Capability verification before routing
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from aragora.gateway.external_agents.base import (
        AgentCapability,
        ExternalAgentTask,
        BaseExternalAgentAdapter,
    )

logger = logging.getLogger(__name__)


class RoutingStrategy(str, Enum):
    """Strategy for routing tasks to agents."""

    CAPABILITY = "capability"  # Match by required capabilities
    COST = "cost"  # Optimize for lowest cost
    LATENCY = "latency"  # Optimize for fastest response
    LOAD_BALANCE = "load_balance"  # Distribute load evenly
    PRIORITY = "priority"  # Use agent priority scores
    HYBRID = "hybrid"  # Weighted combination of factors


@dataclass
class AgentMetrics:
    """Runtime metrics for an agent."""

    agent_name: str
    avg_latency_ms: float = 0.0
    success_rate: float = 1.0
    cost_per_request: float = 0.0
    current_load: int = 0
    max_concurrent: int = 10
    last_error: datetime | None = None
    error_count_24h: int = 0

    @property
    def availability_score(self) -> float:
        """Calculate availability score (0-1)."""
        if self.current_load >= self.max_concurrent:
            return 0.0
        load_factor = 1.0 - (self.current_load / self.max_concurrent)
        return load_factor * self.success_rate

    @property
    def is_available(self) -> bool:
        """Check if agent can accept new tasks."""
        return self.current_load < self.max_concurrent


@dataclass
class RoutingDecision:
    """Decision result from the router."""

    selected_agent: str
    strategy_used: RoutingStrategy
    score: float
    alternatives: list[str] = field(default_factory=list)
    reason: str = ""
    routing_time_ms: float = 0.0

    # Metadata for audit
    task_id: str | None = None
    tenant_id: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class TaskRouter:
    """
    Router for directing tasks to appropriate external agents.

    Supports multiple routing strategies and maintains agent metrics
    for intelligent routing decisions.

    Usage:
        router = TaskRouter()
        router.register_agent("openclaw", openclaw_adapter, capabilities=[...])
        router.register_agent("openhands", openhands_adapter, capabilities=[...])

        decision = await router.route(task, strategy=RoutingStrategy.HYBRID)
        result = await adapters[decision.selected_agent].execute(task)
    """

    def __init__(
        self,
        default_strategy: RoutingStrategy = RoutingStrategy.CAPABILITY,
        weights: dict[str, float] | None = None,
    ):
        self._default_strategy = default_strategy
        self._adapters: dict[str, BaseExternalAgentAdapter] = {}
        self._capabilities: dict[str, set[AgentCapability]] = {}
        self._metrics: dict[str, AgentMetrics] = {}
        self._priority: dict[str, int] = {}  # Higher = preferred

        # Weights for hybrid scoring
        self._weights = weights or {
            "capability": 0.4,
            "latency": 0.2,
            "cost": 0.2,
            "availability": 0.2,
        }

    def register_agent(
        self,
        name: str,
        adapter: BaseExternalAgentAdapter,
        capabilities: list[AgentCapability],
        priority: int = 0,
        cost_per_request: float = 0.0,
        max_concurrent: int = 10,
    ) -> None:
        """
        Register an agent with the router.

        Args:
            name: Unique agent name
            adapter: The agent adapter instance
            capabilities: List of capabilities this agent provides
            priority: Priority score (higher = preferred)
            cost_per_request: Estimated cost per request
            max_concurrent: Maximum concurrent executions
        """
        self._adapters[name] = adapter
        self._capabilities[name] = set(capabilities)
        self._priority[name] = priority
        self._metrics[name] = AgentMetrics(
            agent_name=name,
            cost_per_request=cost_per_request,
            max_concurrent=max_concurrent,
        )
        logger.info("Registered agent: %s with %s capabilities", name, len(capabilities))

    def unregister_agent(self, name: str) -> bool:
        """Unregister an agent from the router."""
        if name in self._adapters:
            del self._adapters[name]
            del self._capabilities[name]
            del self._metrics[name]
            del self._priority[name]
            logger.info("Unregistered agent: %s", name)
            return True
        return False

    def get_capable_agents(
        self,
        required_capabilities: list[AgentCapability],
    ) -> list[str]:
        """Get agents that have all required capabilities."""
        required = set(required_capabilities)
        return [name for name, caps in self._capabilities.items() if required.issubset(caps)]

    async def route(
        self,
        task: ExternalAgentTask,
        strategy: RoutingStrategy | None = None,
        exclude_agents: list[str] | None = None,
    ) -> RoutingDecision:
        """
        Route a task to the best available agent.

        Args:
            task: The task to route
            strategy: Routing strategy (defaults to router's default)
            exclude_agents: Agents to exclude from consideration

        Returns:
            RoutingDecision with selected agent and metadata
        """
        import time

        start_time = time.time()

        strategy = strategy or self._default_strategy
        exclude = set(exclude_agents or [])

        # Get capable agents
        capable = [
            name
            for name in self.get_capable_agents(task.required_capabilities)
            if name not in exclude
        ]

        if not capable:
            raise ValueError(f"No agents available for capabilities: {task.required_capabilities}")

        # Score agents based on strategy
        scores: dict[str, float] = {}
        for agent in capable:
            scores[agent] = self._score_agent(agent, task, strategy)

        # Select best agent
        selected = max(scores, key=lambda a: scores[a])
        alternatives = sorted(
            [a for a in capable if a != selected],
            key=lambda a: scores[a],
            reverse=True,
        )

        routing_time = (time.time() - start_time) * 1000

        decision = RoutingDecision(
            selected_agent=selected,
            strategy_used=strategy,
            score=scores[selected],
            alternatives=alternatives[:3],  # Top 3 alternatives
            reason=self._explain_decision(selected, scores, strategy),
            routing_time_ms=routing_time,
            task_id=task.task_id,
            tenant_id=task.tenant_id,
        )

        logger.info(
            "Routed task %s to %s (strategy=%s, score=%.3f)",
            task.task_id,
            selected,
            strategy.value,
            scores[selected],
        )

        return decision

    def _score_agent(
        self,
        agent: str,
        task: ExternalAgentTask,
        strategy: RoutingStrategy,
    ) -> float:
        """Calculate score for an agent based on strategy."""
        metrics = self._metrics[agent]

        if strategy == RoutingStrategy.CAPABILITY:
            # Score by capability match coverage
            agent_caps = self._capabilities[agent]
            required = set(task.required_capabilities)
            return len(required & agent_caps) / len(required) if required else 1.0

        elif strategy == RoutingStrategy.COST:
            # Lower cost = higher score (normalized)
            max_cost = max(m.cost_per_request for m in self._metrics.values()) or 1.0
            return 1.0 - (metrics.cost_per_request / max_cost)

        elif strategy == RoutingStrategy.LATENCY:
            # Lower latency = higher score (normalized)
            max_latency = max(m.avg_latency_ms for m in self._metrics.values()) or 1.0
            return 1.0 - (metrics.avg_latency_ms / max_latency)

        elif strategy == RoutingStrategy.LOAD_BALANCE:
            return metrics.availability_score

        elif strategy == RoutingStrategy.PRIORITY:
            max_priority = max(self._priority.values()) or 1
            return self._priority[agent] / max_priority

        elif strategy == RoutingStrategy.HYBRID:
            return self._hybrid_score(agent, task)

        return 0.5  # Default neutral score

    def _hybrid_score(
        self,
        agent: str,
        task: ExternalAgentTask,
    ) -> float:
        """Calculate weighted hybrid score across all factors."""
        scores = {
            "capability": self._score_agent(agent, task, RoutingStrategy.CAPABILITY),
            "latency": self._score_agent(agent, task, RoutingStrategy.LATENCY),
            "cost": self._score_agent(agent, task, RoutingStrategy.COST),
            "availability": self._metrics[agent].availability_score,
        }

        weighted_sum = sum(scores[factor] * self._weights.get(factor, 0) for factor in scores)
        total_weight = sum(self._weights.get(f, 0) for f in scores)

        return weighted_sum / total_weight if total_weight > 0 else 0.5

    def _explain_decision(
        self,
        selected: str,
        scores: dict[str, float],
        strategy: RoutingStrategy,
    ) -> str:
        """Generate human-readable explanation for routing decision."""
        metrics = self._metrics[selected]
        return (
            f"Selected {selected} using {strategy.value} strategy. "
            f"Score: {scores[selected]:.3f}, "
            f"Latency: {metrics.avg_latency_ms:.0f}ms, "
            f"Load: {metrics.current_load}/{metrics.max_concurrent}, "
            f"Success rate: {metrics.success_rate:.1%}"
        )

    def update_metrics(
        self,
        agent: str,
        latency_ms: float,
        success: bool,
    ) -> None:
        """Update agent metrics after execution."""
        if agent not in self._metrics:
            return

        metrics = self._metrics[agent]

        # Exponential moving average for latency
        alpha = 0.1
        metrics.avg_latency_ms = alpha * latency_ms + (1 - alpha) * metrics.avg_latency_ms

        # Update success rate
        metrics.success_rate = (
            alpha * (1.0 if success else 0.0) + (1 - alpha) * metrics.success_rate
        )

        if not success:
            metrics.last_error = datetime.now(timezone.utc)
            metrics.error_count_24h += 1

    def increment_load(self, agent: str) -> None:
        """Increment current load for an agent."""
        if agent in self._metrics:
            self._metrics[agent].current_load += 1

    def decrement_load(self, agent: str) -> None:
        """Decrement current load for an agent."""
        if agent in self._metrics:
            self._metrics[agent].current_load = max(0, self._metrics[agent].current_load - 1)

    def get_agent_status(self) -> list[dict[str, Any]]:
        """Get status of all registered agents."""
        return [
            {
                "name": name,
                "capabilities": [c.value for c in self._capabilities[name]],
                "metrics": {
                    "avg_latency_ms": metrics.avg_latency_ms,
                    "success_rate": metrics.success_rate,
                    "current_load": metrics.current_load,
                    "max_concurrent": metrics.max_concurrent,
                    "availability_score": metrics.availability_score,
                },
                "priority": self._priority[name],
            }
            for name, metrics in self._metrics.items()
        ]
