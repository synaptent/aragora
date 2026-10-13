"""
CostAdapter - Bridges Billing/Cost Tracking to the Knowledge Mound.

This adapter enables bidirectional integration between the cost tracking
system and the Knowledge Mound:

- Data flow IN: Budget alerts and cost anomalies stored in KM
- Data flow OUT: Historical cost patterns retrieved for anomaly detection
- Reverse flow: KM patterns inform budget alert thresholds

The adapter provides:
- Budget alert storage (WARNING level and above)
- Cost anomaly detection and persistence
- Historical cost pattern retrieval
- Agent cost analytics

ID Prefix: ct_

Note: This adapter is opt-in (enable_cost_adapter: bool = False in config)
as cost data may be sensitive.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

if TYPE_CHECKING:
    from aragora.knowledge.unified.types import KnowledgeItem
    from aragora.billing.cost_tracker import (
        BudgetAlert,
        CostTracker,
    )

EventCallback = Callable[[str, dict[str, Any]], None]

logger = logging.getLogger(__name__)

from aragora.knowledge.mound.adapters._base import KnowledgeMoundAdapter
from aragora.knowledge.mound.adapters._reverse_flow_base import ReverseFlowMixin
from aragora.knowledge.mound.adapters._semantic_mixin import SemanticSearchMixin
from aragora.knowledge.mound.adapters._fusion_mixin import FusionMixin


@dataclass
class AlertSearchResult:
    """Wrapper for alert search results with adapter metadata."""

    alert: dict[str, Any]
    relevance_score: float = 0.0


@dataclass
class CostAnomaly:
    """A detected cost anomaly."""

    id: str
    workspace_id: str | None
    agent_id: str | None
    anomaly_type: str  # "spike", "unusual_model", "high_latency", etc.
    severity: float  # 0-1
    description: str
    expected_value: float
    actual_value: float
    variance_ratio: float  # actual/expected
    detected_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "agent_id": self.agent_id,
            "anomaly_type": self.anomaly_type,
            "severity": self.severity,
            "description": self.description,
            "expected_value": self.expected_value,
            "actual_value": self.actual_value,
            "variance_ratio": self.variance_ratio,
            "detected_at": self.detected_at.isoformat() if self.detected_at else None,
            "metadata": self.metadata,
        }


class CostAdapter(FusionMixin, SemanticSearchMixin, ReverseFlowMixin, KnowledgeMoundAdapter):
    """
    Adapter that bridges CostTracker to the Knowledge Mound.

    Provides methods for the Knowledge Mound's federated query system:
    - store_alert: Store budget alerts (WARNING+ level)
    - store_anomaly: Store cost anomalies
    - get_cost_patterns: Retrieve historical cost patterns
    - get_agent_costs: Retrieve agent cost history

    Note: This adapter is opt-in due to cost data sensitivity.

    Usage:
        from aragora.billing.cost_tracker import CostTracker
        from aragora.knowledge.mound.adapters import CostAdapter

        tracker = CostTracker()
        adapter = CostAdapter(tracker)

        # Store budget alert
        adapter.store_alert(alert)

        # Get cost patterns for anomaly detection
        patterns = adapter.get_cost_patterns(workspace_id)
    """

    ID_PREFIX = "ct_"

    # Mixin configuration
    adapter_name = "cost"
    source_type = "cost"

    # Thresholds
    MIN_ALERT_LEVEL = "warning"  # Store WARNING and above
    MIN_ANOMALY_VARIANCE = 2.0  # Store anomalies with 2x+ variance

    # Alert level ordering for comparison
    ALERT_LEVELS = ["info", "warning", "critical", "exceeded"]

    # ========================================================================
    # FusionMixin required method implementations
    # ========================================================================

    def _get_fusion_sources(self) -> list[str]:
        """Return list of source adapters this adapter can fuse data from."""
        return ["consensus", "evidence", "insights"]

    def _extract_fusible_data(
        self,
        km_item: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Extract fusible data from a KM item."""
        metadata = km_item.get("metadata", {})
        confidence = km_item.get("confidence") or metadata.get("confidence")
        if confidence is None:
            return None
        return {
            "confidence": float(confidence),
            "is_valid": float(confidence) >= 0.5,
            "source_id": km_item.get("id") or metadata.get("source_id"),
            "severity": metadata.get("severity", 0.5),
            "anomaly_type": metadata.get("anomaly_type"),
            "sources": metadata.get("sources", []),
        }

    def _apply_fusion_result(
        self,
        record: Any,
        fusion_result: Any,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Apply a fusion result to a cost record."""
        try:
            fused_confidence = getattr(fusion_result, "fused_confidence", None)
            if fused_confidence is None:
                return False
            if isinstance(record, dict):
                record["km_fused"] = True
                record["km_fused_confidence"] = fused_confidence
                if metadata:
                    record["fusion_metadata"] = metadata
                logger.debug(
                    f"Applied fusion result to cost record: fused_confidence={fused_confidence:.3f}"
                )
                return True
            return False
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.warning("Failed to apply fusion result to cost: %s", e)
            return False

    # ========================================================================
    # SemanticSearchMixin required method implementations
    # ========================================================================

    def _get_record_by_id(self, record_id: str) -> Any | None:
        """Get an alert, anomaly, or cost snapshot record by ID.

        Searches alerts, anomalies, and cost snapshots. Handles the ct_ prefix
        from the SemanticStore.
        """
        raw_id = record_id
        if record_id.startswith(self.ID_PREFIX):
            raw_id = record_id[len(self.ID_PREFIX) :]

        for storage in (self._alerts, self._anomalies, self._cost_snapshots):
            if record_id in storage:
                return storage[record_id]
            if raw_id in storage:
                return storage[raw_id]
            prefixed = f"{self.ID_PREFIX}{raw_id}"
            if prefixed in storage:
                return storage[prefixed]

        return None

    def _record_to_dict(self, record: Any, similarity: float = 0.0) -> dict[str, Any]:
        """Convert a cost record to dict."""
        if isinstance(record, dict):
            result = dict(record)
            result["similarity"] = similarity
            return result
        # Handle CostAnomaly dataclass
        if hasattr(record, "to_dict"):
            result = record.to_dict()
            result["similarity"] = similarity
            return result
        return {
            "id": getattr(record, "id", None),
            "content": getattr(record, "description", ""),
            "severity": getattr(record, "severity", 0.0),
            "similarity": similarity,
            "metadata": getattr(record, "metadata", {}),
        }

    def _extract_record_id(self, source_id: str) -> str:
        """Extract record ID from prefixed source ID."""
        if source_id.startswith(self.ID_PREFIX):
            return source_id[len(self.ID_PREFIX) :]
        return source_id

    # ========================================================================
    # Initialization
    # ========================================================================

    def __init__(
        self,
        cost_tracker: CostTracker | None = None,
        enable_dual_write: bool = False,
        event_callback: EventCallback | None = None,
        enable_resilience: bool = True,
    ):
        """
        Initialize the adapter.

        Args:
            cost_tracker: Optional CostTracker instance
            enable_dual_write: If True, writes go to both systems during migration
            event_callback: Optional callback for emitting events (event_type, data)
            enable_resilience: If True, enables circuit breaker and bulkhead protection
        """
        # Initialize base adapter (handles dual_write, event_callback, resilience, metrics, tracing)
        super().__init__(
            enable_dual_write=enable_dual_write,
            event_callback=event_callback,
            enable_resilience=enable_resilience,
        )

        self._cost_tracker = cost_tracker

        # In-memory storage for queries (will be replaced by KM backend)
        self._alerts: dict[str, dict[str, Any]] = {}
        self._anomalies: dict[str, dict[str, Any]] = {}
        self._cost_snapshots: dict[str, dict[str, Any]] = {}

        # Indices for fast lookup
        self._workspace_alerts: dict[str, list[str]] = {}  # workspace -> [alert_ids]
        self._workspace_anomalies: dict[str, list[str]] = {}  # workspace -> [anomaly_ids]
        self._agent_costs: dict[str, list[str]] = {}  # agent -> [snapshot_ids]

    # set_event_callback, _emit_event inherited from KnowledgeMoundAdapter

    # ReverseFlowMixin required methods
    def _get_record_for_validation(self, source_id: str) -> Any | None:
        """Get a record for validation (required by ReverseFlowMixin)."""
        # Check alerts first, then anomalies
        if source_id in self._alerts:
            return self._alerts[source_id]
        if source_id in self._anomalies:
            return self._anomalies[source_id]
        return None

    def _apply_km_validation(
        self,
        record: Any,
        km_confidence: float,
        cross_refs: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Apply KM validation to a cost record (required by ReverseFlowMixin)."""
        record["km_validated"] = True
        record["km_validation_confidence"] = km_confidence
        record["km_validation_timestamp"] = datetime.now(timezone.utc).isoformat()

        if metadata:
            # Handle false positive detection
            if metadata.get("false_positive", False):
                record["km_false_positive"] = True
                if "level" in record:  # Alert
                    record["severity_adjusted"] = True
                    record["original_level"] = record.get("level", "unknown")
                    record["level"] = "info"
                elif "severity" in record:  # Anomaly
                    record["severity"] = 0.0

            # Handle confirmation
            if metadata.get("confirmed", False):
                record["km_confirmed"] = True

        if cross_refs:
            record["km_cross_references"] = cross_refs

        return True

    def _extract_source_id(self, item: dict[str, Any]) -> str | None:
        """Extract source ID from KM item (override for ReverseFlowMixin)."""
        return item.get("source_id") or item.get("id")

    @property
    def cost_tracker(self) -> CostTracker | None:
        """Access the underlying CostTracker."""
        return self._cost_tracker

    def _alert_level_meets_threshold(self, level: str) -> bool:
        """Check if alert level meets minimum threshold."""
        try:
            level_idx = self.ALERT_LEVELS.index(level.lower())
            threshold_idx = self.ALERT_LEVELS.index(self.MIN_ALERT_LEVEL)
            return level_idx >= threshold_idx
        except ValueError:
            return False

    def store_alert(
        self,
        alert: BudgetAlert,
    ) -> str | None:
        """
        Store a budget alert in the Knowledge Mound.

        Only stores alerts at WARNING level or above.

        Args:
            alert: The BudgetAlert to store

        Returns:
            The alert ID if stored, None if below threshold
        """
        level = alert.level.value if hasattr(alert.level, "value") else str(alert.level)

        if not self._alert_level_meets_threshold(level):
            logger.debug("Alert %s below level threshold: %s", alert.id, level)
            return None

        alert_id = f"{self.ID_PREFIX}alert_{alert.id}"

        alert_data = {
            "id": alert_id,
            "original_id": alert.id,
            "budget_id": alert.budget_id,
            "workspace_id": alert.workspace_id,
            "org_id": alert.org_id,
            "level": level,
            "message": alert.message,
            "current_spend": str(alert.current_spend),
            "limit": str(alert.limit),
            "percentage": alert.percentage,
            "created_at": (
                alert.created_at.isoformat()
                if alert.created_at
                else datetime.now(timezone.utc).isoformat()
            ),
            "acknowledged": alert.acknowledged,
            "stored_at": datetime.now(timezone.utc).isoformat(),
        }

        self._alerts[alert_id] = alert_data

        # Update indices
        if alert.workspace_id:
            if alert.workspace_id not in self._workspace_alerts:
                self._workspace_alerts[alert.workspace_id] = []
            self._workspace_alerts[alert.workspace_id].append(alert_id)

        logger.info("Stored budget alert: %s (level=%s)", alert_id, level)
        return alert_id

    def store_anomaly(
        self,
        anomaly: CostAnomaly,
    ) -> str | None:
        """
        Store a cost anomaly in the Knowledge Mound.

        Only stores anomalies with variance > 2x.

        Args:
            anomaly: The CostAnomaly to store

        Returns:
            The anomaly ID if stored, None if below threshold
        """
        if anomaly.variance_ratio < self.MIN_ANOMALY_VARIANCE:
            logger.debug(
                f"Anomaly {anomaly.id} below variance threshold: {anomaly.variance_ratio:.2f}"
            )
            return None

        anomaly_id = f"{self.ID_PREFIX}anomaly_{anomaly.id}"

        anomaly_data = anomaly.to_dict()
        anomaly_data["id"] = anomaly_id
        anomaly_data["original_id"] = anomaly.id
        anomaly_data["stored_at"] = datetime.now(timezone.utc).isoformat()

        self._anomalies[anomaly_id] = anomaly_data

        # Update indices
        if anomaly.workspace_id:
            if anomaly.workspace_id not in self._workspace_anomalies:
                self._workspace_anomalies[anomaly.workspace_id] = []
            self._workspace_anomalies[anomaly.workspace_id].append(anomaly_id)

        logger.info(f"Stored cost anomaly: {anomaly_id} (variance={anomaly.variance_ratio:.2f}x)")
        return anomaly_id

    def store_cost_snapshot(
        self,
        workspace_id: str,
        agent_id: str | None,
        total_cost_usd: float,
        tokens_in: int,
        tokens_out: int,
        api_calls: int,
        period: str = "daily",
    ) -> str:
        """
        Store a cost snapshot for historical tracking.

        Args:
            workspace_id: Workspace ID
            agent_id: Optional agent ID
            total_cost_usd: Total cost in USD
            tokens_in: Input tokens used
            tokens_out: Output tokens generated
            api_calls: Number of API calls
            period: Aggregation period (hourly, daily, weekly)

        Returns:
            The snapshot ID
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        snapshot_id = f"{self.ID_PREFIX}snap_{workspace_id}_{timestamp.replace(':', '-')}"

        snapshot_data = {
            "id": snapshot_id,
            "workspace_id": workspace_id,
            "agent_id": agent_id,
            "total_cost_usd": total_cost_usd,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "api_calls": api_calls,
            "period": period,
            "created_at": timestamp,
        }

        self._cost_snapshots[snapshot_id] = snapshot_data

        # Update indices
        if agent_id:
            if agent_id not in self._agent_costs:
                self._agent_costs[agent_id] = []
            self._agent_costs[agent_id].append(snapshot_id)

        logger.debug("Stored cost snapshot: %s", snapshot_id)
        return snapshot_id

    def store_debate_cost_summary(
        self,
        summary_dict: dict[str, Any],
    ) -> str:
        """Store a per-debate cost summary for historical analytics.

        Persists the output of DebateCostSummary.to_dict() as a cost
        snapshot in the Knowledge Mound, enabling cross-debate cost
        comparisons and trend analysis.

        Args:
            summary_dict: Serialized DebateCostSummary (from .to_dict()).

        Returns:
            The stored snapshot ID.
        """
        debate_id = summary_dict.get("debate_id", "unknown")
        timestamp = datetime.now(timezone.utc).isoformat()
        snapshot_id = f"{self.ID_PREFIX}debate_{debate_id}"

        snapshot_data = {
            "id": snapshot_id,
            "debate_id": debate_id,
            "type": "debate_cost_summary",
            "total_cost_usd": summary_dict.get("total_cost_usd", "0"),
            "total_tokens_in": summary_dict.get("total_tokens_in", 0),
            "total_tokens_out": summary_dict.get("total_tokens_out", 0),
            "total_calls": summary_dict.get("total_calls", 0),
            "per_agent": summary_dict.get("per_agent", {}),
            "per_round": summary_dict.get("per_round", {}),
            "model_usage": summary_dict.get("model_usage", {}),
            "started_at": summary_dict.get("started_at"),
            "completed_at": summary_dict.get("completed_at"),
            "stored_at": timestamp,
        }

        self._cost_snapshots[snapshot_id] = snapshot_data

        logger.info(
            "Stored debate cost summary: %s cost=$%s",
            snapshot_id,
            summary_dict.get("total_cost_usd", "0"),
        )
        return snapshot_id

    def get_alert(self, alert_id: str) -> dict[str, Any] | None:
        """
        Get a specific alert by ID.

        Args:
            alert_id: The alert ID

        Returns:
            Alert dict or None
        """
        if not alert_id.startswith(self.ID_PREFIX):
            alert_id = f"{self.ID_PREFIX}alert_{alert_id}"
        return self._alerts.get(alert_id)

    def get_anomaly(self, anomaly_id: str) -> dict[str, Any] | None:
        """
        Get a specific anomaly by ID.

        Args:
            anomaly_id: The anomaly ID

        Returns:
            Anomaly dict or None
        """
        if not anomaly_id.startswith(self.ID_PREFIX):
            anomaly_id = f"{self.ID_PREFIX}anomaly_{anomaly_id}"
        return self._anomalies.get(anomaly_id)

    def get_workspace_alerts(
        self,
        workspace_id: str,
        min_level: str = "warning",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Get alerts for a workspace.

        Args:
            workspace_id: The workspace ID
            min_level: Minimum alert level to include
            limit: Maximum results

        Returns:
            List of alert dicts ordered by time (newest first)
        """
        alert_ids = self._workspace_alerts.get(workspace_id, [])
        results = []

        for alert_id in alert_ids:
            alert = self._alerts.get(alert_id)
            if not alert:
                continue

            if not self._alert_level_meets_threshold(alert.get("level", "info")):
                continue

            results.append(alert)

        results.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        return results[:limit]

    def get_workspace_anomalies(
        self,
        workspace_id: str,
        min_severity: float = 0.0,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Get anomalies for a workspace.

        Args:
            workspace_id: The workspace ID
            min_severity: Minimum severity threshold
            limit: Maximum results

        Returns:
            List of anomaly dicts
        """
        anomaly_ids = self._workspace_anomalies.get(workspace_id, [])
        results = []

        for anomaly_id in anomaly_ids:
            anomaly = self._anomalies.get(anomaly_id)
            if not anomaly:
                continue

            if anomaly.get("severity", 0) < min_severity:
                continue

            results.append(anomaly)

        results.sort(key=lambda x: x.get("detected_at", ""), reverse=True)

        return results[:limit]

    def get_cost_patterns(
        self,
        workspace_id: str,
        agent_id: str | None = None,
        limit: int = 30,
    ) -> dict[str, Any]:
        """
        Get historical cost patterns for anomaly detection.

        Returns average costs and variance for comparison.

        Args:
            workspace_id: The workspace ID
            agent_id: Optional agent filter
            limit: Number of recent snapshots to analyze

        Returns:
            Pattern dict with avg, stddev, etc.
        """
        # Get relevant snapshots
        snapshots = []
        for snap in self._cost_snapshots.values():
            if snap.get("workspace_id") != workspace_id:
                continue
            if agent_id and snap.get("agent_id") != agent_id:
                continue
            snapshots.append(snap)

        if not snapshots:
            return {
                "workspace_id": workspace_id,
                "agent_id": agent_id,
                "sample_size": 0,
                "avg_cost": 0.0,
                "avg_tokens": 0,
                "avg_calls": 0,
            }

        # Sort by time and take recent
        snapshots.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        recent = snapshots[:limit]

        # Calculate stats
        costs = [s.get("total_cost_usd", 0) for s in recent]
        tokens = [s.get("tokens_in", 0) + s.get("tokens_out", 0) for s in recent]
        calls = [s.get("api_calls", 0) for s in recent]

        avg_cost = sum(costs) / len(costs) if costs else 0
        avg_tokens = sum(tokens) / len(tokens) if tokens else 0
        avg_calls = sum(calls) / len(calls) if calls else 0

        # Calculate variance
        if len(costs) > 1:
            import statistics

            cost_stddev = statistics.stdev(costs)
        else:
            cost_stddev = 0.0

        return {
            "workspace_id": workspace_id,
            "agent_id": agent_id,
            "sample_size": len(recent),
            "avg_cost": avg_cost,
            "cost_stddev": cost_stddev,
            "avg_tokens": avg_tokens,
            "avg_calls": avg_calls,
            "min_cost": min(costs) if costs else 0,
            "max_cost": max(costs) if costs else 0,
        }

    def get_agent_cost_history(
        self,
        agent_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Get cost history for an agent.

        Args:
            agent_id: The agent ID
            limit: Maximum snapshots to return

        Returns:
            List of snapshot dicts ordered by time (newest first)
        """
        snapshot_ids = self._agent_costs.get(agent_id, [])
        results = []

        for snap_id in snapshot_ids:
            snap = self._cost_snapshots.get(snap_id)
            if snap:
                results.append(snap)

        results.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        return results[:limit]

    def detect_anomalies(
        self,
        workspace_id: str,
        current_cost: float,
        current_tokens: int,
        current_calls: int,
    ) -> list[CostAnomaly]:
        """
        Detect cost anomalies compared to historical patterns.

        Args:
            workspace_id: The workspace ID
            current_cost: Current period cost
            current_tokens: Current period tokens
            current_calls: Current period API calls

        Returns:
            List of detected anomalies
        """
        import uuid

        patterns = self.get_cost_patterns(workspace_id)

        if patterns["sample_size"] < 5:
            return []  # Not enough data

        anomalies = []

        # Check cost spike
        if patterns["avg_cost"] > 0:
            cost_ratio = current_cost / patterns["avg_cost"]
            if cost_ratio > self.MIN_ANOMALY_VARIANCE:
                anomalies.append(
                    CostAnomaly(
                        id=str(uuid.uuid4())[:12],
                        workspace_id=workspace_id,
                        agent_id=None,
                        anomaly_type="cost_spike",
                        severity=min(1.0, cost_ratio / 5),  # Scale severity
                        description=f"Cost spike detected: {cost_ratio:.1f}x normal",
                        expected_value=patterns["avg_cost"],
                        actual_value=current_cost,
                        variance_ratio=cost_ratio,
                        detected_at=datetime.now(timezone.utc),
                    )
                )

        # Check API call spike
        if patterns["avg_calls"] > 0:
            call_ratio = current_calls / patterns["avg_calls"]
            if call_ratio > self.MIN_ANOMALY_VARIANCE:
                anomalies.append(
                    CostAnomaly(
                        id=str(uuid.uuid4())[:12],
                        workspace_id=workspace_id,
                        agent_id=None,
                        anomaly_type="call_spike",
                        severity=min(1.0, call_ratio / 5),
                        description=f"API call spike detected: {call_ratio:.1f}x normal",
                        expected_value=patterns["avg_calls"],
                        actual_value=current_calls,
                        variance_ratio=call_ratio,
                        detected_at=datetime.now(timezone.utc),
                    )
                )

        return anomalies

    def to_knowledge_item(self, alert: dict[str, Any]) -> KnowledgeItem:
        """
        Convert an alert dict to a KnowledgeItem.

        Args:
            alert: The alert dictionary

        Returns:
            KnowledgeItem for unified knowledge mound API
        """
        from aragora.knowledge.unified.types import (
            ConfidenceLevel,
            KnowledgeItem,
            KnowledgeSource,
        )

        level = alert.get("level", "info")
        if level == "exceeded":
            confidence = ConfidenceLevel.VERIFIED
        elif level == "critical":
            confidence = ConfidenceLevel.HIGH
        elif level == "warning":
            confidence = ConfidenceLevel.MEDIUM
        else:
            confidence = ConfidenceLevel.LOW

        created_at = alert.get("created_at")
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except ValueError:
                created_at = datetime.now(timezone.utc)
        elif created_at is None:
            created_at = datetime.now(timezone.utc)

        return KnowledgeItem(
            id=alert["id"],
            content=alert.get("message", "Budget alert"),
            source=KnowledgeSource.COST,
            source_id=alert.get("original_id", alert["id"]),
            confidence=confidence,
            created_at=created_at,
            updated_at=created_at,
            metadata={
                "workspace_id": alert.get("workspace_id", ""),
                "level": level,
                "percentage": alert.get("percentage", 0),
                "current_spend": alert.get("current_spend", "0"),
                "limit": alert.get("limit", "0"),
            },
            importance=alert.get("percentage", 0) / 100,  # Normalize to 0-1
        )

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about stored cost data."""
        level_counts: dict[str, int] = {}
        for alert in self._alerts.values():
            lvl = alert.get("level", "unknown")
            level_counts[lvl] = level_counts.get(lvl, 0) + 1

        return {
            "total_alerts": len(self._alerts),
            "total_anomalies": len(self._anomalies),
            "total_snapshots": len(self._cost_snapshots),
            "workspaces_with_alerts": len(self._workspace_alerts),
            "agents_tracked": len(self._agent_costs),
            "alert_levels": level_counts,
        }


__all__ = [
    "CostAdapter",
    "CostAnomaly",
    "AlertSearchResult",
]
