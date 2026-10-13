"""Cross-region synchronization event types.

Shared by regional leader election (:mod:`aragora.resilience.leader`) and the
control-plane regional event bus (:mod:`aragora.control_plane.regional_sync`,
which re-exports both names).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RegionalEventType(Enum):
    """Types of regional synchronization events."""

    AGENT_REGISTERED = "agent_registered"
    AGENT_UPDATED = "agent_updated"
    AGENT_UNREGISTERED = "agent_unregistered"
    AGENT_HEARTBEAT = "agent_heartbeat"

    TASK_SUBMITTED = "task_submitted"
    TASK_ASSIGNED = "task_assigned"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_CANCELLED = "task_cancelled"

    LEADER_ELECTED = "leader_elected"
    LEADER_RESIGNED = "leader_resigned"

    REGION_HEALTH = "region_health"
    REGION_JOINED = "region_joined"
    REGION_LEFT = "region_left"


@dataclass
class RegionalEvent:
    """
    An event for cross-region synchronization.

    Uses timestamps for conflict-free ordering (last-write-wins).
    """

    event_type: RegionalEventType
    source_region: str
    entity_id: str  # Agent ID or Task ID
    timestamp: float = field(default_factory=time.time)
    data: dict[str, Any] = field(default_factory=dict)
    version: int = 1  # For future schema evolution

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "event_type": self.event_type.value,
            "source_region": self.source_region,
            "entity_id": self.entity_id,
            "timestamp": self.timestamp,
            "data": self.data,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RegionalEvent:
        """Deserialize from dictionary."""
        return cls(
            event_type=RegionalEventType(data["event_type"]),
            source_region=data["source_region"],
            entity_id=data["entity_id"],
            timestamp=data.get("timestamp", time.time()),
            data=data.get("data", {}),
            version=data.get("version", 1),
        )

    def is_newer_than(self, other: RegionalEvent) -> bool:
        """Check if this event is newer than another (for conflict resolution)."""
        return self.timestamp > other.timestamp


__all__ = ["RegionalEvent", "RegionalEventType"]
