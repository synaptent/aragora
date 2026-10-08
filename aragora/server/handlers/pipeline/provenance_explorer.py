"""
Provenance Explorer REST API Handler.

Serves provenance data in the format expected by the ProvenanceExplorer React
component.  The component fetches two endpoints using the singular ``/graph/``
path prefix:

  GET /api/v1/pipeline/graph/:graphId/react-flow
      Returns nodes and edges formatted for React Flow with ProvenanceNode
      data (id, type, label, hash, metadata).

  GET /api/v1/pipeline/graph/:graphId/provenance/:nodeId
      Walks parent_ids backward from *nodeId* and returns the provenance
      chain as {nodes, edges} suitable for the component's fallback layout.

Both endpoints bridge the existing ``UniversalGraph`` / ``GraphStore``
infrastructure to the ProvenanceExplorer's expected wire format.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from aragora.server.versioning.compat import strip_version_prefix

from ..base import (
    SAFE_ID_PATTERN,
    HandlerResult,
    error_response,
    json_response,
    validate_path_segment,
)
from ..secure import SecureHandler
from ..utils.decorators import require_permission  # noqa: F401 (RBAC enforcement test)
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

_provenance_limiter = RateLimiter(requests_per_minute=60)

# Lazy-loaded store
_store = None


def _get_store():
    global _store
    if _store is None:
        from aragora.pipeline.graph_store import get_graph_store

        _store = get_graph_store()
    return _store


# Stage-to-provenance type mapping (matches ProvenanceExplorer STAGE_COLORS)
_STAGE_TYPE_MAP: dict[str, str] = {
    "ideas": "debate",
    "goals": "goal",
    "actions": "action",
    "orchestration": "orchestration",
}


def _node_to_provenance(node: Any) -> dict[str, Any]:
    """Convert a UniversalNode to a ProvenanceNode dict.

    The ProvenanceExplorer component expects::

        { id, type, label, hash, metadata }

    where ``type`` is one of ``debate | goal | action | orchestration``.
    """
    stage_value = node.stage.value if hasattr(node.stage, "value") else str(node.stage)
    return {
        "id": node.id,
        "type": _STAGE_TYPE_MAP.get(stage_value, "debate"),
        "label": node.label,
        "hash": node.content_hash or "",
        "metadata": {
            "stage": stage_value,
            "subtype": node.node_subtype,
            "status": node.status,
            "confidence": node.confidence,
            "description": node.description,
            **(node.metadata or {}),
        },
    }


class ProvenanceExplorerHandler(SecureHandler):
    """Handler for provenance explorer endpoints (singular /graph/ prefix)."""

    ROUTES = ["/api/v1/pipeline/graph"]

    def __init__(self, ctx: dict[str, Any] | None = None):
        self.ctx = ctx or {}

    def can_handle(self, path: str) -> bool:
        cleaned = strip_version_prefix(path)
        return cleaned.startswith("/api/pipeline/graph/")

    def handle(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        """Route GET requests for the provenance explorer."""
        cleaned = strip_version_prefix(path)
        client_ip = get_client_ip(handler)
        if not _provenance_limiter.is_allowed(client_ip):
            return error_response("Rate limit exceeded", 429)

        # Parse: /api/pipeline/graph/:graphId/react-flow
        #    or: /api/pipeline/graph/:graphId/provenance/:nodeId
        parts = cleaned.split("/")
        # parts[0]="" parts[1]="api" parts[2]="pipeline" parts[3]="graph"
        #       [4]=graphId [5]=sub [6]=nodeId?

        if len(parts) < 6:
            return None

        graph_id = parts[4]
        ok, err = validate_path_segment(graph_id, "graph_id", SAFE_ID_PATTERN)
        if not ok:
            return error_response(cast(str, err), 400)

        sub = parts[5]

        if sub == "react-flow" and len(parts) == 6:
            return self._react_flow_provenance(graph_id, query_params)

        if sub == "provenance" and len(parts) >= 7:
            node_id = parts[6]
            ok2, err2 = validate_path_segment(node_id, "node_id", SAFE_ID_PATTERN)
            if not ok2:
                return error_response(cast(str, err2), 400)
            return self._node_provenance(graph_id, node_id)

        return None

    # -- Endpoint implementations ------------------------------------------

    def _react_flow_provenance(
        self,
        graph_id: str,
        params: dict[str, Any],
    ) -> HandlerResult:
        """Return the full graph as React Flow nodes/edges in ProvenanceNode format.

        Response shape::

            {
                "nodes": [{ "id", "position": {x, y}, "data": ProvenanceNode }],
                "edges": [{ "id", "source", "target", "label" }]
            }
        """
        store = _get_store()
        graph = store.get(graph_id)
        if graph is None:
            return error_response("Graph not found", 404)

        # Build nodes with auto-layout (grid) and ProvenanceNode data
        flow_nodes = []
        for idx, node in enumerate(graph.nodes.values()):
            flow_nodes.append(
                {
                    "id": node.id,
                    "position": {
                        "x": node.position_x if node.position_x else (idx % 4) * 250,
                        "y": node.position_y if node.position_y else (idx // 4) * 150,
                    },
                    "data": _node_to_provenance(node),
                }
            )

        # Build edges
        flow_edges = []
        for edge in graph.edges.values():
            flow_edges.append(
                {
                    "id": edge.id,
                    "source": edge.source_id,
                    "target": edge.target_id,
                    "label": edge.label
                    or (
                        edge.edge_type.value
                        if hasattr(edge.edge_type, "value")
                        else str(edge.edge_type)
                    ),
                }
            )

        return json_response({"nodes": flow_nodes, "edges": flow_edges})

    def _node_provenance(
        self,
        graph_id: str,
        node_id: str,
    ) -> HandlerResult:
        """Return the provenance chain for a single node as {nodes, edges}.

        Walks parent_ids backward from *node_id* and builds both the node
        list and edge list so the ProvenanceExplorer can render the chain.

        Response shape::

            {
                "nodes": [ProvenanceNode, ...],
                "edges": [{ "id", "source", "target", "label" }]
            }
        """
        store = _get_store()
        chain = store.get_provenance_chain(graph_id, node_id)

        if not chain:
            return error_response(f"Node '{node_id}' not found in graph", 404)

        # Convert chain nodes to ProvenanceNode format
        prov_nodes = [_node_to_provenance(n) for n in chain]

        # Build edges from parent relationships within the chain
        chain_ids = {n.id for n in chain}
        edges = []
        edge_idx = 0
        for node in chain:
            for parent_id in node.parent_ids:
                if parent_id in chain_ids:
                    edges.append(
                        {
                            "id": f"prov-edge-{edge_idx}",
                            "source": parent_id,
                            "target": node.id,
                            "label": "derives",
                        }
                    )
                    edge_idx += 1

        return json_response({"nodes": prov_nodes, "edges": edges})


__all__ = ["ProvenanceExplorerHandler"]
