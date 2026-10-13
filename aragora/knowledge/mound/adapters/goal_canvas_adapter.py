"""
GoalCanvasAdapter - Syncs goal canvas nodes/edges to the Knowledge Mound.

Each canvas node becomes a KnowledgeNode with type ``goal_{goal_type}``
(e.g. ``goal_goal``, ``goal_strategy``). Canvas-level visual metadata
(position, size, style) is stored in ``metadata["canvas"]``.

Edges become KnowledgeRelationship entries.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any

from aragora.knowledge.mound.adapters._base import (
    EventCallback,
    KnowledgeMoundAdapter,
)
from aragora.knowledge.mound_types import (
    KnowledgeNode,
    KnowledgeRelationship,
    NodeType,
    ProvenanceChain,
    ProvenanceType,
    RelationshipType,
)

logger = logging.getLogger(__name__)


def _content_hash(text: str) -> str:
    """Short SHA-256 hash for provenance integrity."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class GoalCanvasAdapter(KnowledgeMoundAdapter):
    """Knowledge Mound adapter for Goal Canvas persistence."""

    adapter_name = "goal_canvas"

    # Mapping from GoalNodeType value -> KM NodeType
    _GOAL_TO_KM_TYPE: dict[str, NodeType] = {
        "goal": "goal_goal",
        "principle": "goal_principle",
        "strategy": "goal_strategy",
        "milestone": "goal_milestone",
        "metric": "goal_metric",
        "risk": "goal_risk",
    }

    def __init__(
        self,
        event_callback: EventCallback | None = None,
        enable_resilience: bool = True,
    ):
        super().__init__(
            event_callback=event_callback,
            enable_resilience=enable_resilience,
        )
        # Local caches: canvas_node_id -> km_node_id
        self._node_map: dict[str, str] = {}
        self._edge_map: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Node sync
    # ------------------------------------------------------------------

    def sync_node_to_km(
        self,
        canvas_node: dict[str, Any],
        canvas_id: str,
        user_id: str,
    ) -> str:
        """Convert a goal canvas node dict to a KnowledgeNode and store it.

        Args:
            canvas_node: Dict with keys: id, label, data (including goal_type,
                priority, measurable, description), position, size, style.
            canvas_id: Owning canvas ID.
            user_id: User who created/modified the node.

        Returns:
            KM node ID.
        """
        data = canvas_node.get("data", {})
        goal_type = data.get("goal_type", "goal")
        default_node_type: NodeType = "goal_goal"
        km_type = self._GOAL_TO_KM_TYPE.get(goal_type, default_node_type)

        label = canvas_node.get("label", "")
        description = data.get("description", "")
        content = f"{label}\n{description}".strip() if description else label

        km_node_id = f"kn_goal_{_content_hash(canvas_node.get('id', ''))}"

        _node = KnowledgeNode(
            id=km_node_id,
            node_type=km_type,  # type: ignore[arg-type]
            content=content,
            confidence=float(data.get("confidence", 0.5)),
            provenance=ProvenanceChain(
                source_type=ProvenanceType.USER,
                source_id=canvas_id,
                user_id=user_id,
            ),
            workspace_id=data.get("workspace_id", ""),
            metadata={
                "canvas_id": canvas_id,
                "canvas_node_id": canvas_node.get("id", ""),
                "goal_type": goal_type,
                "priority": data.get("priority", "medium"),
                "measurable": data.get("measurable", ""),
                "source_idea_ids": data.get("source_idea_ids", []),
                "canvas": {
                    "position": canvas_node.get("position", {}),
                    "size": canvas_node.get("size", {}),
                    "style": canvas_node.get("style", {}),
                },
            },
            topics=data.get("tags", []),
        )

        # Store in local cache
        self._node_map[canvas_node.get("id", "")] = km_node_id

        self._emit_event(
            "goal_node_synced",
            {
                "canvas_id": canvas_id,
                "canvas_node_id": canvas_node.get("id", ""),
                "km_node_id": km_node_id,
                "goal_type": goal_type,
            },
        )

        return km_node_id

    # ------------------------------------------------------------------
    # Edge sync
    # ------------------------------------------------------------------

    def sync_edge_to_km(
        self,
        edge: dict[str, Any],
        canvas_id: str,
    ) -> str:
        """Convert a canvas edge dict to a KnowledgeRelationship.

        Args:
            edge: Dict with keys: id, source_id, target_id, edge_type, label.
            canvas_id: Owning canvas ID.

        Returns:
            KM relationship ID.
        """
        kr_id = f"kr_goal_{_content_hash(edge.get('id', str(uuid.uuid4())))}"

        edge_type = edge.get("edge_type", edge.get("type", "related_to"))
        relationship_type = self._map_edge_type(edge_type)

        _rel = KnowledgeRelationship(
            id=kr_id,
            from_node_id=self._node_map.get(edge.get("source_id", edge.get("source", "")), ""),
            to_node_id=self._node_map.get(edge.get("target_id", edge.get("target", "")), ""),
            relationship_type=relationship_type,  # type: ignore[arg-type]
            metadata={
                "canvas_id": canvas_id,
                "canvas_edge_id": edge.get("id", ""),
                "label": edge.get("label", ""),
            },
        )

        self._edge_map[edge.get("id", "")] = kr_id
        return kr_id

    # ------------------------------------------------------------------
    # Bulk sync
    # ------------------------------------------------------------------

    def sync_canvas_to_km(
        self,
        canvas_dict: dict[str, Any],
        user_id: str,
    ) -> dict[str, str]:
        """Batch-sync an entire goal canvas to KM.

        Args:
            canvas_dict: Canvas dict with nodes and edges lists.
            user_id: User performing the sync.

        Returns:
            Mapping of canvas_node_id -> km_node_id.
        """
        canvas_id = canvas_dict.get("id", "")

        for node in canvas_dict.get("nodes", []):
            self.sync_node_to_km(node, canvas_id, user_id)

        for edge in canvas_dict.get("edges", []):
            self.sync_edge_to_km(edge, canvas_id)

        self._emit_event(
            "goal_canvas_synced",
            {
                "canvas_id": canvas_id,
                "node_count": len(canvas_dict.get("nodes", [])),
                "edge_count": len(canvas_dict.get("edges", [])),
            },
        )

        return dict(self._node_map)

    # ------------------------------------------------------------------
    # Load from KM
    # ------------------------------------------------------------------

    def load_canvas_from_km(
        self,
        canvas_id: str,
        km_nodes: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Reconstruct a goal canvas dict from KM nodes.

        Args:
            canvas_id: Canvas to reconstruct.
            km_nodes: List of KnowledgeNode dicts with metadata.

        Returns:
            Canvas-compatible dict or None if no matching nodes.
        """
        matching = [n for n in km_nodes if n.get("metadata", {}).get("canvas_id") == canvas_id]
        if not matching:
            return None

        nodes = []
        for km_node in matching:
            meta = km_node.get("metadata", {})
            canvas_meta = meta.get("canvas", {})
            goal_type = meta.get("goal_type", "goal")

            nodes.append(
                {
                    "id": meta.get("canvas_node_id", km_node["id"]),
                    "type": "knowledge",
                    "position": canvas_meta.get("position", {"x": 0, "y": 0}),
                    "size": canvas_meta.get("size", {"width": 220, "height": 80}),
                    "label": km_node.get("content", "").split("\n")[0],
                    "data": {
                        "goal_type": goal_type,
                        "priority": meta.get("priority", "medium"),
                        "measurable": meta.get("measurable", ""),
                        "description": "\n".join(km_node.get("content", "").split("\n")[1:]),
                        "confidence": km_node.get("confidence", 0.5),
                        "tags": km_node.get("topics", []),
                        "km_node_id": km_node["id"],
                        "source_idea_ids": meta.get("source_idea_ids", []),
                        "stage": "goals",
                        "rf_type": "goalNode",
                    },
                    "style": canvas_meta.get("style", {}),
                }
            )

        return {
            "id": canvas_id,
            "nodes": nodes,
            "edges": [],
            "metadata": {"stage": "goals", "source": "km_restore"},
        }

    # ------------------------------------------------------------------
    # Required adapter interface
    # ------------------------------------------------------------------

    async def sync_to_km(
        self,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        """Forward sync: push cached nodes to KM."""
        return {
            "synced_nodes": len(self._node_map),
            "synced_edges": len(self._edge_map),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _map_edge_type(edge_type: str) -> RelationshipType:
        """Map a canvas/stage edge type to a KM RelationshipType."""
        mapping: dict[str, RelationshipType] = {
            "requires": "related_to",
            "blocks": "related_to",
            "follows": "related_to",
            "derived_from": "derived_from",
            "implements": "related_to",
            "supports": "supports",
            "conflicts": "contradicts",
            "decomposes_into": "related_to",
        }
        default_relationship: RelationshipType = "related_to"
        return mapping.get(edge_type, default_relationship)


__all__ = ["GoalCanvasAdapter"]
