"""
Agent Registry for the Aragora Control Plane.

Provides service discovery for AI agents with:
- Heartbeat-based liveness tracking
- Capability-based agent selection
- Load balancing support
- Redis-backed persistence

The registry maintains a distributed map of all available agents,
their capabilities, and health status. Agents must send periodic
heartbeats to remain in the active pool.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from collections.abc import Sequence

# Observability
from aragora.observability import (
    get_logger,
)

# Resilience
from aragora.resilience import get_v2_circuit_breaker as get_circuit_breaker

logger = get_logger(__name__)

# Circuit breaker for Redis operations in registry
_registry_redis_cb = get_circuit_breaker("registry_redis", failure_threshold=3, cooldown_seconds=30)


class AgentStatus(Enum):
    """Agent lifecycle status."""

    STARTING = "starting"  # Agent is initializing
    READY = "ready"  # Agent is ready to accept tasks
    BUSY = "busy"  # Agent is processing a task
    DRAINING = "draining"  # Agent is completing current task, no new tasks
    OFFLINE = "offline"  # Agent is not responding
    FAILED = "failed"  # Agent has failed


class AgentCapability(Enum):
    """Standard agent capabilities."""

    DEBATE = "debate"  # Can participate in debates
    CODE = "code"  # Can write/analyze code
    ANALYSIS = "analysis"  # Can perform analysis tasks
    CRITIQUE = "critique"  # Can critique other agents' work
    JUDGE = "judge"  # Can serve as a debate judge
    IMPLEMENT = "implement"  # Can implement code changes
    DESIGN = "design"  # Can create designs/architectures
    RESEARCH = "research"  # Can perform research tasks
    AUDIT = "audit"  # Can perform audits
    SUMMARIZE = "summarize"  # Can summarize content


@dataclass
class AgentInfo:
    """
    Information about a registered agent.

    Attributes:
        agent_id: Unique identifier for the agent
        capabilities: Set of capabilities this agent provides
        status: Current agent status
        model: Underlying model (e.g., "claude-3-opus", "gpt-4")
        provider: Model provider (e.g., "anthropic", "openai")
        metadata: Additional agent metadata
        registered_at: When the agent registered
        last_heartbeat: Last heartbeat timestamp
        current_task_id: ID of task being processed (if any)
        tasks_completed: Number of tasks completed
        tasks_failed: Number of tasks failed
        avg_latency_ms: Average task completion time
        tags: Optional tags for filtering
        region_id: Primary region where agent is deployed (e.g., "us-west-2")
        available_regions: Regions where agent can accept tasks
        region_latency_ms: Average latency per region for routing decisions
        last_heartbeat_by_region: Per-region heartbeat timestamps
    """

    agent_id: str
    capabilities: set[str]
    status: AgentStatus = AgentStatus.STARTING
    model: str = "unknown"
    provider: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)
    registered_at: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)
    current_task_id: str | None = None
    tasks_completed: int = 0
    tasks_failed: int = 0
    avg_latency_ms: float = 0.0
    tags: set[str] = field(default_factory=set)
    # Regional metadata for multi-region deployments
    region_id: str = "default"
    available_regions: set[str] = field(default_factory=lambda: {"default"})
    region_latency_ms: dict[str, float] = field(default_factory=dict)
    last_heartbeat_by_region: dict[str, float] = field(default_factory=dict)
    # Blockchain identity (ERC-8004)
    blockchain_agent_id: int | None = None  # On-chain token ID if linked

    def is_available(self) -> bool:
        """Check if agent is available for new tasks."""
        return self.status == AgentStatus.READY

    def is_alive(self, timeout_seconds: float = 30.0) -> bool:
        """Check if agent has sent a heartbeat within timeout."""
        return (time.time() - self.last_heartbeat) < timeout_seconds

    def has_capability(self, capability: str | AgentCapability) -> bool:
        """Check if agent has a specific capability."""
        cap_str = capability.value if isinstance(capability, AgentCapability) else capability
        return cap_str in self.capabilities

    def has_all_capabilities(self, capabilities: Sequence[str | AgentCapability]) -> bool:
        """Check if agent has all specified capabilities."""
        return all(self.has_capability(c) for c in capabilities)

    def is_available_in_region(self, region_id: str) -> bool:
        """Check if agent is available in a specific region."""
        return region_id in self.available_regions

    def get_latency_for_region(self, region_id: str) -> float:
        """Get estimated latency for a specific region.

        Returns:
            Latency in ms, or float('inf') if region not available
        """
        if region_id not in self.available_regions:
            return float("inf")
        return self.region_latency_ms.get(region_id, self.avg_latency_ms)

    def is_alive_in_region(self, region_id: str, timeout_seconds: float = 30.0) -> bool:
        """Check if agent has sent a heartbeat from specific region within timeout."""
        last_hb = self.last_heartbeat_by_region.get(region_id, 0.0)
        return (time.time() - last_hb) < timeout_seconds

    def update_region_heartbeat(self, region_id: str) -> None:
        """Update heartbeat timestamp for a specific region."""
        now = time.time()
        self.last_heartbeat = now
        self.last_heartbeat_by_region[region_id] = now

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "agent_id": self.agent_id,
            "capabilities": list(self.capabilities),
            "status": self.status.value,
            "model": self.model,
            "provider": self.provider,
            "metadata": self.metadata,
            "registered_at": self.registered_at,
            "last_heartbeat": self.last_heartbeat,
            "current_task_id": self.current_task_id,
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "avg_latency_ms": self.avg_latency_ms,
            "tags": list(self.tags),
            # Regional fields
            "region_id": self.region_id,
            "available_regions": list(self.available_regions),
            "region_latency_ms": self.region_latency_ms,
            "last_heartbeat_by_region": self.last_heartbeat_by_region,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentInfo:
        """Deserialize from dictionary."""
        return cls(
            agent_id=data["agent_id"],
            capabilities=set(data.get("capabilities", [])),
            status=AgentStatus(data.get("status", "starting")),
            model=data.get("model", "unknown"),
            provider=data.get("provider", "unknown"),
            metadata=data.get("metadata", {}),
            registered_at=data.get("registered_at", time.time()),
            last_heartbeat=data.get("last_heartbeat", time.time()),
            current_task_id=data.get("current_task_id"),
            tasks_completed=data.get("tasks_completed", 0),
            tasks_failed=data.get("tasks_failed", 0),
            avg_latency_ms=data.get("avg_latency_ms", 0.0),
            tags=set(data.get("tags", [])),
            # Regional fields
            region_id=data.get("region_id", "default"),
            available_regions=set(data.get("available_regions", ["default"])),
            region_latency_ms=data.get("region_latency_ms", {}),
            last_heartbeat_by_region=data.get("last_heartbeat_by_region", {}),
        )


class AgentRegistry:
    """
    Redis-backed registry for agent service discovery.

    The registry maintains a hash of all registered agents and provides
    methods for registration, heartbeats, and capability-based lookups.

    Usage:
        registry = AgentRegistry(redis_url="redis://localhost:6379")
        await registry.connect()

        # Register an agent
        await registry.register(
            agent_id="claude-3",
            capabilities=["debate", "code"],
            model="claude-3-opus",
            provider="anthropic",
        )

        # Send heartbeat
        await registry.heartbeat("claude-3")

        # Find agents with capability
        agents = await registry.find_by_capability("debate")

        await registry.close()
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        key_prefix: str = "aragora:cp:agents:",
        heartbeat_timeout: float = 30.0,
        cleanup_interval: float = 60.0,
    ):
        """
        Initialize the agent registry.

        Args:
            redis_url: Redis connection URL
            key_prefix: Prefix for Redis keys
            heartbeat_timeout: Seconds before agent is considered offline
            cleanup_interval: Seconds between cleanup sweeps
        """
        self._redis_url = redis_url
        self._key_prefix = key_prefix
        self._heartbeat_timeout = heartbeat_timeout
        self._cleanup_interval = cleanup_interval
        self._redis: Any | None = None
        self._cleanup_task: asyncio.Task | None = None
        self._local_cache: dict[str, AgentInfo] = {}
        self._cache_ttl = 5.0  # Local cache TTL in seconds
        self._cache_updated_at: float = 0.0

    async def connect(self) -> None:
        """Connect to Redis and start cleanup task."""
        # Check for explicit in-memory mode via special URL
        if self._redis_url.startswith("memory://"):
            logger.info("AgentRegistry using in-memory mode (memory:// URL specified)")
            self._redis = None
            return

        # Check circuit breaker before attempting Redis connection
        if not _registry_redis_cb.can_execute():
            logger.warning("AgentRegistry Redis circuit breaker open, using in-memory fallback")
            self._redis = None
            return

        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            # Test connection
            await self._redis.ping()
            _registry_redis_cb.record_success()
            logger.info("AgentRegistry connected to Redis: %s", self._redis_url)

            # Start background cleanup task
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

        except ImportError:
            logger.warning("redis package not installed, using in-memory fallback")
            self._redis = None
        except (ConnectionError, TimeoutError, OSError, RuntimeError) as e:
            _registry_redis_cb.record_failure(e)
            logger.warning("Redis not available, using in-memory fallback: %s", e)
            self._redis = None

    async def close(self) -> None:
        """Close Redis connection and stop cleanup task."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass  # noqa: PERF203 -- expected: we just cancelled the task ourselves

        if self._redis:
            await self._redis.close()
            logger.info("AgentRegistry disconnected from Redis")

    async def register(
        self,
        agent_id: str,
        capabilities: Sequence[str | AgentCapability],
        model: str = "unknown",
        provider: str = "unknown",
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        region_id: str = "default",
        available_regions: list[str] | None = None,
    ) -> AgentInfo:
        """
        Register a new agent or update existing registration.

        Args:
            agent_id: Unique identifier for the agent
            capabilities: List of capabilities the agent provides
            model: Underlying model name
            provider: Model provider
            metadata: Additional metadata
            tags: Optional tags for filtering
            region_id: Primary region where agent is deployed
            available_regions: All regions where agent can accept tasks

        Returns:
            AgentInfo for the registered agent
        """
        cap_strs = {c.value if isinstance(c, AgentCapability) else c for c in capabilities}

        # Default available_regions to include region_id
        if available_regions is None:
            available_regions_set = {region_id}
        else:
            available_regions_set = set(available_regions)
            available_regions_set.add(region_id)  # Ensure primary is included

        now = time.time()
        agent = AgentInfo(
            agent_id=agent_id,
            capabilities=cap_strs,
            status=AgentStatus.READY,
            model=model,
            provider=provider,
            metadata=metadata or {},
            registered_at=now,
            last_heartbeat=now,
            tags=set(tags or []),
            region_id=region_id,
            available_regions=available_regions_set,
            last_heartbeat_by_region={region_id: now},
        )

        await self._save_agent(agent)
        logger.info(
            "Agent registered: %s (model=%s, region=%s, capabilities=%s)",
            agent_id,
            model,
            region_id,
            cap_strs,
        )

        return agent

    async def unregister(self, agent_id: str) -> bool:
        """
        Unregister an agent from the registry.

        Args:
            agent_id: Agent to unregister

        Returns:
            True if agent was unregistered, False if not found
        """
        key = f"{self._key_prefix}{agent_id}"

        if self._redis:
            result = await self._redis.delete(key)
            deleted = result > 0
        else:
            deleted = agent_id in self._local_cache
            self._local_cache.pop(agent_id, None)

        if deleted:
            logger.info("Agent unregistered: %s", agent_id)

        return deleted

    async def heartbeat(
        self,
        agent_id: str,
        status: AgentStatus | None = None,
        current_task_id: str | None = None,
    ) -> bool:
        """
        Update agent heartbeat timestamp.

        Args:
            agent_id: Agent sending heartbeat
            status: Optional status update
            current_task_id: Optional current task ID

        Returns:
            True if heartbeat recorded, False if agent not found
        """
        agent = await self.get(agent_id)
        if not agent:
            return False

        agent.last_heartbeat = time.time()
        if status:
            agent.status = status
        if current_task_id is not None:
            agent.current_task_id = current_task_id

        await self._save_agent(agent)
        return True

    async def get(self, agent_id: str) -> AgentInfo | None:
        """
        Get agent info by ID.

        Args:
            agent_id: Agent to look up

        Returns:
            AgentInfo if found, None otherwise
        """
        key = f"{self._key_prefix}{agent_id}"

        if self._redis:
            data = await self._redis.get(key)
            if data:
                return AgentInfo.from_dict(json.loads(data))
            return None
        else:
            return self._local_cache.get(agent_id)

    async def list_all(self, include_offline: bool = False) -> list[AgentInfo]:
        """
        List all registered agents.

        Args:
            include_offline: Whether to include offline agents

        Returns:
            List of AgentInfo objects
        """
        agents = []

        if self._redis:
            # Use SCAN to iterate through keys
            pattern = f"{self._key_prefix}*"
            async for key in self._redis.scan_iter(match=pattern):
                data = await self._redis.get(key)
                if data:
                    agent = AgentInfo.from_dict(json.loads(data))
                    if include_offline or agent.is_alive(self._heartbeat_timeout):
                        agents.append(agent)
        else:
            for agent in self._local_cache.values():
                if include_offline or agent.is_alive(self._heartbeat_timeout):
                    agents.append(agent)

        return agents

    async def find_by_capability(
        self,
        capability: str | AgentCapability,
        only_available: bool = True,
    ) -> list[AgentInfo]:
        """
        Find agents with a specific capability.

        Args:
            capability: Required capability
            only_available: Only return agents in READY status

        Returns:
            List of matching agents
        """
        cap_str = capability.value if isinstance(capability, AgentCapability) else capability
        agents = await self.list_all()

        return [
            a
            for a in agents
            if a.has_capability(cap_str) and (not only_available or a.is_available())
        ]

    async def find_by_capabilities(
        self,
        capabilities: Sequence[str | AgentCapability],
        only_available: bool = True,
    ) -> list[AgentInfo]:
        """
        Find agents with all specified capabilities.

        Args:
            capabilities: Required capabilities
            only_available: Only return agents in READY status

        Returns:
            List of matching agents
        """
        agents = await self.list_all()

        return [
            a
            for a in agents
            if a.has_all_capabilities(capabilities) and (not only_available or a.is_available())
        ]

    async def find_by_region(
        self,
        region_id: str,
        only_available: bool = True,
    ) -> list[AgentInfo]:
        """
        Find agents available in a specific region.

        Args:
            region_id: Region to search for agents
            only_available: Only return agents in READY status

        Returns:
            List of agents available in the region
        """
        agents = await self.list_all()

        return [
            a
            for a in agents
            if a.is_available_in_region(region_id) and (not only_available or a.is_available())
        ]

    async def find_by_capability_and_region(
        self,
        capability: str | AgentCapability,
        region_id: str,
        only_available: bool = True,
    ) -> list[AgentInfo]:
        """
        Find agents with a capability available in a region.

        Args:
            capability: Required capability
            region_id: Region to search
            only_available: Only return agents in READY status

        Returns:
            List of matching agents in the region
        """
        cap_str = capability.value if isinstance(capability, AgentCapability) else capability
        agents = await self.list_all()

        return [
            a
            for a in agents
            if a.has_capability(cap_str)
            and a.is_available_in_region(region_id)
            and (not only_available or a.is_available())
        ]

    async def find_by_capabilities_and_regions(
        self,
        capabilities: Sequence[str | AgentCapability],
        regions: list[str],
        only_available: bool = True,
    ) -> list[AgentInfo]:
        """
        Find agents with all capabilities available in any of the specified regions.

        Args:
            capabilities: Required capabilities
            regions: Regions to search (in priority order)
            only_available: Only return agents in READY status

        Returns:
            List of matching agents, sorted by region priority
        """
        agents = await self.list_all()

        # Filter by capabilities first
        candidates = [
            a
            for a in agents
            if a.has_all_capabilities(capabilities) and (not only_available or a.is_available())
        ]

        # Group by region priority
        result = []
        seen_ids = set()
        for region in regions:
            for agent in candidates:
                if agent.agent_id not in seen_ids and agent.is_available_in_region(region):
                    result.append(agent)
                    seen_ids.add(agent.agent_id)

        # Add remaining agents (available in other regions)
        for agent in candidates:
            if agent.agent_id not in seen_ids:
                result.append(agent)
                seen_ids.add(agent.agent_id)

        return result

    async def select_agent(
        self,
        capabilities: Sequence[str | AgentCapability],
        strategy: str = "least_loaded",
        exclude: list[str] | None = None,
    ) -> AgentInfo | None:
        """
        Select an agent based on capabilities and load balancing strategy.

        Args:
            capabilities: Required capabilities
            strategy: Selection strategy ("least_loaded", "round_robin", "random")
            exclude: Agent IDs to exclude from selection

        Returns:
            Selected agent or None if no suitable agent found
        """
        candidates = await self.find_by_capabilities(capabilities)

        if exclude:
            candidates = [a for a in candidates if a.agent_id not in exclude]

        if not candidates:
            return None

        if strategy == "least_loaded":
            # Prefer agents with fewer completed tasks (proxy for current load)
            # In production, use actual task queue depth
            return min(candidates, key=lambda a: a.tasks_completed)
        elif strategy == "round_robin":
            # Simple round-robin based on last heartbeat
            return min(candidates, key=lambda a: a.last_heartbeat)
        elif strategy == "random":
            import random

            return random.choice(candidates)
        else:
            return candidates[0]

    async def select_agent_in_region(
        self,
        capabilities: Sequence[str | AgentCapability],
        target_region: str | None = None,
        fallback_regions: list[str] | None = None,
        strategy: str = "least_loaded",
        exclude: list[str] | None = None,
        prefer_low_latency: bool = True,
    ) -> AgentInfo | None:
        """
        Select an agent based on capabilities and regional preference.

        This method provides region-aware agent selection, trying the target
        region first, then fallback regions, with optional latency-based
        sorting within each region.

        Args:
            capabilities: Required capabilities
            target_region: Preferred region for execution
            fallback_regions: Regions to try if target has no suitable agents
            strategy: Selection strategy ("least_loaded", "round_robin", "random")
            exclude: Agent IDs to exclude from selection
            prefer_low_latency: Sort by latency within region

        Returns:
            Selected agent or None if no suitable agent found
        """
        # Build region priority list
        regions = []
        if target_region:
            regions.append(target_region)
        if fallback_regions:
            regions.extend([r for r in fallback_regions if r not in regions])

        # Get candidates with capabilities in specified regions
        if regions:
            candidates = await self.find_by_capabilities_and_regions(
                capabilities, regions, only_available=True
            )
        else:
            candidates = await self.find_by_capabilities(capabilities, only_available=True)

        if exclude:
            candidates = [a for a in candidates if a.agent_id not in exclude]

        if not candidates:
            return None

        # Sort by region priority and latency
        if prefer_low_latency and target_region:

            def sort_key(agent: AgentInfo) -> tuple:
                # Primary: is in target region (lower is better)
                in_target = 0 if agent.is_available_in_region(target_region) else 1
                # Secondary: latency to target region
                latency = agent.get_latency_for_region(target_region)
                return (in_target, latency)

            candidates.sort(key=sort_key)

        # Apply final selection strategy
        if strategy == "least_loaded":
            # Among top candidates by region, pick least loaded
            if target_region:
                top_region_candidates = [
                    a for a in candidates if a.is_available_in_region(target_region)
                ]
                if top_region_candidates:
                    return min(top_region_candidates, key=lambda a: a.tasks_completed)
            return min(candidates, key=lambda a: a.tasks_completed)
        elif strategy == "random":
            import random

            return random.choice(candidates)
        else:
            return candidates[0]

    async def list_regions(self) -> list[str]:
        """
        List all unique regions with registered agents.

        Returns:
            List of region IDs
        """
        agents = await self.list_all()
        regions = set()
        for agent in agents:
            regions.add(agent.region_id)
            regions.update(agent.available_regions)
        return sorted(regions)

    async def get_agents_by_region(self) -> dict[str, list[AgentInfo]]:
        """
        Get agents grouped by their primary region.

        Returns:
            Dict mapping region_id to list of agents
        """
        agents = await self.list_all()
        by_region: dict[str, list[AgentInfo]] = {}
        for agent in agents:
            region = agent.region_id
            if region not in by_region:
                by_region[region] = []
            by_region[region].append(agent)
        return by_region

    async def update_status(self, agent_id: str, status: AgentStatus) -> bool:
        """
        Update agent status.

        Args:
            agent_id: Agent to update
            status: New status

        Returns:
            True if updated, False if agent not found
        """
        agent = await self.get(agent_id)
        if not agent:
            return False

        agent.status = status
        await self._save_agent(agent)
        logger.debug("Agent %s status updated to %s", agent_id, status.value)
        return True

    async def record_task_completion(
        self,
        agent_id: str,
        success: bool,
        latency_ms: float,
    ) -> bool:
        """
        Record task completion metrics for an agent.

        Args:
            agent_id: Agent that completed the task
            success: Whether task succeeded
            latency_ms: Task completion time in milliseconds

        Returns:
            True if recorded, False if agent not found
        """
        agent = await self.get(agent_id)
        if not agent:
            return False

        if success:
            agent.tasks_completed += 1
        else:
            agent.tasks_failed += 1

        # Update rolling average latency
        total_tasks = agent.tasks_completed + agent.tasks_failed
        agent.avg_latency_ms = (agent.avg_latency_ms * (total_tasks - 1) + latency_ms) / total_tasks

        agent.current_task_id = None
        agent.status = AgentStatus.READY

        await self._save_agent(agent)
        return True

    async def get_stats(self) -> dict[str, Any]:
        """
        Get registry statistics.

        Returns:
            Dict with agent counts, capability distribution, etc.
        """
        agents = await self.list_all(include_offline=True)

        status_counts: dict[str, int] = {}
        capability_counts: dict[str, int] = {}
        provider_counts: dict[str, int] = {}

        for agent in agents:
            # Count by status
            status = agent.status.value
            status_counts[status] = status_counts.get(status, 0) + 1

            # Count by capability
            for cap in agent.capabilities:
                capability_counts[cap] = capability_counts.get(cap, 0) + 1

            # Count by provider
            provider_counts[agent.provider] = provider_counts.get(agent.provider, 0) + 1

        return {
            "total_agents": len(agents),
            "available_agents": len([a for a in agents if a.is_available()]),
            "by_status": status_counts,
            "by_capability": capability_counts,
            "by_provider": provider_counts,
            "heartbeat_timeout": self._heartbeat_timeout,
        }

    async def _save_agent(self, agent: AgentInfo) -> None:
        """Save agent to Redis or local cache."""
        key = f"{self._key_prefix}{agent.agent_id}"

        if self._redis:
            await self._redis.set(
                key,
                json.dumps(agent.to_dict()),
                ex=int(self._heartbeat_timeout * 3),  # Expire after 3x timeout
            )
        else:
            self._local_cache[agent.agent_id] = agent

    async def _cleanup_loop(self) -> None:
        """Background task to mark offline agents."""
        while True:
            try:
                await asyncio.sleep(self._cleanup_interval)
                await self._cleanup_stale_agents()
            except asyncio.CancelledError:
                break
            except (ConnectionError, TimeoutError, OSError, RuntimeError) as e:
                logger.error("Error in cleanup loop: %s", e)

    async def _cleanup_stale_agents(self) -> int:
        """Mark agents as offline if heartbeat expired."""
        agents = await self.list_all(include_offline=True)
        marked_offline = 0

        for agent in agents:
            if not agent.is_alive(self._heartbeat_timeout):
                if agent.status != AgentStatus.OFFLINE:
                    agent.status = AgentStatus.OFFLINE
                    await self._save_agent(agent)
                    marked_offline += 1
                    logger.warning("Agent marked offline: %s", agent.agent_id)

        if marked_offline > 0:
            logger.info("Marked %s agents as offline", marked_offline)

        return marked_offline


# ---------------------------------------------------------------------------
# Module-level singleton accessor
# ---------------------------------------------------------------------------

_default_registry: AgentRegistry | None = None


def get_default_registry() -> AgentRegistry | None:
    """Return the module-level default registry, if one has been set."""
    return _default_registry


def set_default_registry(registry: AgentRegistry | None) -> None:
    """Set (or clear) the module-level default registry."""
    global _default_registry
    _default_registry = registry
