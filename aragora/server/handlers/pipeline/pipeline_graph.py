"""
Universal Pipeline Graph REST Handler.

Exposes CRUD, stage transitions, provenance queries, and React Flow export
for UniversalGraph objects via GraphStore.

Endpoints:
- POST   /api/v1/pipeline/graph              - Create graph
- GET    /api/v1/pipeline/graph              - List graphs
- GET    /api/v1/pipeline/graph/{id}         - Get graph
- DELETE /api/v1/pipeline/graph/{id}         - Delete graph
- POST   /api/v1/pipeline/graph/{id}/node    - Add node
- DELETE /api/v1/pipeline/graph/{id}/node/{nid} - Remove node
- GET    /api/v1/pipeline/graph/{id}/nodes   - Query nodes (stage/subtype filters)
- POST   /api/v1/pipeline/graph/{id}/promote - Promote nodes to next stage
- GET    /api/v1/pipeline/graph/{id}/provenance/{nid} - Provenance chain
- GET    /api/v1/pipeline/graph/{id}/suggestions - Transition suggestions
- GET    /api/v1/pipeline/graph/{id}/react-flow - React Flow JSON export
- GET    /api/v1/pipeline/graph/{id}/integrity  - Integrity hash
- POST   /api/v1/pipeline/graph/{id}/node/{nid}/reassign - Reassign agent on node
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from aragora.server.handlers.base import HandlerResult, error_response, handle_errors, json_response

logger = logging.getLogger(__name__)

# Path patterns
_GRAPH_ID = re.compile(r"^/api/(?:v1/)?pipeline/graph/([a-zA-Z0-9_-]+)$")
_GRAPH_NODE = re.compile(r"^/api/(?:v1/)?pipeline/graph/([a-zA-Z0-9_-]+)/node$")
_GRAPH_NODE_ID = re.compile(r"^/api/(?:v1/)?pipeline/graph/([a-zA-Z0-9_-]+)/node/([a-zA-Z0-9_-]+)$")
_GRAPH_NODE_REASSIGN = re.compile(
    r"^/api/(?:v1/)?pipeline/graph/([a-zA-Z0-9_-]+)/node/([a-zA-Z0-9_-]+)/reassign$"
)
_GRAPH_NODES = re.compile(r"^/api/(?:v1/)?pipeline/graph/([a-zA-Z0-9_-]+)/nodes$")
_GRAPH_PROMOTE = re.compile(r"^/api/(?:v1/)?pipeline/graph/([a-zA-Z0-9_-]+)/promote$")
_GRAPH_PROVENANCE = re.compile(
    r"^/api/(?:v1/)?pipeline/graph/([a-zA-Z0-9_-]+)/provenance/([a-zA-Z0-9_-]+)$"
)
_GRAPH_REACT_FLOW = re.compile(r"^/api/(?:v1/)?pipeline/graph/([a-zA-Z0-9_-]+)/react-flow$")
_GRAPH_INTEGRITY = re.compile(r"^/api/(?:v1/)?pipeline/graph/([a-zA-Z0-9_-]+)/integrity$")
_GRAPH_SUGGESTIONS = re.compile(r"^/api/(?:v1/)?pipeline/graph/([a-zA-Z0-9_-]+)/suggestions$")
_GRAPH_LIST = re.compile(r"^/api/(?:v1/)?pipeline/graph/?$")


def _get_store() -> Any:
    """Lazy-load the GraphStore singleton."""
    from aragora.pipeline.graph_store import get_graph_store

    return get_graph_store()


class PipelineGraphHandler:
    """HTTP handler for UniversalGraph CRUD and pipeline operations."""

    ROUTES = [
        "POST /api/v1/pipeline/graph",
        "GET /api/v1/pipeline/graph",
        "GET /api/v1/pipeline/graph/{id}",
        "DELETE /api/v1/pipeline/graph/{id}",
        "POST /api/v1/pipeline/graph/{id}/node",
        "DELETE /api/v1/pipeline/graph/{id}/node/{node_id}",
        "GET /api/v1/pipeline/graph/{id}/nodes",
        "POST /api/v1/pipeline/graph/{id}/promote",
        "GET /api/v1/pipeline/graph/{id}/provenance/{node_id}",
        "GET /api/v1/pipeline/graph/{id}/react-flow",
        "GET /api/v1/pipeline/graph/{id}/integrity",
        "GET /api/v1/pipeline/graph/{id}/suggestions",
        "POST /api/v1/pipeline/graph/{id}/node/{nodeId}/reassign",
    ]

    def __init__(self, ctx: dict[str, Any] | None = None) -> None:
        self.ctx = ctx or {}

    def can_handle(self, path: str) -> bool:
        return path.startswith("/api/v1/pipeline/graph") or path.startswith("/api/pipeline/graph")

    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> Any:
        """Dispatch GET requests."""
        # GET /api/v1/pipeline/graph/{id}/react-flow
        m = _GRAPH_REACT_FLOW.match(path)
        if m:
            return self.handle_react_flow(m.group(1), query_params)

        # GET /api/v1/pipeline/graph/{id}/integrity
        m = _GRAPH_INTEGRITY.match(path)
        if m:
            return self.handle_integrity(m.group(1))

        # GET /api/v1/pipeline/graph/{id}/provenance/{node_id}
        m = _GRAPH_PROVENANCE.match(path)
        if m:
            return self.handle_provenance(m.group(1), m.group(2))

        # GET /api/v1/pipeline/graph/{id}/suggestions
        m = _GRAPH_SUGGESTIONS.match(path)
        if m:
            return self.handle_suggestions(m.group(1), query_params)

        # GET /api/v1/pipeline/graph/{id}/nodes
        m = _GRAPH_NODES.match(path)
        if m:
            return self.handle_query_nodes(m.group(1), query_params)

        # GET /api/v1/pipeline/graph/{id}
        m = _GRAPH_ID.match(path)
        if m:
            return self.handle_get_graph(m.group(1))

        # GET /api/v1/pipeline/graph (list)
        m = _GRAPH_LIST.match(path)
        if m:
            return self.handle_list_graphs(query_params)

        return None

    def _check_permission(self, handler: Any, permission: str) -> Any:
        """Check RBAC permission and return error response if denied."""
        try:
            from aragora.billing.jwt_auth import extract_user_from_request
            from aragora.rbac.checker import get_permission_checker
            from aragora.rbac.models import AuthorizationContext
            from aragora.server.handlers.utils.responses import error_response

            user_ctx = extract_user_from_request(handler, None)
            if not user_ctx or not user_ctx.is_authenticated:
                return error_response("Authentication required", status=401)

            auth_ctx = AuthorizationContext(
                user_id=user_ctx.user_id,
                user_email=user_ctx.email,
                org_id=user_ctx.org_id,
                workspace_id=None,
                roles={user_ctx.role} if user_ctx.role else {"member"},
            )
            checker = get_permission_checker()
            decision = checker.check_permission(auth_ctx, permission)
            if not decision.allowed:
                logger.warning("Permission denied: %s", permission)
                return error_response("Permission denied", status=403)
            return None
        except (ImportError, AttributeError, ValueError) as e:
            logger.debug("Permission check unavailable: %s", e)
            return None

    @handle_errors("pipeline graph deletion")
    def handle_delete(self, path: str, query_params: dict[str, Any], handler: Any) -> Any:
        """Dispatch DELETE requests."""
        # Match route first so unknown paths return None (letting other handlers try)
        m = _GRAPH_NODE_ID.match(path)
        if m:
            auth_error = self._check_permission(handler, "pipeline:write")
            if auth_error:
                return auth_error
            return self.handle_remove_node(m.group(1), m.group(2))

        m = _GRAPH_ID.match(path)
        if m:
            auth_error = self._check_permission(handler, "pipeline:write")
            if auth_error:
                return auth_error
            return self.handle_delete_graph(m.group(1))

        return None

    @handle_errors("pipeline graph creation")
    def handle_post(self, path: str, query_params: dict[str, Any], handler: Any) -> Any:
        """Dispatch POST requests."""
        # Match route first so unknown paths return None (letting other handlers try)
        m = _GRAPH_NODE_REASSIGN.match(path)
        if m:
            auth_error = self._check_permission(handler, "pipeline:write")
            if auth_error:
                return auth_error
            body = self._get_request_body(handler)
            return self.handle_node_reassign(m.group(1), m.group(2), body)

        m = _GRAPH_PROMOTE.match(path)
        if m:
            auth_error = self._check_permission(handler, "pipeline:write")
            if auth_error:
                return auth_error
            body = self._get_request_body(handler)
            return self.handle_promote(m.group(1), body)

        m = _GRAPH_NODE.match(path)
        if m:
            auth_error = self._check_permission(handler, "pipeline:write")
            if auth_error:
                return auth_error
            body = self._get_request_body(handler)
            return self.handle_add_node(m.group(1), body)

        m = _GRAPH_LIST.match(path)
        if m:
            auth_error = self._check_permission(handler, "pipeline:write")
            if auth_error:
                return auth_error
            body = self._get_request_body(handler)
            return self.handle_create_graph(body)

        return None

    @staticmethod
    def _get_request_body(handler: Any) -> dict[str, Any]:
        try:
            if hasattr(handler, "request") and hasattr(handler.request, "body"):
                raw = handler.request.body
                if raw:
                    return json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            pass
        return {}

    # -- CRUD endpoints --

    async def handle_create_graph(self, body: dict[str, Any]) -> HandlerResult:
        """POST /api/v1/pipeline/graph"""
        try:
            from aragora.pipeline.universal_node import UniversalGraph

            name = body.get("name", "Untitled Pipeline")
            graph_id = body.get("id", f"graph-{uuid.uuid4().hex[:8]}")

            graph = UniversalGraph(
                id=graph_id,
                name=name,
                owner_id=body.get("owner_id"),
                workspace_id=body.get("workspace_id"),
                metadata=body.get("metadata", {}),
            )

            # Add initial nodes if provided
            if body.get("nodes"):
                from aragora.pipeline.universal_node import UniversalNode

                for nd in body["nodes"]:
                    node = UniversalNode.from_dict(nd)
                    graph.add_node(node)

            store = _get_store()
            store.create(graph)

            return json_response(
                {
                    "id": graph.id,
                    "name": graph.name,
                    "node_count": len(graph.nodes),
                    "created": True,
                },
                201,
            )
        except (ImportError, ValueError, TypeError) as e:
            logger.warning("Create graph failed: %s", e)
            return error_response("Failed to create graph", 500)

    async def handle_get_graph(self, graph_id: str) -> HandlerResult:
        """GET /api/v1/pipeline/graph/{id}"""
        try:
            store = _get_store()
            graph = store.get(graph_id)
            if not graph:
                return error_response(f"Graph {graph_id} not found", 404)
            return json_response(graph.to_dict())
        except (ImportError, OSError) as e:
            logger.warning("Get graph failed: %s", e)
            return error_response("Failed to retrieve graph", 500)

    async def handle_list_graphs(self, query_params: dict[str, Any]) -> HandlerResult:
        """GET /api/v1/pipeline/graph"""
        try:
            store = _get_store()
            owner_id = query_params.get("owner_id")
            workspace_id = query_params.get("workspace_id")
            limit = max(1, min(int(query_params.get("limit", 50)), 500))

            graphs = store.list(
                owner_id=owner_id,
                workspace_id=workspace_id,
                limit=limit,
            )
            return json_response({"graphs": graphs, "count": len(graphs)})
        except (ImportError, OSError, ValueError) as e:
            logger.warning("List graphs failed: %s", e)
            return error_response("Failed to list graphs", 500)

    @handle_errors("pipeline graph operation")
    async def handle_delete_graph(self, graph_id: str) -> HandlerResult:
        """DELETE /api/v1/pipeline/graph/{id}"""
        try:
            store = _get_store()
            deleted = store.delete(graph_id)
            if not deleted:
                return error_response(f"Graph {graph_id} not found", 404)
            return json_response({"id": graph_id, "deleted": True})
        except (ImportError, OSError) as e:
            logger.warning("Delete graph failed: %s", e)
            return error_response("Failed to delete graph", 500)

    # -- Node endpoints --

    async def handle_add_node(self, graph_id: str, body: dict[str, Any]) -> HandlerResult:
        """POST /api/v1/pipeline/graph/{id}/node"""
        try:
            from aragora.pipeline.universal_node import UniversalNode

            store = _get_store()
            graph = store.get(graph_id)
            if not graph:
                return error_response(f"Graph {graph_id} not found", 404)

            if "stage" not in body or "node_subtype" not in body:
                return error_response("Missing required fields: stage, node_subtype", 400)

            node = UniversalNode.from_dict(body)
            store.add_node(graph_id, node)

            return json_response(
                {
                    "graph_id": graph_id,
                    "node_id": node.id,
                    "stage": node.stage.value,
                    "added": True,
                },
                201,
            )
        except (ImportError, ValueError, TypeError) as e:
            logger.warning("Add node failed: %s", e)
            return error_response("Failed to add node", 500)

    async def handle_remove_node(self, graph_id: str, node_id: str) -> HandlerResult:
        """DELETE /api/v1/pipeline/graph/{id}/node/{node_id}"""
        try:
            store = _get_store()
            graph = store.get(graph_id)
            if not graph:
                return error_response(f"Graph {graph_id} not found", 404)

            if node_id not in graph.nodes:
                return error_response(f"Node {node_id} not found in graph {graph_id}", 404)

            store.remove_node(graph_id, node_id)
            return json_response({"graph_id": graph_id, "node_id": node_id, "removed": True})
        except (ImportError, OSError) as e:
            logger.warning("Remove node failed: %s", e)
            return error_response("Failed to remove node", 500)

    async def handle_node_reassign(
        self, graph_id: str, node_id: str, body: dict[str, Any]
    ) -> HandlerResult:
        """POST /api/v1/pipeline/graph/{id}/node/{node_id}/reassign

        Reassign the agent responsible for a pipeline graph node.

        Body:
            agent: str - Name of the new agent to assign
        """
        try:
            store = _get_store()
            graph = store.get(graph_id)
            if not graph:
                return error_response(f"Graph {graph_id} not found", 404)

            if node_id not in graph.nodes:
                return error_response(f"Node {node_id} not found in graph {graph_id}", 404)

            node = graph.nodes[node_id]
            new_agent = body.get("agent")
            if not new_agent:
                return error_response("Missing required field: agent", 400)

            old_agent = node.data.get("assigned_agent")
            node.data["reassigned_from"] = old_agent
            node.data["assigned_agent"] = new_agent

            store.update(graph)

            return json_response({"ok": True, "node_id": node_id, "agent": new_agent})
        except (ImportError, OSError, TypeError) as e:
            logger.warning("Node reassign failed: %s", e)
            return error_response("Failed to reassign node agent", 500)

    async def handle_query_nodes(
        self, graph_id: str, query_params: dict[str, Any]
    ) -> HandlerResult:
        """GET /api/v1/pipeline/graph/{id}/nodes"""
        try:
            from aragora.canvas.stages import PipelineStage

            store = _get_store()
            stage_str = query_params.get("stage")
            subtype = query_params.get("subtype")

            stage = PipelineStage(stage_str) if stage_str else None
            nodes = store.query_nodes(graph_id, stage=stage, subtype=subtype)

            return json_response(
                {
                    "graph_id": graph_id,
                    "nodes": [n.to_dict() for n in nodes],
                    "count": len(nodes),
                }
            )
        except (ImportError, ValueError, OSError) as e:
            logger.warning("Query nodes failed: %s", e)
            return error_response("Failed to query nodes", 500)

    # -- Stage transition --

    async def handle_promote(self, graph_id: str, body: dict[str, Any]) -> HandlerResult:
        """POST /api/v1/pipeline/graph/{id}/promote

        Promote nodes from one stage to the next.

        Body:
            node_ids: list[str] - IDs of nodes to promote
            target_stage: str - Target stage (goals, actions, orchestration)
        """
        try:
            from aragora.canvas.stages import PipelineStage
            from aragora.pipeline.stage_transitions import (
                actions_to_orchestration,
                goals_to_actions,
                ideas_to_goals,
            )

            store = _get_store()
            graph = store.get(graph_id)
            if not graph:
                return error_response(f"Graph {graph_id} not found", 404)

            node_ids = body.get("node_ids", [])
            target_stage_str = body.get("target_stage", "")

            if not node_ids:
                return error_response("Missing required field: node_ids", 400)
            if not target_stage_str:
                return error_response("Missing required field: target_stage", 400)

            try:
                target_stage = PipelineStage(target_stage_str)
            except ValueError:
                return error_response(f"Invalid target stage: {target_stage_str}", 400)

            # Dispatch to the appropriate transition function
            if target_stage == PipelineStage.GOALS:
                created = ideas_to_goals(graph, node_ids)
            elif target_stage == PipelineStage.ACTIONS:
                created = goals_to_actions(graph, node_ids)
            elif target_stage == PipelineStage.ORCHESTRATION:
                created = actions_to_orchestration(graph, node_ids)
            else:
                return error_response(f"Cannot promote to stage: {target_stage_str}", 400)

            # Persist updated graph
            store.update(graph)
            for node in created:
                store.add_node(graph_id, node)

            return json_response(
                {
                    "graph_id": graph_id,
                    "target_stage": target_stage_str,
                    "promoted_count": len(created),
                    "new_node_ids": [n.id for n in created],
                    "transition_count": len(graph.transitions),
                }
            )
        except (ImportError, ValueError, TypeError) as e:
            logger.warning("Promote failed: %s", e)
            return error_response("Stage promotion failed", 500)

    # -- Transition suggestions --

    async def handle_suggestions(
        self, graph_id: str, query_params: dict[str, Any]
    ) -> HandlerResult:
        """GET /api/v1/pipeline/graph/{id}/suggestions?stage={stage}

        Get AI-suggested transitions for the given pipeline stage.
        """
        try:
            from aragora.canvas.stages import PipelineStage
            from aragora.pipeline.stage_transitions import suggest_transitions

            store = _get_store()
            graph = store.get(graph_id)
            if not graph:
                return error_response(f"Graph {graph_id} not found", 404)

            stage_str = query_params.get("stage", "ideas")
            try:
                stage = PipelineStage(stage_str)
            except ValueError:
                return error_response(f"Invalid stage: {stage_str}", 400)

            suggestions = suggest_transitions(graph, stage)

            return json_response(
                {
                    "graph_id": graph_id,
                    "stage": stage_str,
                    "suggestions": [
                        {
                            "target_stage": s.get("to_stage", ""),
                            "confidence": s.get("confidence", 0.5),
                            "rationale": s.get("reason", ""),
                            "node_ids": [s["node_id"]] if "node_id" in s else [],
                            "auto_promotable": s.get("confidence", 0) >= 0.8,
                        }
                        for s in (suggestions if isinstance(suggestions, list) else [])
                    ],
                }
            )
        except (ImportError, ValueError, TypeError, AttributeError) as e:
            logger.warning("Transition suggestions failed: %s", e)
            return error_response("Failed to generate suggestions", 500)

    # -- Provenance / analytics --

    async def handle_provenance(self, graph_id: str, node_id: str) -> HandlerResult:
        """GET /api/v1/pipeline/graph/{id}/provenance/{node_id}"""
        try:
            store = _get_store()
            chain = store.get_provenance_chain(graph_id, node_id)

            return json_response(
                {
                    "graph_id": graph_id,
                    "node_id": node_id,
                    "chain": [n.to_dict() for n in chain],
                    "depth": len(chain),
                }
            )
        except (ImportError, OSError) as e:
            logger.warning("Provenance query failed: %s", e)
            return error_response("Failed to retrieve provenance chain", 500)

    async def handle_react_flow(self, graph_id: str, query_params: dict[str, Any]) -> HandlerResult:
        """GET /api/v1/pipeline/graph/{id}/react-flow"""
        try:
            from aragora.canvas.stages import PipelineStage

            store = _get_store()
            graph = store.get(graph_id)
            if not graph:
                return error_response(f"Graph {graph_id} not found", 404)

            stage_str = query_params.get("stage")
            stage_filter = PipelineStage(stage_str) if stage_str else None

            rf_data = graph.to_react_flow(stage_filter=stage_filter)
            rf_data["graph_id"] = graph_id
            rf_data["graph_name"] = graph.name
            rf_data["node_count"] = len(rf_data.get("nodes", []))
            rf_data["edge_count"] = len(rf_data.get("edges", []))

            return json_response(rf_data)
        except (ImportError, ValueError, OSError) as e:
            logger.warning("React Flow export failed: %s", e)
            return error_response("Failed to export React Flow data", 500)

    async def handle_integrity(self, graph_id: str) -> HandlerResult:
        """GET /api/v1/pipeline/graph/{id}/integrity"""
        try:
            store = _get_store()
            graph = store.get(graph_id)
            if not graph:
                return error_response(f"Graph {graph_id} not found", 404)

            return json_response(
                {
                    "graph_id": graph_id,
                    "integrity_hash": graph.integrity_hash(),
                    "node_count": len(graph.nodes),
                    "edge_count": len(graph.edges),
                    "transition_count": len(graph.transitions),
                }
            )
        except (ImportError, OSError) as e:
            logger.warning("Integrity check failed: %s", e)
            return error_response("Failed to compute integrity hash", 500)
