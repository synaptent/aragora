"""Task decomposition visualization API handler.

Endpoints:
- POST /api/v1/pipeline/:id/decompose/:node_id       Trigger decomposition
- GET  /api/v1/pipeline/:id/decompose/:node_id/tree   Get decomposition tree
"""

from __future__ import annotations

import logging
from typing import Any, cast

from aragora.server.versioning.compat import strip_version_prefix

from ..base import (
    SAFE_ID_PATTERN,
    BaseHandler,
    HandlerResult,
    error_response,
    json_response,
    validate_path_segment,
    handle_errors,
)
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

_decompose_limiter = RateLimiter(requests_per_minute=30)

# Lazy-loaded graph store
_store = None


def _get_store():
    global _store
    if _store is None:
        from aragora.pipeline.graph_store import get_graph_store

        _store = get_graph_store()
    return _store


def _parse_decompose_path(cleaned: str) -> tuple[str | None, str | None, str | None]:
    """Parse /api/pipeline/:id/decompose/:node_id[/tree].

    Returns (pipeline_id, node_id, sub) where sub is 'tree' or None.
    """
    parts = cleaned.split("/")
    # parts: ["", "api", "pipeline", id, "decompose", node_id, ...]
    if len(parts) >= 6 and parts[1] == "api" and parts[2] == "pipeline" and parts[4] == "decompose":
        pipeline_id = parts[3]
        node_id = parts[5]
        sub = parts[6] if len(parts) > 6 else None
        return pipeline_id, node_id, sub
    return None, None, None


class DecompositionHandler(BaseHandler):
    """Handler for task decomposition visualization endpoints."""

    ROUTES = ["/api/v1/pipeline"]

    def __init__(self, ctx: dict[str, Any] | None = None):
        self.ctx = ctx or {}

    def can_handle(self, path: str) -> bool:
        cleaned = strip_version_prefix(path)
        return "/decompose/" in cleaned and cleaned.startswith("/api/pipeline/")

    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Route GET requests (decomposition tree)."""
        cleaned = strip_version_prefix(path)
        client_ip = get_client_ip(handler)
        if not _decompose_limiter.is_allowed(client_ip):
            return error_response("Rate limit exceeded", 429)

        pipeline_id, node_id, sub = _parse_decompose_path(cleaned)
        if not pipeline_id or not node_id:
            return None

        ok, err = validate_path_segment(pipeline_id, "pipeline_id", SAFE_ID_PATTERN)
        if not ok:
            return error_response(cast(str, err), 400)
        ok2, err2 = validate_path_segment(node_id, "node_id", SAFE_ID_PATTERN)
        if not ok2:
            return error_response(cast(str, err2), 400)

        if sub == "tree":
            return self._get_decomposition_tree(pipeline_id, node_id)

        return None

    def _check_permission(self, handler: Any, permission: str) -> HandlerResult | None:
        """Check RBAC permission."""
        try:
            from aragora.billing.jwt_auth import extract_user_from_request
            from aragora.rbac.checker import get_permission_checker
            from aragora.rbac.models import AuthorizationContext

            user_ctx = extract_user_from_request(handler, None)
            if not user_ctx or not user_ctx.is_authenticated:
                return error_response("Authentication required", 401)

            auth_ctx = AuthorizationContext(
                user_id=cast(str, user_ctx.user_id),
                user_email=user_ctx.email,
                org_id=user_ctx.org_id,
                workspace_id=None,
                roles={user_ctx.role} if user_ctx.role else {"member"},
            )
            checker = get_permission_checker()
            decision = checker.check_permission(auth_ctx, permission)
            if not decision.allowed:
                logger.warning("Permission denied: %s", permission)
                return error_response("Permission denied", 403)
            return None
        except (ImportError, AttributeError, ValueError) as e:
            logger.debug("Permission check unavailable: %s", e)
            return None

    @handle_errors("task decomposition")
    def handle_post(self, path: str, body: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Route POST requests (trigger decomposition)."""
        auth_error = self._check_permission(handler, "pipeline:write")
        if auth_error:
            return auth_error

        cleaned = strip_version_prefix(path)
        client_ip = get_client_ip(handler)
        if not _decompose_limiter.is_allowed(client_ip):
            return error_response("Rate limit exceeded", 429)

        pipeline_id, node_id, _sub = _parse_decompose_path(cleaned)
        if not pipeline_id or not node_id:
            return None

        ok, err = validate_path_segment(pipeline_id, "pipeline_id", SAFE_ID_PATTERN)
        if not ok:
            return error_response(cast(str, err), 400)
        ok2, err2 = validate_path_segment(node_id, "node_id", SAFE_ID_PATTERN)
        if not ok2:
            return error_response(cast(str, err2), 400)

        return self._decompose_node(pipeline_id, node_id, body or {})

    def _decompose_node(
        self, pipeline_id: str, node_id: str, body: dict[str, Any]
    ) -> HandlerResult:
        store = _get_store()
        graph = store.get(pipeline_id)
        if graph is None:
            return error_response("Pipeline graph not found", 404)

        node = graph.nodes.get(node_id)
        if node is None:
            return error_response("Node not found", 404)

        # Try DAGOperationsCoordinator first
        try:
            from aragora.pipeline.dag_operations import DAGOperationsCoordinator

            coord = DAGOperationsCoordinator(graph, store=store)
            import asyncio

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                # Can't await in sync handler, use TaskDecomposer directly
                raise ImportError("async context")

            result = asyncio.run(coord.decompose_node(node_id))
            return json_response(
                {
                    "pipeline_id": pipeline_id,
                    "node_id": node_id,
                    "success": result.success,
                    "message": result.message,
                    "created_nodes": result.created_nodes,
                    "metadata": result.metadata,
                }
            )
        except (ImportError, RuntimeError, ValueError, OSError):
            pass

        # Fallback to TaskDecomposer directly
        try:
            from aragora.nomic.task_decomposer import TaskDecomposer

            decomposer = TaskDecomposer()
            task_desc = f"{node.label}: {getattr(node, 'description', '')}"
            decomposition = decomposer.analyze(task_desc)

            subtasks = [
                {
                    "id": s.id,
                    "title": s.title,
                    "description": s.description,
                    "complexity": s.estimated_complexity,
                    "dependencies": s.dependencies,
                    "parent_id": s.parent_id,
                    "depth": s.depth,
                }
                for s in decomposition.subtasks
            ]

            return json_response(
                {
                    "pipeline_id": pipeline_id,
                    "node_id": node_id,
                    "success": True,
                    "complexity_score": decomposition.complexity_score,
                    "complexity_level": decomposition.complexity_level,
                    "should_decompose": decomposition.should_decompose,
                    "subtasks": subtasks,
                    "rationale": decomposition.rationale,
                }
            )
        except (ImportError, RuntimeError, ValueError, OSError) as e:
            logger.warning("Task decomposition failed: %s", type(e).__name__)
            return error_response("Task decomposition not available", 503)

    def _get_decomposition_tree(self, pipeline_id: str, node_id: str) -> HandlerResult:
        store = _get_store()
        graph = store.get(pipeline_id)
        if graph is None:
            return error_response("Pipeline graph not found", 404)

        node = graph.nodes.get(node_id)
        if node is None:
            return error_response("Node not found", 404)

        # Build tree from graph edges (decomposes_into edges)
        tree = self._build_subtree(graph, node_id)

        # Convert to React Flow format
        rf_nodes: list[dict[str, Any]] = []
        rf_edges: list[dict[str, Any]] = []
        self._tree_to_react_flow(tree, rf_nodes, rf_edges, x=0, y=0)

        return json_response(
            {
                "pipeline_id": pipeline_id,
                "root_node_id": node_id,
                "tree": tree,
                "react_flow": {"nodes": rf_nodes, "edges": rf_edges},
            }
        )

    def _build_subtree(
        self, graph: Any, node_id: str, depth: int = 0, max_depth: int = 5
    ) -> dict[str, Any]:
        """Recursively build decomposition subtree from graph edges."""
        node = graph.nodes.get(node_id)
        if node is None:
            return {"id": node_id, "label": "unknown", "children": []}

        children = []
        if depth < max_depth:
            for edge in graph.edges.values():
                if getattr(edge, "source_id", None) == node_id:
                    edge_label = getattr(edge, "label", "")
                    if edge_label == "decomposes_into" or "decompos" in edge_label.lower():
                        child = self._build_subtree(graph, edge.target_id, depth + 1, max_depth)
                        children.append(child)

        return {
            "id": node_id,
            "label": getattr(node, "label", ""),
            "description": getattr(node, "description", ""),
            "stage": getattr(node, "stage", None),
            "status": getattr(node, "status", "active"),
            "depth": depth,
            "children": children,
        }

    def _tree_to_react_flow(
        self,
        tree: dict[str, Any],
        rf_nodes: list[dict[str, Any]],
        rf_edges: list[dict[str, Any]],
        x: float = 0,
        y: float = 0,
    ) -> None:
        """Convert tree structure to React Flow nodes/edges."""
        stage = tree.get("stage")
        stage_val = (
            stage.value
            if stage is not None and hasattr(stage, "value")
            else str(stage)
            if stage
            else ""
        )
        rf_nodes.append(
            {
                "id": tree["id"],
                "type": "decomposition",
                "position": {"x": x, "y": y},
                "data": {
                    "label": tree.get("label", ""),
                    "description": tree.get("description", ""),
                    "stage": stage_val,
                    "status": tree.get("status", "active"),
                    "depth": tree.get("depth", 0),
                    "childCount": len(tree.get("children", [])),
                },
            }
        )

        spacing_x = 250
        spacing_y = 150
        children = tree.get("children", [])
        start_x = x - (len(children) - 1) * spacing_x / 2

        for i, child in enumerate(children):
            child_x = start_x + i * spacing_x
            child_y = y + spacing_y

            rf_edges.append(
                {
                    "id": f"edge-{tree['id']}-{child['id']}",
                    "source": tree["id"],
                    "target": child["id"],
                    "type": "smoothstep",
                    "label": "decomposes_into",
                }
            )

            self._tree_to_react_flow(child, rf_nodes, rf_edges, child_x, child_y)


__all__ = ["DecompositionHandler"]
