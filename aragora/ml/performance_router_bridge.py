"""
Performance Monitor to Agent Router Bridge.

Bridges real-time telemetry from AgentPerformanceMonitor into the AgentRouter's
historical performance data, enabling data-driven routing decisions.

This closes the loop between:
1. AgentPerformanceMonitor: Tracks actual agent call metrics (latency, success, timeouts)
2. AgentRouter: Makes routing decisions but maintains its own disconnected history

Usage:
    from aragora.ml.performance_router_bridge import PerformanceRouterBridge

    bridge = PerformanceRouterBridge(
        performance_monitor=monitor,
        agent_router=router,
        sync_interval=10,  # Sync every 10 calls
    )

    # Sync current telemetry into router
    result = bridge.sync_performance()

    # Or auto-sync in arena lifecycle
    bridge.enable_auto_sync()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.agents.performance_monitor import AgentPerformanceMonitor, AgentStats
    from aragora.ml.agent_router import AgentRouter, TaskType

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """Result of a performance sync operation."""

    agents_synced: int
    records_added: int
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    agents_updated: list[str] = field(default_factory=list)


@dataclass
class PerformanceRouterBridgeConfig:
    """Configuration for the performance-router bridge."""

    # Minimum calls before syncing an agent
    min_calls_for_sync: int = 5

    # Weight for success rate in router scoring
    success_rate_weight: float = 0.4

    # Weight for latency in router scoring (inverted - lower is better)
    latency_weight: float = 0.2

    # Weight for timeout rate (inverted - lower is better)
    timeout_penalty_weight: float = 0.3

    # Weight for consistency (low variance is better)
    consistency_weight: float = 0.1

    # Auto-sync interval (number of calls between syncs)
    auto_sync_interval: int = 20


@dataclass
class PerformanceRouterBridge:
    """Bridges AgentPerformanceMonitor telemetry into AgentRouter decisions.

    Key integration points:
    1. Syncs success rates into router's historical performance
    2. Converts latency metrics into speed tier adjustments
    3. Tracks timeout patterns for task complexity routing
    4. Feeds consistency metrics into reliability scoring
    """

    performance_monitor: AgentPerformanceMonitor | None = None
    agent_router: AgentRouter | None = None
    config: PerformanceRouterBridgeConfig = field(default_factory=PerformanceRouterBridgeConfig)

    # Internal state
    _last_sync_counts: dict[str, int] = field(default_factory=dict, repr=False)
    _call_count_since_sync: int = field(default=0, repr=False)
    _auto_sync_enabled: bool = field(default=False, repr=False)
    _sync_history: list[SyncResult] = field(default_factory=list, repr=False)

    def sync_performance(self, force: bool = False) -> SyncResult:
        """Sync current performance telemetry into router.

        Args:
            force: If True, sync all agents regardless of min_calls threshold

        Returns:
            SyncResult with details of what was synced
        """
        if self.performance_monitor is None:
            logger.debug("No performance monitor configured, skipping sync")
            return SyncResult(agents_synced=0, records_added=0)

        if self.agent_router is None:
            logger.debug("No agent router configured, skipping sync")
            return SyncResult(agents_synced=0, records_added=0)

        agents_synced = 0
        records_added = 0
        agents_updated = []

        # Get all agent stats from monitor
        for agent_name, stats in self.performance_monitor.agent_stats.items():
            # Check if we have enough new data to sync
            last_count = self._last_sync_counts.get(agent_name, 0)
            new_calls = stats.total_calls - last_count

            if not force and new_calls < self.config.min_calls_for_sync:
                continue

            # Sync this agent's performance into router
            try:
                records = self._sync_agent_performance(agent_name, stats)
                if records > 0:
                    agents_synced += 1
                    records_added += records
                    agents_updated.append(agent_name)
                    self._last_sync_counts[agent_name] = stats.total_calls
            except (RuntimeError, ValueError, TypeError, KeyError) as e:
                logger.warning("Failed to sync agent %s: %s", agent_name, e)

        result = SyncResult(
            agents_synced=agents_synced,
            records_added=records_added,
            agents_updated=agents_updated,
        )

        self._sync_history.append(result)
        self._call_count_since_sync = 0

        logger.info("performance_router_sync agents=%s records=%s", agents_synced, records_added)

        return result

    def _sync_agent_performance(self, agent_name: str, stats: AgentStats) -> int:
        """Sync a single agent's performance into the router.

        Args:
            agent_name: Name of the agent
            stats: Current performance statistics

        Returns:
            Number of records added to router history
        """
        if stats.total_calls < self.config.min_calls_for_sync:
            return 0

        router = self.agent_router
        if router is None:
            return 0

        # Determine task type from agent's typical usage
        # For now, use GENERAL as default - could be enhanced with task tracking

        task_type = self._infer_task_type(agent_name)

        # Convert success rate to individual success/failure records
        # This populates router's _historical_performance
        records_added = 0
        success_rate = stats.success_rate / 100.0  # Convert from percentage

        # Add weighted records based on success rate
        # This gives the router historical data it can learn from
        last_count = self._last_sync_counts.get(agent_name, 0)
        new_calls = stats.total_calls - last_count

        if new_calls > 0:
            successes = int(new_calls * success_rate)
            failures = new_calls - successes

            # Record successes
            for _ in range(successes):
                router.record_performance(agent_name, task_type.value, success=True)
                records_added += 1

            # Record failures
            for _ in range(failures):
                router.record_performance(agent_name, task_type.value, success=False)
                records_added += 1

        # Also update agent capabilities based on telemetry
        self._update_agent_capabilities(agent_name, stats)

        return records_added

    def _infer_task_type(self, agent_name: str) -> TaskType:
        """Infer the typical task type for an agent.

        Args:
            agent_name: Name of the agent

        Returns:
            Most likely TaskType based on agent characteristics
        """
        from aragora.ml.agent_router import TaskType

        # Check if router has capability info
        if self.agent_router and agent_name in self.agent_router._capabilities:
            caps = self.agent_router._capabilities[agent_name]
            if caps.strengths:
                return caps.strengths[0]

        # Default mapping based on common agent names
        agent_lower = agent_name.lower()
        if "codex" in agent_lower or "code" in agent_lower:
            return TaskType.CODING
        elif "claude" in agent_lower:
            return TaskType.REASONING
        elif "gemini" in agent_lower:
            return TaskType.RESEARCH
        elif "gpt" in agent_lower:
            return TaskType.GENERAL

        return TaskType.GENERAL

    def _update_agent_capabilities(self, agent_name: str, stats: AgentStats) -> None:
        """Update router's agent capabilities based on telemetry.

        Args:
            agent_name: Name of the agent
            stats: Current performance statistics
        """
        router = self.agent_router
        if router is None or agent_name not in router._capabilities:
            return

        caps = router._capabilities[agent_name]

        # Update speed tier based on latency
        if stats.avg_duration_ms > 0:
            if stats.avg_duration_ms < 2000:  # < 2s = fast
                caps.speed_tier = 1
            elif stats.avg_duration_ms < 10000:  # < 10s = medium
                caps.speed_tier = 2
            else:  # >= 10s = slow
                caps.speed_tier = 3

        logger.debug("Updated capabilities for %s: speed_tier=%s", agent_name, caps.speed_tier)

    def compute_agent_score(self, agent_name: str) -> float:
        """Compute a composite performance score for an agent.

        This can be used by other systems (e.g., TeamSelector) to factor
        in real telemetry data.

        Args:
            agent_name: Name of the agent

        Returns:
            Score from 0.0 to 1.0 based on performance telemetry
        """
        if self.performance_monitor is None:
            return 0.5  # Neutral score

        stats = self.performance_monitor.agent_stats.get(agent_name)
        if stats is None or stats.total_calls < self.config.min_calls_for_sync:
            return 0.5  # Neutral score for insufficient data

        # Compute component scores
        success_score = stats.success_rate / 100.0  # 0-1

        # Latency score (inverted, normalized to 0-30s range)
        latency_score = max(0, 1 - (stats.avg_duration_ms / 30000))

        # Timeout penalty score (inverted)
        timeout_score = 1 - (stats.timeout_rate / 100.0)

        # Consistency score based on variance
        if stats.max_duration_ms > 0 and stats.min_duration_ms < float("inf"):
            variance_ratio = (stats.max_duration_ms - stats.min_duration_ms) / stats.max_duration_ms
            consistency_score = 1 - min(1, variance_ratio)
        else:
            consistency_score = 0.5

        # Weighted composite
        score = (
            self.config.success_rate_weight * success_score
            + self.config.latency_weight * latency_score
            + self.config.timeout_penalty_weight * timeout_score
            + self.config.consistency_weight * consistency_score
        )

        return min(1.0, max(0.0, score))

    def get_agent_scores(self) -> dict[str, float]:
        """Get performance scores for all tracked agents.

        Returns:
            Dict mapping agent names to performance scores (0-1)
        """
        if self.performance_monitor is None:
            return {}

        return {
            agent_name: self.compute_agent_score(agent_name)
            for agent_name in self.performance_monitor.agent_stats.keys()
        }

    def enable_auto_sync(self) -> None:
        """Enable automatic syncing after N calls."""
        self._auto_sync_enabled = True
        logger.info("Auto-sync enabled (interval=%s)", self.config.auto_sync_interval)

    def disable_auto_sync(self) -> None:
        """Disable automatic syncing."""
        self._auto_sync_enabled = False
        logger.info("Auto-sync disabled")

    def maybe_auto_sync(self) -> SyncResult | None:
        """Check if auto-sync should run and execute if needed.

        Call this after each agent call to potentially trigger sync.

        Returns:
            SyncResult if sync was performed, None otherwise
        """
        if not self._auto_sync_enabled:
            return None

        self._call_count_since_sync += 1

        if self._call_count_since_sync >= self.config.auto_sync_interval:
            return self.sync_performance()

        return None

    def get_sync_history(self) -> list[SyncResult]:
        """Get history of sync operations.

        Returns:
            List of SyncResult objects
        """
        return list(self._sync_history)

    def get_stats(self) -> dict[str, Any]:
        """Get bridge statistics.

        Returns:
            Dict with bridge metrics
        """
        return {
            "auto_sync_enabled": self._auto_sync_enabled,
            "calls_since_sync": self._call_count_since_sync,
            "total_syncs": len(self._sync_history),
            "last_sync": (self._sync_history[-1].timestamp if self._sync_history else None),
            "agents_tracked": len(self._last_sync_counts),
        }


def create_performance_router_bridge(
    performance_monitor: AgentPerformanceMonitor | None = None,
    agent_router: AgentRouter | None = None,
    auto_sync: bool = True,
    **config_kwargs: Any,
) -> PerformanceRouterBridge:
    """Create and optionally configure a PerformanceRouterBridge.

    Args:
        performance_monitor: AgentPerformanceMonitor instance
        agent_router: AgentRouter instance
        auto_sync: If True, enable automatic syncing
        **config_kwargs: Additional configuration options

    Returns:
        Configured PerformanceRouterBridge instance
    """
    config = PerformanceRouterBridgeConfig(**config_kwargs)
    bridge = PerformanceRouterBridge(
        performance_monitor=performance_monitor,
        agent_router=agent_router,
        config=config,
    )

    if auto_sync:
        bridge.enable_auto_sync()

    return bridge


__all__ = [
    "PerformanceRouterBridge",
    "PerformanceRouterBridgeConfig",
    "SyncResult",
    "create_performance_router_bridge",
]
