"""
HTTP Handler for Orchestration Canvas (Stage 4 of the Idea-to-Execution Pipeline).

REST endpoints:
    GET    /api/v1/orchestration/canvas                           -- List orchestration canvases
    POST   /api/v1/orchestration/canvas                           -- Create canvas
    GET    /api/v1/orchestration/canvas/{canvas_id}               -- Get full canvas
    PUT    /api/v1/orchestration/canvas/{canvas_id}               -- Update canvas metadata
    DELETE /api/v1/orchestration/canvas/{canvas_id}               -- Delete canvas
    POST   /api/v1/orchestration/canvas/{canvas_id}/nodes         -- Add node
    PUT    /api/v1/orchestration/canvas/{canvas_id}/nodes/{id}    -- Update node
    DELETE /api/v1/orchestration/canvas/{canvas_id}/nodes/{id}    -- Delete node
    POST   /api/v1/orchestration/canvas/{canvas_id}/edges         -- Add edge
    DELETE /api/v1/orchestration/canvas/{canvas_id}/edges/{id}    -- Delete edge
    GET    /api/v1/orchestration/canvas/{canvas_id}/export        -- Export as React Flow JSON
    POST   /api/v1/orchestration/canvas/{canvas_id}/execute       -- Execute pipeline

RBAC:
    orchestration:read, orchestration:create, orchestration:update,
    orchestration:delete, orchestration:execute
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from typing import Any

from aragora.server.handlers.secure import SecureHandler
from aragora.server.handlers.base import (
    HandlerResult,
    error_response,
    json_response,
)
from aragora.server.handlers.utils.rate_limit import RateLimiter, get_client_ip
from aragora.rbac.decorators import require_permission, PermissionDeniedError
from aragora.rbac.models import AuthorizationContext

logger = logging.getLogger(__name__)

_orchestration_limiter = RateLimiter(requests_per_minute=120)

# Route patterns — all under /api/v1/orchestration/canvas to avoid conflict
# with the deliberation handler at /api/v1/orchestration
ORCH_LIST = re.compile(r"^/api/v1/orchestration/canvas$")
ORCH_BY_ID = re.compile(r"^/api/v1/orchestration/canvas/([a-zA-Z0-9_-]+)$")
ORCH_NODES = re.compile(r"^/api/v1/orchestration/canvas/([a-zA-Z0-9_-]+)/nodes$")
ORCH_NODE = re.compile(r"^/api/v1/orchestration/canvas/([a-zA-Z0-9_-]+)/nodes/([a-zA-Z0-9_-]+)$")
ORCH_EDGES = re.compile(r"^/api/v1/orchestration/canvas/([a-zA-Z0-9_-]+)/edges$")
ORCH_EDGE = re.compile(r"^/api/v1/orchestration/canvas/([a-zA-Z0-9_-]+)/edges/([a-zA-Z0-9_-]+)$")
ORCH_EXPORT = re.compile(r"^/api/v1/orchestration/canvas/([a-zA-Z0-9_-]+)/export$")
ORCH_EXECUTE = re.compile(r"^/api/v1/orchestration/canvas/([a-zA-Z0-9_-]+)/execute$")


class OrchestrationCanvasHandler(SecureHandler):
    """Handler for Orchestration Canvas REST API endpoints."""

    def __init__(self, ctx: dict | None = None):
        self.ctx = ctx or {}

    RESOURCE_TYPE = "orchestration"

    def can_handle(self, path: str) -> bool:
        return path.startswith("/api/v1/orchestration/canvas")

    def handle(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        client_ip = get_client_ip(handler)
        if not _orchestration_limiter.is_allowed(client_ip):
            return error_response("Rate limit exceeded", 429)

        user_id = None
        workspace_id = None
        try:
            user, err = self.require_auth_or_error(handler)
            if err:
                return err
            if user:
                user_id = user.user_id
                workspace_id = user.org_id
        except (ValueError, AttributeError, KeyError) as e:
            logger.warning("Authentication failed for orchestration: %s", e)
            return error_response("Authentication required", 401)

        method = getattr(handler, "command", "GET")
        auth_context = AuthorizationContext(
            user_id=user_id or "anonymous",
            org_id=workspace_id,
            roles=getattr(user, "roles", set()) if user else {"member"},
        )

        workspace_id = query_params.get("workspace_id") or workspace_id
        body = self._get_request_body(handler)

        try:
            return self._route_request(
                path,
                method,
                query_params,
                body,
                user_id,
                workspace_id,
                auth_context,
            )
        except PermissionDeniedError as e:
            perm = e.permission_key if hasattr(e, "permission_key") else "unknown"
            logger.warning("Permission denied: %s", perm)
            return error_response("Permission denied", 403)

    def _get_request_body(self, handler: Any) -> dict[str, Any]:
        try:
            if hasattr(handler, "request") and hasattr(handler.request, "body"):
                raw = handler.request.body
                if raw:
                    return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.debug("Failed to parse request body: %s", e)
        return {}

    def _route_request(
        self,
        path: str,
        method: str,
        query_params: dict[str, Any],
        body: dict[str, Any],
        user_id: str | None,
        workspace_id: str | None,
        context: AuthorizationContext,
    ) -> HandlerResult | None:
        # List / Create
        if ORCH_LIST.match(path):
            if method == "GET":
                return self._list_canvases(context, query_params, user_id, workspace_id)
            if method == "POST":
                return self._create_canvas(context, body, user_id, workspace_id)
            return error_response("Method not allowed", 405)

        # Export (must be checked before generic ID)
        m = ORCH_EXPORT.match(path)
        if m:
            if method == "GET":
                return self._export_canvas(context, m.group(1), user_id)
            return error_response("Method not allowed", 405)

        # Execute pipeline
        m = ORCH_EXECUTE.match(path)
        if m:
            if method == "POST":
                return self._execute_pipeline(context, m.group(1), body, user_id)
            return error_response("Method not allowed", 405)

        # Nodes collection
        m = ORCH_NODES.match(path)
        if m:
            if method == "POST":
                return self._add_node(context, m.group(1), body, user_id)
            return error_response("Method not allowed", 405)

        # Single node
        m = ORCH_NODE.match(path)
        if m:
            canvas_id, node_id = m.groups()
            if method == "PUT":
                return self._update_node(context, canvas_id, node_id, body, user_id)
            if method == "DELETE":
                return self._delete_node(context, canvas_id, node_id, user_id)
            return error_response("Method not allowed", 405)

        # Edges collection
        m = ORCH_EDGES.match(path)
        if m:
            if method == "POST":
                return self._add_edge(context, m.group(1), body, user_id)
            return error_response("Method not allowed", 405)

        # Single edge
        m = ORCH_EDGE.match(path)
        if m:
            canvas_id, edge_id = m.groups()
            if method == "DELETE":
                return self._delete_edge(context, canvas_id, edge_id, user_id)
            return error_response("Method not allowed", 405)

        # Canvas by ID
        m = ORCH_BY_ID.match(path)
        if m:
            canvas_id = m.group(1)
            if method == "GET":
                return self._get_canvas(context, canvas_id, user_id)
            if method == "PUT":
                return self._update_canvas(context, canvas_id, body, user_id)
            if method == "DELETE":
                return self._delete_canvas(context, canvas_id, user_id)
            return error_response("Method not allowed", 405)

        return None

    # ------------------------------------------------------------------
    # Store helpers
    # ------------------------------------------------------------------

    def _get_store(self):
        from aragora.canvas.orchestration_store import get_orchestration_canvas_store

        return get_orchestration_canvas_store()

    def _get_canvas_manager(self):
        from aragora.canvas import get_canvas_manager

        return get_canvas_manager()

    def _run_async(self, coro):
        import concurrent.futures

        try:
            asyncio.get_running_loop()
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result(timeout=30)
        except RuntimeError:
            return asyncio.run(coro)

    # ------------------------------------------------------------------
    # Canvas CRUD
    # ------------------------------------------------------------------

    @require_permission("orchestration:read")
    def _list_canvases(
        self,
        context: AuthorizationContext,
        query_params: dict[str, Any],
        user_id: str | None,
        workspace_id: str | None,
    ) -> HandlerResult:
        try:
            store = self._get_store()
            canvases = store.list_canvases(
                workspace_id=query_params.get("workspace_id") or workspace_id,
                owner_id=query_params.get("owner_id") or user_id,
                source_canvas_id=query_params.get("source_canvas_id"),
                limit=max(1, min(int(query_params.get("limit", 100)), 1000)),
                offset=max(0, int(query_params.get("offset", 0))),
            )
            return json_response({"canvases": canvases, "count": len(canvases)})
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to list orchestration canvases: %s", e)
            return error_response("Failed to list orchestration canvases", 500)

    @require_permission("orchestration:create")
    def _create_canvas(
        self,
        context: AuthorizationContext,
        body: dict[str, Any],
        user_id: str | None,
        workspace_id: str | None,
    ) -> HandlerResult:
        try:
            store = self._get_store()
            canvas_id = body.get("id") or f"orch-{uuid.uuid4().hex[:8]}"
            result = store.save_canvas(
                canvas_id=canvas_id,
                name=body.get("name", "Untitled Orchestration"),
                owner_id=user_id,
                workspace_id=workspace_id,
                description=body.get("description", ""),
                source_canvas_id=body.get("source_canvas_id"),
                metadata=body.get("metadata", {"stage": "orchestration"}),
            )
            return json_response(result, status=201)
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to create orchestration canvas: %s", e)
            return error_response("Canvas creation failed", 500)

    @require_permission("orchestration:read")
    def _get_canvas(
        self,
        context: AuthorizationContext,
        canvas_id: str,
        user_id: str | None,
    ) -> HandlerResult:
        try:
            store = self._get_store()
            canvas_meta = store.load_canvas(canvas_id)
            if not canvas_meta:
                return error_response("Orchestration canvas not found", 404)

            # Get live canvas state from manager
            manager = self._get_canvas_manager()
            canvas = self._run_async(manager.get_canvas(canvas_id))
            if canvas:
                canvas_meta["nodes"] = [n.to_dict() for n in canvas.nodes.values()]
                canvas_meta["edges"] = [e.to_dict() for e in canvas.edges.values()]
            else:
                canvas_meta.setdefault("nodes", [])
                canvas_meta.setdefault("edges", [])

            return json_response(canvas_meta)
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to get orchestration canvas: %s", e)
            return error_response("Failed to retrieve orchestration canvas", 500)

    @require_permission("orchestration:update")
    def _update_canvas(
        self,
        context: AuthorizationContext,
        canvas_id: str,
        body: dict[str, Any],
        user_id: str | None,
    ) -> HandlerResult:
        try:
            store = self._get_store()
            result = store.update_canvas(
                canvas_id=canvas_id,
                name=body.get("name"),
                description=body.get("description"),
                metadata=body.get("metadata"),
            )
            if not result:
                return error_response("Orchestration canvas not found", 404)
            return json_response(result)
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to update orchestration canvas: %s", e)
            return error_response("Canvas update failed", 500)

    @require_permission("orchestration:delete")
    def _delete_canvas(
        self,
        context: AuthorizationContext,
        canvas_id: str,
        user_id: str | None,
    ) -> HandlerResult:
        try:
            store = self._get_store()
            deleted = store.delete_canvas(canvas_id)
            if not deleted:
                return error_response("Orchestration canvas not found", 404)
            return json_response({"deleted": True, "canvas_id": canvas_id})
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to delete orchestration canvas: %s", e)
            return error_response("Canvas deletion failed", 500)

    # ------------------------------------------------------------------
    # Node CRUD
    # ------------------------------------------------------------------

    @require_permission("orchestration:create")
    def _add_node(
        self,
        context: AuthorizationContext,
        canvas_id: str,
        body: dict[str, Any],
        user_id: str | None,
    ) -> HandlerResult:
        try:
            from aragora.canvas import CanvasNodeType, Position
            from aragora.canvas.stages import OrchestrationNodeType

            manager = self._get_canvas_manager()

            orch_type = body.get("orchestration_type", "agent_task")
            try:
                OrchestrationNodeType(orch_type)
            except ValueError:
                return error_response(f"Invalid orchestration type: {orch_type}", 400)

            pos_data = body.get("position", {})
            position = Position(
                x=float(pos_data.get("x", 0)),
                y=float(pos_data.get("y", 0)),
            )

            data = body.get("data", {})
            data["orchestration_type"] = orch_type
            data["agent_id"] = body.get("agent_id", data.get("agent_id", ""))
            data["stage"] = "orchestration"
            data["rf_type"] = "orchestrationNode"

            node = self._run_async(
                manager.add_node(
                    canvas_id=canvas_id,
                    node_type=CanvasNodeType.KNOWLEDGE,
                    position=position,
                    label=body.get("label", ""),
                    data=data,
                    user_id=user_id,
                )
            )
            if not node:
                return error_response("Canvas not found", 404)
            return json_response(node.to_dict(), status=201)
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to add orchestration node: %s", e)
            return error_response("Node addition failed", 500)

    @require_permission("orchestration:update")
    def _update_node(
        self,
        context: AuthorizationContext,
        canvas_id: str,
        node_id: str,
        body: dict[str, Any],
        user_id: str | None,
    ) -> HandlerResult:
        try:
            from aragora.canvas import Position

            manager = self._get_canvas_manager()
            updates: dict[str, Any] = {}
            if "position" in body:
                p = body["position"]
                updates["position"] = Position(x=float(p.get("x", 0)), y=float(p.get("y", 0)))
            if "label" in body:
                updates["label"] = body["label"]
            if "data" in body:
                updates["data"] = body["data"]

            node = self._run_async(
                manager.update_node(
                    canvas_id=canvas_id,
                    node_id=node_id,
                    user_id=user_id,
                    **updates,
                )
            )
            if not node:
                return error_response("Node or canvas not found", 404)
            return json_response(node.to_dict())
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to update orchestration node: %s", e)
            return error_response("Node update failed", 500)

    @require_permission("orchestration:delete")
    def _delete_node(
        self,
        context: AuthorizationContext,
        canvas_id: str,
        node_id: str,
        user_id: str | None,
    ) -> HandlerResult:
        try:
            manager = self._get_canvas_manager()
            deleted = self._run_async(manager.remove_node(canvas_id, node_id, user_id=user_id))
            if not deleted:
                return error_response("Node or canvas not found", 404)
            return json_response({"deleted": True, "node_id": node_id})
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to delete orchestration node: %s", e)
            return error_response("Node deletion failed", 500)

    # ------------------------------------------------------------------
    # Edge CRUD
    # ------------------------------------------------------------------

    @require_permission("orchestration:create")
    def _add_edge(
        self,
        context: AuthorizationContext,
        canvas_id: str,
        body: dict[str, Any],
        user_id: str | None,
    ) -> HandlerResult:
        try:
            from aragora.canvas import EdgeType

            manager = self._get_canvas_manager()
            source_id = body.get("source_id") or body.get("source")
            target_id = body.get("target_id") or body.get("target")
            if not source_id or not target_id:
                return error_response("source_id and target_id are required", 400)

            edge_type_str = body.get("type", "default")
            try:
                edge_type = EdgeType(edge_type_str)
            except ValueError:
                edge_type = EdgeType.DEFAULT

            edge = self._run_async(
                manager.add_edge(
                    canvas_id=canvas_id,
                    source_id=source_id,
                    target_id=target_id,
                    edge_type=edge_type,
                    label=body.get("label", ""),
                    data=body.get("data", {}),
                    user_id=user_id,
                )
            )
            if not edge:
                return error_response("Canvas or nodes not found", 404)
            return json_response(edge.to_dict(), status=201)
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to add orchestration edge: %s", e)
            return error_response("Edge addition failed", 500)

    @require_permission("orchestration:delete")
    def _delete_edge(
        self,
        context: AuthorizationContext,
        canvas_id: str,
        edge_id: str,
        user_id: str | None,
    ) -> HandlerResult:
        try:
            manager = self._get_canvas_manager()
            deleted = self._run_async(manager.remove_edge(canvas_id, edge_id, user_id=user_id))
            if not deleted:
                return error_response("Edge or canvas not found", 404)
            return json_response({"deleted": True, "edge_id": edge_id})
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to delete orchestration edge: %s", e)
            return error_response("Edge deletion failed", 500)

    # ------------------------------------------------------------------
    # Export & Execute
    # ------------------------------------------------------------------

    @require_permission("orchestration:read")
    def _export_canvas(
        self,
        context: AuthorizationContext,
        canvas_id: str,
        user_id: str | None,
    ) -> HandlerResult:
        try:
            from aragora.canvas.converters import to_react_flow

            manager = self._get_canvas_manager()
            canvas = self._run_async(manager.get_canvas(canvas_id))
            if not canvas:
                return error_response("Canvas not found", 404)
            return json_response(to_react_flow(canvas))
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to export orchestration canvas: %s", e)
            return error_response("Export failed", 500)

    @require_permission("orchestration:execute")
    def _execute_pipeline(
        self,
        context: AuthorizationContext,
        canvas_id: str,
        body: dict[str, Any],
        user_id: str | None,
    ) -> HandlerResult:
        """Execute the orchestration pipeline defined by this canvas."""
        try:
            store = self._get_store()
            canvas_meta = store.load_canvas(canvas_id)
            if not canvas_meta:
                return error_response("Canvas not found", 404)

            manager = self._get_canvas_manager()
            canvas = self._run_async(manager.get_canvas(canvas_id))

            nodes = []
            edges = []
            if canvas:
                nodes = [n.to_dict() for n in canvas.nodes.values()]
                edges = [e.to_dict() for e in canvas.edges.values()]

            from aragora.pipeline.canonical_execution import (
                build_decision_plan_from_orchestration,
                execute_queued_plan,
                queue_plan_execution,
                schedule_coroutine,
            )

            plan, tasks = build_decision_plan_from_orchestration(
                subject_id=canvas_id,
                subject_label=canvas_meta.get("name") or f"Orchestration canvas {canvas_id}",
                nodes=nodes,
                edges=edges,
                source_surface="orchestration_canvas",
                metadata={
                    "canvas_id": canvas_id,
                    "canvas_metadata": canvas_meta.get("metadata", {}),
                },
                execution_mode="workflow",
            )
            launch = queue_plan_execution(plan, auth_context=context, execution_mode="workflow")

            metadata = dict(canvas_meta.get("metadata", {}) or {})
            metadata["execution"] = {
                **launch,
                "runtime": "decision_plan",
                "status": "queued",
                "tasks_total": len(tasks),
                "nodes_count": len(nodes),
                "edges_count": len(edges),
            }
            store.update_canvas(canvas_id=canvas_id, metadata=metadata)

            async def _execute() -> None:
                try:
                    outcome, record, decision_receipt = await execute_queued_plan(
                        plan,
                        execution_id=launch["execution_id"],
                        correlation_id=launch["correlation_id"],
                        auth_context=context,
                        execution_mode=launch["execution_mode"],
                    )
                    updated_metadata = dict(store.load_canvas(canvas_id).get("metadata", {}) or {})
                    updated_metadata["execution"] = {
                        **updated_metadata.get("execution", {}),
                        "status": "completed" if outcome.success else "failed",
                        "record": record,
                        "outcome": outcome.to_dict(),
                        "receipt": decision_receipt,
                    }
                    store.update_canvas(canvas_id=canvas_id, metadata=updated_metadata)
                except Exception as exc:  # noqa: BLE001 - persist terminal failure state
                    logger.error("Failed to execute orchestration canvas %s: %s", canvas_id, exc)
                    updated_metadata = dict(store.load_canvas(canvas_id).get("metadata", {}) or {})
                    updated_metadata["execution"] = {
                        **updated_metadata.get("execution", {}),
                        "status": "failed",
                        "error": str(exc),
                    }
                    store.update_canvas(canvas_id=canvas_id, metadata=updated_metadata)

            schedule_coroutine(
                _execute(),
                name=f"orch-plan-exec-{canvas_id[:8]}",
            )

            return json_response(
                {
                    "execution_id": launch["execution_id"],
                    "plan_id": plan.id,
                    "correlation_id": launch["correlation_id"],
                    "canvas_id": canvas_id,
                    "stage": "orchestration",
                    "nodes_count": len(nodes),
                    "edges_count": len(edges),
                    "metadata": canvas_meta.get("metadata", {}),
                    "status": "queued",
                    "runtime": "decision_plan",
                },
                status=201,
            )
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to execute orchestration pipeline: %s", e)
            return error_response("Pipeline execution failed", 500)
