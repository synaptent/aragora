"""
CRUD operations handler mixin for debates.

Extracted from handler.py for modularity. Provides:
- List debates
- Get debate by slug
- Update debate (patch)
- Delete debate
- Get debate messages (paginated)
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Protocol

from aragora.config import DEFAULT_ROUNDS
from aragora.exceptions import (
    DatabaseError,
    RecordNotFoundError,
    StorageError,
)
from aragora.rbac.decorators import require_permission
from aragora.server.debate_utils import _active_debates
from aragora.server.middleware.abac import Action, ResourceType, check_resource_access
from aragora.server.validation.schema import (
    DEBATE_UPDATE_SCHEMA,
    validate_against_schema,
)

from ..base import (
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
    require_storage,
    ttl_cache,
)
from ..openapi_decorator import api_endpoint
from ..utils.rate_limit import rate_limit
from .response_formatting import (
    CACHE_TTL_DEBATES_LIST,
    denormalize_status,
    normalize_debate_response,
    normalize_status,
)

if TYPE_CHECKING:
    from aragora.billing.auth.context import UserAuthContext


logger = logging.getLogger(__name__)


class _DebatesHandlerProtocol(Protocol):
    """Protocol defining the interface expected by CrudOperationsMixin.

    This protocol enables proper type checking for mixin classes that
    expect to be mixed into a class providing these methods/attributes.
    """

    ctx: dict[str, Any]

    def get_storage(self) -> Any | None:
        """Get debate storage instance."""
        ...

    def read_json_body(self, handler: Any, max_size: int | None = None) -> dict[str, Any] | None:
        """Read and parse JSON body from request handler."""
        ...

    def get_current_user(self, handler: Any) -> UserAuthContext | None:
        """Get authenticated user from request."""
        ...


class CrudOperationsMixin:
    """Mixin providing CRUD operations for DebatesHandler."""

    @api_endpoint(
        method="GET",
        path="/api/v1/debates",
        summary="List all debates",
        description="List recent debates with optional organization filtering. Requires authentication.",
        tags=["Debates"],
        responses={
            "200": {
                "description": "List of debates returned",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "debates": {"type": "array", "items": {"type": "object"}},
                                "count": {"type": "integer"},
                            },
                        },
                    },
                },
            },
            "401": {"description": "Unauthorized"},
            "500": {"description": "Database error"},
        },
    )
    @rate_limit(requests_per_minute=30, limiter_name="debates_list")
    @require_storage
    @ttl_cache(ttl_seconds=CACHE_TTL_DEBATES_LIST, key_prefix="debates_list", skip_first=True)
    @handle_errors("list debates")
    def _list_debates(
        self: _DebatesHandlerProtocol, limit: int, org_id: str | None = None
    ) -> HandlerResult:
        """List recent debates, optionally filtered by organization.

        Args:
            limit: Maximum number of debates to return
            org_id: If provided, only return debates for this organization.
                    If None, returns all debates (backwards compatible).

        Cached for 30 seconds. Cache key includes org_id for per-org isolation.
        """
        storage = self.get_storage()
        debates = storage.list_recent(limit=limit, org_id=org_id)
        # Convert DebateMetadata objects to dicts and normalize for SDK compatibility
        debates_list = [
            normalize_debate_response(
                d.__dict__ if hasattr(d, "__dict__") else dict(d)
            )  # DebateMetadata may be dict-like at runtime
            for d in debates
        ]
        return json_response({"debates": debates_list, "count": len(debates_list)})

    @api_endpoint(
        method="GET",
        path="/api/v1/debates/{slug}",
        summary="Get debate by slug",
        description="Retrieve a debate by its slug/ID. Returns in-progress debates if not yet persisted.",
        tags=["Debates"],
        parameters=[{"name": "slug", "in": "path", "required": True, "schema": {"type": "string"}}],
        responses={
            "200": {
                "description": "Debate details returned",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "debate_id": {"type": "string"},
                                "task": {"type": "string"},
                                "status": {"type": "string"},
                                "agents": {"type": "array", "items": {"type": "string"}},
                                "rounds": {"type": "integer"},
                                "in_progress": {"type": "boolean"},
                            },
                        },
                    },
                },
            },
            "404": {"description": "Debate not found"},
        },
    )
    @require_storage
    @handle_errors("get debate by slug")
    def _get_debate_by_slug(
        self: _DebatesHandlerProtocol, handler: Any, slug: str
    ) -> HandlerResult:
        """Get a debate by slug.

        Checks both persistent storage and in-progress debates (_active_debates).
        In-progress debates haven't been persisted yet but should still be queryable.

        SECURITY: After retrieval, verifies the requesting user's tenant/org matches
        the debate's tenant to prevent cross-tenant data access (IDOR).
        """
        # First check persistent storage
        storage = self.get_storage()
        debate = storage.get_debate(slug)
        if debate:
            # Public playground debates are accessible without authentication
            visibility = debate.get("visibility", "private")
            source = debate.get("source", "")
            if visibility == "public" or source in ("landing", "playground", "try"):
                return json_response(normalize_debate_response(debate))

            # SECURITY: Verify tenant isolation - requesting user must belong
            # to the same org/tenant as the debate, or the debate must be public
            user = self.get_current_user(handler)
            if user:
                debate_org_id = (
                    debate.get("org_id") or debate.get("tenant_id") or debate.get("workspace_id")
                )
                user_org_id = getattr(user, "org_id", None)

                if debate_org_id and user_org_id and debate_org_id != user_org_id:
                    # Cross-tenant access attempt
                    logger.warning(
                        "Tenant isolation: user %s (org=%s) denied access to debate %s (org=%s)",
                        user.user_id,
                        user_org_id,
                        slug,
                        debate_org_id,
                    )
                    return error_response(f"Debate not found: {slug}", 404)

                # If debate has an owner and is not public, check participation
                debate_visibility = debate.get("visibility", "private")
                debate_owner_id = debate.get("user_id") or debate.get("owner_id")
                if debate_visibility != "public" and debate_owner_id and not debate_org_id:
                    # No org scoping -- fall back to ownership/participant check
                    participants = debate.get("participants", [])
                    if (
                        user.user_id != debate_owner_id
                        and user.user_id not in participants
                        and getattr(user, "role", "user") not in ("admin", "superadmin")
                    ):
                        logger.warning(
                            "IDOR blocked: user %s denied access to debate %s owned by %s",
                            user.user_id,
                            slug,
                            debate_owner_id,
                        )
                        return error_response(f"Debate not found: {slug}", 404)

            return json_response(normalize_debate_response(debate))

        # Fallback: check in-progress debates that haven't been persisted yet
        active_debates = _active_debates
        try:
            from aragora.server.handlers.debates import handler as handler_module

            active_debates = getattr(handler_module, "_active_debates", _active_debates)
        except (ImportError, AttributeError) as exc:
            logger.debug("Failed to load active debates from handler module: %s", exc)
            active_debates = _active_debates

        if slug in active_debates:
            active_raw = active_debates[slug]
            if not isinstance(active_raw, dict):
                logger.warning(
                    "Malformed active debate state for %s: expected dict, got %s",
                    slug,
                    type(active_raw).__name__,
                )
                return error_response(f"Debate not found: {slug}", 404)

            active = active_raw
            active_result = active.get("result") if isinstance(active, dict) else None
            mode = active.get("mode")
            settlement = active.get("settlement")
            active_metadata = active.get("metadata") if isinstance(active, dict) else None
            if isinstance(active_metadata, dict):
                mode = mode or active_metadata.get("mode")
                settlement = settlement or active_metadata.get("settlement")
                if not isinstance(active_result, dict):
                    active_result = active_metadata.get("result")
            if isinstance(active_result, dict):
                mode = mode or active_result.get("mode")
                settlement = settlement or active_result.get("settlement")
            # Return minimal info for in-progress debate
            # Support both "task" (new) and "question" (legacy) field names
            response_payload: dict[str, Any] = {
                "id": slug,
                "debate_id": slug,
                "task": active.get("task") or active.get("question", ""),
                "status": normalize_status(active.get("status", "starting")),
                "agents": (
                    active.get("agents", "").split(",")
                    if isinstance(active.get("agents"), str)
                    else active.get("agents", [])
                ),
                "rounds": active.get("rounds", DEFAULT_ROUNDS),
                "in_progress": True,
            }
            if mode:
                response_payload["mode"] = mode
            if isinstance(settlement, dict):
                response_payload["settlement"] = settlement

            return json_response(response_payload)

        return error_response(f"Debate not found: {slug}", 404)

    @api_endpoint(
        method="GET",
        path="/api/v1/debates/{id}/messages",
        summary="Get debate messages",
        description="Get paginated message history for a debate including role, content, agent, and round information.",
        tags=["Debates"],
        parameters=[
            {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}},
            {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 50}},
            {"name": "offset", "in": "query", "schema": {"type": "integer", "default": 0}},
        ],
        responses={
            "200": {
                "description": "Paginated messages returned",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "debate_id": {"type": "string"},
                                "messages": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "index": {"type": "integer"},
                                            "role": {"type": "string"},
                                            "content": {"type": "string"},
                                            "agent": {"type": "string"},
                                            "round": {"type": "integer"},
                                            "timestamp": {"type": "string"},
                                            "metadata": {"type": "object"},
                                        },
                                    },
                                },
                                "total": {"type": "integer"},
                                "offset": {"type": "integer"},
                                "limit": {"type": "integer"},
                                "has_more": {"type": "boolean"},
                            },
                        },
                    },
                },
            },
            "404": {"description": "Debate not found"},
            "500": {"description": "Database error"},
        },
    )
    @require_storage
    def _get_debate_messages(
        self: _DebatesHandlerProtocol, debate_id: str, limit: int = 50, offset: int = 0
    ) -> HandlerResult:
        """Get paginated message history for a debate.

        Args:
            debate_id: The debate ID
            limit: Maximum messages to return (default 50, max 200)
            offset: Starting offset for pagination

        Returns:
            Paginated list of messages with metadata
        """
        storage = self.get_storage()
        # Clamp limit
        limit = min(max(1, limit), 200)
        offset = max(0, offset)

        try:
            debate = storage.get_debate(debate_id)
            if not debate:
                return error_response(f"Debate not found: {debate_id}", 404)

            messages = debate.get("messages", [])
            total = len(messages)

            # Apply pagination
            paginated_messages = messages[offset : offset + limit]

            # Format messages for API response
            formatted_messages = []
            for i, msg in enumerate(paginated_messages):
                formatted_msg = {
                    "index": offset + i,
                    "role": msg.get("role", "unknown"),
                    "content": msg.get("content", ""),
                    "agent": msg.get("agent") or msg.get("name"),
                    "round": msg.get("round", 0),
                }
                # Include optional fields if present
                if "timestamp" in msg:
                    formatted_msg["timestamp"] = msg["timestamp"]
                if "metadata" in msg:
                    formatted_msg["metadata"] = msg["metadata"]
                formatted_messages.append(formatted_msg)

            return json_response(
                {
                    "debate_id": debate_id,
                    "messages": formatted_messages,
                    "total": total,
                    "offset": offset,
                    "limit": limit,
                    "has_more": offset + len(paginated_messages) < total,
                }
            )

        except RecordNotFoundError:
            logger.info("Messages failed - debate not found: %s", debate_id)
            return error_response(f"Debate not found: {debate_id}", 404)
        except (StorageError, DatabaseError) as e:
            logger.error(
                "Failed to get messages for %s: %s: %s",
                debate_id,
                type(e).__name__,
                e,
                exc_info=True,
            )
            return error_response("Database error retrieving messages", 500)

    @api_endpoint(
        method="PATCH",
        path="/api/v1/debates/{id}",
        summary="Update debate metadata",
        description="Update debate title, tags, status, or custom metadata. Requires write permission.",
        tags=["Debates"],
        parameters=[{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
        responses={
            "200": {
                "description": "Debate updated successfully",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "success": {"type": "boolean"},
                                "debate_id": {"type": "string"},
                                "updated_fields": {"type": "array", "items": {"type": "string"}},
                                "debate": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "string"},
                                        "title": {"type": "string"},
                                        "status": {"type": "string"},
                                        "tags": {"type": "array", "items": {"type": "string"}},
                                    },
                                },
                            },
                        },
                    },
                },
            },
            "400": {"description": "Invalid update data"},
            "403": {"description": "Permission denied"},
            "404": {"description": "Debate not found"},
            "500": {"description": "Database error"},
        },
    )
    @require_storage
    @require_permission("debates:update")
    def _patch_debate(self: _DebatesHandlerProtocol, handler: Any, debate_id: str) -> HandlerResult:
        """Update debate metadata.

        Request body can include:
            {
                "title": str,  # Optional: update debate title
                "tags": list[str],  # Optional: update tags
                "status": str,  # Optional: "active", "paused", "concluded"
                "metadata": dict  # Optional: custom metadata
            }

        Returns:
            Updated debate summary
        """
        # Read and validate request body
        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid or missing JSON body", 400)

        if not body:
            return error_response("Empty update body", 400)

        # Schema validation for input sanitization
        validation_result = validate_against_schema(body, DEBATE_UPDATE_SCHEMA)
        if not validation_result.is_valid:
            return error_response(validation_result.error, 400)

        # Get storage and find debate
        storage = self.get_storage()
        try:
            debate = storage.get_debate(debate_id)
            if not debate:
                return error_response(f"Debate not found: {debate_id}", 404)

            # ABAC: Check if user has write access to this debate
            user = self.get_current_user(handler)
            if user:
                debate_owner_id = debate.get("user_id") or debate.get("owner_id")
                debate_workspace_id = debate.get("workspace_id") or debate.get("org_id")

                access_decision = check_resource_access(
                    user_id=user.user_id,
                    user_role=getattr(user, "role", "user"),
                    user_plan=getattr(user, "plan", "free"),
                    resource_type=ResourceType.DEBATE,
                    resource_id=debate_id,
                    action=Action.WRITE,
                    resource_owner_id=debate_owner_id,
                    resource_workspace_id=debate_workspace_id,
                    user_workspace_id=getattr(user, "org_id", None),
                    user_workspace_role=getattr(user, "org_role", None),
                )

                if not access_decision.allowed:
                    logger.warning(
                        "ABAC denied WRITE access to debate %s for user %s: %s",
                        debate_id,
                        user.user_id,
                        access_decision.reason,
                    )
                    return error_response(
                        "You do not have permission to update this debate",
                        403,
                    )

            # Apply updates (only allowed fields)
            allowed_fields = {"title", "tags", "status", "metadata"}
            updates = {k: v for k, v in body.items() if k in allowed_fields}

            if not updates:
                return error_response(
                    f"No valid fields to update. Allowed: {', '.join(allowed_fields)}", 400
                )

            # Validate and normalize status if provided
            if "status" in updates:
                # Accept both internal and SDK status values
                valid_internal = {"active", "paused", "concluded", "archived"}
                valid_sdk = {"pending", "running", "completed", "failed", "cancelled"}
                input_status = updates["status"]

                if input_status in valid_sdk:
                    # Convert SDK status to internal status for storage
                    updates["status"] = denormalize_status(input_status)
                elif input_status not in valid_internal:
                    all_valid = valid_internal | valid_sdk
                    return error_response(
                        f"Invalid status. Must be one of: {', '.join(sorted(all_valid))}", 400
                    )

            # Apply updates to debate
            for key, value in updates.items():
                debate[key] = value

            # Save updated debate
            if hasattr(storage, "save_debate"):
                storage.save_debate(debate_id, debate)

            logger.info("Debate %s updated: %s", debate_id, list(updates.keys()))

            # Return normalized status for SDK compatibility
            return json_response(
                {
                    "success": True,
                    "debate_id": debate_id,
                    "updated_fields": list(updates.keys()),
                    "debate": {
                        "id": debate_id,
                        "title": debate.get("title", debate.get("task", "")),
                        "status": normalize_status(debate.get("status", "active")),
                        "tags": debate.get("tags", []),
                    },
                }
            )
        except RecordNotFoundError:
            logger.info("Update failed - debate not found: %s", debate_id)
            return error_response(f"Debate not found: {debate_id}", 404)
        except (StorageError, DatabaseError) as e:
            logger.error(
                "Failed to update debate %s: %s: %s", debate_id, type(e).__name__, e, exc_info=True
            )
            return error_response("Database error updating debate", 500)
        except ValueError as e:
            logger.warning("Invalid update request for %s: %s", debate_id, e)
            return error_response("Invalid update data", 400)

    @api_endpoint(
        method="GET",
        path="/api/v1/debates/{id}/events",
        summary="Poll debate events (fallback for missed WebSocket events)",
        description="Returns buffered debate events since a given sequence number. "
        "Use this as a polling fallback when WebSocket reconnection is not possible.",
        tags=["Debates", "Streaming"],
        parameters=[
            {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}},
            {"name": "since", "in": "query", "schema": {"type": "integer", "default": 0}},
            {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 100}},
        ],
        responses={
            "200": {
                "description": "Buffered events returned",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "events": {"type": "array", "items": {"type": "object"}},
                                "next_seq": {"type": "integer"},
                            },
                        },
                    },
                },
            },
        },
    )
    @handle_errors("get debate events")
    def _get_debate_events(
        self: _DebatesHandlerProtocol,
        handler: Any,
        debate_id: str,
        since_seq: int = 0,
        limit: int = 100,
    ) -> HandlerResult:
        """Return buffered debate events for polling fallback.

        Clients that lose their WebSocket connection can poll this endpoint
        to retrieve events they missed, using ``since_seq`` to avoid
        re-fetching already-seen events.

        Args:
            handler: HTTP request handler (unused but required by dispatch)
            debate_id: The debate to fetch events for
            since_seq: Return events with seq > since_seq (default 0)
            limit: Maximum number of events to return (default 100, max 500)
        """
        from aragora.server.stream.debate_stream_server import get_global_replay_buffer

        replay_buffer = get_global_replay_buffer()
        if replay_buffer is None:
            return json_response({"events": [], "next_seq": 0})

        limit = min(max(1, limit), 500)
        raw_events = replay_buffer.replay_since(debate_id, since_seq)
        limited = raw_events[:limit]

        # Parse JSON strings back to dicts for the response
        events = []
        last_seq = since_seq
        for event_json in limited:
            try:
                parsed = json.loads(event_json)
                events.append(parsed)
                event_seq = parsed.get("seq", 0)
                if event_seq > last_seq:
                    last_seq = event_seq
            except (json.JSONDecodeError, TypeError, KeyError):
                continue

        # Polling fallback hydration:
        # When replay buffer has no events for an active debate on the first poll,
        # emit a synthetic sync frame so clients can hydrate task/agents/mode/settlement.
        if not events and since_seq <= 0:
            active_snapshot = _active_debates.get(debate_id)
            if isinstance(active_snapshot, dict):
                synthetic_seq = max(1, since_seq + 1)
                sync_data: dict[str, Any] = {
                    "debate_id": debate_id,
                    "task": active_snapshot.get("task", ""),
                    "agents": active_snapshot.get("agents", []),
                    "ended": False,
                }

                mode = active_snapshot.get("mode")
                settlement = active_snapshot.get("settlement")
                if isinstance(mode, str) and mode.strip():
                    sync_data["mode"] = mode
                if isinstance(settlement, dict):
                    sync_data["settlement"] = settlement

                return json_response(
                    {
                        "events": [
                            {
                                "type": "sync",
                                "seq": synthetic_seq,
                                "loop_id": debate_id,
                                "data": sync_data,
                            }
                        ],
                        "next_seq": synthetic_seq + 1,
                    }
                )

        return json_response({"events": events, "next_seq": last_seq + 1 if events else since_seq})

    @api_endpoint(
        method="DELETE",
        path="/api/v1/debates/{id}",
        summary="Delete a debate",
        description="Permanently delete a debate and cascade to associated critiques. Use PATCH with status='archived' for soft-delete.",
        tags=["Debates"],
        parameters=[{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
        responses={
            "200": {
                "description": "Debate deleted successfully",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "deleted": {"type": "boolean"},
                                "id": {"type": "string"},
                            },
                        },
                    },
                },
            },
            "403": {"description": "Permission denied"},
            "404": {"description": "Debate not found"},
            "500": {"description": "Database error"},
        },
    )
    @require_permission("debates:delete")
    @require_storage
    def _delete_debate(
        self: _DebatesHandlerProtocol, handler: Any, debate_id: str
    ) -> HandlerResult:
        """Delete a debate and its associated data.

        Performs a permanent deletion of the debate record and cascades
        to associated critiques. For soft-delete, use PATCH with
        status="archived" instead.

        Returns:
            JSON confirmation with deleted debate ID.
        """
        storage = self.get_storage()
        try:
            debate = storage.get_debate(debate_id)
            if not debate:
                return error_response(f"Debate not found: {debate_id}", 404)

            # ABAC: Check if user has delete access to this debate
            user = self.get_current_user(handler)
            if user:
                debate_owner_id = debate.get("user_id") or debate.get("owner_id")
                debate_workspace_id = debate.get("workspace_id") or debate.get("org_id")

                access_decision = check_resource_access(
                    user_id=user.user_id,
                    user_role=getattr(user, "role", "user"),
                    user_plan=getattr(user, "plan", "free"),
                    resource_type=ResourceType.DEBATE,
                    resource_id=debate_id,
                    action=Action.DELETE,
                    resource_owner_id=debate_owner_id,
                    resource_workspace_id=debate_workspace_id,
                    user_workspace_id=getattr(user, "org_id", None),
                    user_workspace_role=getattr(user, "org_role", None),
                )

                if not access_decision.allowed:
                    logger.warning(
                        "ABAC denied DELETE access to debate %s for user %s: %s",
                        debate_id,
                        user.user_id,
                        access_decision.reason,
                    )
                    return error_response(
                        "You do not have permission to delete this debate",
                        403,
                    )

            # Cancel if still running
            if debate_id in _active_debates:
                active = _active_debates[debate_id]
                if hasattr(active, "task") and active.task and not active.task.done():
                    active.task.cancel()
                del _active_debates[debate_id]

            # Perform deletion with cascade
            deleted = storage.delete_debate(debate_id, cascade_critiques=True)
            if not deleted:
                return error_response(f"Debate not found: {debate_id}", 404)

            logger.info("Debate %s permanently deleted", debate_id)
            return json_response({"deleted": True, "id": debate_id})

        except RecordNotFoundError:
            return error_response(f"Debate not found: {debate_id}", 404)
        except (StorageError, DatabaseError) as e:
            logger.error(
                "Failed to delete debate %s: %s: %s", debate_id, type(e).__name__, e, exc_info=True
            )
            return error_response("Database error deleting debate", 500)


__all__ = ["CrudOperationsMixin"]
