"""
HTTP Handler for Action Canvas (Stage 3 of the Idea-to-Execution Pipeline).

REST endpoints:
    GET    /api/v1/actions                           -- List action canvases
    POST   /api/v1/actions                           -- Create action canvas
    GET    /api/v1/actions/{canvas_id}               -- Get full action canvas
    PUT    /api/v1/actions/{canvas_id}               -- Update action canvas metadata
    DELETE /api/v1/actions/{canvas_id}               -- Delete action canvas
    POST   /api/v1/actions/{canvas_id}/nodes         -- Add action node
    PUT    /api/v1/actions/{canvas_id}/nodes/{id}    -- Update action node
    DELETE /api/v1/actions/{canvas_id}/nodes/{id}    -- Delete action node
    POST   /api/v1/actions/{canvas_id}/edges         -- Add action edge
    DELETE /api/v1/actions/{canvas_id}/edges/{id}    -- Delete action edge
    GET    /api/v1/actions/{canvas_id}/export        -- Export as React Flow JSON
    POST   /api/v1/actions/{canvas_id}/advance       -- Advance to orchestration stage

RBAC:
    actions:read, actions:create, actions:update, actions:delete, actions:advance
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

_actions_limiter = RateLimiter(requests_per_minute=120)

# Route patterns
ACTIONS_LIST = re.compile(r"^/api/v1/actions$")
ACTIONS_BY_ID = re.compile(r"^/api/v1/actions/([a-zA-Z0-9_-]+)$")
ACTIONS_NODES = re.compile(r"^/api/v1/actions/([a-zA-Z0-9_-]+)/nodes$")
ACTIONS_NODE = re.compile(r"^/api/v1/actions/([a-zA-Z0-9_-]+)/nodes/([a-zA-Z0-9_-]+)$")
ACTIONS_EDGES = re.compile(r"^/api/v1/actions/([a-zA-Z0-9_-]+)/edges$")
ACTIONS_EDGE = re.compile(r"^/api/v1/actions/([a-zA-Z0-9_-]+)/edges/([a-zA-Z0-9_-]+)$")
ACTIONS_EXPORT = re.compile(r"^/api/v1/actions/([a-zA-Z0-9_-]+)/export$")
ACTIONS_ADVANCE = re.compile(r"^/api/v1/actions/([a-zA-Z0-9_-]+)/advance$")


class ActionCanvasHandler(SecureHandler):
    """Handler for Action Canvas REST API endpoints."""

    def __init__(self, ctx: dict | None = None):
        self.ctx = ctx or {}

    RESOURCE_TYPE = "actions"

    def can_handle(self, path: str) -> bool:
        return path.startswith("/api/v1/actions")

    def handle(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        client_ip = get_client_ip(handler)
        if not _actions_limiter.is_allowed(client_ip):
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
            logger.warning("Authentication failed for actions: %s", e)
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
        if ACTIONS_LIST.match(path):
            if method == "GET":
                return self._list_canvases(context, query_params, user_id, workspace_id)
            if method == "POST":
                return self._create_canvas(context, body, user_id, workspace_id)
            return error_response("Method not allowed", 405)

        # Export (must be checked before generic ID)
        m = ACTIONS_EXPORT.match(path)
        if m:
            if method == "GET":
                return self._export_canvas(context, m.group(1), user_id)
            return error_response("Method not allowed", 405)

        # Advance to orchestration stage
        m = ACTIONS_ADVANCE.match(path)
        if m:
            if method == "POST":
                return self._advance_to_orchestration(context, m.group(1), body, user_id)
            return error_response("Method not allowed", 405)

        # Nodes collection
        m = ACTIONS_NODES.match(path)
        if m:
            if method == "POST":
                return self._add_node(context, m.group(1), body, user_id)
            return error_response("Method not allowed", 405)

        # Single node
        m = ACTIONS_NODE.match(path)
        if m:
            canvas_id, node_id = m.groups()
            if method == "PUT":
                return self._update_node(context, canvas_id, node_id, body, user_id)
            if method == "DELETE":
                return self._delete_node(context, canvas_id, node_id, user_id)
            return error_response("Method not allowed", 405)

        # Edges collection
        m = ACTIONS_EDGES.match(path)
        if m:
            if method == "POST":
                return self._add_edge(context, m.group(1), body, user_id)
            return error_response("Method not allowed", 405)

        # Single edge
        m = ACTIONS_EDGE.match(path)
        if m:
            canvas_id, edge_id = m.groups()
            if method == "DELETE":
                return self._delete_edge(context, canvas_id, edge_id, user_id)
            return error_response("Method not allowed", 405)

        # Canvas by ID
        m = ACTIONS_BY_ID.match(path)
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
        from aragora.canvas.action_store import get_action_canvas_store

        return get_action_canvas_store()

    def _get_orchestration_store(self):
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

    @staticmethod
    def _snapshot_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
        snapshot = dict(metadata or {})
        snapshot.setdefault("stage", "actions")
        snapshot["state_snapshot_version"] = 1
        return snapshot

    @staticmethod
    def _has_persisted_state(canvas_meta: dict[str, Any] | None) -> bool:
        if not canvas_meta:
            return False
        metadata = canvas_meta.get("metadata", {}) or {}
        return bool(
            canvas_meta.get("nodes")
            or canvas_meta.get("edges")
            or metadata.get("state_snapshot_version")
        )

    def _persist_canvas_state(self, canvas) -> dict[str, Any] | None:
        store = self._get_store()
        return store.update_canvas(
            canvas_id=canvas.id,
            name=canvas.name,
            metadata=self._snapshot_metadata(getattr(canvas, "metadata", {})),
            nodes=[n.to_dict() for n in canvas.nodes.values()],
            edges=[e.to_dict() for e in canvas.edges.values()],
        )

    def _restore_canvas_state(self, canvas_meta: dict[str, Any]):
        if not self._has_persisted_state(canvas_meta):
            return None

        from aragora.canvas import Canvas

        snapshot = Canvas.from_dict(
            {
                "id": canvas_meta.get("id"),
                "name": canvas_meta.get("name", "Untitled Actions"),
                "metadata": self._snapshot_metadata(canvas_meta.get("metadata", {})),
                "owner_id": canvas_meta.get("owner_id"),
                "workspace_id": canvas_meta.get("workspace_id"),
                "nodes": canvas_meta.get("nodes", []),
                "edges": canvas_meta.get("edges", []),
            }
        )
        manager = self._get_canvas_manager()

        async def _restore():
            live_canvas = await manager.get_or_create_canvas(
                snapshot.id,
                name=snapshot.name,
                owner_id=snapshot.owner_id,
                workspace_id=snapshot.workspace_id,
                **snapshot.metadata,
            )
            live_canvas.name = snapshot.name
            live_canvas.owner_id = snapshot.owner_id
            live_canvas.workspace_id = snapshot.workspace_id
            live_canvas.metadata = dict(snapshot.metadata)
            live_canvas.nodes = dict(snapshot.nodes)
            live_canvas.edges = dict(snapshot.edges)
            return live_canvas

        return self._run_async(_restore())

    def _get_or_restore_canvas(
        self,
        canvas_id: str,
        canvas_meta: dict[str, Any] | None = None,
    ):
        manager = self._get_canvas_manager()
        canvas = self._run_async(manager.get_canvas(canvas_id))
        if canvas is not None:
            return canvas
        if canvas_meta is None:
            canvas_meta = self._get_store().load_canvas(canvas_id)
        if not canvas_meta:
            return None
        return self._restore_canvas_state(canvas_meta)

    # ------------------------------------------------------------------
    # Canvas CRUD
    # ------------------------------------------------------------------

    @require_permission("actions:read")
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
            logger.error("Failed to list action canvases: %s", e)
            return error_response("Failed to list action canvases", 500)

    @require_permission("actions:create")
    def _create_canvas(
        self,
        context: AuthorizationContext,
        body: dict[str, Any],
        user_id: str | None,
        workspace_id: str | None,
    ) -> HandlerResult:
        try:
            store = self._get_store()
            canvas_id = body.get("id") or f"actions-{uuid.uuid4().hex[:8]}"
            metadata = self._snapshot_metadata(body.get("metadata", {"stage": "actions"}))
            result = store.save_canvas(
                canvas_id=canvas_id,
                name=body.get("name", "Untitled Actions"),
                owner_id=user_id,
                workspace_id=workspace_id,
                description=body.get("description", ""),
                source_canvas_id=body.get("source_canvas_id"),
                metadata=metadata,
                nodes=body.get("nodes", []),
                edges=body.get("edges", []),
            )
            return json_response(result, status=201)
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to create action canvas: %s", e)
            return error_response("Canvas creation failed", 500)

    @require_permission("actions:read")
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
                return error_response("Action canvas not found", 404)

            canvas = self._get_or_restore_canvas(canvas_id, canvas_meta)
            if canvas:
                self._persist_canvas_state(canvas)
                canvas_meta["metadata"] = self._snapshot_metadata(
                    getattr(canvas, "metadata", canvas_meta.get("metadata", {}))
                )
                canvas_meta["nodes"] = [n.to_dict() for n in canvas.nodes.values()]
                canvas_meta["edges"] = [e.to_dict() for e in canvas.edges.values()]
            else:
                canvas_meta["nodes"] = list(canvas_meta.get("nodes") or [])
                canvas_meta["edges"] = list(canvas_meta.get("edges") or [])

            return json_response(canvas_meta)
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to get action canvas: %s", e)
            return error_response("Failed to retrieve action canvas", 500)

    @require_permission("actions:update")
    def _update_canvas(
        self,
        context: AuthorizationContext,
        canvas_id: str,
        body: dict[str, Any],
        user_id: str | None,
    ) -> HandlerResult:
        try:
            store = self._get_store()
            metadata = body.get("metadata")
            if metadata is not None:
                metadata = self._snapshot_metadata(metadata)
            result = store.update_canvas(
                canvas_id=canvas_id,
                name=body.get("name"),
                description=body.get("description"),
                metadata=metadata,
            )
            if not result:
                return error_response("Action canvas not found", 404)
            if body.get("name") is not None or metadata is not None:
                manager = self._get_canvas_manager()
                canvas = self._get_or_restore_canvas(canvas_id, result)
                if canvas is not None:
                    updated_canvas = self._run_async(
                        manager.update_canvas(
                            canvas_id=canvas_id,
                            name=body.get("name"),
                            metadata=metadata,
                            user_id=user_id,
                        )
                    )
                    if updated_canvas is not None:
                        result = self._persist_canvas_state(updated_canvas) or result
            return json_response(result)
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to update action canvas: %s", e)
            return error_response("Canvas update failed", 500)

    @require_permission("actions:delete")
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
                return error_response("Action canvas not found", 404)
            manager = self._get_canvas_manager()
            self._run_async(manager.delete_canvas(canvas_id))
            return json_response({"deleted": True, "canvas_id": canvas_id})
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to delete action canvas: %s", e)
            return error_response("Canvas deletion failed", 500)

    # ------------------------------------------------------------------
    # Node CRUD
    # ------------------------------------------------------------------

    @require_permission("actions:create")
    def _add_node(
        self,
        context: AuthorizationContext,
        canvas_id: str,
        body: dict[str, Any],
        user_id: str | None,
    ) -> HandlerResult:
        try:
            from aragora.canvas import CanvasNodeType, Position
            from aragora.canvas.stages import ActionNodeType

            action_type = body.get("action_type", "task")
            try:
                ActionNodeType(action_type)
            except ValueError:
                return error_response(f"Invalid action type: {action_type}", 400)

            store = self._get_store()
            canvas_meta = store.load_canvas(canvas_id)
            if not canvas_meta:
                return error_response("Canvas not found", 404)

            if self._get_or_restore_canvas(canvas_id, canvas_meta) is None:
                return error_response("Action canvas state unavailable", 409)

            manager = self._get_canvas_manager()
            pos_data = body.get("position", {})
            position = Position(
                x=float(pos_data.get("x", 0)),
                y=float(pos_data.get("y", 0)),
            )

            data = body.get("data", {})
            data["action_type"] = action_type
            data["assignee"] = body.get("assignee", data.get("assignee", ""))
            data["status"] = body.get("status", data.get("status", "todo"))
            data["stage"] = "actions"
            data["rf_type"] = "actionNode"

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
            canvas = self._run_async(manager.get_canvas(canvas_id))
            if canvas is not None:
                self._persist_canvas_state(canvas)
            return json_response(node.to_dict(), status=201)
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to add action node: %s", e)
            return error_response("Node addition failed", 500)

    @require_permission("actions:update")
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

            store = self._get_store()
            canvas_meta = store.load_canvas(canvas_id)
            if not canvas_meta:
                return error_response("Node or canvas not found", 404)

            if self._get_or_restore_canvas(canvas_id, canvas_meta) is None:
                return error_response("Action canvas state unavailable", 409)

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
            canvas = self._run_async(manager.get_canvas(canvas_id))
            if canvas is not None:
                self._persist_canvas_state(canvas)
            return json_response(node.to_dict())
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to update action node: %s", e)
            return error_response("Node update failed", 500)

    @require_permission("actions:delete")
    def _delete_node(
        self,
        context: AuthorizationContext,
        canvas_id: str,
        node_id: str,
        user_id: str | None,
    ) -> HandlerResult:
        try:
            store = self._get_store()
            canvas_meta = store.load_canvas(canvas_id)
            if not canvas_meta:
                return error_response("Node or canvas not found", 404)

            if self._get_or_restore_canvas(canvas_id, canvas_meta) is None:
                return error_response("Action canvas state unavailable", 409)

            manager = self._get_canvas_manager()
            deleted = self._run_async(manager.remove_node(canvas_id, node_id, user_id=user_id))
            if not deleted:
                return error_response("Node or canvas not found", 404)
            canvas = self._run_async(manager.get_canvas(canvas_id))
            if canvas is not None:
                self._persist_canvas_state(canvas)
            return json_response({"deleted": True, "node_id": node_id})
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to delete action node: %s", e)
            return error_response("Node deletion failed", 500)

    # ------------------------------------------------------------------
    # Edge CRUD
    # ------------------------------------------------------------------

    @require_permission("actions:create")
    def _add_edge(
        self,
        context: AuthorizationContext,
        canvas_id: str,
        body: dict[str, Any],
        user_id: str | None,
    ) -> HandlerResult:
        try:
            from aragora.canvas import EdgeType

            source_id = body.get("source_id") or body.get("source")
            target_id = body.get("target_id") or body.get("target")
            if not source_id or not target_id:
                return error_response("source_id and target_id are required", 400)

            store = self._get_store()
            canvas_meta = store.load_canvas(canvas_id)
            if not canvas_meta:
                return error_response("Canvas or nodes not found", 404)

            if self._get_or_restore_canvas(canvas_id, canvas_meta) is None:
                return error_response("Action canvas state unavailable", 409)

            manager = self._get_canvas_manager()
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
            canvas = self._run_async(manager.get_canvas(canvas_id))
            if canvas is not None:
                self._persist_canvas_state(canvas)
            return json_response(edge.to_dict(), status=201)
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to add action edge: %s", e)
            return error_response("Edge addition failed", 500)

    @require_permission("actions:delete")
    def _delete_edge(
        self,
        context: AuthorizationContext,
        canvas_id: str,
        edge_id: str,
        user_id: str | None,
    ) -> HandlerResult:
        try:
            store = self._get_store()
            canvas_meta = store.load_canvas(canvas_id)
            if not canvas_meta:
                return error_response("Edge or canvas not found", 404)

            if self._get_or_restore_canvas(canvas_id, canvas_meta) is None:
                return error_response("Action canvas state unavailable", 409)

            manager = self._get_canvas_manager()
            deleted = self._run_async(manager.remove_edge(canvas_id, edge_id, user_id=user_id))
            if not deleted:
                return error_response("Edge or canvas not found", 404)
            canvas = self._run_async(manager.get_canvas(canvas_id))
            if canvas is not None:
                self._persist_canvas_state(canvas)
            return json_response({"deleted": True, "edge_id": edge_id})
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to delete action edge: %s", e)
            return error_response("Edge deletion failed", 500)

    # ------------------------------------------------------------------
    # Export & Advance
    # ------------------------------------------------------------------

    def _build_orchestration_canvas(
        self,
        action_canvas: Any,
        source_canvas_id: str,
        canvas_meta: dict[str, Any],
    ):
        from aragora.canvas import execution_to_orchestration_canvas
        from aragora.pipeline.idea_to_execution import IdeaToExecutionPipeline

        pipeline = IdeaToExecutionPipeline()
        execution_plan = pipeline._actions_to_execution_plan(action_canvas)
        orchestration_canvas = execution_to_orchestration_canvas(
            execution_plan,
            canvas_name=f"{canvas_meta.get('name', 'Untitled Actions')} Orchestration",
        )
        orchestration_canvas.metadata.update(
            {
                "stage": "orchestration",
                "source_canvas_id": source_canvas_id,
                "source_stage": "actions",
            }
        )
        return orchestration_canvas

    @require_permission("actions:read")
    def _export_canvas(
        self,
        context: AuthorizationContext,
        canvas_id: str,
        user_id: str | None,
    ) -> HandlerResult:
        try:
            from aragora.canvas.converters import to_react_flow

            canvas_meta = self._get_store().load_canvas(canvas_id)
            canvas = self._get_or_restore_canvas(canvas_id, canvas_meta)
            if not canvas:
                return error_response("Canvas not found", 404)
            self._persist_canvas_state(canvas)
            return json_response(to_react_flow(canvas))
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to export action canvas: %s", e)
            return error_response("Export failed", 500)

    @require_permission("actions:advance")
    def _advance_to_orchestration(
        self,
        context: AuthorizationContext,
        canvas_id: str,
        body: dict[str, Any],
        user_id: str | None,
    ) -> HandlerResult:
        """Advance action canvas to the orchestration stage (Stage 4)."""
        try:
            store = self._get_store()
            canvas_meta = store.load_canvas(canvas_id)
            if not canvas_meta:
                return error_response("Canvas not found", 404)

            canvas = self._get_or_restore_canvas(canvas_id, canvas_meta)
            if canvas is None:
                return error_response("Action canvas state unavailable", 409)
            self._persist_canvas_state(canvas)

            orchestration_canvas = self._build_orchestration_canvas(canvas, canvas_id, canvas_meta)
            orchestration_store = self._get_orchestration_store()
            orchestration_meta = orchestration_store.save_canvas(
                canvas_id=orchestration_canvas.id,
                name=orchestration_canvas.name,
                owner_id=user_id,
                workspace_id=canvas_meta.get("workspace_id"),
                description=body.get("description", canvas_meta.get("description", "")),
                source_canvas_id=canvas_id,
                metadata=orchestration_canvas.metadata,
            )

            manager = self._get_canvas_manager()
            live_orchestration = self._run_async(
                manager.get_or_create_canvas(
                    orchestration_canvas.id,
                    name=orchestration_canvas.name,
                    owner_id=user_id,
                    workspace_id=canvas_meta.get("workspace_id"),
                    **orchestration_canvas.metadata,
                )
            )
            live_orchestration.name = orchestration_canvas.name
            live_orchestration.metadata = dict(orchestration_canvas.metadata)
            live_orchestration.owner_id = user_id
            live_orchestration.workspace_id = canvas_meta.get("workspace_id")
            live_orchestration.nodes = dict(orchestration_canvas.nodes)
            live_orchestration.edges = dict(orchestration_canvas.edges)

            return json_response(
                {
                    **orchestration_meta,
                    "source_canvas_id": canvas_id,
                    "source_stage": "actions",
                    "target_stage": "orchestration",
                    "orchestration_canvas_id": orchestration_canvas.id,
                    "nodes": [n.to_dict() for n in live_orchestration.nodes.values()],
                    "edges": [e.to_dict() for e in live_orchestration.edges.values()],
                    "metadata": orchestration_meta.get("metadata", live_orchestration.metadata),
                    "status": "created",
                },
                status=201,
            )
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to advance action canvas: %s", e)
            return error_response("Advance to orchestration failed", 500)
