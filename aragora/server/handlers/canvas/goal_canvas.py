"""
HTTP Handler for Goal Canvas (Stage 2 of the Idea-to-Execution Pipeline).

REST endpoints:
    GET    /api/v1/goals                           -- List goal canvases
    POST   /api/v1/goals                           -- Create goal canvas
    GET    /api/v1/goals/{canvas_id}               -- Get full goal canvas
    PUT    /api/v1/goals/{canvas_id}               -- Update goal canvas metadata
    DELETE /api/v1/goals/{canvas_id}               -- Delete goal canvas
    POST   /api/v1/goals/{canvas_id}/nodes         -- Add goal node
    PUT    /api/v1/goals/{canvas_id}/nodes/{id}    -- Update goal node
    DELETE /api/v1/goals/{canvas_id}/nodes/{id}    -- Delete goal node
    POST   /api/v1/goals/{canvas_id}/edges         -- Add goal edge
    DELETE /api/v1/goals/{canvas_id}/edges/{id}    -- Delete goal edge
    GET    /api/v1/goals/{canvas_id}/export        -- Export as React Flow JSON
    POST   /api/v1/goals/{canvas_id}/advance       -- Advance to actions stage

RBAC:
    goals:read, goals:create, goals:update, goals:delete, goals:advance
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

_goals_limiter = RateLimiter(requests_per_minute=120)

# Route patterns
GOALS_LIST = re.compile(r"^/api/v1/goals$")
GOALS_BY_ID = re.compile(r"^/api/v1/goals/([a-zA-Z0-9_-]+)$")
GOALS_NODES = re.compile(r"^/api/v1/goals/([a-zA-Z0-9_-]+)/nodes$")
GOALS_NODE = re.compile(r"^/api/v1/goals/([a-zA-Z0-9_-]+)/nodes/([a-zA-Z0-9_-]+)$")
GOALS_EDGES = re.compile(r"^/api/v1/goals/([a-zA-Z0-9_-]+)/edges$")
GOALS_EDGE = re.compile(r"^/api/v1/goals/([a-zA-Z0-9_-]+)/edges/([a-zA-Z0-9_-]+)$")
GOALS_EXPORT = re.compile(r"^/api/v1/goals/([a-zA-Z0-9_-]+)/export$")
GOALS_ADVANCE = re.compile(r"^/api/v1/goals/([a-zA-Z0-9_-]+)/advance$")


class GoalCanvasHandler(SecureHandler):
    """Handler for Goal Canvas REST API endpoints."""

    def __init__(self, ctx: dict | None = None):
        self.ctx = ctx or {}

    RESOURCE_TYPE = "goals"

    def can_handle(self, path: str) -> bool:
        return path.startswith("/api/v1/goals")

    def handle(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        client_ip = get_client_ip(handler)
        if not _goals_limiter.is_allowed(client_ip):
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
            logger.warning("Authentication failed for goals: %s", e)
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
        if GOALS_LIST.match(path):
            if method == "GET":
                return self._list_canvases(context, query_params, user_id, workspace_id)
            if method == "POST":
                return self._create_canvas(context, body, user_id, workspace_id)
            return error_response("Method not allowed", 405)

        # Export (must be checked before generic ID)
        m = GOALS_EXPORT.match(path)
        if m:
            if method == "GET":
                return self._export_canvas(context, m.group(1), user_id)
            return error_response("Method not allowed", 405)

        # Advance to actions stage
        m = GOALS_ADVANCE.match(path)
        if m:
            if method == "POST":
                return self._advance_to_actions(context, m.group(1), body, user_id)
            return error_response("Method not allowed", 405)

        # Nodes collection
        m = GOALS_NODES.match(path)
        if m:
            if method == "POST":
                return self._add_node(context, m.group(1), body, user_id)
            return error_response("Method not allowed", 405)

        # Single node
        m = GOALS_NODE.match(path)
        if m:
            canvas_id, node_id = m.groups()
            if method == "PUT":
                return self._update_node(context, canvas_id, node_id, body, user_id)
            if method == "DELETE":
                return self._delete_node(context, canvas_id, node_id, user_id)
            return error_response("Method not allowed", 405)

        # Edges collection
        m = GOALS_EDGES.match(path)
        if m:
            if method == "POST":
                return self._add_edge(context, m.group(1), body, user_id)
            return error_response("Method not allowed", 405)

        # Single edge
        m = GOALS_EDGE.match(path)
        if m:
            canvas_id, edge_id = m.groups()
            if method == "DELETE":
                return self._delete_edge(context, canvas_id, edge_id, user_id)
            return error_response("Method not allowed", 405)

        # Canvas by ID
        m = GOALS_BY_ID.match(path)
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
        from aragora.canvas.goal_store import get_goal_canvas_store

        return get_goal_canvas_store()

    def _get_action_store(self):
        from aragora.canvas.action_store import get_action_canvas_store

        return get_action_canvas_store()

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

    def _goal_canvas_to_goal_graph(self, canvas):
        from aragora.canvas import EdgeType
        from aragora.canvas.stages import GoalNodeType
        from aragora.goals.extractor import GoalGraph, GoalNode

        goal_ids = set(canvas.nodes)
        dependencies_by_target: dict[str, list[str]] = {}

        for edge in canvas.edges.values():
            if edge.source_id not in goal_ids or edge.target_id not in goal_ids:
                continue

            edge_type = getattr(edge.edge_type, "value", edge.edge_type)
            stage_edge_type = str(edge.data.get("stage_edge_type", "")).lower()
            edge_label = str(edge.label or "").lower()
            if (
                edge_type != EdgeType.DEPENDENCY.value
                and stage_edge_type != "requires"
                and edge_label not in {"requires", "after"}
            ):
                continue

            deps = dependencies_by_target.setdefault(edge.target_id, [])
            if edge.source_id not in deps:
                deps.append(edge.source_id)

        goals = []
        for node in canvas.nodes.values():
            if node.node_type.value != "decision" and node.data.get("stage") != "goals":
                continue

            goal_type_str = str(node.data.get("goal_type", "goal")).lower()
            try:
                goal_type = GoalNodeType(goal_type_str)
            except ValueError:
                goal_type = GoalNodeType.GOAL

            source_node_id = node.data.get("source_node_id")
            confidence = node.data.get("confidence", 0.0)
            try:
                confidence_value = float(confidence)
            except (TypeError, ValueError):
                confidence_value = 0.0

            goals.append(
                GoalNode(
                    id=node.id,
                    title=node.label or "Untitled Goal",
                    description=node.data.get("description", ""),
                    goal_type=goal_type,
                    priority=str(node.data.get("priority", "medium")).lower(),
                    measurable=str(node.data.get("measurable", "")),
                    dependencies=dependencies_by_target.get(node.id, []),
                    source_idea_ids=[source_node_id] if source_node_id else [],
                    confidence=confidence_value,
                    metadata={
                        key: value
                        for key, value in node.data.items()
                        if key
                        not in {
                            "stage",
                            "goal_type",
                            "description",
                            "priority",
                            "measurable",
                            "source_node_id",
                            "content_hash",
                            "rf_type",
                            "confidence",
                        }
                    },
                )
            )

        return GoalGraph(
            id=canvas.id,
            goals=goals,
            metadata={"source_canvas_id": canvas.id, "source_stage": "goals"},
        )

    def _build_actions_canvas(self, canvas, canvas_meta: dict[str, Any], body: dict[str, Any]):
        from aragora.canvas import workflow_to_actions_canvas
        from aragora.pipeline.idea_to_execution import IdeaToExecutionPipeline

        goal_graph = self._goal_canvas_to_goal_graph(canvas)
        if not goal_graph.goals:
            raise ValueError("Goal canvas has no goal nodes to advance")

        pipeline = IdeaToExecutionPipeline()
        workflow_data = pipeline._goals_to_workflow(goal_graph)

        target_canvas_id = (
            body.get("target_canvas_id") or body.get("id") or f"actions-{uuid.uuid4().hex[:8]}"
        )
        target_canvas_name = (
            body.get("name") or f"Action Plan for {canvas_meta.get('name', 'Goals')}"
        )

        action_canvas = workflow_to_actions_canvas(
            workflow_data,
            canvas_id=target_canvas_id,
            canvas_name=target_canvas_name,
        )
        action_canvas.owner_id = canvas.owner_id or canvas_meta.get("owner_id")
        action_canvas.workspace_id = canvas.workspace_id or canvas_meta.get("workspace_id")
        action_canvas.metadata.update(
            {
                "stage": "actions",
                "source_canvas_id": canvas.id,
                "source_stage": "goals",
                "state_snapshot_version": 1,
                "workflow_step_count": len(workflow_data.get("steps", [])),
            }
        )
        return action_canvas, workflow_data

    def _persist_canvas_state(self, canvas):
        manager = self._get_canvas_manager()

        async def _persist():
            live_canvas = await manager.get_or_create_canvas(
                canvas.id,
                name=canvas.name,
                owner_id=canvas.owner_id,
                workspace_id=canvas.workspace_id,
                **canvas.metadata,
            )
            live_canvas.name = canvas.name
            live_canvas.owner_id = canvas.owner_id
            live_canvas.workspace_id = canvas.workspace_id
            live_canvas.metadata = dict(canvas.metadata)
            live_canvas.nodes = dict(canvas.nodes)
            live_canvas.edges = dict(canvas.edges)
            return live_canvas

        return self._run_async(_persist())

    # ------------------------------------------------------------------
    # Canvas CRUD
    # ------------------------------------------------------------------

    @require_permission("goals:read")
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
            logger.error("Failed to list goal canvases: %s", e)
            return error_response("Failed to list goal canvases", 500)

    @require_permission("goals:create")
    def _create_canvas(
        self,
        context: AuthorizationContext,
        body: dict[str, Any],
        user_id: str | None,
        workspace_id: str | None,
    ) -> HandlerResult:
        try:
            store = self._get_store()
            canvas_id = body.get("id") or f"goals-{uuid.uuid4().hex[:8]}"
            result = store.save_canvas(
                canvas_id=canvas_id,
                name=body.get("name", "Untitled Goals"),
                owner_id=user_id,
                workspace_id=workspace_id,
                description=body.get("description", ""),
                source_canvas_id=body.get("source_canvas_id"),
                metadata=body.get("metadata", {"stage": "goals"}),
            )
            return json_response(result, status=201)
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to create goal canvas: %s", e)
            return error_response("Canvas creation failed", 500)

    @require_permission("goals:read")
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
                return error_response("Goal canvas not found", 404)

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
            logger.error("Failed to get goal canvas: %s", e)
            return error_response("Failed to retrieve goal canvas", 500)

    @require_permission("goals:update")
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
                return error_response("Goal canvas not found", 404)
            return json_response(result)
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to update goal canvas: %s", e)
            return error_response("Canvas update failed", 500)

    @require_permission("goals:delete")
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
                return error_response("Goal canvas not found", 404)
            return json_response({"deleted": True, "canvas_id": canvas_id})
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to delete goal canvas: %s", e)
            return error_response("Canvas deletion failed", 500)

    # ------------------------------------------------------------------
    # Node CRUD
    # ------------------------------------------------------------------

    @require_permission("goals:create")
    def _add_node(
        self,
        context: AuthorizationContext,
        canvas_id: str,
        body: dict[str, Any],
        user_id: str | None,
    ) -> HandlerResult:
        try:
            from aragora.canvas import CanvasNodeType, Position
            from aragora.canvas.stages import GoalNodeType

            manager = self._get_canvas_manager()

            goal_type = body.get("goal_type", "goal")
            try:
                GoalNodeType(goal_type)
            except ValueError:
                return error_response(f"Invalid goal type: {goal_type}", 400)

            pos_data = body.get("position", {})
            position = Position(
                x=float(pos_data.get("x", 0)),
                y=float(pos_data.get("y", 0)),
            )

            data = body.get("data", {})
            data["goal_type"] = goal_type
            data["priority"] = body.get("priority", data.get("priority", "medium"))
            data["measurable"] = body.get("measurable", data.get("measurable", False))
            data["stage"] = "goals"
            data["rf_type"] = "goalNode"

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
            logger.error("Failed to add goal node: %s", e)
            return error_response("Node addition failed", 500)

    @require_permission("goals:update")
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
            logger.error("Failed to update goal node: %s", e)
            return error_response("Node update failed", 500)

    @require_permission("goals:delete")
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
            logger.error("Failed to delete goal node: %s", e)
            return error_response("Node deletion failed", 500)

    # ------------------------------------------------------------------
    # Edge CRUD
    # ------------------------------------------------------------------

    @require_permission("goals:create")
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
            logger.error("Failed to add goal edge: %s", e)
            return error_response("Edge addition failed", 500)

    @require_permission("goals:delete")
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
            logger.error("Failed to delete goal edge: %s", e)
            return error_response("Edge deletion failed", 500)

    # ------------------------------------------------------------------
    # Export & Advance
    # ------------------------------------------------------------------

    @require_permission("goals:read")
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
            logger.error("Failed to export goal canvas: %s", e)
            return error_response("Export failed", 500)

    @require_permission("goals:advance")
    def _advance_to_actions(
        self,
        context: AuthorizationContext,
        canvas_id: str,
        body: dict[str, Any],
        user_id: str | None,
    ) -> HandlerResult:
        """Advance goal canvas to the actions stage (Stage 3)."""
        try:
            store = self._get_store()
            canvas_meta = store.load_canvas(canvas_id)
            if not canvas_meta:
                return error_response("Canvas not found", 404)

            manager = self._get_canvas_manager()
            canvas = self._run_async(manager.get_canvas(canvas_id))
            if not canvas:
                return error_response("Goal canvas state unavailable", 409)

            action_canvas, workflow_data = self._build_actions_canvas(canvas, canvas_meta, body)
            action_store = self._get_action_store()
            saved_canvas = action_store.save_canvas(
                canvas_id=action_canvas.id,
                name=action_canvas.name,
                owner_id=action_canvas.owner_id or user_id,
                workspace_id=action_canvas.workspace_id,
                description=body.get("description", canvas_meta.get("description", "")),
                source_canvas_id=canvas_id,
                metadata=action_canvas.metadata,
                nodes=[n.to_dict() for n in action_canvas.nodes.values()],
                edges=[e.to_dict() for e in action_canvas.edges.values()],
            )
            self._persist_canvas_state(action_canvas)

            return json_response(
                {
                    "canvas_id": action_canvas.id,
                    "target_canvas_id": action_canvas.id,
                    "source_canvas_id": canvas_id,
                    "source_stage": "goals",
                    "target_stage": "actions",
                    "nodes": [n.to_dict() for n in action_canvas.nodes.values()],
                    "edges": [e.to_dict() for e in action_canvas.edges.values()],
                    "metadata": saved_canvas.get("metadata", action_canvas.metadata),
                    "workflow_step_count": len(workflow_data.get("steps", [])),
                    "status": "ready",
                },
                status=201,
            )
        except ValueError as e:
            logger.warning("Cannot advance goal canvas %s: %s", canvas_id, e)
            return error_response(str(e), 422)
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to advance goal canvas: %s", e)
            return error_response("Advance to actions failed", 500)
