"""
HTTP API Handlers for Team Inbox Collaboration.

Provides REST APIs for team inbox features:
- Team member management
- Message presence (viewing, typing)
- Internal notes and comments
- @mentions management
- Activity feed

Endpoints:
- GET /api/v1/inbox/shared/{id}/team - Get team members
- POST /api/v1/inbox/shared/{id}/team - Add team member
- DELETE /api/v1/inbox/shared/{id}/team/{user_id} - Remove team member
- POST /api/v1/inbox/shared/{id}/messages/{msg_id}/viewing - Start viewing
- DELETE /api/v1/inbox/shared/{id}/messages/{msg_id}/viewing - Stop viewing
- POST /api/v1/inbox/shared/{id}/messages/{msg_id}/typing - Start typing
- DELETE /api/v1/inbox/shared/{id}/messages/{msg_id}/typing - Stop typing
- GET /api/v1/inbox/shared/{id}/messages/{msg_id}/notes - Get notes
- POST /api/v1/inbox/shared/{id}/messages/{msg_id}/notes - Add note
- GET /api/v1/inbox/mentions - Get mentions for current user
- POST /api/v1/inbox/mentions/{id}/acknowledge - Acknowledge mention
- GET /api/v1/inbox/shared/{id}/activity - Get activity feed
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from aragora.server.handlers.base import (
    BaseHandler,
    error_response,
    require_permission,
    safe_error_message,
    success_response,
)
from aragora.server.handlers.openapi_decorator import api_endpoint
from aragora.server.handlers.utils import decorators as handler_decorators
from aragora.server.handlers.utils.lazy_stores import LazyStoreFactory
from aragora.server.handlers.utils.responses import HandlerResult
from aragora.server.versioning.compat import strip_version_prefix

logger = logging.getLogger(__name__)

# Thread-safe lazy-initialized service instances
_team_inbox_emitter = LazyStoreFactory(
    store_name="team_inbox_emitter",
    import_path="aragora.server.stream.team_inbox",
    factory_name="get_team_inbox_emitter",
    logger_context="TeamInbox",
)

_activity_store = LazyStoreFactory(
    store_name="inbox_activity_store",
    import_path="aragora.storage.inbox_activity_store",
    factory_name="get_inbox_activity_store",
    logger_context="TeamInbox",
)


def get_team_inbox_emitter_instance():
    """Get or create team inbox emitter (thread-safe)."""
    return _team_inbox_emitter.get()


def _get_activity_store():
    """Get or create the activity store (lazy init, thread-safe)."""
    return _activity_store.get()


def _log_activity(
    inbox_id: str,
    org_id: str,
    actor_id: str,
    action: str,
    target_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Log an inbox activity (non-blocking helper)."""
    store = _get_activity_store()
    if store:
        try:
            from aragora.storage.inbox_activity_store import InboxActivity

            activity = InboxActivity(
                inbox_id=inbox_id,
                org_id=org_id,
                actor_id=actor_id,
                action=action,
                target_id=target_id,
                metadata=metadata or {},
            )
            store.log_activity(activity)
        except (OSError, RuntimeError, ValueError) as e:
            # Non-critical: activity logging failures shouldn't break the main operation
            logger.debug("[TeamInbox] Failed to log activity: %s", e)


# =============================================================================
# Team Member Management
# =============================================================================


@api_endpoint(
    method="GET",
    path="/api/v1/inbox/shared/{inbox_id}/team",
    summary="Get team members",
    description="Get team members for a shared inbox.",
    tags=["Inbox", "Team"],
    parameters=[{"name": "inbox_id", "in": "path", "required": True, "schema": {"type": "string"}}],
    responses={
        "200": {"description": "List of team members"},
        "400": {"description": "inbox_id is required"},
        "401": {"description": "Authentication required"},
    },
)
@require_permission("inbox:read")
async def handle_get_team_members(
    data: dict[str, Any],
    inbox_id: str = "",
    user_id: str = "default",
) -> HandlerResult:
    """
    Get team members for a shared inbox.

    GET /api/v1/inbox/shared/{id}/team
    """
    try:
        if not inbox_id:
            inbox_id = data.get("inbox_id", "")
        if not inbox_id:
            return error_response("inbox_id is required", status=400)

        emitter = get_team_inbox_emitter_instance()
        members = await emitter.get_team_members(inbox_id)

        return success_response(
            {
                "inbox_id": inbox_id,
                "team_members": [m.to_dict() for m in members],
                "count": len(members),
            }
        )

    except (KeyError, ValueError, TypeError, AttributeError, RuntimeError) as e:
        logger.exception("Failed to get team members")
        return error_response(safe_error_message(e, "get team members"), status=500)


@api_endpoint(
    method="POST",
    path="/api/v1/inbox/shared/{inbox_id}/team",
    summary="Add team member",
    description="Add a team member to a shared inbox with role assignment.",
    tags=["Inbox", "Team"],
    parameters=[{"name": "inbox_id", "in": "path", "required": True, "schema": {"type": "string"}}],
    responses={
        "200": {"description": "Team member added"},
        "400": {"description": "Missing required fields"},
        "401": {"description": "Authentication required"},
    },
)
@require_permission("inbox:create")
async def handle_add_team_member(
    data: dict[str, Any],
    inbox_id: str = "",
    user_id: str = "default",
) -> HandlerResult:
    """
    Add a team member to a shared inbox.

    POST /api/v1/inbox/shared/{id}/team
    Body: {
        user_id: str,
        email: str,
        name: str,
        role: str (optional - admin, member, viewer)
    }
    """
    try:
        if not inbox_id:
            inbox_id = data.get("inbox_id", "")
        if not inbox_id:
            return error_response("inbox_id is required", status=400)

        new_user_id = data.get("user_id", "")
        email = data.get("email", "")
        name = data.get("name", "")
        role = data.get("role", "member")

        if not new_user_id:
            return error_response("'user_id' is required", status=400)
        if not email:
            return error_response("'email' is required", status=400)
        if not name:
            return error_response("'name' is required", status=400)

        valid_roles = {"admin", "member", "viewer"}
        if role not in valid_roles:
            return error_response(
                f"Invalid role. Must be one of: {', '.join(valid_roles)}",
                status=400,
            )

        emitter = get_team_inbox_emitter_instance()
        member = await emitter.add_team_member(
            inbox_id=inbox_id,
            user_id=new_user_id,
            email=email,
            name=name,
            role=role,
        )

        # Emit activity (WebSocket)
        await emitter.emit_activity(
            inbox_id=inbox_id,
            activity_type="team_member_added",
            description=f"{name} was added to the team",
            user_id=user_id,
            user_name="System",  # Could be enhanced to get actual name
            metadata={"addedUserId": new_user_id, "role": role},
        )

        # Persist activity log
        org_id = data.get("org_id")
        if org_id:
            _log_activity(
                inbox_id=inbox_id,
                org_id=org_id,
                actor_id=user_id,
                action="member_added",
                target_id=new_user_id,
                metadata={"email": email, "name": name, "role": role},
            )

        return success_response(
            {
                "inbox_id": inbox_id,
                "member": member.to_dict(),
                "message": f"Added {name} to the team",
            }
        )

    except (KeyError, ValueError, TypeError, AttributeError, RuntimeError) as e:
        logger.exception("Failed to add team member")
        return error_response(safe_error_message(e, "add team member"), status=500)


@require_permission("org:members")
async def handle_remove_team_member(
    data: dict[str, Any],
    inbox_id: str = "",
    member_user_id: str = "",
    user_id: str = "default",
) -> HandlerResult:
    """
    Remove a team member from a shared inbox.

    DELETE /api/v1/inbox/shared/{id}/team/{user_id}
    """
    try:
        if not inbox_id:
            inbox_id = data.get("inbox_id", "")
        if not member_user_id:
            member_user_id = data.get("member_user_id", "")
        if not inbox_id or not member_user_id:
            return error_response("inbox_id and member_user_id are required", status=400)

        emitter = get_team_inbox_emitter_instance()
        removed = await emitter.remove_team_member(inbox_id, member_user_id)

        if not removed:
            return error_response("Team member not found", status=404)

        # Emit activity (WebSocket)
        await emitter.emit_activity(
            inbox_id=inbox_id,
            activity_type="team_member_removed",
            description="A team member was removed",
            user_id=user_id,
            user_name="System",
            metadata={"removedUserId": member_user_id},
        )

        # Persist activity log
        org_id = data.get("org_id")
        if org_id:
            _log_activity(
                inbox_id=inbox_id,
                org_id=org_id,
                actor_id=user_id,
                action="member_removed",
                target_id=member_user_id,
                metadata={},
            )

        return success_response(
            {
                "inbox_id": inbox_id,
                "removed_user_id": member_user_id,
                "message": "Team member removed",
            }
        )

    except (KeyError, ValueError, TypeError, AttributeError, RuntimeError) as e:
        logger.exception("Failed to remove team member")
        return error_response(safe_error_message(e, "remove team member"), status=500)


# =============================================================================
# Presence (Viewing / Typing)
# =============================================================================


@require_permission("inbox:read")
async def handle_start_viewing(
    data: dict[str, Any],
    inbox_id: str = "",
    message_id: str = "",
    user_id: str = "default",
) -> HandlerResult:
    """
    Signal that a user started viewing a message.

    POST /api/v1/inbox/shared/{id}/messages/{msg_id}/viewing
    Body: {
        user_name: str
    }
    """
    try:
        if not inbox_id:
            inbox_id = data.get("inbox_id", "")
        if not message_id:
            message_id = data.get("message_id", "")
        if not inbox_id or not message_id:
            return error_response("inbox_id and message_id are required", status=400)

        user_name = data.get("user_name", "Unknown")

        emitter = get_team_inbox_emitter_instance()
        await emitter.emit_user_viewing(
            inbox_id=inbox_id,
            message_id=message_id,
            user_id=user_id,
            user_name=user_name,
        )

        viewers = await emitter.get_message_viewers(message_id)

        return success_response(
            {
                "message_id": message_id,
                "viewing": True,
                "current_viewers": viewers,
            }
        )

    except (KeyError, ValueError, TypeError, AttributeError, RuntimeError) as e:
        logger.exception("Failed to start viewing")
        return error_response(safe_error_message(e, "start viewing"), status=500)


@require_permission("inbox:read")
async def handle_stop_viewing(
    data: dict[str, Any],
    inbox_id: str = "",
    message_id: str = "",
    user_id: str = "default",
) -> HandlerResult:
    """
    Signal that a user stopped viewing a message.

    DELETE /api/v1/inbox/shared/{id}/messages/{msg_id}/viewing
    """
    try:
        if not inbox_id:
            inbox_id = data.get("inbox_id", "")
        if not message_id:
            message_id = data.get("message_id", "")
        if not inbox_id or not message_id:
            return error_response("inbox_id and message_id are required", status=400)

        user_name = data.get("user_name", "Unknown")

        emitter = get_team_inbox_emitter_instance()
        await emitter.emit_user_left(
            inbox_id=inbox_id,
            message_id=message_id,
            user_id=user_id,
            user_name=user_name,
        )

        return success_response(
            {
                "message_id": message_id,
                "viewing": False,
            }
        )

    except (KeyError, ValueError, TypeError, AttributeError, RuntimeError) as e:
        logger.exception("Failed to stop viewing")
        return error_response(safe_error_message(e, "stop viewing"), status=500)


@require_permission("inbox:write")
async def handle_start_typing(
    data: dict[str, Any],
    inbox_id: str = "",
    message_id: str = "",
    user_id: str = "default",
) -> HandlerResult:
    """
    Signal that a user started typing a response.

    POST /api/v1/inbox/shared/{id}/messages/{msg_id}/typing
    Body: {
        user_name: str
    }
    """
    try:
        if not inbox_id:
            inbox_id = data.get("inbox_id", "")
        if not message_id:
            message_id = data.get("message_id", "")
        if not inbox_id or not message_id:
            return error_response("inbox_id and message_id are required", status=400)

        user_name = data.get("user_name", "Unknown")

        emitter = get_team_inbox_emitter_instance()
        await emitter.emit_user_typing(
            inbox_id=inbox_id,
            message_id=message_id,
            user_id=user_id,
            user_name=user_name,
        )

        return success_response(
            {
                "message_id": message_id,
                "typing": True,
            }
        )

    except (KeyError, ValueError, TypeError, AttributeError, RuntimeError) as e:
        logger.exception("Failed to start typing")
        return error_response(safe_error_message(e, "start typing"), status=500)


@require_permission("inbox:write")
async def handle_stop_typing(
    data: dict[str, Any],
    inbox_id: str = "",
    message_id: str = "",
    user_id: str = "default",
) -> HandlerResult:
    """
    Signal that a user stopped typing.

    DELETE /api/v1/inbox/shared/{id}/messages/{msg_id}/typing
    """
    try:
        if not inbox_id:
            inbox_id = data.get("inbox_id", "")
        if not message_id:
            message_id = data.get("message_id", "")
        if not inbox_id or not message_id:
            return error_response("inbox_id and message_id are required", status=400)

        user_name = data.get("user_name", "Unknown")

        emitter = get_team_inbox_emitter_instance()
        await emitter.emit_user_stopped_typing(
            inbox_id=inbox_id,
            message_id=message_id,
            user_id=user_id,
            user_name=user_name,
        )

        return success_response(
            {
                "message_id": message_id,
                "typing": False,
            }
        )

    except (KeyError, ValueError, TypeError, AttributeError, RuntimeError) as e:
        logger.exception("Failed to stop typing")
        return error_response(safe_error_message(e, "stop typing"), status=500)


# =============================================================================
# Internal Notes
# =============================================================================


@require_permission("inbox:read")
async def handle_get_notes(
    data: dict[str, Any],
    inbox_id: str = "",
    message_id: str = "",
    user_id: str = "default",
) -> HandlerResult:
    """
    Get internal notes for a message.

    GET /api/v1/inbox/shared/{id}/messages/{msg_id}/notes
    """
    try:
        if not inbox_id:
            inbox_id = data.get("inbox_id", "")
        if not message_id:
            message_id = data.get("message_id", "")
        if not inbox_id or not message_id:
            return error_response("inbox_id and message_id are required", status=400)

        emitter = get_team_inbox_emitter_instance()
        notes = await emitter.get_notes(message_id)

        return success_response(
            {
                "message_id": message_id,
                "notes": [n.to_dict() for n in notes],
                "count": len(notes),
            }
        )

    except (KeyError, ValueError, TypeError, AttributeError, RuntimeError) as e:
        logger.exception("Failed to get notes")
        return error_response(safe_error_message(e, "get notes"), status=500)


@require_permission("inbox:create")
async def handle_add_note(
    data: dict[str, Any],
    inbox_id: str = "",
    message_id: str = "",
    user_id: str = "default",
) -> HandlerResult:
    """
    Add an internal note to a message.

    POST /api/v1/inbox/shared/{id}/messages/{msg_id}/notes
    Body: {
        content: str,
        author_name: str
    }
    """
    try:
        if not inbox_id:
            inbox_id = data.get("inbox_id", "")
        if not message_id:
            message_id = data.get("message_id", "")
        if not inbox_id or not message_id:
            return error_response("inbox_id and message_id are required", status=400)

        content = data.get("content", "")
        author_name = data.get("author_name", "Unknown")

        if not content:
            return error_response("'content' is required", status=400)

        emitter = get_team_inbox_emitter_instance()
        note = await emitter.add_note(
            inbox_id=inbox_id,
            message_id=message_id,
            author_id=user_id,
            author_name=author_name,
            content=content,
        )

        # Process @mentions in the note
        mentioned_usernames = emitter.extract_mentions(content)
        if mentioned_usernames:
            # Create mention records for each mentioned user
            # In production, would resolve usernames to user_ids
            for username in mentioned_usernames:
                try:
                    await emitter.create_mention(
                        mentioned_user_id=username,  # Should be resolved to actual user_id
                        mentioned_by_user_id=user_id,
                        message_id=message_id,
                        inbox_id=inbox_id,
                        context=content[:100],  # First 100 chars as context
                    )
                except (
                    KeyError,
                    ValueError,
                    TypeError,
                    AttributeError,
                    RuntimeError,
                ) as mention_error:
                    logger.warning("Failed to create mention for %s: %s", username, mention_error)

        # Persist activity log
        org_id = data.get("org_id")
        if org_id:
            _log_activity(
                inbox_id=inbox_id,
                org_id=org_id,
                actor_id=user_id,
                action="note_added",
                target_id=message_id,
                metadata={
                    "note_id": note.id,
                    "has_mentions": len(mentioned_usernames) > 0,
                },
            )

        return success_response(
            {
                "note": note.to_dict(),
                "message": "Note added successfully",
                "mentions_created": len(mentioned_usernames),
            }
        )

    except (KeyError, ValueError, TypeError, AttributeError, RuntimeError) as e:
        logger.exception("Failed to add note")
        return error_response(safe_error_message(e, "add note"), status=500)


# =============================================================================
# Mentions
# =============================================================================


@api_endpoint(
    method="GET",
    path="/api/v1/inbox/mentions",
    summary="Get mentions",
    description="Get @mentions for the current user.",
    tags=["Inbox", "Mentions"],
    parameters=[
        {
            "name": "unacknowledged_only",
            "in": "query",
            "schema": {"type": "boolean", "default": False},
        }
    ],
    responses={
        "200": {"description": "List of mentions"},
        "401": {"description": "Authentication required"},
    },
)
@require_permission("inbox:read")
async def handle_get_mentions(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Get @mentions for the current user.

    GET /api/v1/inbox/mentions
    Query params:
        unacknowledged_only: bool (optional, default false)
    """
    try:
        unacknowledged_only = data.get("unacknowledged_only", False)
        if isinstance(unacknowledged_only, str):
            unacknowledged_only = unacknowledged_only.lower() == "true"

        emitter = get_team_inbox_emitter_instance()
        mentions = await emitter.get_mentions_for_user(
            user_id=user_id,
            unacknowledged_only=unacknowledged_only,
        )

        return success_response(
            {
                "mentions": [m.to_dict() for m in mentions],
                "count": len(mentions),
                "unacknowledged_count": sum(1 for m in mentions if not m.acknowledged),
            }
        )

    except (KeyError, ValueError, TypeError, AttributeError, RuntimeError) as e:
        logger.exception("Failed to get mentions")
        return error_response(safe_error_message(e, "get mentions"), status=500)


@api_endpoint(
    method="POST",
    path="/api/v1/inbox/mentions/{mention_id}/acknowledge",
    summary="Acknowledge mention",
    description="Mark a mention as acknowledged.",
    tags=["Inbox", "Mentions"],
    parameters=[
        {"name": "mention_id", "in": "path", "required": True, "schema": {"type": "string"}}
    ],
    responses={
        "200": {"description": "Mention acknowledged"},
        "400": {"description": "mention_id is required"},
        "401": {"description": "Authentication required"},
        "404": {"description": "Mention not found"},
    },
)
@require_permission("inbox:write")
async def handle_acknowledge_mention(
    data: dict[str, Any],
    mention_id: str = "",
    user_id: str = "default",
) -> HandlerResult:
    """
    Acknowledge a mention.

    POST /api/v1/inbox/mentions/{id}/acknowledge
    """
    try:
        if not mention_id:
            mention_id = data.get("mention_id", "")
        if not mention_id:
            return error_response("mention_id is required", status=400)

        emitter = get_team_inbox_emitter_instance()
        acknowledged = await emitter.acknowledge_mention(user_id, mention_id)

        if not acknowledged:
            return error_response("Mention not found", status=404)

        return success_response(
            {
                "mention_id": mention_id,
                "acknowledged": True,
                "acknowledged_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    except (KeyError, ValueError, TypeError, AttributeError, RuntimeError) as e:
        logger.exception("Failed to acknowledge mention")
        return error_response(safe_error_message(e, "acknowledge mention"), status=500)


# =============================================================================
# Activity Feed
# =============================================================================


@api_endpoint(
    method="GET",
    path="/api/v1/inbox/shared/{inbox_id}/activity",
    summary="Get activity feed",
    description="Get activity feed for a shared inbox.",
    tags=["Inbox", "Activity"],
    parameters=[
        {"name": "inbox_id", "in": "path", "required": True, "schema": {"type": "string"}},
        {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 50}},
        {"name": "offset", "in": "query", "schema": {"type": "integer", "default": 0}},
    ],
    responses={
        "200": {"description": "Activity feed items"},
        "400": {"description": "inbox_id is required"},
        "401": {"description": "Authentication required"},
    },
)
@require_permission("inbox:read")
async def handle_get_activity_feed(
    data: dict[str, Any],
    inbox_id: str = "",
    user_id: str = "default",
) -> HandlerResult:
    """
    Get activity feed for a shared inbox.

    GET /api/v1/inbox/shared/{id}/activity
    Query params:
        limit: int (optional, default 50)
        offset: int (optional, default 0)
    """
    try:
        if not inbox_id:
            inbox_id = data.get("inbox_id", "")
        if not inbox_id:
            return error_response("inbox_id is required", status=400)

        limit = max(1, min(int(data.get("limit", 50)), 200))
        offset = max(0, int(data.get("offset", 0)))

        # In production, this would fetch from a persistent activity log
        # For now, return empty as activities are streamed via WebSocket

        return success_response(
            {
                "inbox_id": inbox_id,
                "activities": [],
                "limit": limit,
                "offset": offset,
                "message": "Activity feed is available via WebSocket subscription",
            }
        )

    except (KeyError, ValueError, TypeError, AttributeError, RuntimeError) as e:
        logger.exception("Failed to get activity feed")
        return error_response(safe_error_message(e, "get activity feed"), status=500)


# =============================================================================
# Handler Registration
# =============================================================================


def get_team_inbox_handlers() -> dict[str, Any]:
    """Get all team inbox handlers for registration."""
    return {
        # Team members
        "get_team_members": handle_get_team_members,
        "add_team_member": handle_add_team_member,
        "remove_team_member": handle_remove_team_member,
        # Presence
        "start_viewing": handle_start_viewing,
        "stop_viewing": handle_stop_viewing,
        "start_typing": handle_start_typing,
        "stop_typing": handle_stop_typing,
        # Notes
        "get_notes": handle_get_notes,
        "add_note": handle_add_note,
        # Mentions
        "get_mentions": handle_get_mentions,
        "acknowledge_mention": handle_acknowledge_mention,
        # Activity
        "get_activity_feed": handle_get_activity_feed,
    }


class TeamInboxMentionsHandler(BaseHandler):
    """Registry-dispatched handler for the current user's @mentions.

    ``handle_get_mentions`` above is an emitter-level function that was never
    reachable through the HTTP dispatch registry; this handler serves the
    spec-documented ``GET /api/v1/inbox/mentions`` operation truthfully.
    """

    ROUTES = ["/api/v1/inbox/mentions"]

    def can_handle(self, path: str) -> bool:
        return strip_version_prefix(path.split("?")[0]) == "/api/inbox/mentions"

    @handler_decorators.require_permission("inbox:read")
    async def handle(  # type: ignore[override]
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
        user: Any = None,
    ) -> HandlerResult | None:
        method = (getattr(handler, "command", None) or "GET").upper()
        if method != "GET":
            return None

        unacknowledged_only = query_params.get("unacknowledged_only", False)
        if isinstance(unacknowledged_only, str):
            unacknowledged_only = unacknowledged_only.lower() == "true"

        user_id = getattr(user, "user_id", None) or "default"
        try:
            emitter = get_team_inbox_emitter_instance()
            mentions = await emitter.get_mentions_for_user(
                user_id=user_id,
                unacknowledged_only=bool(unacknowledged_only),
            )
            return success_response(
                {
                    "mentions": [m.to_dict() for m in mentions],
                    "count": len(mentions),
                    "unacknowledged_count": sum(1 for m in mentions if not m.acknowledged),
                }
            )
        except (KeyError, ValueError, TypeError, AttributeError, RuntimeError) as e:
            logger.exception("Failed to get mentions")
            return error_response(safe_error_message(e, "get mentions"), status=500)


__all__ = [
    # Team members
    "handle_get_team_members",
    "handle_add_team_member",
    "handle_remove_team_member",
    # Presence
    "handle_start_viewing",
    "handle_stop_viewing",
    "handle_start_typing",
    "handle_stop_typing",
    # Notes
    "handle_get_notes",
    "handle_add_note",
    # Mentions
    "handle_get_mentions",
    "handle_acknowledge_mention",
    # Activity
    "handle_get_activity_feed",
    # Registry-dispatched handlers
    "TeamInboxMentionsHandler",
    # Registration
    "get_team_inbox_handlers",
]
