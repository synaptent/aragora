"""
Control Plane Adapter for Knowledge Mound Integration.

Bridges the Control Plane with Knowledge Mound to enable:
- Cross-workspace knowledge sharing
- Task performance history
- Agent capability learning
- Organizational knowledge federation

ID Prefixes:
- cp_task_: Task outcome records
- cp_agent_: Agent performance data
- cp_capability_: Capability patterns
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast
from collections.abc import Callable

from aragora.knowledge.mound.adapters._base import KnowledgeMoundAdapter

if TYPE_CHECKING:
    from aragora.knowledge.mound.facade import KnowledgeMound
    from aragora.control_plane.coordinator import ControlPlaneCoordinator

logger = logging.getLogger(__name__)

# Type alias for event callbacks
EventCallback = Callable[[str, dict[str, Any]], None]


@dataclass
class TaskOutcome:
    """Record of a completed task for KM storage."""

    task_id: str
    task_type: str
    agent_id: str
    success: bool
    duration_seconds: float
    workspace_id: str = "default"
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentCapabilityRecord:
    """Record of agent capability performance."""

    agent_id: str
    capability: str
    success_count: int
    failure_count: int
    avg_duration_seconds: float
    workspace_id: str = "default"
    confidence: float = 0.8


@dataclass
class CrossWorkspaceInsight:
    """Insight shared across workspaces."""

    insight_id: str
    source_workspace: str
    target_workspaces: list[str]
    task_type: str
    content: str
    confidence: float
    created_at: str


class ControlPlaneAdapter(KnowledgeMoundAdapter):
    """
    Adapter that bridges Control Plane to the Knowledge Mound.

    Provides bidirectional sync between Control Plane operations and KM:
    - Forward: Task outcomes and agent performance → KM
    - Reverse: Historical patterns → Control Plane decisions

    Usage:
        from aragora.control_plane.coordinator import ControlPlaneCoordinator
        from aragora.knowledge.mound.adapters import ControlPlaneAdapter

        coordinator = await ControlPlaneCoordinator.create()
        adapter = ControlPlaneAdapter(coordinator)

        # Store task outcome
        await adapter.store_task_outcome(task_outcome)

        # Get agent capability recommendations
        recommendations = await adapter.get_capability_recommendations("debate")
    """

    adapter_name = "control_plane"

    def __init__(
        self,
        coordinator: ControlPlaneCoordinator | None = None,
        knowledge_mound: KnowledgeMound | None = None,
        workspace_id: str = "default",
        event_callback: EventCallback | None = None,
        enable_dual_write: bool = False,
        enable_resilience: bool = True,
        min_task_confidence: float = 0.6,
        min_capability_sample_size: int = 5,
    ):
        """
        Initialize the adapter.

        Args:
            coordinator: The ControlPlaneCoordinator to wrap
            knowledge_mound: Optional KnowledgeMound for direct storage
            workspace_id: Workspace ID for multi-tenancy
            event_callback: Optional callback for emitting events
            enable_dual_write: If True, writes go to both systems during migration
            enable_resilience: If True, enables circuit breaker and bulkhead protection
            min_task_confidence: Minimum confidence to store task outcomes
            min_capability_sample_size: Minimum samples before capability recommendations
        """
        # Initialize base adapter (handles dual_write, event_callback, resilience, metrics, tracing)
        super().__init__(
            enable_dual_write=enable_dual_write,
            event_callback=event_callback,
            enable_resilience=enable_resilience,
        )

        self._coordinator = coordinator
        self._knowledge_mound = knowledge_mound
        self._workspace_id = workspace_id
        self._min_task_confidence = min_task_confidence
        self._min_capability_sample_size = min_capability_sample_size

        # Caches
        self._capability_cache: dict[str, list[AgentCapabilityRecord]] = {}
        self._cache_ttl: float = 300  # 5 minutes
        self._cache_times: dict[str, float] = {}

        # Stats
        self._stats = {
            "task_outcomes_stored": 0,
            "capability_records_stored": 0,
            "capability_queries": 0,
            "cross_workspace_shares": 0,
        }

    # set_event_callback, _emit_event inherited from KnowledgeMoundAdapter

    # =========================================================================
    # Forward Sync: Control Plane → KM
    # =========================================================================

    async def store_task_outcome(
        self,
        outcome: TaskOutcome,
    ) -> str | None:
        """
        Store a task outcome in the Knowledge Mound.

        Args:
            outcome: Task outcome to store

        Returns:
            KM item ID if stored, None if below threshold
        """
        if not self._knowledge_mound:
            logger.debug("No KnowledgeMound configured, skipping task outcome storage")
            return None

        try:
            from aragora.knowledge.unified.types import (
                KnowledgeItem,
                KnowledgeSource,
                ConfidenceLevel,
            )

            # Calculate confidence based on consistency
            confidence_val = 0.8 if outcome.success else 0.5

            if confidence_val < self._min_task_confidence:
                logger.debug(f"Task outcome below confidence threshold: {confidence_val:.2f}")
                return None

            # Map confidence value to enum
            confidence = ConfidenceLevel.HIGH if outcome.success else ConfidenceLevel.MEDIUM
            now = datetime.now()

            # Create knowledge item
            item = KnowledgeItem(
                id=f"cp_task_{outcome.task_id}",
                content=(
                    f"Task {outcome.task_type} completed by {outcome.agent_id}: "
                    f"{'success' if outcome.success else 'failure'} in "
                    f"{outcome.duration_seconds:.2f}s"
                ),
                source=KnowledgeSource.CONTINUUM,  # Use existing source type
                source_id=outcome.task_id,
                confidence=confidence,
                created_at=now,
                updated_at=now,
                metadata={
                    "type": "control_plane_task_outcome",
                    "task_id": outcome.task_id,
                    "task_type": outcome.task_type,
                    "agent_id": outcome.agent_id,
                    "success": outcome.success,
                    "duration_seconds": outcome.duration_seconds,
                    "error_message": outcome.error_message,
                    "workspace_id": outcome.workspace_id,
                    **outcome.metadata,
                },
            )

            item_id = await self._knowledge_mound.ingest(item)

            self._stats["task_outcomes_stored"] += 1
            self._emit_event(
                "cp_task_outcome_stored",
                {
                    "task_id": outcome.task_id,
                    "agent_id": outcome.agent_id,
                    "success": outcome.success,
                },
            )

            logger.debug(
                "Stored task outcome: task=%s agent=%s success=%s",
                outcome.task_id,
                outcome.agent_id,
                outcome.success,
            )

            return item_id

        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.error("Failed to store task outcome: %s", e)
            return None

    async def store_capability_record(
        self,
        record: AgentCapabilityRecord,
    ) -> str | None:
        """
        Store an agent capability record in the Knowledge Mound.

        Args:
            record: Capability record to store

        Returns:
            KM item ID if stored, None if below threshold
        """
        if not self._knowledge_mound:
            return None

        try:
            from aragora.knowledge.unified.types import (
                KnowledgeItem,
                KnowledgeSource,
                ConfidenceLevel,
            )

            total_tasks = record.success_count + record.failure_count
            if total_tasks < self._min_capability_sample_size:
                logger.debug("Capability record below sample threshold: %s", total_tasks)
                return None

            success_rate = record.success_count / total_tasks if total_tasks > 0 else 0

            # Map confidence value to enum
            if record.confidence >= 0.8:
                confidence = ConfidenceLevel.HIGH
            elif record.confidence >= 0.6:
                confidence = ConfidenceLevel.MEDIUM
            else:
                confidence = ConfidenceLevel.LOW
            now = datetime.now()

            item = KnowledgeItem(
                id=f"cp_capability_{record.agent_id}_{record.capability}",
                content=(
                    f"Agent {record.agent_id} capability '{record.capability}': "
                    f"{success_rate:.1%} success rate over {total_tasks} tasks, "
                    f"avg duration {record.avg_duration_seconds:.2f}s"
                ),
                source=KnowledgeSource.ELO,  # Use existing source type
                source_id=f"{record.agent_id}_{record.capability}",
                confidence=confidence,
                created_at=now,
                updated_at=now,
                metadata={
                    "type": "control_plane_capability",
                    "agent_id": record.agent_id,
                    "capability": record.capability,
                    "success_count": record.success_count,
                    "failure_count": record.failure_count,
                    "success_rate": success_rate,
                    "avg_duration_seconds": record.avg_duration_seconds,
                    "workspace_id": record.workspace_id,
                },
            )

            item_id = await self._knowledge_mound.ingest(item)

            self._stats["capability_records_stored"] += 1

            # Invalidate cache for this capability
            if record.capability in self._capability_cache:
                del self._capability_cache[record.capability]

            return item_id

        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.error("Failed to store capability record: %s", e)
            return None

    # =========================================================================
    # Reverse Flow: KM → Control Plane
    # =========================================================================

    async def get_capability_recommendations(
        self,
        capability: str,
        limit: int = 5,
        use_cache: bool = True,
    ) -> list[AgentCapabilityRecord]:
        """
        Get agent recommendations for a capability from KM.

        Queries historical capability performance to recommend agents.

        Args:
            capability: Capability to query
            limit: Maximum agents to return
            use_cache: Whether to use cached results

        Returns:
            List of AgentCapabilityRecord sorted by success rate
        """
        self._stats["capability_queries"] += 1

        # Check cache
        if use_cache:
            cache_key = capability.lower()
            if cache_key in self._capability_cache:
                cache_time = self._cache_times.get(cache_key, 0)
                if time.time() - cache_time < self._cache_ttl:
                    return self._capability_cache[cache_key][:limit]

        if not self._knowledge_mound:
            return []

        try:
            # Query KM for capability records
            query_result = await self._knowledge_mound.query(
                query=f"agent capability {capability}",
                limit=limit * 2,  # Query more, then filter
                workspace_id=self._workspace_id,
            )
            results = query_result.items if hasattr(query_result, "items") else []

            records = []
            for result in results:
                # KnowledgeItem has metadata as dict attribute
                metadata = getattr(result, "metadata", {}) or {}
                if metadata.get("type") != "control_plane_capability":
                    continue

                # Get confidence from KnowledgeItem
                conf = getattr(result, "confidence", 0.8)
                if hasattr(conf, "value"):
                    conf = conf.value

                record = AgentCapabilityRecord(
                    agent_id=metadata.get("agent_id", ""),
                    capability=metadata.get("capability", ""),
                    success_count=metadata.get("success_count", 0),
                    failure_count=metadata.get("failure_count", 0),
                    avg_duration_seconds=metadata.get("avg_duration_seconds", 0),
                    workspace_id=self._workspace_id,
                    confidence=conf,
                )
                if record.agent_id:
                    records.append(record)

            # Sort by success rate
            records.sort(
                key=lambda r: r.success_count / max(1, r.success_count + r.failure_count),
                reverse=True,
            )

            # Cache results
            if use_cache:
                cache_key = capability.lower()
                self._capability_cache[cache_key] = records
                self._cache_times[cache_key] = time.time()

            return records[:limit]

        except (OSError, ConnectionError, RuntimeError) as e:
            logger.error("Failed to get capability recommendations: %s", e)
            return []

    async def get_task_history(
        self,
        task_type: str,
        limit: int = 20,
    ) -> list[TaskOutcome]:
        """
        Get historical task outcomes for a task type.

        Args:
            task_type: Type of task to query
            limit: Maximum outcomes to return

        Returns:
            List of TaskOutcome sorted by recency
        """
        if not self._knowledge_mound:
            return []

        try:
            query_result = await self._knowledge_mound.query(
                query=f"task {task_type}",
                limit=limit,
                workspace_id=self._workspace_id,
            )
            results = query_result.items if hasattr(query_result, "items") else []

            outcomes = []
            for result in results:
                # KnowledgeItem has metadata as dict attribute
                metadata = getattr(result, "metadata", {}) or {}
                if metadata.get("type") != "control_plane_task_outcome":
                    continue

                outcome = TaskOutcome(
                    task_id=metadata.get("task_id", ""),
                    task_type=metadata.get("task_type", ""),
                    agent_id=metadata.get("agent_id", ""),
                    success=metadata.get("success", False),
                    duration_seconds=metadata.get("duration_seconds", 0),
                    workspace_id=self._workspace_id,
                    error_message=metadata.get("error_message"),
                )
                if outcome.task_id:
                    outcomes.append(outcome)

            return outcomes

        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.error("Failed to get task history: %s", e)
            return []

    # =========================================================================
    # Cross-Workspace Federation
    # =========================================================================

    async def share_insight_cross_workspace(
        self,
        insight: CrossWorkspaceInsight,
    ) -> bool:
        """
        Share an insight across workspaces via KM federation.

        Args:
            insight: Insight to share

        Returns:
            True if shared successfully
        """
        if not self._knowledge_mound:
            return False

        try:
            from aragora.knowledge.unified.types import (
                KnowledgeItem,
                KnowledgeSource,
                ConfidenceLevel,
            )

            # Map confidence value to enum
            if insight.confidence >= 0.8:
                confidence = ConfidenceLevel.HIGH
            elif insight.confidence >= 0.6:
                confidence = ConfidenceLevel.MEDIUM
            else:
                confidence = ConfidenceLevel.LOW
            now = datetime.now()

            # Create item with organization-wide visibility
            item = KnowledgeItem(
                id=f"cp_insight_{insight.insight_id}",
                content=insight.content,
                source=KnowledgeSource.INSIGHT,
                source_id=insight.insight_id,
                confidence=confidence,
                created_at=now,
                updated_at=now,
                metadata={
                    "type": "cross_workspace_insight",
                    "insight_id": insight.insight_id,
                    "source_workspace": insight.source_workspace,
                    "target_workspaces": insight.target_workspaces,
                    "task_type": insight.task_type,
                    "workspace_id": insight.source_workspace,
                },
            )

            # Ingest with organization visibility
            await self._knowledge_mound.ingest(item)

            self._stats["cross_workspace_shares"] += 1
            self._emit_event(
                "cp_insight_shared",
                {
                    "insight_id": insight.insight_id,
                    "source_workspace": insight.source_workspace,
                    "target_count": len(insight.target_workspaces),
                },
            )

            return True

        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.error("Failed to share cross-workspace insight: %s", e)
            return False

    async def get_cross_workspace_insights(
        self,
        task_type: str,
        limit: int = 10,
    ) -> list[CrossWorkspaceInsight]:
        """
        Get insights from other workspaces for a task type.

        Args:
            task_type: Type of task to query insights for
            limit: Maximum insights to return

        Returns:
            List of CrossWorkspaceInsight from other workspaces
        """
        if not self._knowledge_mound:
            return []

        try:
            # Query for organization-wide insights
            query_result = await self._knowledge_mound.query(
                query=f"cross workspace insight {task_type}",
                limit=limit,
                workspace_id="__organization__",  # Query across workspaces
            )
            results = query_result.items if hasattr(query_result, "items") else []

            insights = []
            for result in results:
                # KnowledgeItem has metadata as dict attribute
                metadata = getattr(result, "metadata", {}) or {}
                if metadata.get("type") != "cross_workspace_insight":
                    continue

                # Skip insights from our own workspace
                if metadata.get("source_workspace") == self._workspace_id:
                    continue

                # Get content and confidence from KnowledgeItem
                content = getattr(result, "content", "")
                conf = getattr(result, "confidence", 0.8)
                if hasattr(conf, "value"):
                    conf = conf.value

                insight = CrossWorkspaceInsight(
                    insight_id=metadata.get("insight_id", ""),
                    source_workspace=metadata.get("source_workspace", ""),
                    target_workspaces=metadata.get("target_workspaces", []),
                    task_type=metadata.get("task_type", ""),
                    content=content,
                    confidence=conf,
                    created_at=metadata.get("created_at", ""),
                )
                if insight.insight_id:
                    insights.append(insight)

            return insights

        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.error("Failed to get cross-workspace insights: %s", e)
            return []

    # =========================================================================
    # Bidirectional Sync: KM → Agent Selection
    # =========================================================================

    async def get_similar_task_outcomes(
        self,
        task_type: str,
        question: str,
        limit: int = 10,
    ) -> list[TaskOutcome]:
        """
        Retrieve similar past task outcomes for learning.

        Uses semantic similarity to find tasks similar to the given question,
        enabling learning from historical patterns.

        Args:
            task_type: Type of task to filter by
            question: Question or task description to find similar outcomes
            limit: Maximum outcomes to return

        Returns:
            List of TaskOutcome sorted by similarity
        """
        if not self._knowledge_mound:
            return []

        try:
            # Query KM with semantic search
            query_result = await self._knowledge_mound.query(
                query=f"task {task_type} {question[:200]}",  # Truncate long questions
                limit=limit * 2,  # Over-fetch for filtering
                workspace_id=self._workspace_id,
            )
            results = query_result.items if hasattr(query_result, "items") else []

            outcomes = []
            for result in results:
                # KnowledgeItem has metadata as dict attribute
                metadata = getattr(result, "metadata", {}) or {}
                if metadata.get("type") != "control_plane_task_outcome":
                    continue
                if metadata.get("task_type") != task_type:
                    continue

                # Get score from result (if available via similarity_score attribute)
                score = getattr(result, "similarity_score", 0.0)

                outcome = TaskOutcome(
                    task_id=metadata.get("task_id", ""),
                    task_type=metadata.get("task_type", ""),
                    agent_id=metadata.get("agent_id", ""),
                    success=metadata.get("success", False),
                    duration_seconds=metadata.get("duration_seconds", 0),
                    workspace_id=self._workspace_id,
                    error_message=metadata.get("error_message"),
                    metadata={
                        "similarity_score": score,
                        **{
                            k: v
                            for k, v in metadata.items()
                            if k
                            not in [
                                "type",
                                "task_id",
                                "task_type",
                                "agent_id",
                                "success",
                                "duration_seconds",
                                "error_message",
                            ]
                        },
                    },
                )
                if outcome.task_id:
                    outcomes.append(outcome)

            # Sort by similarity (highest first)
            outcomes.sort(
                key=lambda o: o.metadata.get("similarity_score", 0),
                reverse=True,
            )

            logger.debug("Found %s similar task outcomes for %s", len(outcomes), task_type)

            return outcomes[:limit]

        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.error("Failed to get similar task outcomes: %s", e)
            return []

    async def get_agent_success_rates(
        self,
        task_type: str,
        agents: list[str],
        recency_days: int = 30,
    ) -> dict[str, float]:
        """
        Get historical success rates per agent for a task type.

        Calculates success rate from stored task outcomes with
        time-weighted recency bias.

        Args:
            task_type: Type of task to analyze
            agents: List of agent IDs to query
            recency_days: How many days back to consider

        Returns:
            Dict mapping agent_id to success rate (0.0-1.0)
        """
        if not self._knowledge_mound:
            return dict.fromkeys(agents, 0.5)  # Default 50% if no KM

        try:
            # Query for task outcomes
            query_result = await self._knowledge_mound.query(
                query=f"task outcome {task_type}",
                limit=500,  # Query many for statistical significance
                workspace_id=self._workspace_id,
            )
            results = query_result.items if hasattr(query_result, "items") else []

            # Aggregate by agent
            agent_stats: dict[str, dict[str, int]] = {
                agent: {"success": 0, "total": 0} for agent in agents
            }

            import time as time_module

            cutoff_time = time_module.time() - (recency_days * 86400)

            for result in results:
                # KnowledgeItem has metadata as dict attribute
                metadata = getattr(result, "metadata", {}) or {}
                if metadata.get("type") != "control_plane_task_outcome":
                    continue
                if metadata.get("task_type") != task_type:
                    continue

                agent_id = metadata.get("agent_id", "")
                if agent_id not in agent_stats:
                    continue

                # Check recency (if timestamp available)
                created_at = metadata.get("created_at")
                if created_at and isinstance(created_at, (int, float)):
                    if created_at < cutoff_time:
                        continue  # Skip old results

                agent_stats[agent_id]["total"] += 1
                if metadata.get("success", False):
                    agent_stats[agent_id]["success"] += 1

            # Calculate success rates
            success_rates = {}
            for agent_id, stats in agent_stats.items():
                if stats["total"] > 0:
                    success_rates[agent_id] = stats["success"] / stats["total"]
                else:
                    success_rates[agent_id] = 0.5  # Default for no history

            logger.debug("Success rates for %s: %s", task_type, success_rates)

            return success_rates

        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.error("Failed to get agent success rates: %s", e)
            return dict.fromkeys(agents, 0.5)

    async def get_agent_recommendations_for_task(
        self,
        task_type: str,
        available_agents: list[str],
        required_capabilities: list[str] | None = None,
        top_n: int = 3,
    ) -> list[dict[str, Any]]:
        """
        Get agent recommendations for a task based on KM history.

        Combines capability performance and task-specific success rates
        to recommend the best agents.

        Args:
            task_type: Type of task
            available_agents: List of available agent IDs
            required_capabilities: Required capabilities (optional)
            top_n: Number of recommendations to return

        Returns:
            List of agent recommendations with scores
        """
        recommendations = []

        # Get success rates
        success_rates = await self.get_agent_success_rates(task_type, available_agents)

        # Get capability recommendations if specified
        capability_scores: dict[str, float] = {}
        if required_capabilities:
            for capability in required_capabilities:
                cap_records = await self.get_capability_recommendations(capability)
                for record in cap_records:
                    if record.agent_id in available_agents:
                        total = record.success_count + record.failure_count
                        if total > 0:
                            score = record.success_count / total
                            current = capability_scores.get(record.agent_id, 0)
                            capability_scores[record.agent_id] = max(current, score)

        # Combine scores
        for agent_id in available_agents:
            task_score = success_rates.get(agent_id, 0.5)
            cap_score = capability_scores.get(agent_id, 0.5)

            # Weight: 60% task success, 40% capability
            combined_score = (task_score * 0.6) + (cap_score * 0.4)

            recommendations.append(
                {
                    "agent_id": agent_id,
                    "combined_score": combined_score,
                    "task_success_rate": task_score,
                    "capability_score": cap_score,
                    "confidence": min(1.0, combined_score * 1.1),  # Boost slightly
                }
            )

        # Sort by combined score
        recommendations.sort(key=lambda r: cast(float, r["combined_score"]), reverse=True)

        return recommendations[:top_n]

    # =========================================================================
    # Stats and Metrics
    # =========================================================================

    def get_stats(self) -> dict[str, Any]:
        """Get adapter statistics."""
        return {
            **self._stats,
            "workspace_id": self._workspace_id,
            "cache_size": len(self._capability_cache),
            "has_knowledge_mound": self._knowledge_mound is not None,
            "has_coordinator": self._coordinator is not None,
        }

    def clear_cache(self) -> int:
        """Clear all caches and return count of cleared items."""
        count = len(self._capability_cache)
        self._capability_cache.clear()
        self._cache_times.clear()
        return count


__all__ = [
    "ControlPlaneAdapter",
    "TaskOutcome",
    "AgentCapabilityRecord",
    "CrossWorkspaceInsight",
]
