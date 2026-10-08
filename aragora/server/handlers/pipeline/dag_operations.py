"""DAG Operations REST Handler.

Exposes the DAGOperationsCoordinator via REST endpoints:

- POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/debate
- POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/decompose
- POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/prioritize
- POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/assign-agents
- POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/execute
- POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/find-precedents
- POST /api/v1/pipeline/dag/{graph_id}/cluster-ideas
- POST /api/v1/pipeline/dag/{graph_id}/auto-flow
- GET  /api/v1/pipeline/dag/{graph_id}

Every route needs an org-scoped caller (``canvas:read`` to read the graph,
``canvas:run`` for the operations) and answers the missing-graph 404 when
the caller's org does not own the graph.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from aragora.server.handlers.base import HandlerResult, error_response, handle_errors, json_response
from aragora.tenancy import pipeline_access
from aragora.tenancy.record_scope import OrgScope, record_not_found

logger = logging.getLogger(__name__)

# Path patterns
_DAG_BASE = re.compile(r"^/api/v1/pipeline/dag/([a-zA-Z0-9_-]+)$")
_DAG_NODE_OP = re.compile(
    r"^/api/v1/pipeline/dag/([a-zA-Z0-9_-]+)/nodes/([a-zA-Z0-9_-]+)/(debate|decompose|prioritize|assign-agents|execute|find-precedents)$"
)
_DAG_CLUSTER = re.compile(r"^/api/v1/pipeline/dag/([a-zA-Z0-9_-]+)/cluster-ideas$")
_DAG_AUTO_FLOW = re.compile(r"^/api/v1/pipeline/dag/([a-zA-Z0-9_-]+)/auto-flow$")


def _get_graph_store() -> Any:
    """Lazy-load the graph store."""
    from aragora.pipeline.graph_store import get_graph_store

    return get_graph_store()


def _get_coordinator(graph_id: str) -> tuple[Any, Any] | None:
    """Load graph from store and create coordinator.

    Returns (coordinator, graph) or None if graph not found.
    """
    from aragora.pipeline.dag_operations import DAGOperationsCoordinator

    store = _get_graph_store()
    graph = store.get(graph_id)
    if graph is None:
        return None
    coordinator = DAGOperationsCoordinator(graph, store=store)
    return coordinator, graph


class DAGOperationsHandler:
    """HTTP handler for DAG pipeline operations."""

    ROUTES = [
        "POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/debate",
        "POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/decompose",
        "POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/prioritize",
        "POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/assign-agents",
        "POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/execute",
        "POST /api/v1/pipeline/dag/{graph_id}/nodes/{node_id}/find-precedents",
        "POST /api/v1/pipeline/dag/{graph_id}/cluster-ideas",
        "POST /api/v1/pipeline/dag/{graph_id}/auto-flow",
        "GET /api/v1/pipeline/dag/{graph_id}",
    ]

    def __init__(self, ctx: dict[str, Any] | None = None) -> None:
        self.ctx = ctx or {}

    def can_handle(self, path: str) -> bool:
        """Check if this handler can handle the given path."""
        return "/api/v1/pipeline/dag/" in path

    @staticmethod
    def _check_permission(
        handler: Any, permission: str
    ) -> tuple[OrgScope, None] | tuple[None, HandlerResult]:
        """``(scope, None)`` when the caller has an org and ``permission``, else ``(None, error)``."""
        return pipeline_access.authorize_pipeline_request(handler, permission)

    @staticmethod
    def _owns(graph_id: str, scope: OrgScope) -> bool:
        return pipeline_access.graph_owned(graph_id, scope, store=_get_graph_store())

    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> Any:
        """Dispatch GET requests."""
        m = _DAG_BASE.match(path)
        if not m:
            return None
        scope, denial = self._check_permission(handler, pipeline_access.PIPELINE_READ)
        if scope is None:
            return denial
        if not self._owns(m.group(1), scope):
            return record_not_found("Graph")
        return self._handle_get_graph(m.group(1))

    @handle_errors("DAG operation")
    def handle_post(self, path: str, query_params: dict[str, Any], handler: Any) -> Any:
        """Dispatch POST requests."""
        node_op = _DAG_NODE_OP.match(path)
        cluster = _DAG_CLUSTER.match(path)
        match = node_op or cluster or _DAG_AUTO_FLOW.match(path)
        if match is None:
            return None
        scope, denial = self._check_permission(handler, pipeline_access.PIPELINE_RUN)
        if scope is None:
            return denial
        if not self._owns(match.group(1), scope):
            return record_not_found("Graph")

        body = self._get_request_body(handler)
        if node_op:
            graph_id, node_id, operation = node_op.group(1), node_op.group(2), node_op.group(3)
            return self._dispatch_node_op(graph_id, node_id, operation, body)
        if cluster:
            return self._handle_cluster_ideas(cluster.group(1), body)
        return self._handle_auto_flow(match.group(1), body)

    @staticmethod
    def _get_request_body(handler: Any) -> dict[str, Any]:
        """Extract JSON body from the request handler."""
        try:
            if hasattr(handler, "request") and hasattr(handler.request, "body"):
                raw = handler.request.body
                if raw:
                    return json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            pass
        return {}

    async def _handle_get_graph(self, graph_id: str) -> HandlerResult:
        """GET /api/v1/pipeline/dag/{graph_id}"""
        store = _get_graph_store()
        graph = store.get(graph_id)
        if graph is None:
            return error_response(f"Graph {graph_id} not found", 404)

        return json_response({"data": graph.to_dict()})

    async def _dispatch_node_op(
        self,
        graph_id: str,
        node_id: str,
        operation: str,
        body: dict[str, Any],
    ) -> HandlerResult:
        """Dispatch a node-level operation."""
        pair = _get_coordinator(graph_id)
        if pair is None:
            return error_response(f"Graph {graph_id} not found", 404)
        coordinator, graph = pair

        if operation == "debate":
            result = await coordinator.debate_node(
                node_id,
                agents=body.get("agents"),
                rounds=body.get("rounds", 3),
            )
        elif operation == "decompose":
            result = await coordinator.decompose_node(node_id)
        elif operation == "prioritize":
            result = await coordinator.prioritize_children(node_id)
        elif operation == "assign-agents":
            # For assign-agents on a single node, wrap in list
            node_ids = body.get("node_ids", [node_id])
            result = await coordinator.assign_agents(node_ids)
        elif operation == "execute":
            result = await coordinator.execute_node(node_id)
        elif operation == "find-precedents":
            result = await coordinator.find_precedents(
                node_id,
                max_results=body.get("max_results", 5),
            )
        else:
            return error_response(f"Unknown operation: {operation}", 400)

        status = 200 if result.success else 400
        return json_response(
            {
                "data": {
                    "success": result.success,
                    "message": result.message,
                    "created_nodes": result.created_nodes,
                    "metadata": result.metadata,
                }
            },
            status,
        )

    async def _handle_cluster_ideas(
        self,
        graph_id: str,
        body: dict[str, Any],
    ) -> HandlerResult:
        """POST /api/v1/pipeline/dag/{graph_id}/cluster-ideas"""
        pair = _get_coordinator(graph_id)
        if pair is None:
            return error_response(f"Graph {graph_id} not found", 404)
        coordinator, graph = pair

        ideas = body.get("ideas", [])
        if not ideas:
            return error_response("Missing required field: ideas", 400)

        threshold = body.get("threshold", 0.3)
        result = await coordinator.cluster_ideas(ideas, threshold=threshold)

        status = 200 if result.success else 400
        return json_response(
            {
                "data": {
                    "success": result.success,
                    "message": result.message,
                    "created_nodes": result.created_nodes,
                    "metadata": result.metadata,
                }
            },
            status,
        )

    async def _handle_auto_flow(
        self,
        graph_id: str,
        body: dict[str, Any],
    ) -> HandlerResult:
        """POST /api/v1/pipeline/dag/{graph_id}/auto-flow"""
        pair = _get_coordinator(graph_id)
        if pair is None:
            return error_response(f"Graph {graph_id} not found", 404)
        coordinator, graph = pair

        ideas = body.get("ideas", [])
        if not ideas:
            return error_response("Missing required field: ideas", 400)

        config = body.get("config")
        result = await coordinator.auto_flow(ideas, config=config)

        status = 200 if result.success else 400
        return json_response(
            {
                "data": {
                    "success": result.success,
                    "message": result.message,
                    "created_nodes": result.created_nodes,
                    "metadata": result.metadata,
                }
            },
            status,
        )


__all__ = ["DAGOperationsHandler"]
