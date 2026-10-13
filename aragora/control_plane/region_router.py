"""
Regional Task Router for Multi-Region Control Plane.

Provides intelligent regional routing with:
- Health-aware region selection
- Data residency compliance
- Latency-optimized routing
- Automatic failover to healthy regions

Usage:
    router = RegionRouter(
        regional_event_bus=event_bus,
        local_region="us-west-2",
    )

    # Select best region for a task
    region = await router.select_region(
        task=my_task,
        constraints=RegionConstraint(allowed_regions=["us-west-2", "us-east-1"]),
    )

    # Handle failover when primary fails
    fallback = await router.failover_region(
        task_id=task.id,
        failed_region="us-west-2",
    )
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from aragora.observability import get_logger
from aragora.control_plane.scheduler import Task, RegionRoutingMode

if TYPE_CHECKING:
    from aragora.control_plane.regional_sync import RegionalEventBus
    from aragora.control_plane.policy import RegionConstraint

logger = get_logger(__name__)


class RegionStatus(Enum):
    """Health status of a region."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class RegionHealth:
    """Health metrics for a region."""

    region_id: str
    status: RegionStatus = RegionStatus.UNKNOWN
    last_seen: float = 0.0
    latency_ms: float = 0.0
    agent_count: int = 0
    pending_tasks: int = 0
    capacity_pct: float = 0.0  # 0-100, how full the region is
    error_rate: float = 0.0  # 0-1, recent error rate
    is_local: bool = False

    @property
    def is_available(self) -> bool:
        """Check if region is available for task routing."""
        return self.status in (RegionStatus.HEALTHY, RegionStatus.DEGRADED)

    @property
    def health_score(self) -> float:
        """Calculate composite health score (0-100, higher is better)."""
        if self.status == RegionStatus.UNHEALTHY:
            return 0.0
        if self.status == RegionStatus.UNKNOWN:
            return 10.0  # Low score for unknown

        score = 100.0

        # Penalize high latency (up to -30 points)
        if self.latency_ms > 0:
            latency_penalty = min(30.0, self.latency_ms / 10.0)
            score -= latency_penalty

        # Penalize high capacity usage (up to -40 points)
        if self.capacity_pct > 50:
            capacity_penalty = (self.capacity_pct - 50) * 0.8
            score -= min(40.0, capacity_penalty)

        # Penalize high error rate (up to -30 points)
        score -= self.error_rate * 30.0

        # Bonus for having agents
        if self.agent_count == 0:
            score -= 20.0
        elif self.agent_count < 2:
            score -= 10.0

        # Degraded status penalty
        if self.status == RegionStatus.DEGRADED:
            score *= 0.7

        return max(0.0, score)


@dataclass
class RegionRoutingDecision:
    """Result of a region routing decision."""

    selected_region: str | None
    fallback_regions: list[str]
    reason: str
    health_scores: dict[str, float] = field(default_factory=dict)
    data_residency_compliant: bool = True
    latency_optimized: bool = False


class RegionRouter:
    """
    Routes tasks to optimal regions based on health, constraints, and affinity.

    Provides:
    - Health-aware region selection
    - Data residency compliance
    - Latency optimization
    - Automatic failover
    """

    def __init__(
        self,
        regional_event_bus: RegionalEventBus | None = None,
        local_region: str = "default",
        health_timeout_seconds: float = 30.0,
        latency_weight: float = 0.3,
        capacity_weight: float = 0.4,
        error_weight: float = 0.3,
    ):
        """
        Initialize the region router.

        Args:
            regional_event_bus: Event bus for regional health updates
            local_region: Local region identifier
            health_timeout_seconds: Time before region is considered unhealthy
            latency_weight: Weight for latency in scoring (0-1)
            capacity_weight: Weight for capacity in scoring (0-1)
            error_weight: Weight for error rate in scoring (0-1)
        """
        self._event_bus = regional_event_bus
        self._local_region = local_region
        self._health_timeout = health_timeout_seconds
        self._latency_weight = latency_weight
        self._capacity_weight = capacity_weight
        self._error_weight = error_weight

        # Region health cache
        self._region_health: dict[str, RegionHealth] = {}

        # Track recent routing decisions for analytics
        self._routing_history: list[dict[str, Any]] = []
        self._max_history = 1000

        # Initialize local region as healthy
        self._update_region_health(
            local_region,
            RegionHealth(
                region_id=local_region,
                status=RegionStatus.HEALTHY,
                last_seen=time.time(),
                is_local=True,
            ),
        )

    @property
    def local_region(self) -> str:
        """Get the local region identifier."""
        return self._local_region

    def _update_region_health(self, region_id: str, health: RegionHealth) -> None:
        """Update cached health for a region."""
        self._region_health[region_id] = health

    def get_region_health(self, region_id: str) -> RegionHealth:
        """Get health status for a specific region."""
        if region_id in self._region_health:
            health = self._region_health[region_id]
            # Check if stale
            if time.time() - health.last_seen > self._health_timeout:
                health.status = RegionStatus.UNKNOWN
            return health

        return RegionHealth(region_id=region_id, status=RegionStatus.UNKNOWN)

    def get_all_region_health(self) -> dict[str, RegionHealth]:
        """Get health status for all known regions."""
        now = time.time()
        result = {}

        for region_id, health in self._region_health.items():
            # Update status if stale
            if now - health.last_seen > self._health_timeout:
                health.status = RegionStatus.UNKNOWN
            result[region_id] = health

        return result

    async def refresh_health(self) -> None:
        """Refresh health data from the event bus."""
        if not self._event_bus:
            return

        # Get health from event bus
        bus_health = self._event_bus.get_region_health()

        for region_id, data in bus_health.items():
            existing = self._region_health.get(region_id)
            status = RegionStatus.HEALTHY if data.get("healthy", False) else RegionStatus.UNHEALTHY

            health = RegionHealth(
                region_id=region_id,
                status=status,
                last_seen=data.get("last_seen", 0.0),
                agent_count=existing.agent_count if existing else 0,
                pending_tasks=existing.pending_tasks if existing else 0,
                capacity_pct=existing.capacity_pct if existing else 0.0,
                error_rate=existing.error_rate if existing else 0.0,
                is_local=(region_id == self._local_region),
            )
            self._update_region_health(region_id, health)

    def update_region_metrics(
        self,
        region_id: str,
        agent_count: int | None = None,
        pending_tasks: int | None = None,
        latency_ms: float | None = None,
        error_rate: float | None = None,
    ) -> None:
        """Update metrics for a region.

        Args:
            region_id: Region to update
            agent_count: Number of registered agents
            pending_tasks: Number of pending tasks
            latency_ms: Latest measured latency
            error_rate: Recent error rate (0-1)
        """
        health = self.get_region_health(region_id)

        if agent_count is not None:
            health.agent_count = agent_count
        if pending_tasks is not None:
            health.pending_tasks = pending_tasks
        if latency_ms is not None:
            health.latency_ms = latency_ms
        if error_rate is not None:
            health.error_rate = error_rate

        # Update status based on metrics
        if health.agent_count == 0:
            health.status = RegionStatus.DEGRADED
        elif health.error_rate > 0.5:
            health.status = RegionStatus.UNHEALTHY
        elif health.error_rate > 0.2 or health.capacity_pct > 90:
            health.status = RegionStatus.DEGRADED
        else:
            health.status = RegionStatus.HEALTHY

        health.last_seen = time.time()
        health.is_local = region_id == self._local_region
        self._update_region_health(region_id, health)

    async def select_region(
        self,
        task: Task,
        constraints: RegionConstraint | None = None,
        prefer_local: bool = True,
    ) -> RegionRoutingDecision:
        """
        Select the optimal region for task execution.

        Args:
            task: Task to route
            constraints: Optional policy constraints
            prefer_local: Whether to prefer local region

        Returns:
            RegionRoutingDecision with selected region and fallbacks
        """
        # Refresh health data
        await self.refresh_health()

        # Build candidate list
        candidates = self._get_candidate_regions(task, constraints)

        if not candidates:
            return RegionRoutingDecision(
                selected_region=None,
                fallback_regions=[],
                reason="No eligible regions available",
                data_residency_compliant=False,
            )

        # Score candidates
        scored = []
        health_scores = {}

        for region_id in candidates:
            health = self.get_region_health(region_id)
            score = health.health_score

            # Local region bonus
            if prefer_local and region_id == self._local_region:
                score += 15.0

            # Target region bonus (user-specified preference)
            if task.target_region and region_id == task.target_region:
                score += 20.0

            health_scores[region_id] = score
            scored.append((region_id, score))

        # Sort by score (highest first)
        scored.sort(key=lambda x: x[1], reverse=True)

        # Select best region
        selected = scored[0][0] if scored else None
        fallbacks = [r for r, _ in scored[1:4]]  # Top 3 fallbacks

        # Determine reason
        if selected == self._local_region:
            reason = "Selected local region"
        elif selected == task.target_region:
            reason = "Selected user-preferred region"
        else:
            reason = f"Selected highest-scoring region ({health_scores.get(selected or '', 0):.1f})"

        decision = RegionRoutingDecision(
            selected_region=selected,
            fallback_regions=fallbacks,
            reason=reason,
            health_scores=health_scores,
            data_residency_compliant=self._check_data_residency(selected, constraints),
            latency_optimized=prefer_local,
        )

        # Record decision for analytics
        self._record_routing_decision(task.id, decision)

        logger.info(
            "Region routing: task=%s -> %s (score=%.1f, fallbacks=%s)",
            task.id,
            selected,
            health_scores.get(selected or "", 0),
            fallbacks,
        )

        return decision

    def _get_candidate_regions(
        self,
        task: Task,
        constraints: RegionConstraint | None,
    ) -> list[str]:
        """Get list of candidate regions for a task."""
        candidates = []

        # Get all known regions
        all_regions = set(self._region_health.keys())

        # Add task-specified regions
        if task.target_region:
            all_regions.add(task.target_region)
        all_regions.update(task.fallback_regions)

        for region_id in all_regions:
            # Check task routing mode
            if task.region_routing_mode == RegionRoutingMode.STRICT:
                if region_id != task.target_region:
                    continue

            # Check policy constraints
            if constraints:
                if constraints.blocked_regions and region_id in constraints.blocked_regions:
                    continue
                if constraints.allowed_regions and region_id not in constraints.allowed_regions:
                    continue

            # Check health
            health = self.get_region_health(region_id)
            if health.is_available:
                candidates.append(region_id)

        return candidates

    def _check_data_residency(
        self,
        region_id: str | None,
        constraints: RegionConstraint | None,
    ) -> bool:
        """Check if region selection complies with data residency."""
        if not constraints or not region_id:
            return True

        if not constraints.require_data_residency:
            return True

        if constraints.allowed_regions and region_id in constraints.allowed_regions:
            return True

        return False

    async def failover_region(
        self,
        task_id: str,
        failed_region: str,
        task: Task | None = None,
        constraints: RegionConstraint | None = None,
    ) -> str | None:
        """
        Find a failover region when the primary fails.

        Args:
            task_id: Task that needs failover
            failed_region: Region that failed
            task: Optional task object (for routing preferences)
            constraints: Optional policy constraints

        Returns:
            Failover region ID, or None if no failover available
        """
        # Mark failed region as unhealthy
        health = self.get_region_health(failed_region)
        health.status = RegionStatus.UNHEALTHY
        health.error_rate = min(1.0, health.error_rate + 0.2)
        self._update_region_health(failed_region, health)

        # Get candidates excluding failed region
        candidates = []

        if task:
            # Use task preferences
            for region_id in task.get_eligible_regions():
                if region_id != failed_region:
                    region_health = self.get_region_health(region_id)
                    if region_health.is_available:
                        candidates.append(region_id)
        else:
            # Get all healthy regions
            for region_id, region_health in self._region_health.items():
                if region_id != failed_region and region_health.is_available:
                    candidates.append(region_id)

        # Apply constraints
        if constraints:
            candidates = [
                r
                for r in candidates
                if r not in (constraints.blocked_regions or [])
                and (not constraints.allowed_regions or r in constraints.allowed_regions)
            ]

        if not candidates:
            logger.warning(
                "No failover region available for task %s (failed: %s)", task_id, failed_region
            )
            return None

        # Score and select best
        scored = []
        for region_id in candidates:
            health = self.get_region_health(region_id)
            scored.append((region_id, health.health_score))

        scored.sort(key=lambda x: x[1], reverse=True)
        failover = scored[0][0]

        logger.info("Failover routing: task=%s %s -> %s", task_id, failed_region, failover)

        return failover

    def _record_routing_decision(
        self,
        task_id: str,
        decision: RegionRoutingDecision,
    ) -> None:
        """Record routing decision for analytics."""
        self._routing_history.append(
            {
                "task_id": task_id,
                "timestamp": time.time(),
                "selected": decision.selected_region,
                "fallbacks": decision.fallback_regions,
                "reason": decision.reason,
                "scores": decision.health_scores,
            }
        )

        # Trim history
        if len(self._routing_history) > self._max_history:
            self._routing_history = self._routing_history[-self._max_history :]

    def get_routing_stats(self) -> dict[str, Any]:
        """Get routing statistics."""
        if not self._routing_history:
            return {"total_decisions": 0, "by_region": {}}

        by_region: dict[str, int] = {}
        for record in self._routing_history:
            region = record.get("selected")
            if region:
                by_region[region] = by_region.get(region, 0) + 1

        return {
            "total_decisions": len(self._routing_history),
            "by_region": by_region,
            "recent_decisions": self._routing_history[-10:],
        }


# Module-level singleton
_region_router: RegionRouter | None = None


def get_region_router() -> RegionRouter | None:
    """Get the global region router instance."""
    return _region_router


def set_region_router(router: RegionRouter) -> None:
    """Set the global region router instance."""
    global _region_router
    _region_router = router


def init_region_router(
    regional_event_bus: RegionalEventBus | None = None,
    local_region: str = "default",
) -> RegionRouter:
    """Initialize and set the global region router."""
    router = RegionRouter(
        regional_event_bus=regional_event_bus,
        local_region=local_region,
    )
    set_region_router(router)
    return router


__all__ = [
    "RegionStatus",
    "RegionHealth",
    "RegionRoutingDecision",
    "RegionRouter",
    "get_region_router",
    "set_region_router",
    "init_region_router",
]
