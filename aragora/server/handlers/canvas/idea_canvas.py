"""
HTTP Handler for Idea Canvas (Stage 1 of the Idea-to-Execution Pipeline).

REST endpoints:
    GET    /api/v1/ideas                           -- List canvases
    POST   /api/v1/ideas                           -- Create canvas
    GET    /api/v1/ideas/{canvas_id}               -- Get full canvas
    PUT    /api/v1/ideas/{canvas_id}               -- Update canvas metadata
    DELETE /api/v1/ideas/{canvas_id}               -- Delete canvas
    POST   /api/v1/ideas/{canvas_id}/nodes         -- Add node
    PUT    /api/v1/ideas/{canvas_id}/nodes/{id}    -- Update node
    DELETE /api/v1/ideas/{canvas_id}/nodes/{id}    -- Delete node
    POST   /api/v1/ideas/{canvas_id}/edges         -- Add edge
    DELETE /api/v1/ideas/{canvas_id}/edges/{id}    -- Delete edge
    GET    /api/v1/ideas/{canvas_id}/export        -- Export as React Flow JSON
    POST   /api/v1/ideas/{canvas_id}/promote       -- Promote nodes to goals

RBAC:
    ideas:read, ideas:create, ideas:update, ideas:delete, ideas:promote
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

_ideas_limiter = RateLimiter(requests_per_minute=120)

# Route patterns
IDEAS_LIST = re.compile(r"^/api/v1/ideas$")
IDEAS_BY_ID = re.compile(r"^/api/v1/ideas/([a-zA-Z0-9_-]+)$")
IDEAS_NODES = re.compile(r"^/api/v1/ideas/([a-zA-Z0-9_-]+)/nodes$")
IDEAS_NODE = re.compile(r"^/api/v1/ideas/([a-zA-Z0-9_-]+)/nodes/([a-zA-Z0-9_-]+)$")
IDEAS_EDGES = re.compile(r"^/api/v1/ideas/([a-zA-Z0-9_-]+)/edges$")
IDEAS_EDGE = re.compile(r"^/api/v1/ideas/([a-zA-Z0-9_-]+)/edges/([a-zA-Z0-9_-]+)$")
IDEAS_EXPORT = re.compile(r"^/api/v1/ideas/([a-zA-Z0-9_-]+)/export$")
IDEAS_PROMOTE = re.compile(r"^/api/v1/ideas/([a-zA-Z0-9_-]+)/promote$")


class InvalidRequestError(Exception):
    """Raised when an idea canvas request payload is invalid."""


class IdeaCanvasHandler(SecureHandler):
    """Handler for Idea Canvas REST API endpoints."""

    def __init__(self, ctx: dict | None = None):
        self.ctx = ctx or {}

    RESOURCE_TYPE = "ideas"

    ROUTES = [
        "/api/v1/ideas",
        "/api/v1/ideas/*",
        "/api/v1/ideas/*/nodes",
        "/api/v1/ideas/*/nodes/*",
        "/api/v1/ideas/*/edges",
        "/api/v1/ideas/*/edges/*",
        "/api/v1/ideas/*/export",
        "/api/v1/ideas/*/promote",
    ]

    def can_handle(self, path: str) -> bool:
        return path.startswith("/api/v1/ideas")

    def handle(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        client_ip = get_client_ip(handler)
        if not _ideas_limiter.is_allowed(client_ip):
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
            logger.warning("Authentication failed for ideas: %s", e)
            return error_response("Authentication required", 401)

        method = getattr(handler, "command", "GET")
        auth_context = AuthorizationContext(
            user_id=user_id or "anonymous",
            org_id=workspace_id,
            roles=getattr(user, "roles", set()) if user else {"member"},
        )

        workspace_id = query_params.get("workspace_id") or workspace_id
        try:
            body = self._get_request_body(handler)
            return self._route_request(
                path,
                method,
                query_params,
                body,
                user_id,
                workspace_id,
                auth_context,
            )
        except InvalidRequestError as e:
            logger.debug("Invalid idea canvas request: %s", e)
            return error_response(str(e), 400)
        except PermissionDeniedError as e:
            perm = e.permission_key if hasattr(e, "permission_key") else "unknown"
            logger.warning("Permission denied: %s", perm)
            return error_response("Permission denied", 403)

    def _get_request_body(self, handler: Any) -> dict[str, Any]:
        if hasattr(handler, "request") and hasattr(handler.request, "body"):
            raw = handler.request.body
            if raw:
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError as e:
                    raise InvalidRequestError("Request body must be valid JSON") from e
                except UnicodeDecodeError as e:
                    raise InvalidRequestError("Request body must be valid UTF-8 JSON") from e
                if not isinstance(payload, dict):
                    raise InvalidRequestError("Request body must be a JSON object")
                return payload
        return {}

    def _validate_optional_string(
        self,
        body: dict[str, Any],
        field: str,
        *,
        allow_blank: bool = True,
        max_length: int = 5000,
    ) -> str | None:
        if field not in body:
            return None
        value = body[field]
        if not isinstance(value, str):
            raise InvalidRequestError(f"{field} must be a string")
        if not allow_blank and not value.strip():
            raise InvalidRequestError(f"{field} must be a non-empty string")
        if len(value) > max_length:
            raise InvalidRequestError(f"{field} exceeds maximum length of {max_length}")
        return value

    def _validate_required_string(self, value: Any, field: str, *, max_length: int = 1000) -> str:
        if not isinstance(value, str) or not value.strip():
            raise InvalidRequestError(f"{field} is required and must be a non-empty string")
        if len(value) > max_length:
            raise InvalidRequestError(f"{field} exceeds maximum length of {max_length}")
        return value

    def _validate_optional_object(self, body: dict[str, Any], field: str) -> dict[str, Any] | None:
        if field not in body:
            return None
        value = body[field]
        if not isinstance(value, dict):
            raise InvalidRequestError(f"{field} must be an object")
        return value

    def _validate_position(self, value: Any) -> tuple[float, float]:
        if not isinstance(value, dict):
            raise InvalidRequestError("position must be an object")
        if "x" not in value and "y" not in value:
            return 0.0, 0.0
        if "x" not in value or "y" not in value:
            raise InvalidRequestError("position.x and position.y are required")
        try:
            return float(value["x"]), float(value["y"])
        except (TypeError, ValueError) as e:
            raise InvalidRequestError("position.x and position.y must be numbers") from e

    def _validate_string_list(self, value: Any, field: str) -> list[str]:
        if not isinstance(value, list) or not value:
            raise InvalidRequestError(f"{field} must be a non-empty list")
        if any(not isinstance(item, str) or not item.strip() for item in value):
            raise InvalidRequestError(f"{field} must contain non-empty strings")
        return value

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
        if IDEAS_LIST.match(path):
            if method == "GET":
                return self._list_canvases(context, query_params, user_id, workspace_id)
            if method == "POST":
                return self._create_canvas(context, body, user_id, workspace_id)
            return error_response("Method not allowed", 405)

        # Export (must be checked before generic ID)
        m = IDEAS_EXPORT.match(path)
        if m:
            if method == "GET":
                return self._export_canvas(context, m.group(1), user_id)
            return error_response("Method not allowed", 405)

        # Promote
        m = IDEAS_PROMOTE.match(path)
        if m:
            if method == "POST":
                return self._promote_nodes(context, m.group(1), body, user_id)
            return error_response("Method not allowed", 405)

        # Nodes collection
        m = IDEAS_NODES.match(path)
        if m:
            if method == "POST":
                return self._add_node(context, m.group(1), body, user_id)
            return error_response("Method not allowed", 405)

        # Single node
        m = IDEAS_NODE.match(path)
        if m:
            canvas_id, node_id = m.groups()
            if method == "PUT":
                return self._update_node(context, canvas_id, node_id, body, user_id)
            if method == "DELETE":
                return self._delete_node(context, canvas_id, node_id, user_id)
            return error_response("Method not allowed", 405)

        # Edges collection
        m = IDEAS_EDGES.match(path)
        if m:
            if method == "POST":
                return self._add_edge(context, m.group(1), body, user_id)
            return error_response("Method not allowed", 405)

        # Single edge
        m = IDEAS_EDGE.match(path)
        if m:
            canvas_id, edge_id = m.groups()
            if method == "DELETE":
                return self._delete_edge(context, canvas_id, edge_id, user_id)
            return error_response("Method not allowed", 405)

        # Canvas by ID
        m = IDEAS_BY_ID.match(path)
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
        from aragora.canvas.idea_store import get_idea_canvas_store

        return get_idea_canvas_store()

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

    @require_permission("ideas:read")
    def _list_canvases(
        self,
        context: AuthorizationContext,
        query_params: dict[str, Any],
        user_id: str | None,
        workspace_id: str | None,
    ) -> HandlerResult:
        try:
            raw_limit = query_params.get("limit", 100)
            raw_offset = query_params.get("offset", 0)
            try:
                limit = max(1, min(int(raw_limit), 1000))
            except (TypeError, ValueError):
                raise InvalidRequestError("limit must be an integer")
            try:
                offset = max(0, int(raw_offset))
            except (TypeError, ValueError):
                raise InvalidRequestError("offset must be an integer")

            store = self._get_store()
            canvases = store.list_canvases(
                workspace_id=query_params.get("workspace_id") or workspace_id,
                owner_id=query_params.get("owner_id") or user_id,
                limit=limit,
                offset=offset,
            )
            return json_response({"canvases": canvases, "count": len(canvases)})
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to list idea canvases: %s", e)
            return error_response("Failed to list idea canvases", 500)

    @require_permission("ideas:create")
    def _create_canvas(
        self,
        context: AuthorizationContext,
        body: dict[str, Any],
        user_id: str | None,
        workspace_id: str | None,
    ) -> HandlerResult:
        try:
            store = self._get_store()
            canvas_id = body.get("id")
            if canvas_id is not None:
                canvas_id = self._validate_required_string(canvas_id, "id")
            else:
                canvas_id = f"ideas-{uuid.uuid4().hex[:8]}"

            name = (
                self._validate_optional_string(body, "name", allow_blank=False) or "Untitled Ideas"
            )
            description = self._validate_optional_string(body, "description") or ""
            metadata = self._validate_optional_object(body, "metadata")
            if metadata is None:
                metadata = {"stage": "ideas"}

            result = store.save_canvas(
                canvas_id=canvas_id,
                name=name,
                owner_id=user_id,
                workspace_id=workspace_id,
                description=description,
                metadata=metadata,
            )
            return json_response(result, status=201)
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to create idea canvas: %s", e)
            return error_response("Canvas creation failed", 500)

    @require_permission("ideas:read")
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
                return error_response("Idea canvas not found", 404)

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
            logger.error("Failed to get idea canvas: %s", e)
            return error_response("Failed to retrieve idea canvas", 500)

    @require_permission("ideas:update")
    def _update_canvas(
        self,
        context: AuthorizationContext,
        canvas_id: str,
        body: dict[str, Any],
        user_id: str | None,
    ) -> HandlerResult:
        try:
            store = self._get_store()
            name = self._validate_optional_string(body, "name", allow_blank=False)
            description = self._validate_optional_string(body, "description")
            metadata = self._validate_optional_object(body, "metadata")
            if name is None and description is None and metadata is None:
                raise InvalidRequestError(
                    "At least one of name, description, or metadata is required"
                )

            result = store.update_canvas(
                canvas_id=canvas_id,
                name=name,
                description=description,
                metadata=metadata,
            )
            if not result:
                return error_response("Idea canvas not found", 404)
            return json_response(result)
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to update idea canvas: %s", e)
            return error_response("Canvas update failed", 500)

    @require_permission("ideas:delete")
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
                return error_response("Idea canvas not found", 404)
            return json_response({"deleted": True, "canvas_id": canvas_id})
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to delete idea canvas: %s", e)
            return error_response("Canvas deletion failed", 500)

    # ------------------------------------------------------------------
    # Node CRUD
    # ------------------------------------------------------------------

    @require_permission("ideas:create")
    def _add_node(
        self,
        context: AuthorizationContext,
        canvas_id: str,
        body: dict[str, Any],
        user_id: str | None,
    ) -> HandlerResult:
        try:
            from aragora.canvas import CanvasNodeType, Position
            from aragora.canvas.stages import IdeaNodeType

            manager = self._get_canvas_manager()

            idea_type = body.get("idea_type", "concept")
            if not isinstance(idea_type, str) or not idea_type.strip():
                raise InvalidRequestError("idea_type must be a non-empty string")
            try:
                IdeaNodeType(idea_type)
            except ValueError:
                return error_response(f"Invalid idea type: {idea_type}", 400)

            label = self._validate_optional_string(body, "label") or ""
            data = self._validate_optional_object(body, "data")
            if data is None:
                data = {}
            else:
                data = dict(data)

            if "position" in body:
                pos_x, pos_y = self._validate_position(body["position"])
            else:
                pos_x, pos_y = 0.0, 0.0
            position = Position(x=pos_x, y=pos_y)

            data["idea_type"] = idea_type
            data["stage"] = "ideas"
            data["rf_type"] = "ideaNode"

            node = self._run_async(
                manager.add_node(
                    canvas_id=canvas_id,
                    node_type=CanvasNodeType.KNOWLEDGE,
                    position=position,
                    label=label,
                    data=data,
                    user_id=user_id,
                )
            )
            if not node:
                return error_response("Canvas not found", 404)
            return json_response(node.to_dict(), status=201)
        except InvalidRequestError as e:
            return error_response(str(e), 400)
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to add idea node: %s", e)
            return error_response("Node addition failed", 500)

    @require_permission("ideas:update")
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
                pos_x, pos_y = self._validate_position(body["position"])
                updates["position"] = Position(x=pos_x, y=pos_y)
            if "label" in body:
                updates["label"] = self._validate_optional_string(body, "label")
            if "data" in body:
                updates["data"] = self._validate_optional_object(body, "data")
            if not updates:
                raise InvalidRequestError("At least one of position, label, or data is required")

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
            logger.error("Failed to update idea node: %s", e)
            return error_response("Node update failed", 500)

    @require_permission("ideas:delete")
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
            logger.error("Failed to delete idea node: %s", e)
            return error_response("Node deletion failed", 500)

    # ------------------------------------------------------------------
    # Edge CRUD
    # ------------------------------------------------------------------

    @require_permission("ideas:create")
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
            source_id = self._validate_required_string(source_id, "source_id")
            target_id = self._validate_required_string(target_id, "target_id")
            if source_id == target_id:
                raise InvalidRequestError("source_id and target_id must be different")

            edge_type_str = body.get("type", "default")
            if not isinstance(edge_type_str, str) or not edge_type_str.strip():
                raise InvalidRequestError("type must be a non-empty string")

            label = self._validate_optional_string(body, "label") or ""
            data = self._validate_optional_object(body, "data")
            if data is None:
                data = {}

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
                    label=label,
                    data=data,
                    user_id=user_id,
                )
            )
            if not edge:
                return error_response("Canvas or nodes not found", 404)
            return json_response(edge.to_dict(), status=201)
        except InvalidRequestError as e:
            return error_response(str(e), 400)
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to add idea edge: %s", e)
            return error_response("Edge addition failed", 500)

    @require_permission("ideas:delete")
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
            logger.error("Failed to delete idea edge: %s", e)
            return error_response("Edge deletion failed", 500)

    # ------------------------------------------------------------------
    # Export & Promote
    # ------------------------------------------------------------------

    @require_permission("ideas:read")
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
            logger.error("Failed to export idea canvas: %s", e)
            return error_response("Export failed", 500)

    @require_permission("ideas:promote")
    def _promote_nodes(
        self,
        context: AuthorizationContext,
        canvas_id: str,
        body: dict[str, Any],
        user_id: str | None,
    ) -> HandlerResult:
        try:
            from aragora.canvas.promotion import promote_ideas_to_goals

            manager = self._get_canvas_manager()
            canvas = self._run_async(manager.get_canvas(canvas_id))
            if not canvas:
                return error_response("Canvas not found", 404)

            if "node_ids" not in body:
                raise InvalidRequestError("node_ids is required")
            node_ids = self._validate_string_list(body["node_ids"], "node_ids")

            goals_canvas, provenance = promote_ideas_to_goals(
                canvas,
                node_ids,
                user_id or "anonymous",
            )

            return json_response(
                {
                    "goals_canvas": goals_canvas.to_dict(),
                    "provenance": [p.to_dict() for p in provenance],
                    "promoted_count": len(provenance),
                },
                status=201,
            )
        except InvalidRequestError as e:
            return error_response(str(e), 400)
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to promote idea nodes: %s", e)
            return error_response("Promotion failed", 500)
