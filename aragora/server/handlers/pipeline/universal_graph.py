"""
Universal Graph REST API Handler.

Provides CRUD and query endpoints for UniversalGraph objects:
  POST   /api/v1/pipeline/graphs              Create graph
  GET    /api/v1/pipeline/graphs              List graphs
  GET    /api/v1/pipeline/graphs/:id          Get graph
  PUT    /api/v1/pipeline/graphs/:id          Update graph
  DELETE /api/v1/pipeline/graphs/:id          Delete graph
  POST   /api/v1/pipeline/graphs/:id/nodes    Add node
  DELETE /api/v1/pipeline/graphs/:id/nodes/:nid  Remove node
  GET    /api/v1/pipeline/graphs/:id/nodes    Query nodes
  POST   /api/v1/pipeline/graphs/:id/edges    Add edge
  DELETE /api/v1/pipeline/graphs/:id/edges/:eid  Remove edge
  POST   /api/v1/pipeline/graphs/:id/promote  Promote nodes
  GET    /api/v1/pipeline/graphs/:id/provenance/:nid  Provenance chain
  GET    /api/v1/pipeline/graphs/:id/react-flow  React Flow export
  GET    /api/v1/pipeline/graphs/:id/integrity   Integrity hash

Every route needs an org-scoped caller. Reads need ``canvas:read``, creating
a graph ``canvas:create``, editing a graph or its nodes and edges
``canvas:update``, executing a node ``canvas:run`` and deleting a graph
``canvas:delete``. A graph belongs to the org that created it; the list
shows only the caller's org's graphs, and every route on another org's graph
answers the same 404 as a missing one.
"""

from __future__ import annotations

import functools
import logging
import uuid
from collections.abc import Callable
from typing import Any, NamedTuple, TypeAlias, cast

from aragora.server.versioning.compat import strip_version_prefix
from aragora.tenancy import pipeline_access
from aragora.tenancy.record_scope import OrgScope, record_not_found

from ..base import (
    SAFE_ID_PATTERN,
    BaseHandler,
    HandlerResult,
    error_response,
    get_int_param,
    get_string_param,
    json_response,
    validate_path_segment,
    handle_errors,
)
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

_graph_limiter = RateLimiter(requests_per_minute=60)

_GRAPH = "Graph"

# Lazy-loaded store
_store = None


def _get_store():
    global _store
    if _store is None:
        from aragora.pipeline.graph_store import get_graph_store

        _store = get_graph_store()
    return _store


class _Route(NamedTuple):
    """A matched route: the permission it needs, the graph it acts on and its call.

    ``graph_id`` is None for the list and create routes, which act on no
    existing graph.
    """

    permission: str
    graph_id: str | None
    call: Callable[[OrgScope], HandlerResult]
    rate_limited: bool = True


_Match: TypeAlias = _Route | HandlerResult | None


def _graph_route(
    permission: str,
    graph_id: str,
    call: Callable[[], HandlerResult],
    rate_limited: bool = True,
) -> _Route:
    return _Route(permission, graph_id, lambda _scope: call(), rate_limited)


def _invalid_ids(**ids: str) -> HandlerResult | None:
    """The 400 response for the first path id that is not a safe id, else None."""
    for name, value in ids.items():
        ok, err = validate_path_segment(value, name, SAFE_ID_PATTERN)
        if not ok:
            return error_response(cast(str, err), 400)
    return None


class UniversalGraphHandler(BaseHandler):
    """Handler for universal pipeline graph endpoints."""

    ROUTES = ["/api/v1/pipeline/graphs"]

    def __init__(self, ctx: dict[str, Any] | None = None):
        self.ctx = ctx or {}

    def can_handle(self, path: str) -> bool:
        cleaned = strip_version_prefix(path)
        return cleaned.startswith("/api/pipeline/graphs")

    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Route GET requests."""
        route = self._match_get(strip_version_prefix(path).split("/"), query_params)
        if not isinstance(route, _Route):
            return route
        scope, denial = self._check_permission(handler, route.permission)
        if scope is None:
            return denial
        return self._serve(route, scope, handler)

    @handle_errors("universal graph creation")
    def handle_post(self, path: str, body: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Route POST requests."""
        route = self._match_post(strip_version_prefix(path).split("/"), body)
        if not isinstance(route, _Route):
            return route
        scope, denial = self._check_permission(handler, route.permission)
        if scope is None:
            return denial
        return self._serve(route, scope, handler)

    @handle_errors("universal graph update")
    def handle_put(self, path: str, body: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Route PUT requests."""
        route = self._match_put(strip_version_prefix(path).split("/"), body)
        if not isinstance(route, _Route):
            return route
        scope, denial = self._check_permission(handler, route.permission)
        if scope is None:
            return denial
        return self._serve(route, scope, handler)

    @handle_errors("universal graph node update")
    def handle_patch(self, path: str, body: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Route PATCH requests for node updates (position, label, status)."""
        route = self._match_patch(strip_version_prefix(path).split("/"), body)
        if not isinstance(route, _Route):
            return route
        scope, denial = self._check_permission(handler, route.permission)
        if scope is None:
            return denial
        return self._serve(route, scope, handler)

    @handle_errors("universal graph deletion")
    def handle_delete(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route DELETE requests."""
        route = self._match_delete(strip_version_prefix(path).split("/"))
        if not isinstance(route, _Route):
            return route
        scope, denial = self._check_permission(handler, route.permission)
        if scope is None:
            return denial
        return self._serve(route, scope, handler)

    @staticmethod
    def _check_permission(
        handler: Any, permission: str
    ) -> tuple[OrgScope, None] | tuple[None, HandlerResult]:
        """``(scope, None)`` when the caller has an org and ``permission``, else ``(None, error)``.

        Fails closed: when the permission checker cannot be imported or raises,
        the caller is denied.
        """
        return pipeline_access.authorize_pipeline_request(handler, permission)

    @staticmethod
    def _owns(graph_id: str, scope: OrgScope) -> bool:
        return pipeline_access.graph_owned(graph_id, scope, store=_get_store())

    def _serve(self, route: _Route, scope: OrgScope, handler: Any) -> HandlerResult:
        """Run an authorized route once rate limiting and graph ownership allow it."""
        if route.rate_limited and not _graph_limiter.is_allowed(get_client_ip(handler)):
            return error_response("Rate limit exceeded", 429)
        if route.graph_id is not None and not self._owns(route.graph_id, scope):
            return record_not_found(_GRAPH)
        return route.call(scope)

    # -- Route matching -----------------------------------------------------
    # parts: "", "api", "pipeline", "graphs"[, graph_id[, sub[, sub_id]]]. Each
    # matcher answers a _Route, the 400 for a malformed path id, or None for a
    # path this handler does not serve.

    def _match_get(self, parts: list[str], query_params: dict[str, Any]) -> _Match:
        read = pipeline_access.PIPELINE_READ
        if len(parts) == 4 and parts[3] == "graphs":
            return _Route(read, None, lambda scope: self._list_graphs(query_params, scope))
        if len(parts) < 5:
            return None
        graph_id = parts[4]
        sub = parts[5] if len(parts) > 5 else ""
        invalid = _invalid_ids(graph_id=graph_id)
        if invalid is not None:
            return invalid
        if len(parts) == 5:
            return _graph_route(read, graph_id, lambda: self._get_graph(graph_id))
        if sub == "nodes" and len(parts) == 6:
            return _graph_route(read, graph_id, lambda: self._query_nodes(graph_id, query_params))
        if sub == "react-flow":
            return _graph_route(read, graph_id, lambda: self._react_flow(graph_id, query_params))
        if sub == "integrity":
            return _graph_route(read, graph_id, lambda: self._integrity(graph_id))
        if sub == "provenance" and len(parts) >= 7:
            node_id = parts[6]
            invalid = _invalid_ids(node_id=node_id)
            if invalid is not None:
                return invalid
            return _graph_route(read, graph_id, lambda: self._provenance_chain(graph_id, node_id))
        return None

    def _match_post(self, parts: list[str], body: dict[str, Any]) -> _Match:
        update = pipeline_access.PIPELINE_UPDATE
        if len(parts) == 4 and parts[3] == "graphs":
            create = pipeline_access.PIPELINE_CREATE
            return _Route(create, None, lambda scope: self._create_graph(body, scope))
        if len(parts) < 6:
            return None
        graph_id, sub = parts[4], parts[5]
        invalid = _invalid_ids(graph_id=graph_id)
        if invalid is not None:
            return invalid
        if sub == "nodes":
            return _graph_route(update, graph_id, lambda: self._add_node(graph_id, body))
        if sub == "edges":
            return _graph_route(update, graph_id, lambda: self._add_edge(graph_id, body))
        if sub == "promote":
            return _graph_route(update, graph_id, lambda: self._promote(graph_id, body))
        if sub == "execute" and len(parts) >= 7:
            node_id = parts[6]
            invalid = _invalid_ids(node_id=node_id)
            if invalid is not None:
                return invalid
            return _graph_route(
                pipeline_access.PIPELINE_RUN,
                graph_id,
                lambda: self._execute_node(graph_id, node_id, body),
            )
        return None

    def _match_put(self, parts: list[str], body: dict[str, Any]) -> _Match:
        if len(parts) != 5 or parts[3] != "graphs":
            return None
        graph_id = parts[4]
        invalid = _invalid_ids(graph_id=graph_id)
        if invalid is not None:
            return invalid
        return _graph_route(
            pipeline_access.PIPELINE_UPDATE,
            graph_id,
            lambda: self._update_graph(graph_id, body),
            rate_limited=False,
        )

    def _match_patch(self, parts: list[str], body: dict[str, Any]) -> _Match:
        # PATCH /api/pipeline/graphs/:id/nodes/:node_id
        if len(parts) < 7 or parts[3] != "graphs" or parts[5] != "nodes":
            return None
        graph_id, node_id = parts[4], parts[6]
        invalid = _invalid_ids(graph_id=graph_id, node_id=node_id)
        if invalid is not None:
            return invalid
        return _graph_route(
            pipeline_access.PIPELINE_UPDATE,
            graph_id,
            lambda: self._update_node(graph_id, node_id, body),
            rate_limited=False,
        )

    def _match_delete(self, parts: list[str]) -> _Match:
        if len(parts) < 5:
            return None
        graph_id = parts[4]
        invalid = _invalid_ids(graph_id=graph_id)
        if invalid is not None:
            return invalid
        if len(parts) == 5:
            return _graph_route(
                pipeline_access.PIPELINE_DELETE,
                graph_id,
                lambda: self._delete_graph(graph_id),
                rate_limited=False,
            )
        sub = parts[5]
        if sub not in ("nodes", "edges") or len(parts) < 7:
            return None
        sub_id = parts[6]
        if sub == "nodes":
            invalid = _invalid_ids(node_id=sub_id)
            call = functools.partial(self._remove_node, graph_id, sub_id)
        else:
            invalid = _invalid_ids(edge_id=sub_id)
            call = functools.partial(self._remove_edge, graph_id, sub_id)
        if invalid is not None:
            return invalid
        return _graph_route(pipeline_access.PIPELINE_UPDATE, graph_id, call, rate_limited=False)

    # -- Endpoint implementations -------------------------------------------

    def _create_graph(self, body: dict[str, Any], scope: OrgScope) -> HandlerResult:
        from aragora.pipeline.universal_node import UniversalGraph

        store = _get_store()
        # A client-chosen "id" is ignored: honoring it would either replace an existing
        # graph or reveal, by refusing, that another org already holds that id.
        graph = UniversalGraph(
            id=f"graph-{uuid.uuid4().hex}",
            name=body.get("name", "Untitled Pipeline"),
            owner_id=body.get("owner_id"),
            workspace_id=body.get("workspace_id"),
            metadata=body.get("metadata", {}),
        )
        store.create(graph, org_id=scope.org_id, created_by=scope.user_id)
        return json_response(graph.to_dict(), status=201)

    def _list_graphs(self, params: dict[str, Any], scope: OrgScope) -> HandlerResult:
        store = _get_store()
        owner = get_string_param(params, "owner_id")
        workspace = get_string_param(params, "workspace_id")
        limit = get_int_param(params, "limit", 50)
        graphs = store.list(
            owner_id=owner, workspace_id=workspace, limit=limit, org_id=scope.org_id
        )
        return json_response({"graphs": graphs, "count": len(graphs)})

    def _get_graph(self, graph_id: str) -> HandlerResult:
        store = _get_store()
        graph = store.get(graph_id)
        if graph is None:
            return error_response("Graph not found", 404)
        return json_response(graph.to_dict())

    def _update_graph(self, graph_id: str, body: dict[str, Any]) -> HandlerResult:
        store = _get_store()
        graph = store.get(graph_id)
        if graph is None:
            return error_response("Graph not found", 404)
        if "name" in body:
            graph.name = body["name"]
        if "metadata" in body:
            graph.metadata.update(body["metadata"])
        if "owner_id" in body:
            graph.owner_id = body["owner_id"]
        if "workspace_id" in body:
            graph.workspace_id = body["workspace_id"]
        import time

        graph.updated_at = time.time()
        store.update(graph)
        return json_response(graph.to_dict())

    def _delete_graph(self, graph_id: str) -> HandlerResult:
        store = _get_store()
        deleted = store.delete(graph_id)
        if not deleted:
            return error_response("Graph not found", 404)
        return json_response({"deleted": True, "id": graph_id})

    def _add_node(self, graph_id: str, body: dict[str, Any]) -> HandlerResult:
        from aragora.canvas.stages import PipelineStage
        from aragora.pipeline.universal_node import UniversalNode

        store = _get_store()
        graph = store.get(graph_id)
        if graph is None:
            return error_response("Graph not found", 404)

        try:
            stage = PipelineStage(body.get("stage", "ideas"))
        except ValueError:
            return error_response("Invalid stage", 400)

        # Node ids are unique across all graphs, so a client-chosen "id" is ignored for
        # the same reason as on graph create.
        node = UniversalNode(
            id=f"node-{uuid.uuid4().hex}",
            stage=stage,
            node_subtype=body.get("node_subtype", "concept"),
            label=body.get("label", ""),
            description=body.get("description", ""),
            position_x=float(body.get("position_x", 0)),
            position_y=float(body.get("position_y", 0)),
            status=body.get("status", "active"),
            confidence=float(body.get("confidence", 0)),
            data=body.get("data", {}),
            metadata=body.get("metadata", {}),
        )
        store.add_node(graph_id, node)
        return json_response(node.to_dict(), status=201)

    def _remove_node(self, graph_id: str, node_id: str) -> HandlerResult:
        store = _get_store()
        store.remove_node(graph_id, node_id)
        return json_response({"deleted": True, "node_id": node_id})

    def _query_nodes(self, graph_id: str, params: dict[str, Any]) -> HandlerResult:
        from aragora.canvas.stages import PipelineStage

        store = _get_store()
        stage_str = get_string_param(params, "stage")
        subtype = get_string_param(params, "subtype")

        stage = None
        if stage_str:
            try:
                stage = PipelineStage(stage_str)
            except ValueError:
                return error_response("Invalid stage filter", 400)

        nodes = store.query_nodes(graph_id, stage=stage, subtype=subtype)
        return json_response(
            {
                "nodes": [n.to_dict() for n in nodes],
                "count": len(nodes),
            }
        )

    def _add_edge(self, graph_id: str, body: dict[str, Any]) -> HandlerResult:
        from aragora.canvas.stages import StageEdgeType
        from aragora.pipeline.universal_node import UniversalEdge

        store = _get_store()
        graph = store.get(graph_id)
        if graph is None:
            return error_response("Graph not found", 404)

        try:
            edge_type = StageEdgeType(body.get("edge_type", "relates_to"))
        except ValueError:
            return error_response("Invalid edge_type", 400)

        source_id = body.get("source_id", "")
        target_id = body.get("target_id", "")

        if source_id not in graph.nodes or target_id not in graph.nodes:
            return error_response("Source or target node not found in graph", 400)

        edge = UniversalEdge(
            id=body.get("id", f"edge-{uuid.uuid4().hex[:8]}"),
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            label=body.get("label", ""),
            weight=float(body.get("weight", 1.0)),
            data=body.get("data", {}),
        )
        graph.add_edge(edge)
        store.update(graph)
        return json_response(edge.to_dict(), status=201)

    def _remove_edge(self, graph_id: str, edge_id: str) -> HandlerResult:
        store = _get_store()
        graph = store.get(graph_id)
        if graph is None:
            return error_response("Graph not found", 404)
        removed = graph.remove_edge(edge_id)
        if removed is None:
            return error_response("Edge not found", 404)
        store.update(graph)
        return json_response({"deleted": True, "edge_id": edge_id})

    def _promote(self, graph_id: str, body: dict[str, Any]) -> HandlerResult:
        from aragora.canvas.stages import PipelineStage
        from aragora.pipeline.stage_transitions import (
            actions_to_orchestration,
            goals_to_actions,
            ideas_to_goals,
        )

        store = _get_store()
        graph = store.get(graph_id)
        if graph is None:
            return error_response("Graph not found", 404)

        node_ids = body.get("node_ids", [])
        target_stage_str = body.get("target_stage", "")
        try:
            target_stage = PipelineStage(target_stage_str)
        except ValueError:
            return error_response("Invalid target_stage", 400)

        if not node_ids:
            return error_response("node_ids required", 400)

        if target_stage == PipelineStage.GOALS:
            created = ideas_to_goals(graph, node_ids)
        elif target_stage == PipelineStage.ACTIONS:
            created = goals_to_actions(graph, node_ids)
        elif target_stage == PipelineStage.ORCHESTRATION:
            created = actions_to_orchestration(graph, node_ids)
        else:
            return error_response("Cannot promote to IDEAS stage", 400)

        # Persist updated graph
        store.update(graph)
        for node in created:
            store.add_node(graph_id, node)

        return json_response(
            {
                "created": [n.to_dict() for n in created],
                "count": len(created),
                "target_stage": target_stage.value,
            }
        )

    def _update_node(self, graph_id: str, node_id: str, body: dict[str, Any]) -> HandlerResult:
        """Update individual node properties (position, label, status, etc.)."""
        store = _get_store()
        graph = store.get(graph_id)
        if graph is None:
            return error_response("Graph not found", 404)
        node = graph.nodes.get(node_id)
        if node is None:
            return error_response("Node not found", 404)

        if "label" in body:
            node.label = str(body["label"])
        if "description" in body:
            node.description = str(body["description"])
        if "status" in body:
            node.status = str(body["status"])
        if "position_x" in body:
            node.position_x = float(body["position_x"])
        if "position_y" in body:
            node.position_y = float(body["position_y"])
        if "confidence" in body:
            node.confidence = float(body["confidence"])
        if "data" in body and isinstance(body["data"], dict):
            node.data.update(body["data"])
        if "metadata" in body and isinstance(body["metadata"], dict):
            node.metadata.update(body["metadata"])

        store.update(graph)
        return json_response(node.to_dict())

    def _execute_node(self, graph_id: str, node_id: str, body: dict[str, Any]) -> HandlerResult:
        """Trigger execution on a specific node via DAGOperationsCoordinator."""
        store = _get_store()
        graph = store.get(graph_id)
        if graph is None:
            return error_response("Graph not found", 404)

        node = graph.nodes.get(node_id)
        if node is None:
            return error_response("Node not found", 404)

        try:
            from aragora.pipeline.dag_operations import DAGOperationsCoordinator

            # Optionally inject federation coordinator for cross-workspace execution
            federation_coordinator = None
            try:
                from aragora.coordination.cross_workspace import get_coordinator

                federation_coordinator = get_coordinator()
            except (ImportError, RuntimeError):
                pass

            coord = DAGOperationsCoordinator(
                graph, store=store, federation_coordinator=federation_coordinator
            )
            # For debate-based execution, use agents from body or defaults
            agents = body.get("agents")
            rounds = body.get("rounds", 3)

            import asyncio

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                # Already in async context — schedule and return accepted
                loop.create_task(coord.debate_node(node_id, agents=agents, rounds=rounds))
                return json_response(
                    {"status": "accepted", "node_id": node_id, "graph_id": graph_id},
                    status=202,
                )

            result = asyncio.run(coord.debate_node(node_id, agents=agents, rounds=rounds))
            return json_response(
                {
                    "success": result.success,
                    "message": result.message,
                    "metadata": result.metadata,
                }
            )
        except (ImportError, RuntimeError, ValueError, OSError) as e:
            logger.warning("Node execution failed: %s", e)
            return error_response("Node execution failed", 500)

    def _provenance_chain(self, graph_id: str, node_id: str) -> HandlerResult:
        store = _get_store()
        chain = store.get_provenance_chain(graph_id, node_id)
        return json_response(
            {
                "chain": [n.to_dict() for n in chain],
                "depth": len(chain),
            }
        )

    def _react_flow(self, graph_id: str, params: dict[str, Any]) -> HandlerResult:
        from aragora.canvas.stages import PipelineStage

        store = _get_store()
        graph = store.get(graph_id)
        if graph is None:
            return error_response("Graph not found", 404)

        stage_str = get_string_param(params, "stage")
        stage_filter = None
        if stage_str:
            try:
                stage_filter = PipelineStage(stage_str)
            except ValueError:
                return error_response("Invalid stage filter", 400)

        rf = graph.to_react_flow(stage_filter=stage_filter)
        return json_response(rf)

    def _integrity(self, graph_id: str) -> HandlerResult:
        store = _get_store()
        graph = store.get(graph_id)
        if graph is None:
            return error_response("Graph not found", 404)
        return json_response(
            {
                "graph_id": graph_id,
                "integrity_hash": graph.integrity_hash(),
                "node_count": len(graph.nodes),
                "edge_count": len(graph.edges),
            }
        )


__all__ = ["UniversalGraphHandler"]
