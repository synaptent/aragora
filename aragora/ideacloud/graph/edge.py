"""IdeaEdge — connections between ideas in the graph.

Edges represent relationships: supports, refutes, relates_to, extends, conflicts.
They are stored both as wiki-links in markdown bodies and structurally in index.json.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from aragora.ideacloud.graph.node import _now_iso

EdgeType = Literal[
    "supports",
    "refutes",
    "relates_to",
    "extends",
    "conflicts",
]


@dataclass
class IdeaEdge:
    """A directed connection between two ideas."""

    source_id: str
    target_id: str
    edge_type: str = "relates_to"  # EdgeType
    weight: float = 1.0  # 0.0-1.0 strength
    reason: str = ""  # Why these are connected
    auto_created: bool = False  # True if from auto-linking
    confidence: float = 0.5
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        """Serialize for index.json."""
        d = {
            "source": self.source_id,
            "target": self.target_id,
            "type": self.edge_type,
            "weight": self.weight,
            "auto_created": self.auto_created,
            "confidence": self.confidence,
            "created_at": self.created_at,
        }
        if self.reason:
            d["reason"] = self.reason
        return d

    @classmethod
    def from_dict(cls, d: dict) -> IdeaEdge:
        """Deserialize from index.json entry."""
        return cls(
            source_id=d["source"],
            target_id=d["target"],
            edge_type=d.get("type", "relates_to"),
            weight=float(d.get("weight", 1.0)),
            reason=d.get("reason", ""),
            auto_created=bool(d.get("auto_created", False)),
            confidence=float(d.get("confidence", 0.5)),
            created_at=d.get("created_at", _now_iso()),
        )

    def __repr__(self) -> str:
        return (
            f"IdeaEdge({self.source_id} --{self.edge_type}--> {self.target_id}, "
            f"w={self.weight:.2f})"
        )
