"""
Arena-Fabric integration for high-scale agent orchestration.

This module provides the bridge between Arena (debate orchestration) and
AgentFabric (agent lifecycle, scheduling, policy, budget). It enables
debates to run with fabric-managed agents while maintaining backwards
compatibility with direct agent lists.

Usage:
    from aragora.fabric import AgentFabric
    from aragora.debate.fabric_integration import FabricDebateRunner

    async with AgentFabric() as fabric:
        # Create a debate agent pool
        pool = await fabric.create_pool("debate-agents", "claude-opus-4", min_agents=3)

        # Run a debate through the fabric
        runner = FabricDebateRunner(fabric)
        result = await runner.run_debate(
            environment=Environment(task="Design a rate limiter"),
            pool_id=pool.id,
        )
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, cast
from uuid import uuid4

from aragora.config import DEFAULT_CONSENSUS, DEFAULT_ROUNDS
from aragora.debate.config.defaults import DEBATE_DEFAULTS

from aragora.fabric.models import (
    Policy,
    PolicyContext,
    PolicyEffect,
    PolicyRule,
    Priority,
    Task,
    TaskHandle,
    Usage,
)

if TYPE_CHECKING:
    from aragora.core import Agent
    from aragora.core_types import DebateResult, Environment
    from aragora.protocols.debate import DebateProtocol
    from aragora.fabric import AgentFabric

logger = logging.getLogger(__name__)

FABRIC_DEFAULT_MAX_AGENTS = DEBATE_DEFAULTS.max_agents_per_debate


@dataclass
class FabricDebateConfig:
    """Configuration for fabric-managed debates."""

    pool_id: str  # Agent pool to use for this debate
    policy_ids: list[str] = field(default_factory=list)  # Additional policies to enforce
    budget_per_debate_usd: float | None = None  # Per-debate budget cap
    priority: Priority = Priority.NORMAL  # Task priority for scheduling
    timeout_seconds: float = 600.0  # Maximum debate duration
    min_agents: int = DEBATE_DEFAULTS.min_agents_per_debate
    max_agents: int = FABRIC_DEFAULT_MAX_AGENTS

    # Policy settings
    require_policy_check: bool = True  # Check policy before starting
    fail_on_budget_exceeded: bool = True  # Fail if budget would be exceeded

    # Metadata
    org_id: str = ""
    user_id: str = ""
    workspace_id: str = ""
    metadata: dict[str, str] = field(default_factory=dict)


class FabricUsageTracker:
    """
    Tracks debate usage through the fabric budget system.

    This adapter connects Arena's usage tracking to AgentFabric's
    budget management, enabling per-debate cost tracking and
    budget enforcement.
    """

    def __init__(
        self,
        fabric: AgentFabric,
        entity_id: str,
        debate_id: str = "",
        budget_limit_usd: float | None = None,
    ):
        self.fabric = fabric
        self.entity_id = entity_id
        self.debate_id = debate_id
        self.budget_limit_usd = budget_limit_usd
        self._total_cost = 0.0
        self._total_tokens = 0
        self._per_agent: dict[str, dict[str, float]] = {}

    async def track(
        self,
        tokens_input: int,
        tokens_output: int,
        cost_usd: float,
        agent_id: str,
        model: str = "",
    ) -> bool:
        """
        Track usage for a single agent operation.

        Args:
            tokens_input: Input tokens used
            tokens_output: Output tokens generated
            cost_usd: Cost in USD
            agent_id: Agent that performed the operation
            model: Model used (optional)

        Returns:
            True if within budget, False if budget exceeded
        """
        # Update local tracking
        self._total_cost += cost_usd
        self._total_tokens += tokens_input + tokens_output

        if agent_id not in self._per_agent:
            self._per_agent[agent_id] = {"cost": 0.0, "tokens": 0}
        self._per_agent[agent_id]["cost"] += cost_usd
        self._per_agent[agent_id]["tokens"] += tokens_input + tokens_output

        # Track through fabric
        usage = Usage(
            agent_id=agent_id,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            cost_usd=cost_usd,
            model=model,
            task_id=self.debate_id,
        )

        status = await self.fabric.track_usage(usage)

        # Check budget limit
        if self.budget_limit_usd and self._total_cost > self.budget_limit_usd:
            logger.warning(
                "Debate %s exceeded budget: $%.4f > $%.4f",
                self.debate_id,
                self._total_cost,
                self.budget_limit_usd,
            )
            return False

        return not status.over_limit

    @property
    def total_cost(self) -> float:
        """Total cost for this debate."""
        return self._total_cost

    @property
    def total_tokens(self) -> int:
        """Total tokens used in this debate."""
        return self._total_tokens

    @property
    def per_agent_cost(self) -> dict[str, float]:
        """Cost breakdown by agent."""
        return {k: v["cost"] for k, v in self._per_agent.items()}


class FabricAgentAdapter:
    """
    Adapts fabric-managed agents to the Agent protocol expected by Arena.

    This wrapper allows fabric agents to be used seamlessly with Arena
    while routing operations through the fabric scheduler.
    """

    def __init__(
        self,
        fabric: AgentFabric,
        agent_id: str,
        model: str,
        usage_tracker: FabricUsageTracker | None = None,
    ):
        self.fabric = fabric
        self.agent_id = agent_id
        self.model = model
        self.name = agent_id  # Arena expects 'name' attribute
        self.usage_tracker = usage_tracker
        self._generate_count = 0

    async def generate(self, prompt: str, **kwargs: Any) -> str:
        """
        Generate a response via the fabric.

        This routes the generation through fabric for:
        - Policy checks
        - Budget tracking
        - Task scheduling
        """
        self._generate_count += 1

        # Check policy before generation
        context = PolicyContext(
            agent_id=self.agent_id,
            action="generate",
            resource="llm",
            attributes={"prompt_length": len(prompt), "model": self.model},
        )
        decision = await self.fabric.check_policy("agent.generate", context)
        if not decision.allowed:
            raise PermissionError(f"Policy denied generation: {decision.reason}")

        # Check budget
        estimated_tokens = len(prompt) // 4  # Rough estimate
        can_proceed, status = await self.fabric.check_budget(
            self.agent_id,
            estimated_tokens=estimated_tokens * 2,  # Input + output estimate
        )
        if not can_proceed:
            raise RuntimeError(f"Budget exceeded for agent {self.agent_id}")

        # Create generation task
        task = Task(
            id=f"gen-{self.agent_id}-{self._generate_count}",
            type="llm_generate",
            payload={"prompt": prompt, "model": self.model, **kwargs},
        )

        # Schedule through fabric
        handle = await self.fabric.schedule(task, self.agent_id)

        # Execute generation (actual LLM call would happen here)
        # For now, we're wrapping the existing agent implementation
        start_time = time.time()
        try:
            # Get the underlying agent from fabric lifecycle
            agent_handle = await self.fabric.get_agent(self.agent_id)
            if not agent_handle:
                raise RuntimeError(f"Agent {self.agent_id} not found")

            # The actual generation is done by the underlying agent
            # This is a placeholder - real implementation would use the model
            result = f"[Fabric-managed response from {self.agent_id}]"

            # Track usage if tracker available
            if self.usage_tracker:
                tokens_in = len(prompt) // 4
                tokens_out = len(result) // 4
                cost = (tokens_in * 0.000015) + (tokens_out * 0.000060)  # Rough pricing
                await self.usage_tracker.track(
                    tokens_input=tokens_in,
                    tokens_output=tokens_out,
                    cost_usd=cost,
                    agent_id=self.agent_id,
                    model=self.model,
                )

            duration = time.time() - start_time
            await self.fabric.complete_task(handle.task_id, result=result)

            logger.debug("Agent %s generated response in %.2fs", self.agent_id, duration)
            return result

        except (RuntimeError, ValueError, TypeError, OSError, ConnectionError, TimeoutError) as e:
            logger.warning("Agent %s generation failed: %s", self.agent_id, e)
            await self.fabric.complete_task(handle.task_id, error=f"agent_error:{type(e).__name__}")
            raise


class FabricDebateRunner:
    """
    Runs debates through the Agent Fabric.

    This is the main entry point for fabric-managed debates. It:
    1. Gets agents from the specified pool
    2. Checks policies before starting
    3. Creates Arena with fabric agents
    4. Tracks costs through fabric budget
    5. Reports task completion to fabric
    """

    def __init__(self, fabric: AgentFabric):
        self.fabric = fabric
        self._active_debates: dict[str, TaskHandle] = {}

    async def run_debate(
        self,
        environment: Environment,
        pool_id: str,
        protocol: DebateProtocol | None = None,
        config: FabricDebateConfig | None = None,
    ) -> DebateResult:
        """
        Run a debate using fabric-managed agents.

        Args:
            environment: The debate environment (task, context, etc.)
            pool_id: ID of the agent pool to use
            protocol: Optional debate protocol
            config: Optional fabric-specific configuration

        Returns:
            DebateResult from the completed debate

        Raises:
            PermissionError: If policy denies the debate
            RuntimeError: If pool has insufficient agents or budget exceeded
            TimeoutError: If debate exceeds timeout
        """
        from aragora.debate.orchestrator import Arena
        from aragora.protocols.debate import DebateProtocol

        config = config or FabricDebateConfig(pool_id=pool_id)
        debate_id = f"debate-{uuid4().hex[:8]}"

        # 1. Get pool and validate
        pool = await self.fabric.get_pool(pool_id)
        if not pool:
            raise ValueError(f"Pool {pool_id} not found")

        if len(pool.current_agents) < config.min_agents:
            raise RuntimeError(
                f"Pool {pool_id} has {len(pool.current_agents)} agents, "
                f"minimum required: {config.min_agents}"
            )

        # 2. Check policy before starting
        if config.require_policy_check:
            context = PolicyContext(
                agent_id=pool_id,
                user_id=config.user_id,
                tenant_id=config.org_id,
                workspace_id=config.workspace_id,
                action="start_debate",
                resource="arena",
                attributes={
                    "task": environment.task[:100],
                    "agent_count": len(pool.current_agents),
                },
            )
            decision = await self.fabric.check_policy("debate.start", context)
            if not decision.allowed:
                raise PermissionError(f"Policy denied debate start: {decision.reason}")

        # 3. Create debate task for tracking
        task = Task(
            id=debate_id,
            type="debate",
            payload={
                "task": environment.task,
                "pool_id": pool_id,
            },
            timeout_seconds=config.timeout_seconds,
            metadata={
                "org_id": config.org_id,
                "user_id": config.user_id,
                **config.metadata,
            },
        )

        # Schedule as a task (uses first agent in pool as primary)
        primary_agent = pool.current_agents[0] if pool.current_agents else pool_id
        handle = await self.fabric.schedule(
            task,
            primary_agent,
            priority=config.priority,
        )
        self._active_debates[debate_id] = handle

        # 4. Create usage tracker
        usage_tracker = FabricUsageTracker(
            fabric=self.fabric,
            entity_id=pool_id,
            debate_id=debate_id,
            budget_limit_usd=config.budget_per_debate_usd,
        )

        # 5. Create fabric-adapted agents
        agents = []
        for agent_id in pool.current_agents[: config.max_agents]:
            adapter = FabricAgentAdapter(
                fabric=self.fabric,
                agent_id=agent_id,
                model=pool.model,
                usage_tracker=usage_tracker,
            )
            agents.append(adapter)

        # 6. Create and run Arena
        consensus_type = cast(
            Literal[
                "majority",
                "unanimous",
                "judge",
                "none",
                "weighted",
                "supermajority",
                "any",
                "byzantine",
            ],
            DEFAULT_CONSENSUS,
        )
        arena_protocol = protocol or DebateProtocol(
            rounds=DEFAULT_ROUNDS,
            consensus=consensus_type,
        )

        try:
            arena = Arena(
                environment=environment,
                agents=cast(list["Agent"], agents),
                protocol=arena_protocol,
                org_id=config.org_id,
                user_id=config.user_id,
            )

            # Run with timeout
            result = await asyncio.wait_for(
                arena.run(),
                timeout=config.timeout_seconds,
            )

            # Add fabric metadata to result
            result.total_cost_usd = usage_tracker.total_cost
            result.total_tokens = usage_tracker.total_tokens
            result.per_agent_cost = usage_tracker.per_agent_cost
            result.budget_limit_usd = config.budget_per_debate_usd

            # Complete task successfully
            await self.fabric.complete_task(handle.task_id, result=result)

            logger.info(
                "Debate %s completed: confidence=%.2f, cost=$%.4f",
                debate_id,
                result.confidence,
                result.total_cost_usd,
            )

            return result

        except asyncio.TimeoutError:
            await self.fabric.complete_task(
                handle.task_id, error=f"Debate timeout after {config.timeout_seconds}s"
            )
            raise TimeoutError(f"Debate {debate_id} exceeded timeout")

        except (
            RuntimeError,
            ValueError,
            TypeError,
            OSError,
            ConnectionError,
            PermissionError,
        ) as e:
            logger.exception("Debate %s failed: %s", debate_id, e)
            await self.fabric.complete_task(
                handle.task_id, error=f"debate_failed:{type(e).__name__}"
            )
            raise

        finally:
            self._active_debates.pop(debate_id, None)

    async def get_active_debates(self) -> list[str]:
        """Get list of active debate IDs."""
        return list(self._active_debates.keys())

    async def cancel_debate(self, debate_id: str) -> bool:
        """Cancel an active debate."""
        if debate_id in self._active_debates:
            handle = self._active_debates[debate_id]
            return await self.fabric.cancel_task(handle.task_id)
        return False


def create_debate_policy(
    name: str = "default-debate-policy",
    max_agents: int = FABRIC_DEFAULT_MAX_AGENTS,
    max_cost_per_debate: float = 10.0,
    allowed_models: list[str] | None = None,
) -> Policy:
    """
    Create a standard policy for debate operations.

    Args:
        name: Policy name
        max_agents: Maximum agents per debate
        max_cost_per_debate: Maximum cost per debate in USD
        allowed_models: List of allowed model names (None = all)

    Returns:
        Policy configured for debate operations
    """
    rules = [
        # Allow debate start
        PolicyRule(
            action_pattern="debate.start",
            effect=PolicyEffect.ALLOW,
            conditions={"max_agent_count": max_agents},
            description=f"Allow debates with up to {max_agents} agents",
        ),
        # Allow agent generation
        PolicyRule(
            action_pattern="agent.generate",
            effect=PolicyEffect.ALLOW,
            description="Allow agent text generation",
        ),
    ]

    if allowed_models:
        rules.append(
            PolicyRule(
                action_pattern="agent.generate",
                effect=PolicyEffect.DENY,
                conditions={"model_not_in": allowed_models},
                description=f"Only allow models: {', '.join(allowed_models)}",
            )
        )

    return Policy(
        id=f"policy-{uuid4().hex[:8]}",
        name=name,
        rules=rules,
        priority=10,
        metadata={
            "max_cost_per_debate": str(max_cost_per_debate),
            "type": "debate",
        },
    )


# Register debate executor with fabric
async def register_debate_executor(fabric: AgentFabric) -> None:
    """
    Register the debate task executor with the fabric.

    This enables fabric to handle "debate" type tasks through
    the FabricDebateRunner.
    """
    runner = FabricDebateRunner(fabric)

    async def execute_debate(task: Task, agent_handle: Any) -> Any:
        """Execute a debate task."""
        from aragora.core_types import Environment

        env = Environment(task=task.payload.get("task", ""))
        pool_id = task.payload.get("pool_id")

        if not pool_id:
            raise ValueError("pool_id required in task payload")

        config = FabricDebateConfig(
            pool_id=pool_id,
            timeout_seconds=task.timeout_seconds or 600.0,
            org_id=task.metadata.get("org_id", ""),
            user_id=task.metadata.get("user_id", ""),
        )

        return await runner.run_debate(
            environment=env,
            pool_id=pool_id,
            config=config,
        )

    fabric.register_executor("debate", execute_debate)
    logger.info("Registered debate executor with Agent Fabric")


__all__ = [
    "FabricDebateConfig",
    "FabricDebateRunner",
    "FabricUsageTracker",
    "FabricAgentAdapter",
    "create_debate_policy",
    "register_debate_executor",
]
