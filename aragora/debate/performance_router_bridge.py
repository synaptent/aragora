"""
Performance Monitor to Agent Router Bridge.

Bridges performance metrics from AgentPerformanceMonitor into the AgentRouter's
routing decisions, enabling performance-aware agent selection.

This closes the loop between:
1. AgentPerformanceMonitor: Tracks response times, quality scores, consistency
2. AgentRouter: Routes tasks to agents based on capabilities

By connecting them, we enable:
- Fast routing to agents with low latency for time-sensitive tasks
- Quality-weighted routing for precision-critical tasks
- Consistency-based routing for reliable execution
- Dynamic routing adjustments based on recent performance

Usage:
    from aragora.debate.performance_router_bridge import PerformanceRouterBridge

    bridge = PerformanceRouterBridge(
        performance_monitor=monitor,
        agent_router=router,
    )

    # Get routing score for an agent
    score = bridge.compute_routing_score("claude", task_type="precision")

    # Sync performance data to router
    bridge.sync_to_router()
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.debate.agent_router import AgentRouter

logger = logging.getLogger(__name__)


def _record_routing_metrics(task_type: str, selected_agent: str, latency: float) -> None:
    """Record routing decision metrics to Prometheus."""
    try:
        from aragora.observability.metrics.ranking import (
            record_performance_routing_decision,
            record_performance_routing_latency,
        )

        record_performance_routing_decision(task_type or "balanced", selected_agent)
        record_performance_routing_latency(latency)
    except ImportError:
        logger.debug("Performance routing metrics not available")


@dataclass
class AgentRoutingScore:
    """Routing score breakdown for an agent."""

    agent_name: str
    overall_score: float = 0.0  # 0-1, higher = better for routing
    latency_score: float = 0.0  # 0-1, based on response time
    quality_score: float = 0.0  # 0-1, based on output quality
    consistency_score: float = 0.0  # 0-1, based on variance in performance
    data_points: int = 0  # Number of observations
    last_updated: datetime | None = None

    @property
    def is_reliable(self) -> bool:
        """Check if we have enough data for reliable routing."""
        return self.data_points >= 5


@dataclass
class SyncResult:
    """Result of syncing performance data to router."""

    agents_synced: int = 0
    agents_skipped: int = 0
    timestamp: datetime = field(default_factory=datetime.now)
    success: bool = True
    error: str | None = None


@dataclass
class PerformanceRouterBridgeConfig:
    """Configuration for the performance-router bridge."""

    # Minimum data points before using performance for routing
    min_data_points: int = 5

    # Weights for different performance dimensions
    latency_weight: float = 0.3
    quality_weight: float = 0.4
    consistency_weight: float = 0.3

    # Whether to auto-sync to router after updates
    auto_sync: bool = True

    # Sync interval in seconds (0 = sync on every update)
    sync_interval_seconds: int = 60

    # Latency thresholds for scoring (seconds)
    fast_latency_threshold: float = 1.0  # Below this = full score
    slow_latency_threshold: float = 10.0  # Above this = zero score

    # Quality thresholds
    high_quality_threshold: float = 0.8
    low_quality_threshold: float = 0.4

    # Speed tier thresholds
    fast_tier_threshold: float = 0.8  # Score above this = fast tier
    slow_tier_threshold: float = 0.4  # Score below this = slow tier


@dataclass
class PerformanceRouterBridge:
    """Bridges AgentPerformanceMonitor into AgentRouter decisions.

    Key integration points:
    1. Computes routing scores from performance metrics
    2. Syncs performance-based weights to router
    3. Provides task-type-specific routing recommendations
    4. Tracks routing decisions and outcomes
    """

    performance_monitor: Any | None = None  # AgentPerformanceMonitor
    agent_router: AgentRouter | None = None
    config: PerformanceRouterBridgeConfig = field(default_factory=PerformanceRouterBridgeConfig)

    # Internal state
    _routing_scores: dict[str, AgentRoutingScore] = field(default_factory=dict, repr=False)
    _last_sync: datetime | None = field(default=None, repr=False)
    _sync_history: list[SyncResult] = field(default_factory=list, repr=False)

    def compute_routing_score(
        self,
        agent_name: str,
        task_type: str | None = None,
    ) -> AgentRoutingScore:
        """Compute routing score for an agent.

        Args:
            agent_name: Name of the agent
            task_type: Optional task type for weighted scoring
                       ("speed", "precision", "balanced")

        Returns:
            AgentRoutingScore with breakdown
        """
        score = AgentRoutingScore(agent_name=agent_name)

        if self.performance_monitor is None:
            return score

        # Get metrics from monitor
        metrics = self._get_agent_metrics(agent_name)
        if metrics is None:
            return score

        # Compute individual scores
        score.latency_score = self._compute_latency_score(metrics)
        score.quality_score = self._compute_quality_score(metrics)
        score.consistency_score = self._compute_consistency_score(metrics)
        score.data_points = getattr(metrics, "total_calls", 0)
        score.last_updated = datetime.now()

        # Compute weighted overall score
        weights = self._get_weights_for_task_type(task_type)
        score.overall_score = (
            score.latency_score * weights["latency"]
            + score.quality_score * weights["quality"]
            + score.consistency_score * weights["consistency"]
        )

        # Cache the score
        self._routing_scores[agent_name] = score

        logger.debug(
            "routing_score agent=%s overall=%.2f latency=%.2f quality=%.2f consistency=%.2f",
            agent_name,
            score.overall_score,
            score.latency_score,
            score.quality_score,
            score.consistency_score,
        )

        return score

    def _get_agent_metrics(self, agent_name: str) -> Any | None:
        """Get performance metrics from monitor."""
        if self.performance_monitor is None:
            return None

        try:
            # Try different possible method names
            if hasattr(self.performance_monitor, "get_agent_metrics"):
                return self.performance_monitor.get_agent_metrics(agent_name)
            elif hasattr(self.performance_monitor, "get_metrics"):
                return self.performance_monitor.get_metrics(agent_name)
            elif hasattr(self.performance_monitor, "metrics"):
                return self.performance_monitor.metrics.get(agent_name)
        except (RuntimeError, ValueError, TypeError, AttributeError, KeyError, OSError) as e:
            logger.debug("Could not get metrics for %s: %s", agent_name, e)

        return None

    def _compute_latency_score(self, metrics: Any) -> float:
        """Compute latency score from metrics."""
        # Try to get average response time
        avg_time = getattr(metrics, "avg_response_time", None)
        if avg_time is None:
            avg_time = getattr(metrics, "average_latency", None)
        if avg_time is None:
            return 0.5  # Neutral

        # Score: 1.0 for fast, 0.0 for slow
        if avg_time <= self.config.fast_latency_threshold:
            return 1.0
        elif avg_time >= self.config.slow_latency_threshold:
            return 0.0
        else:
            # Linear interpolation
            range_size = self.config.slow_latency_threshold - self.config.fast_latency_threshold
            return 1.0 - (avg_time - self.config.fast_latency_threshold) / range_size

    def _compute_quality_score(self, metrics: Any) -> float:
        """Compute quality score from metrics."""
        quality = getattr(metrics, "quality_score", None)
        if quality is None:
            quality = getattr(metrics, "avg_quality", None)
        if quality is None:
            return 0.5  # Neutral

        return min(1.0, max(0.0, quality))

    def _compute_consistency_score(self, metrics: Any) -> float:
        """Compute consistency score from metrics."""
        consistency = getattr(metrics, "consistency_score", None)
        if consistency is None:
            # Try to compute from variance
            variance = getattr(metrics, "response_time_variance", None)
            if variance is not None:
                # Lower variance = higher consistency
                # Assume variance of 5.0 or more = 0 consistency
                consistency = max(0.0, 1.0 - variance / 5.0)
            else:
                return 0.5  # Neutral

        return min(1.0, max(0.0, consistency))

    def _get_weights_for_task_type(self, task_type: str | None) -> dict[str, float]:
        """Get scoring weights based on task type."""
        if task_type == "speed":
            return {"latency": 0.6, "quality": 0.2, "consistency": 0.2}
        elif task_type == "precision":
            return {"latency": 0.1, "quality": 0.6, "consistency": 0.3}
        elif task_type == "reliable":
            return {"latency": 0.2, "quality": 0.3, "consistency": 0.5}
        else:
            # Balanced/default
            return {
                "latency": self.config.latency_weight,
                "quality": self.config.quality_weight,
                "consistency": self.config.consistency_weight,
            }

    def sync_to_router(self, force: bool = False) -> SyncResult:
        """Sync performance scores to agent router.

        Args:
            force: Force sync even if interval hasn't passed

        Returns:
            SyncResult with sync details
        """
        start_time = time.perf_counter()
        result = SyncResult()

        if self.agent_router is None:
            result.success = False
            result.error = "No agent router attached"
            self._record_sync_metrics(result, time.perf_counter() - start_time)
            return result

        # Check sync interval
        if not force and self._last_sync is not None:
            elapsed = (datetime.now() - self._last_sync).total_seconds()
            if elapsed < self.config.sync_interval_seconds:
                result.agents_skipped = len(self._routing_scores)
                return result

        # Sync each agent's score to router
        for agent_name, score in self._routing_scores.items():
            if not score.is_reliable:
                result.agents_skipped += 1
                continue

            try:
                # Try to update router weights
                if hasattr(self.agent_router, "set_agent_weight"):
                    self.agent_router.set_agent_weight(agent_name, score.overall_score)
                    result.agents_synced += 1
                elif hasattr(self.agent_router, "update_weight"):
                    self.agent_router.update_weight(agent_name, score.overall_score)
                    result.agents_synced += 1
                else:
                    result.agents_skipped += 1
            except (
                RuntimeError,
                ValueError,
                TypeError,
                AttributeError,
                OSError,
                ConnectionError,
            ) as e:
                logger.warning("Failed to sync %s to router: %s", agent_name, e)
                result.agents_skipped += 1

        self._last_sync = datetime.now()
        self._sync_history.append(result)

        logger.debug(
            "router_sync synced=%s skipped=%s", result.agents_synced, result.agents_skipped
        )

        # Record telemetry
        self._record_sync_metrics(result, time.perf_counter() - start_time)

        return result

    def _record_sync_metrics(self, result: SyncResult, latency: float) -> None:
        """Record sync metrics to Prometheus."""
        try:
            from aragora.observability.metrics import (
                record_bridge_sync,
                record_bridge_sync_latency,
            )

            record_bridge_sync("performance_router", result.success)
            record_bridge_sync_latency("performance_router", latency)
        except ImportError:
            logger.debug("Bridge sync metrics not available")

    def get_best_agent_for_task(
        self,
        available_agents: list[str],
        task_type: str | None = None,
    ) -> str | None:
        """Get the best agent for a task based on performance.

        Args:
            available_agents: List of available agent names
            task_type: Optional task type ("speed", "precision", "balanced")

        Returns:
            Name of best agent, or None if no data
        """
        if not available_agents:
            return None

        start_time = time.perf_counter()
        best_agent = None
        best_score = -1.0

        for agent_name in available_agents:
            score = self.compute_routing_score(agent_name, task_type)
            if score.is_reliable and score.overall_score > best_score:
                best_score = score.overall_score
                best_agent = agent_name

        # Record metrics for the routing decision
        latency = time.perf_counter() - start_time
        if best_agent:
            _record_routing_metrics(task_type or "balanced", best_agent, latency)

        return best_agent

    def rank_agents_for_task(
        self,
        available_agents: list[str],
        task_type: str | None = None,
    ) -> list[tuple[str, float]]:
        """Rank agents by performance for a task type.

        Args:
            available_agents: List of available agent names
            task_type: Optional task type

        Returns:
            List of (agent_name, score) tuples sorted by score descending
        """
        rankings: list[tuple[str, float]] = []

        for agent_name in available_agents:
            score = self.compute_routing_score(agent_name, task_type)
            rankings.append((agent_name, score.overall_score))

        rankings.sort(key=lambda x: x[1], reverse=True)
        return rankings

    def get_speed_tier(self, agent_name: str) -> str:
        """Get speed tier classification for an agent.

        Args:
            agent_name: Name of the agent

        Returns:
            "fast", "medium", or "slow"
        """
        score = self._routing_scores.get(agent_name)
        if score is None:
            score = self.compute_routing_score(agent_name)

        if score.latency_score >= self.config.fast_tier_threshold:
            return "fast"
        elif score.latency_score <= self.config.slow_tier_threshold:
            return "slow"
        else:
            return "medium"

    def get_routing_score(self, agent_name: str) -> AgentRoutingScore | None:
        """Get cached routing score for an agent.

        Args:
            agent_name: Name of the agent

        Returns:
            AgentRoutingScore if available
        """
        return self._routing_scores.get(agent_name)

    def get_all_scores(self) -> dict[str, AgentRoutingScore]:
        """Get all cached routing scores.

        Returns:
            Dict of agent name -> routing score
        """
        return dict(self._routing_scores)

    def get_sync_history(self, limit: int = 10) -> list[SyncResult]:
        """Get recent sync history.

        Args:
            limit: Max number of results

        Returns:
            List of recent SyncResults
        """
        return self._sync_history[-limit:]

    def get_stats(self) -> dict[str, Any]:
        """Get bridge statistics.

        Returns:
            Dict with bridge metrics
        """
        reliable_agents = [
            name for name, score in self._routing_scores.items() if score.is_reliable
        ]

        return {
            "agents_tracked": len(self._routing_scores),
            "reliable_agents": len(reliable_agents),
            "last_sync": self._last_sync.isoformat() if self._last_sync else None,
            "total_syncs": len(self._sync_history),
            "auto_sync_enabled": self.config.auto_sync,
            "performance_monitor_attached": self.performance_monitor is not None,
            "agent_router_attached": self.agent_router is not None,
        }

    def clear_cache(self) -> None:
        """Clear cached routing scores."""
        self._routing_scores.clear()
        logger.debug("Cleared routing score cache")


def create_performance_router_bridge(
    performance_monitor: Any | None = None,
    agent_router: Any | None = None,
    **config_kwargs: Any,
) -> PerformanceRouterBridge:
    """Create and configure a PerformanceRouterBridge.

    Args:
        performance_monitor: AgentPerformanceMonitor instance
        agent_router: AgentRouter instance
        **config_kwargs: Additional configuration options

    Returns:
        Configured PerformanceRouterBridge instance
    """
    config = PerformanceRouterBridgeConfig(**config_kwargs)
    return PerformanceRouterBridge(
        performance_monitor=performance_monitor,
        agent_router=agent_router,
        config=config,
    )


__all__ = [
    "PerformanceRouterBridge",
    "PerformanceRouterBridgeConfig",
    "AgentRoutingScore",
    "SyncResult",
    "create_performance_router_bridge",
]
