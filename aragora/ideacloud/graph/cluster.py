"""IdeaCluster — a group of related ideas.

Clusters emerge from explicit connections and tag overlap.
They are the primary unit for debate proposition generation
and pipeline export.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from aragora.ideacloud.graph.node import _now_iso


def _generate_cluster_id() -> str:
    """Generate a short unique ID with cl_ prefix."""
    return f"cl_{uuid.uuid4().hex[:7]}"


@dataclass
class IdeaCluster:
    """A group of related ideas."""

    id: str = field(default_factory=_generate_cluster_id)
    name: str = ""
    description: str = ""
    node_ids: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    confidence: float = 0.5
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    @property
    def size(self) -> int:
        return len(self.node_ids)

    def add_node(self, node_id: str) -> None:
        """Add a node to this cluster (idempotent)."""
        if node_id not in self.node_ids:
            self.node_ids.append(node_id)
            self.updated_at = _now_iso()

    def remove_node(self, node_id: str) -> None:
        """Remove a node from this cluster."""
        if node_id in self.node_ids:
            self.node_ids.remove(node_id)
            self.updated_at = _now_iso()

    def to_dict(self) -> dict[str, Any]:
        """Serialize for index.json."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "node_ids": self.node_ids,
            "tags": self.tags,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> IdeaCluster:
        """Deserialize from index.json entry."""
        return cls(
            id=d.get("id", _generate_cluster_id()),
            name=d.get("name", ""),
            description=d.get("description", ""),
            node_ids=d.get("node_ids", []),
            tags=d.get("tags", []),
            confidence=float(d.get("confidence", 0.5)),
            created_at=d.get("created_at", _now_iso()),
            updated_at=d.get("updated_at", _now_iso()),
        )

    def __repr__(self) -> str:
        return f"IdeaCluster(id={self.id!r}, name={self.name!r}, size={self.size})"
