"""
HTTP Handler for Live Canvas System.

Provides REST endpoints for canvas management:
- GET /api/v1/canvas - List canvases
- POST /api/v1/canvas - Create canvas
- GET /api/v1/canvas/{id} - Get canvas
- PUT /api/v1/canvas/{id} - Update canvas
- DELETE /api/v1/canvas/{id} - Delete canvas
- POST /api/v1/canvas/{id}/nodes - Add node
- PUT /api/v1/canvas/{id}/nodes/{node_id} - Update node
- DELETE /api/v1/canvas/{id}/nodes/{node_id} - Delete node
- POST /api/v1/canvas/{id}/edges - Add edge
- DELETE /api/v1/canvas/{id}/edges/{edge_id} - Delete edge
- POST /api/v1/canvas/{id}/action - Execute action

Security:
    All endpoints require RBAC permissions enforced via @require_permission decorators:
    - canvas:read: List, get canvas
    - canvas:create: Create canvas, add nodes/edges
    - canvas:update: Update canvas/nodes
    - canvas:delete: Delete canvas/nodes/edges
    - canvas:run: Execute actions
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from aragora.server.handlers.secure import (
    SecureHandler,
)
from aragora.server.handlers.base import (
    HandlerResult,
    error_response,
    json_response,
)
from aragora.server.handlers.utils.rate_limit import RateLimiter, get_client_ip
from aragora.rbac.decorators import require_permission, PermissionDeniedError
from aragora.rbac.models import AuthorizationContext

logger = logging.getLogger(__name__)

# Rate limiter for canvas endpoints
_canvas_limiter = RateLimiter(requests_per_minute=120)

# Route patterns
CANVAS_ID_PATTERN = re.compile(r"^/api/v1/canvas/([a-zA-Z0-9_-]+)$")
CANVAS_NODES_PATTERN = re.compile(r"^/api/v1/canvas/([a-zA-Z0-9_-]+)/nodes$")
CANVAS_NODE_PATTERN = re.compile(r"^/api/v1/canvas/([a-zA-Z0-9_-]+)/nodes/([a-zA-Z0-9_-]+)$")
CANVAS_EDGES_PATTERN = re.compile(r"^/api/v1/canvas/([a-zA-Z0-9_-]+)/edges$")
CANVAS_EDGE_PATTERN = re.compile(r"^/api/v1/canvas/([a-zA-Z0-9_-]+)/edges/([a-zA-Z0-9_-]+)$")
CANVAS_ACTION_PATTERN = re.compile(r"^/api/v1/canvas/([a-zA-Z0-9_-]+)/action$")
# Served by CanvasPipelineHandler, which is registered after this handler.
_PIPELINE_FAMILIES = re.compile(r"^/api/v1/canvas/(?:pipeline|convert)(?:/|$)")


class CanvasHandler(SecureHandler):
    """Handler for Live Canvas REST API endpoints.

    Endpoints:
        GET /api/v1/canvas - List canvases
        POST /api/v1/canvas - Create canvas
        GET /api/v1/canvas/{id} - Get canvas
        PUT /api/v1/canvas/{id} - Update canvas
        DELETE /api/v1/canvas/{id} - Delete canvas
        POST /api/v1/canvas/{id}/nodes - Add node
        PUT /api/v1/canvas/{id}/nodes/{node_id} - Update node
        DELETE /api/v1/canvas/{id}/nodes/{node_id} - Delete node
        POST /api/v1/canvas/{id}/edges - Add edge
        DELETE /api/v1/canvas/{id}/edges/{edge_id} - Delete edge
        POST /api/v1/canvas/{id}/action - Execute action

    RBAC Permissions (enforced via @require_permission decorators):
        - canvas:read: List, get canvas
        - canvas:create: Create canvas, add nodes/edges
        - canvas:update: Update canvas/nodes
        - canvas:delete: Delete canvas/nodes/edges
        - canvas:run: Execute actions
    """

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    RESOURCE_TYPE = "canvas"  # For audit logging

    def can_handle(self, path: str) -> bool:
        """Check if this handler can handle the given path."""
        return path.startswith("/api/v1/canvas") and not _PIPELINE_FAMILIES.match(path)

    def handle(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        """Handle requests with RBAC enforcement."""
        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _canvas_limiter.is_allowed(client_ip):
            return error_response("Rate limit exceeded", 429)

        # Require authentication
        user_id = None
        workspace_id = None
        try:
            user, err = self.require_auth_or_error(handler)
            if err:
                return err
            if user:
                user_id = user.user_id
                workspace_id = user.org_id  # Use org_id as workspace identifier
        except (ValueError, AttributeError, KeyError) as e:
            logger.warning("Authentication failed for canvas: %s", e)
            return error_response("Authentication required", 401)

        # Build authorization context for RBAC decorator enforcement
        method = getattr(handler, "command", "GET")
        auth_context = AuthorizationContext(
            user_id=user_id or "anonymous",
            org_id=workspace_id,
            roles=getattr(user, "roles", set()) if user else {"member"},
        )

        # Override workspace from query params if provided
        workspace_id = query_params.get("workspace_id") or workspace_id

        body = self._get_request_body(handler)

        # Route to appropriate handler - RBAC enforced via @require_permission decorators
        try:
            return self._route_request(
                path, method, query_params, body, user_id, workspace_id, auth_context
            )
        except PermissionDeniedError as e:
            permission_key = e.permission_key if hasattr(e, "permission_key") else "unknown"
            logger.warning("Permission denied: %s", permission_key)
            return error_response("Permission denied", 403)

    def _get_request_body(self, handler: Any) -> dict[str, Any]:
        """Extract JSON body from request."""
        try:
            if hasattr(handler, "request") and hasattr(handler.request, "body"):
                raw_body = handler.request.body
                if raw_body:
                    return json.loads(raw_body.decode("utf-8"))
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
        """Route request to appropriate handler method.

        RBAC permissions are enforced via @require_permission decorators on each
        operation method. The AuthorizationContext is passed to enable permission checks.
        """
        # List/Create canvases
        if path == "/api/v1/canvas":
            if method == "GET":
                return self._list_canvases(context, query_params, user_id, workspace_id)
            elif method == "POST":
                return self._create_canvas(context, body, user_id, workspace_id)
            return error_response("Method not allowed", 405)

        # Canvas by ID
        match = CANVAS_ID_PATTERN.match(path)
        if match:
            canvas_id = match.group(1)
            if method == "GET":
                return self._get_canvas(context, canvas_id, user_id)
            elif method == "PUT":
                return self._update_canvas(context, canvas_id, body, user_id)
            elif method == "DELETE":
                return self._delete_canvas(context, canvas_id, user_id)
            return error_response("Method not allowed", 405)

        # Nodes
        match = CANVAS_NODES_PATTERN.match(path)
        if match:
            canvas_id = match.group(1)
            if method == "POST":
                return self._add_node(context, canvas_id, body, user_id)
            return error_response("Method not allowed", 405)

        match = CANVAS_NODE_PATTERN.match(path)
        if match:
            canvas_id, node_id = match.groups()
            if method == "PUT":
                return self._update_node(context, canvas_id, node_id, body, user_id)
            elif method == "DELETE":
                return self._delete_node(context, canvas_id, node_id, user_id)
            return error_response("Method not allowed", 405)

        # Edges
        match = CANVAS_EDGES_PATTERN.match(path)
        if match:
            canvas_id = match.group(1)
            if method == "POST":
                return self._add_edge(context, canvas_id, body, user_id)
            return error_response("Method not allowed", 405)

        match = CANVAS_EDGE_PATTERN.match(path)
        if match:
            canvas_id, edge_id = match.groups()
            if method == "DELETE":
                return self._delete_edge(context, canvas_id, edge_id, user_id)
            return error_response("Method not allowed", 405)

        # Actions
        match = CANVAS_ACTION_PATTERN.match(path)
        if match:
            canvas_id = match.group(1)
            if method == "POST":
                return self._execute_action(context, canvas_id, body, user_id)
            return error_response("Method not allowed", 405)

        return None

    def _get_canvas_manager(self):
        """Get the canvas state manager singleton."""
        from aragora.canvas import get_canvas_manager

        return get_canvas_manager()

    def _run_async(self, coro):
        """Run an async coroutine synchronously."""
        import concurrent.futures

        try:
            asyncio.get_running_loop()
            # Create a new event loop in a thread
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result(timeout=30)
        except RuntimeError:
            # No event loop, create one
            return asyncio.run(coro)

    # =========================================================================
    # Canvas Operations
    # =========================================================================

    @require_permission("canvas:read")
    def _list_canvases(
        self,
        context: AuthorizationContext,
        query_params: dict[str, Any],
        user_id: str | None,
        workspace_id: str | None,
    ) -> HandlerResult:
        """List canvases.

        Requires canvas:read permission.
        """
        try:
            manager = self._get_canvas_manager()
            owner_id = query_params.get("owner_id") or user_id
            ws_id = query_params.get("workspace_id") or workspace_id

            canvases = self._run_async(manager.list_canvases(owner_id=owner_id, workspace_id=ws_id))

            return json_response(
                {
                    "canvases": [c.to_dict() for c in canvases],
                    "count": len(canvases),
                }
            )
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to list canvases: %s", e)
            return error_response("Failed to list canvases", 500)

    @require_permission("canvas:create")
    def _create_canvas(
        self,
        context: AuthorizationContext,
        body: dict[str, Any],
        user_id: str | None,
        workspace_id: str | None,
    ) -> HandlerResult:
        """Create a new canvas.

        Requires canvas:create permission.
        """
        try:
            manager = self._get_canvas_manager()

            name = body.get("name", "Untitled Canvas")
            canvas_id = body.get("id")
            metadata = body.get("metadata", {})

            canvas = self._run_async(
                manager.create_canvas(
                    canvas_id=canvas_id,
                    name=name,
                    owner_id=user_id,
                    workspace_id=workspace_id,
                    **metadata,
                )
            )

            return json_response(canvas.to_dict(), status=201)
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to create canvas: %s", e)
            return error_response("Canvas creation failed", 500)

    @require_permission("canvas:read")
    def _get_canvas(
        self,
        context: AuthorizationContext,
        canvas_id: str,
        user_id: str | None,
    ) -> HandlerResult:
        """Get a canvas by ID.

        Requires canvas:read permission.
        """
        try:
            manager = self._get_canvas_manager()
            canvas = self._run_async(manager.get_canvas(canvas_id))

            if not canvas:
                return error_response("Canvas not found", 404)

            return json_response(canvas.to_dict())
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to get canvas: %s", e)
            return error_response("Failed to retrieve canvas", 500)

    @require_permission("canvas:update")
    def _update_canvas(
        self,
        context: AuthorizationContext,
        canvas_id: str,
        body: dict[str, Any],
        user_id: str | None,
    ) -> HandlerResult:
        """Update a canvas.

        Requires canvas:update permission.
        """
        try:
            manager = self._get_canvas_manager()

            # Use the manager's update method for proper event broadcasting
            canvas = self._run_async(
                manager.update_canvas(
                    canvas_id=canvas_id,
                    name=body.get("name"),
                    metadata=body.get("metadata"),
                    owner_id=body.get("owner_id"),
                    workspace_id=body.get("workspace_id"),
                    user_id=user_id,
                )
            )

            if not canvas:
                return error_response("Canvas not found", 404)

            return json_response(canvas.to_dict())
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to update canvas: %s", e)
            return error_response("Canvas update failed", 500)

    @require_permission("canvas:delete")
    def _delete_canvas(
        self,
        context: AuthorizationContext,
        canvas_id: str,
        user_id: str | None,
    ) -> HandlerResult:
        """Delete a canvas.

        Requires canvas:delete permission.
        """
        try:
            manager = self._get_canvas_manager()
            deleted = self._run_async(manager.delete_canvas(canvas_id))

            if not deleted:
                return error_response("Canvas not found", 404)

            return json_response({"deleted": True, "canvas_id": canvas_id})
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to delete canvas: %s", e)
            return error_response("Canvas deletion failed", 500)

    # =========================================================================
    # Node Operations
    # =========================================================================

    @require_permission("canvas:create")
    def _add_node(
        self,
        context: AuthorizationContext,
        canvas_id: str,
        body: dict[str, Any],
        user_id: str | None,
    ) -> HandlerResult:
        """Add a node to the canvas.

        Requires canvas:create permission (adding nodes is a create operation).
        """
        try:
            from aragora.canvas import CanvasNodeType, Position

            manager = self._get_canvas_manager()

            # Parse node type
            node_type_str = body.get("type", "text")
            try:
                node_type = CanvasNodeType(node_type_str)
            except ValueError:
                return error_response(f"Invalid node type: {node_type_str}", 400)

            # Parse position
            pos_data = body.get("position", {})
            position = Position(
                x=float(pos_data.get("x", 0)),
                y=float(pos_data.get("y", 0)),
            )

            label = body.get("label", "")
            data = body.get("data", {})

            node = self._run_async(
                manager.add_node(
                    canvas_id=canvas_id,
                    node_type=node_type,
                    position=position,
                    label=label,
                    data=data,
                    user_id=user_id,
                )
            )

            if not node:
                return error_response("Canvas not found", 404)

            return json_response(node.to_dict(), status=201)
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to add node: %s", e)
            return error_response("Node addition failed", 500)

    @require_permission("canvas:update")
    def _update_node(
        self,
        context: AuthorizationContext,
        canvas_id: str,
        node_id: str,
        body: dict[str, Any],
        user_id: str | None,
    ) -> HandlerResult:
        """Update a node.

        Requires canvas:update permission.
        """
        try:
            from aragora.canvas import Position

            manager = self._get_canvas_manager()

            # Parse updates
            updates: dict[str, Any] = {}
            if "position" in body:
                pos_data = body["position"]
                updates["position"] = Position(
                    x=float(pos_data.get("x", 0)),
                    y=float(pos_data.get("y", 0)),
                )
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
            logger.error("Failed to update node: %s", e)
            return error_response("Node update failed", 500)

    @require_permission("canvas:delete")
    def _delete_node(
        self,
        context: AuthorizationContext,
        canvas_id: str,
        node_id: str,
        user_id: str | None,
    ) -> HandlerResult:
        """Delete a node.

        Requires canvas:delete permission.
        """
        try:
            manager = self._get_canvas_manager()
            deleted = self._run_async(manager.remove_node(canvas_id, node_id, user_id=user_id))

            if not deleted:
                return error_response("Node or canvas not found", 404)

            return json_response({"deleted": True, "node_id": node_id})
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to delete node: %s", e)
            return error_response("Node deletion failed", 500)

    # =========================================================================
    # Edge Operations
    # =========================================================================

    @require_permission("canvas:create")
    def _add_edge(
        self,
        context: AuthorizationContext,
        canvas_id: str,
        body: dict[str, Any],
        user_id: str | None,
    ) -> HandlerResult:
        """Add an edge to the canvas.

        Requires canvas:create permission (adding edges is a create operation).
        """
        try:
            from aragora.canvas import EdgeType

            manager = self._get_canvas_manager()

            source_id = body.get("source_id") or body.get("source")
            target_id = body.get("target_id") or body.get("target")

            if not source_id or not target_id:
                return error_response("source_id and target_id are required", 400)

            # Parse edge type
            edge_type_str = body.get("type", "default")
            try:
                edge_type = EdgeType(edge_type_str)
            except ValueError:
                edge_type = EdgeType.DEFAULT

            label = body.get("label", "")
            data = body.get("data", {})

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
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to add edge: %s", e)
            return error_response("Edge addition failed", 500)

    @require_permission("canvas:delete")
    def _delete_edge(
        self,
        context: AuthorizationContext,
        canvas_id: str,
        edge_id: str,
        user_id: str | None,
    ) -> HandlerResult:
        """Delete an edge.

        Requires canvas:delete permission.
        """
        try:
            manager = self._get_canvas_manager()
            deleted = self._run_async(manager.remove_edge(canvas_id, edge_id, user_id=user_id))

            if not deleted:
                return error_response("Edge or canvas not found", 404)

            return json_response({"deleted": True, "edge_id": edge_id})
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to delete edge: %s", e)
            return error_response("Edge deletion failed", 500)

    # =========================================================================
    # Actions
    # =========================================================================

    @require_permission("canvas:run")
    def _execute_action(
        self,
        context: AuthorizationContext,
        canvas_id: str,
        body: dict[str, Any],
        user_id: str | None,
    ) -> HandlerResult:
        """Execute an action on the canvas.

        Requires canvas:run permission.
        """
        try:
            manager = self._get_canvas_manager()

            action = body.get("action")
            if not action:
                return error_response("action is required", 400)

            # Receipt enforcement gate (Phase 2 — Decision Integrity Kernel)
            receipt_id = body.get("receipt_id")
            try:
                from aragora.pipeline.receipt_enforcement import (
                    ReceiptEnforcementError,
                    is_receipt_enforcement_enabled,
                    require_receipt_gate,
                    transition_receipt_executed,
                )

                if is_receipt_enforcement_enabled("canvas"):
                    require_receipt_gate(
                        action_domain="canvas",
                        action_type="execute_action",
                        actor_id=user_id or "anonymous",
                        resource_id=canvas_id,
                        receipt_id=receipt_id,
                    )
            except ReceiptEnforcementError as re_err:
                logger.warning("Receipt enforcement denied canvas action: %s", re_err)
                return error_response("Receipt required for this action", 428)
            except ImportError:
                logger.debug("Receipt enforcement module not available, skipping gate")

            node_id = body.get("node_id")
            params = body.get("params", {})

            result = self._run_async(
                manager.execute_action(
                    canvas_id=canvas_id,
                    action=action,
                    node_id=node_id,
                    user_id=user_id,
                    **params,
                )
            )

            # Transition receipt to EXECUTED after successful action
            if receipt_id:
                try:
                    from aragora.pipeline.receipt_enforcement import (
                        is_receipt_enforcement_enabled,
                        transition_receipt_executed,
                    )

                    if is_receipt_enforcement_enabled("canvas"):
                        transition_receipt_executed(receipt_id)
                except ImportError:
                    pass

            return json_response(
                {
                    "action": action,
                    "canvas_id": canvas_id,
                    "node_id": node_id,
                    "result": result,
                }
            )
        except (ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError) as e:
            logger.error("Failed to execute action: %s", e)
            return error_response("Action execution failed", 500)
