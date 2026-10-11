"""
KMEloBridge - Bridges Knowledge Mound patterns to ELO system.

This bridge enables bidirectional integration between the Knowledge Mound
and the ELO ranking system:

- Periodically queries KM for agent-related patterns
- Analyzes patterns to detect success contributors, domain experts, etc.
- Computes and applies ELO adjustments based on knowledge quality
- Tracks adjustment history for auditing

This creates a feedback loop where agents that consistently contribute
to successful outcomes get ELO boosts, while those whose claims are
frequently contradicted receive penalties.

Usage:
    from aragora.ranking.km_elo_bridge import KMEloBridge

    bridge = KMEloBridge(elo_system, elo_adapter, knowledge_mound)

    # Run sync (typically called periodically or after debates)
    result = await bridge.sync_km_to_elo()

    # Get specific agent's KM patterns
    patterns = await bridge.get_agent_km_patterns("claude")
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, cast

# Prometheus metrics - optional dependency
try:
    from prometheus_client import Counter, Gauge, Histogram

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

# ============================================================================
# KMEloBridge Prometheus Metrics
# ============================================================================

if PROMETHEUS_AVAILABLE:
    # Sync operation metrics
    KM_ELO_SYNC_TOTAL = Counter(
        "aragora_km_elo_sync_total",
        "Total KM → ELO sync operations",
        ["status"],  # status: completed, failed, skipped
    )

    KM_ELO_SYNC_DURATION = Histogram(
        "aragora_km_elo_sync_duration_seconds",
        "KM → ELO sync operation duration",
        buckets=[0.1, 0.5, 1, 5, 10, 30, 60, 120],
    )

    # Pattern detection metrics
    KM_ELO_PATTERNS_DETECTED = Counter(
        "aragora_km_elo_patterns_detected_total",
        "Total KM patterns detected for ELO analysis",
        ["agent"],
    )

    KM_ELO_AGENTS_ANALYZED = Counter(
        "aragora_km_elo_agents_analyzed_total",
        "Total agents analyzed in KM → ELO sync",
    )

    # Adjustment metrics
    KM_ELO_ADJUSTMENTS_RECOMMENDED = Counter(
        "aragora_km_elo_adjustments_recommended_total",
        "Total ELO adjustments recommended from KM patterns",
    )

    KM_ELO_ADJUSTMENTS_APPLIED = Counter(
        "aragora_km_elo_adjustments_applied_total",
        "Total ELO adjustments actually applied",
    )

    KM_ELO_ADJUSTMENTS_SKIPPED = Counter(
        "aragora_km_elo_adjustments_skipped_total",
        "Total ELO adjustments skipped (low confidence, etc.)",
    )

    # ELO change metrics
    KM_ELO_TOTAL_CHANGE = Histogram(
        "aragora_km_elo_total_change",
        "Total ELO rating change per sync operation",
        buckets=[-100, -50, -25, -10, 0, 10, 25, 50, 100],
    )

    KM_ELO_CHANGE_PER_AGENT = Histogram(
        "aragora_km_elo_change_per_agent",
        "ELO rating change per agent",
        ["agent"],
        buckets=[-50, -25, -10, -5, 0, 5, 10, 25, 50],
    )

    # Status gauges
    KM_ELO_SYNC_IN_PROGRESS = Gauge(
        "aragora_km_elo_sync_in_progress",
        "Whether a sync operation is currently in progress (0/1)",
    )

    KM_ELO_PENDING_ADJUSTMENTS = Gauge(
        "aragora_km_elo_pending_adjustments",
        "Number of pending ELO adjustments waiting to be applied",
    )

    KM_ELO_TOTAL_SYNCS = Gauge(
        "aragora_km_elo_total_syncs",
        "Total number of syncs completed since startup",
    )

    KM_ELO_LAST_SYNC_TIMESTAMP = Gauge(
        "aragora_km_elo_last_sync_timestamp",
        "Timestamp of the last successful sync (Unix epoch)",
    )


def _record_sync_start() -> None:
    """Record sync operation starting."""
    if PROMETHEUS_AVAILABLE:
        KM_ELO_SYNC_IN_PROGRESS.set(1)


def _record_sync_end(
    status: str,
    duration_ms: int,
    agents_analyzed: int,
    patterns_detected: int,
    adjustments_recommended: int,
    adjustments_applied: int,
    adjustments_skipped: int,
    total_elo_change: float,
    agents_affected: list[str],
) -> None:
    """Record sync operation completion with metrics."""
    if not PROMETHEUS_AVAILABLE:
        return

    # Sync status
    KM_ELO_SYNC_IN_PROGRESS.set(0)
    KM_ELO_SYNC_TOTAL.labels(status=status).inc()
    KM_ELO_SYNC_DURATION.observe(duration_ms / 1000.0)

    # Pattern and agent metrics
    KM_ELO_AGENTS_ANALYZED.inc(agents_analyzed)

    # Adjustment metrics
    if adjustments_recommended > 0:
        KM_ELO_ADJUSTMENTS_RECOMMENDED.inc(adjustments_recommended)
    if adjustments_applied > 0:
        KM_ELO_ADJUSTMENTS_APPLIED.inc(adjustments_applied)
    if adjustments_skipped > 0:
        KM_ELO_ADJUSTMENTS_SKIPPED.inc(adjustments_skipped)

    # ELO change metrics
    KM_ELO_TOTAL_CHANGE.observe(total_elo_change)

    # Timestamp
    if status == "completed":
        KM_ELO_LAST_SYNC_TIMESTAMP.set(time.time())


def _record_patterns_for_agent(agent_name: str, pattern_count: int) -> None:
    """Record patterns detected for a specific agent."""
    if PROMETHEUS_AVAILABLE and pattern_count > 0:
        KM_ELO_PATTERNS_DETECTED.labels(agent=agent_name).inc(pattern_count)


def _update_pending_adjustments(count: int) -> None:
    """Update the pending adjustments gauge."""
    if PROMETHEUS_AVAILABLE:
        KM_ELO_PENDING_ADJUSTMENTS.set(count)


def _update_total_syncs(count: int) -> None:
    """Update the total syncs gauge."""
    if PROMETHEUS_AVAILABLE:
        KM_ELO_TOTAL_SYNCS.set(count)


if TYPE_CHECKING:
    from aragora.knowledge.mound.adapters.performance_adapter import (
        EloAdapter,
        EloAdjustmentRecommendation,
        KMEloPattern,
    )
    from aragora.knowledge.mound.facade import KnowledgeMound
    from aragora.ranking.elo import EloSystem

logger = logging.getLogger(__name__)


@dataclass
class KMEloBridgeConfig:
    """Configuration for KMEloBridge."""

    # Sync settings
    sync_interval_hours: int = 24  # Interval between automatic syncs
    min_pattern_confidence: float = 0.7  # Min confidence for ELO adjustments
    max_adjustment_per_sync: float = 50.0  # Max ELO change per agent per sync

    # Pattern detection
    min_km_items_for_pattern: int = 5  # Min KM items to detect patterns
    pattern_lookback_days: int = 30  # How far back to look for patterns

    # Behavior
    auto_apply: bool = False  # Auto-apply adjustments (vs. recommend only)
    track_history: bool = True  # Track adjustment history
    batch_size: int = 20  # Agents to process per sync batch


@dataclass
class KMEloBridgeSyncResult:
    """Result of a KM → ELO sync operation."""

    agents_analyzed: int = 0
    patterns_detected: int = 0
    adjustments_recommended: int = 0
    adjustments_applied: int = 0
    adjustments_skipped: int = 0
    total_elo_change: float = 0.0
    agents_affected: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0
    timestamp: str = ""


class KMEloBridge:
    """
    Bridges Knowledge Mound patterns to ELO ranking system.

    Provides orchestration layer on top of EloAdapter's bidirectional
    methods, adding:
    - Periodic sync scheduling
    - Batch processing of agents
    - History tracking and auditing
    - Configuration management
    """

    def __init__(
        self,
        elo_system: EloSystem | None = None,
        elo_adapter: EloAdapter | None = None,
        knowledge_mound: KnowledgeMound | None = None,
        config: KMEloBridgeConfig | None = None,
    ):
        """
        Initialize the bridge.

        Args:
            elo_system: EloSystem for rankings
            elo_adapter: EloAdapter for KM integration
            knowledge_mound: KnowledgeMound for pattern queries
            config: Optional configuration
        """
        self._elo_system = elo_system
        self._elo_adapter = elo_adapter
        self._knowledge_mound = knowledge_mound
        self._config = config or KMEloBridgeConfig()

        # Sync state
        self._last_sync: float | None = None
        self._sync_in_progress: bool = False
        self._sync_lock = asyncio.Lock()

        # History tracking
        self._sync_history: list[KMEloBridgeSyncResult] = []
        self._max_history: int = 50
        self._total_syncs: int = 0
        self._total_adjustments: int = 0

    @property
    def elo_system(self) -> EloSystem | None:
        """Get the ELO system."""
        return self._elo_system

    @property
    def elo_adapter(self) -> EloAdapter | None:
        """Get the ELO adapter."""
        return self._elo_adapter

    @property
    def knowledge_mound(self) -> KnowledgeMound | None:
        """Get the knowledge mound."""
        return self._knowledge_mound

    def set_elo_system(self, elo_system: EloSystem) -> None:
        """Set the ELO system."""
        self._elo_system = elo_system
        if self._elo_adapter:
            self._elo_adapter.set_elo_system(elo_system)

    def set_elo_adapter(self, adapter: EloAdapter) -> None:
        """Set the ELO adapter."""
        self._elo_adapter = adapter

    def set_knowledge_mound(self, mound: KnowledgeMound) -> None:
        """Set the knowledge mound."""
        self._knowledge_mound = mound

    async def sync_km_to_elo(
        self,
        agent_names: list[str] | None = None,
        force: bool = False,
    ) -> KMEloBridgeSyncResult:
        """
        Sync KM patterns to ELO adjustments.

        Queries KM for patterns about agents, analyzes them, and
        computes/applies ELO adjustments.

        Args:
            agent_names: Optional list of agents to process (None = all)
            force: If True, bypass interval check

        Returns:
            KMEloBridgeSyncResult with operation details
        """
        async with self._sync_lock:
            if self._sync_in_progress:
                return KMEloBridgeSyncResult(
                    errors=["Sync already in progress"],
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
            self._sync_in_progress = True
            _record_sync_start()

        start_time = time.time()
        result = KMEloBridgeSyncResult(
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        sync_status = "failed"  # Default status, updated on success

        try:
            # Check interval if not forced
            if not force and self._last_sync:
                elapsed_hours = (time.time() - self._last_sync) / 3600
                if elapsed_hours < self._config.sync_interval_hours:
                    result.errors.append(
                        f"Sync interval not reached ({elapsed_hours:.1f}h / "
                        f"{self._config.sync_interval_hours}h)"
                    )
                    sync_status = "skipped"
                    return result

            # Get agents to process
            agents = agent_names or await self._get_all_agents()
            if not agents:
                result.errors.append("No agents to process")
                sync_status = "skipped"
                return result

            # Process agents in batches
            all_patterns: dict[str, list[KMEloPattern]] = {}

            for i in range(0, len(agents), self._config.batch_size):
                batch = agents[i : i + self._config.batch_size]

                for agent_name in batch:
                    try:
                        patterns = await self._analyze_agent_patterns(agent_name)
                        if patterns:
                            all_patterns[agent_name] = patterns
                            result.patterns_detected += len(patterns)
                            _record_patterns_for_agent(agent_name, len(patterns))
                    except (AttributeError, TypeError, ValueError, RuntimeError) as e:
                        error_msg = f"Error analyzing {agent_name}: {e}"
                        logger.error(error_msg)
                        result.errors.append(error_msg)

                result.agents_analyzed += len(batch)

            # Apply patterns via adapter
            if self._elo_adapter and all_patterns:
                sync_result = await self._elo_adapter.sync_km_to_elo(
                    agent_patterns=all_patterns,
                    max_adjustment=self._config.max_adjustment_per_sync,
                    min_confidence=self._config.min_pattern_confidence,
                    auto_apply=self._config.auto_apply,
                )

                result.adjustments_recommended = sync_result.adjustments_recommended
                result.adjustments_applied = sync_result.adjustments_applied
                result.adjustments_skipped = sync_result.adjustments_skipped
                result.total_elo_change = sync_result.total_elo_change
                result.agents_affected = sync_result.agents_affected

            self._last_sync = time.time()
            self._total_syncs += 1
            self._total_adjustments += result.adjustments_applied
            sync_status = "completed"

            # Update gauges
            _update_total_syncs(self._total_syncs)

        except (AttributeError, TypeError, ValueError, RuntimeError, OSError) as e:
            error_msg = f"Sync error: {e}"
            logger.error(error_msg, exc_info=True)
            result.errors.append(error_msg)
            sync_status = "failed"

        finally:
            self._sync_in_progress = False

        result.duration_ms = int((time.time() - start_time) * 1000)

        # Record metrics
        _record_sync_end(
            status=sync_status,
            duration_ms=result.duration_ms,
            agents_analyzed=result.agents_analyzed,
            patterns_detected=result.patterns_detected,
            adjustments_recommended=result.adjustments_recommended,
            adjustments_applied=result.adjustments_applied,
            adjustments_skipped=result.adjustments_skipped,
            total_elo_change=result.total_elo_change,
            agents_affected=result.agents_affected,
        )

        # Store in history
        if self._config.track_history:
            self._sync_history.append(result)
            if len(self._sync_history) > self._max_history:
                self._sync_history = self._sync_history[-self._max_history :]

        logger.info(
            "KM → ELO sync complete: agents=%s, patterns=%s, applied=%s, elo_change=%+.1f",
            result.agents_analyzed,
            result.patterns_detected,
            result.adjustments_applied,
            result.total_elo_change,
        )

        return result

    async def _get_all_agents(self) -> list[str]:
        """Get all agents from ELO system."""
        if not self._elo_system:
            return []

        try:
            ratings = self._elo_system.get_all_ratings()
            return [r.agent_name for r in ratings]
        except (AttributeError, TypeError, ValueError) as e:
            logger.error("Error getting agents: %s", e)
            return []

    async def _analyze_agent_patterns(
        self,
        agent_name: str,
    ) -> list[KMEloPattern]:
        """
        Analyze KM patterns for a specific agent.

        Args:
            agent_name: The agent to analyze

        Returns:
            List of detected patterns
        """
        if not self._elo_adapter:
            return []

        # Get KM items mentioning this agent
        km_items = await self._query_agent_km_items(agent_name)

        if len(km_items) < self._config.min_km_items_for_pattern:
            logger.debug("Insufficient KM items for %s: %s", agent_name, len(km_items))
            return []

        # Use adapter's pattern analysis
        patterns = await self._elo_adapter.analyze_km_patterns_for_agent(
            agent_name=agent_name,
            km_items=km_items,
            min_confidence=self._config.min_pattern_confidence,
        )

        return patterns

    async def _query_agent_km_items(
        self,
        agent_name: str,
    ) -> list[dict[str, Any]]:
        """Query KM for items related to an agent."""
        if not self._knowledge_mound:
            return []

        try:
            # Try different query methods
            if hasattr(self._knowledge_mound, "query_by_agent"):
                return await self._knowledge_mound.query_by_agent(
                    agent_name=agent_name,
                    limit=100,
                )
            elif hasattr(self._knowledge_mound, "query"):
                # KnowledgeMound.query return type varies by mixin; at runtime
                # it returns list[dict] for this call pattern.
                result = await self._knowledge_mound.query(
                    query=f"agent:{agent_name}",
                    limit=100,
                )
                return cast(list[dict[str, Any]], result)
            elif hasattr(self._knowledge_mound, "search"):
                return await self._knowledge_mound.search(
                    agent_name,
                    limit=100,
                )
        except (AttributeError, TypeError, ValueError, RuntimeError) as e:
            logger.error("Error querying KM for %s: %s", agent_name, e)

        return []

    async def get_agent_km_patterns(
        self,
        agent_name: str,
    ) -> list[KMEloPattern]:
        """
        Get stored KM patterns for an agent.

        Args:
            agent_name: The agent to query

        Returns:
            List of patterns (may be empty if not analyzed recently)
        """
        if not self._elo_adapter:
            return []

        return self._elo_adapter.get_agent_km_patterns(agent_name)

    async def get_pending_adjustments(
        self,
    ) -> list[EloAdjustmentRecommendation]:
        """Get pending ELO adjustments that haven't been applied."""
        if not self._elo_adapter:
            return []

        return self._elo_adapter.get_pending_adjustments()

    async def apply_pending_adjustments(
        self,
        agent_names: list[str] | None = None,
        min_confidence: float = 0.7,
    ) -> int:
        """
        Apply pending ELO adjustments.

        Args:
            agent_names: Optional list of agents to apply (None = all)
            min_confidence: Minimum confidence to apply

        Returns:
            Number of adjustments applied
        """
        if not self._elo_adapter:
            return 0

        pending = self._elo_adapter.get_pending_adjustments()
        applied = 0

        for adj in pending:
            if agent_names and adj.agent_name not in agent_names:
                continue

            if adj.confidence < min_confidence:
                continue

            success = await self._elo_adapter.apply_km_elo_adjustment(adj)
            if success:
                applied += 1
                self._total_adjustments += 1

        logger.info("Applied %s pending ELO adjustments", applied)
        return applied

    def get_status(self) -> dict[str, Any]:
        """Get bridge status and metrics."""
        pending = []
        if self._elo_adapter:
            pending = self._elo_adapter.get_pending_adjustments()

        return {
            "elo_system_available": self._elo_system is not None,
            "elo_adapter_available": self._elo_adapter is not None,
            "knowledge_mound_available": self._knowledge_mound is not None,
            "sync_in_progress": self._sync_in_progress,
            "last_sync": self._last_sync,
            "total_syncs": self._total_syncs,
            "total_adjustments": self._total_adjustments,
            "pending_adjustments": len(pending),
            "sync_history_count": len(self._sync_history),
            "config": {
                "sync_interval_hours": self._config.sync_interval_hours,
                "min_pattern_confidence": self._config.min_pattern_confidence,
                "max_adjustment": self._config.max_adjustment_per_sync,
                "auto_apply": self._config.auto_apply,
            },
        }

    def get_sync_history(
        self,
        limit: int = 10,
    ) -> list[KMEloBridgeSyncResult]:
        """Get recent sync history."""
        return self._sync_history[-limit:]

    def reset_metrics(self) -> None:
        """Reset metrics and history."""
        self._total_syncs = 0
        self._total_adjustments = 0
        self._sync_history = []
        self._last_sync = None

        if self._elo_adapter:
            self._elo_adapter.clear_pending_adjustments()


def create_km_elo_bridge(
    elo_system: EloSystem | None = None,
    elo_adapter: EloAdapter | None = None,
    knowledge_mound: KnowledgeMound | None = None,
    config: KMEloBridgeConfig | None = None,
) -> KMEloBridge:
    """Factory function to create KMEloBridge."""
    return KMEloBridge(
        elo_system=elo_system,
        elo_adapter=elo_adapter,
        knowledge_mound=knowledge_mound,
        config=config,
    )


__all__ = [
    "KMEloBridge",
    "KMEloBridgeConfig",
    "KMEloBridgeSyncResult",
    "create_km_elo_bridge",
]
