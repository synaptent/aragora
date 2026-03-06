"""
HTTP handlers for shared inbox and message operations.

Handles inbox CRUD, message assignment, status updates, and tagging.
"""

from __future__ import annotations

import logging
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

from aragora.observability.metrics import track_handler
from aragora.server.handlers.utils.decorators import require_permission

from .models import (
    MessageStatus,
    SharedInbox,
    SharedInboxMessage,
)
from .storage import (
    _get_activity_store as _get_activity_store_impl,
    _get_store as _get_store_impl,
    _log_activity as _log_activity_impl,
    _shared_inboxes,
    _inbox_messages,
    _storage_lock,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Store shims for test compatibility
# Tests patch aragora.server.handlers._shared_inbox_handler._get_store
# =============================================================================


def _get_store() -> Any:
    """Get store with test patch support."""
    module = sys.modules.get("aragora.server.handlers._shared_inbox_handler")
    if module is not None:
        patched = getattr(module, "_get_store", None)
        if patched is not None and patched is not _get_store:
            return patched()
    return _get_store_impl()


def _get_activity_store() -> Any:
    """Get activity store with test patch support."""
    module = sys.modules.get("aragora.server.handlers._shared_inbox_handler")
    if module is not None:
        patched = getattr(module, "_get_activity_store", None)
        if patched is not None and patched is not _get_activity_store:
            return patched()
    return _get_activity_store_impl()


def _log_activity(
    inbox_id: str,
    org_id: str,
    actor_id: str,
    action: str,
    target_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Log activity with test patch support.

    Checks for patched _get_activity_store and uses it for logging.
    """
    module = sys.modules.get("aragora.server.handlers._shared_inbox_handler")
    if module is not None:
        # Check for direct _log_activity mock (for assert_called tests)
        patched = getattr(module, "_log_activity", None)
        if patched is not None and hasattr(patched, "assert_called"):
            return patched(inbox_id, org_id, actor_id, action, target_id, metadata)

        # Check for patched _get_activity_store
        patched_store_getter = getattr(module, "_get_activity_store", None)
        if patched_store_getter is not None:
            store = patched_store_getter()
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
                except (KeyError, ValueError, OSError, TypeError) as e:
                    logger.debug("Failed to log inbox activity: %s", e)
                return

    # Fall back to default implementation
    _log_activity_impl(inbox_id, org_id, actor_id, action, target_id, metadata)


@require_permission("inbox:write")
async def handle_create_shared_inbox(
    workspace_id: str,
    name: str,
    description: str | None = None,
    email_address: str | None = None,
    connector_type: str | None = None,
    team_members: list[str] | None = None,
    admins: list[str] | None = None,
    settings: dict[str, Any] | None = None,
    created_by: str | None = None,
) -> dict[str, Any]:
    """
    Create a new shared inbox.

    POST /api/v1/inbox/shared
    {
        "workspace_id": "ws_123",
        "name": "Support Inbox",
        "description": "Customer support emails",
        "email_address": "support@company.com",
        "connector_type": "gmail",
        "team_members": ["user1", "user2"],
        "admins": ["admin1"]
    }
    """
    try:
        inbox_id = f"inbox_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        inbox = SharedInbox(
            id=inbox_id,
            workspace_id=workspace_id,
            name=name,
            description=description,
            email_address=email_address,
            connector_type=connector_type,
            team_members=team_members or [],
            admins=admins or [],
            settings=settings or {},
            created_at=now,
            updated_at=now,
            created_by=created_by,
        )

        # Persist to store if available
        store = _get_store()
        if store and hasattr(store, "get_inbox_messages"):
            try:
                store.create_shared_inbox(
                    inbox_id=inbox_id,
                    workspace_id=workspace_id,
                    name=name,
                    description=description,
                    email_address=email_address,
                    connector_type=connector_type,
                    team_members=team_members or [],
                    admins=admins or [],
                    settings=settings or {},
                    created_by=created_by,
                )
            except TypeError:
                try:
                    store.create_shared_inbox(
                        inbox_id=inbox_id,
                        workspace_id=workspace_id,
                        name=name,
                        description=description,
                        email_address=email_address,
                        team_members=team_members or [],
                        admins=admins or [],
                        settings=settings or {},
                        created_by=created_by,
                    )
                except (OSError, RuntimeError, ValueError, KeyError, TypeError) as e:
                    logger.warning("[SharedInbox] Failed to persist inbox to store: %s", e)
            except (OSError, RuntimeError, ValueError, KeyError) as e:
                logger.warning("[SharedInbox] Failed to persist inbox to store: %s", e)

        # Always keep in-memory cache for fast reads
        with _storage_lock:
            _shared_inboxes[inbox_id] = inbox
            _inbox_messages[inbox_id] = {}

        logger.info("[SharedInbox] Created inbox %s: %s", inbox_id, name)

        return {
            "success": True,
            "inbox": inbox.to_dict(),
        }

    except (KeyError, ValueError, OSError, TypeError, RuntimeError) as e:
        logger.exception("Failed to create shared inbox: %s", e)
        return {
            "success": False,
            "error": "Internal server error",
        }


@track_handler("inbox/shared/list", method="GET")
@require_permission("inbox:read")
async def handle_list_shared_inboxes(
    workspace_id: str,
    user_id: str | None = None,
) -> dict[str, Any]:
    """
    List shared inboxes the user has access to.

    GET /api/v1/inbox/shared?workspace_id=ws_123
    """
    try:
        # Try persistent store first
        store = _get_store()
        if store and hasattr(store, "get_inbox_messages"):
            try:
                stored_inboxes = store.list_shared_inboxes(workspace_id, user_id)
                if stored_inboxes:
                    # Update in-memory cache
                    for inbox_data in stored_inboxes:
                        inbox_id = inbox_data.get("id")
                        if inbox_id and inbox_id not in _shared_inboxes:
                            # Reconstruct SharedInbox object for cache
                            with _storage_lock:
                                if inbox_id not in _inbox_messages:
                                    _inbox_messages[inbox_id] = {}
                    return {
                        "success": True,
                        "inboxes": stored_inboxes,
                        "total": len(stored_inboxes),
                    }
            except (OSError, RuntimeError, ValueError, KeyError) as e:
                logger.error("[SharedInbox] Failed to load from store: %s", e)
                return {
                    "success": False,
                    "error": "Storage operation failed",
                }

        # No persistent store available -- use in-memory
        with _storage_lock:
            inboxes = [
                inbox.to_dict()
                for inbox in _shared_inboxes.values()
                if inbox.workspace_id == workspace_id
                and (user_id is None or user_id in inbox.team_members or user_id in inbox.admins)
            ]

        return {
            "success": True,
            "inboxes": inboxes,
            "total": len(inboxes),
        }

    except (KeyError, ValueError, OSError, TypeError, RuntimeError) as e:
        logger.exception("Failed to list shared inboxes: %s", e)
        return {
            "success": False,
            "error": "Internal server error",
        }


@require_permission("inbox:read")
async def handle_get_shared_inbox(
    inbox_id: str,
) -> dict[str, Any]:
    """
    Get shared inbox details.

    GET /api/v1/inbox/shared/:id
    """
    try:
        # Try persistent store first
        store = _get_store()
        if store and hasattr(store, "update_message"):
            try:
                inbox_data = store.get_shared_inbox(inbox_id)
                if inbox_data:
                    return {
                        "success": True,
                        "inbox": inbox_data,
                    }
            except (OSError, RuntimeError, ValueError, KeyError) as e:
                logger.warning("[SharedInbox] Failed to load from store: %s", e)

        # Fallback to in-memory
        with _storage_lock:
            inbox = _shared_inboxes.get(inbox_id)
            if not inbox:
                return {"success": False, "error": "Inbox not found"}

            # Update counts
            messages = _inbox_messages.get(inbox_id, {})
            inbox.message_count = len(messages)
            inbox.unread_count = sum(1 for m in messages.values() if m.status == MessageStatus.OPEN)

            return {
                "success": True,
                "inbox": inbox.to_dict(),
            }

    except (KeyError, ValueError, OSError, TypeError, RuntimeError) as e:
        logger.exception("Failed to get shared inbox: %s", e)
        return {
            "success": False,
            "error": "Internal server error",
        }


@track_handler("inbox/shared/messages", method="GET")
@require_permission("inbox:read")
async def handle_get_inbox_messages(
    inbox_id: str,
    status: str | None = None,
    assigned_to: str | None = None,
    tag: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """
    Get messages in a shared inbox.

    GET /api/v1/inbox/shared/:id/messages
    Query params: status, assigned_to, tag, limit, offset
    """
    try:
        # Try persistent store first
        store = _get_store()
        getter = None
        if store:
            if hasattr(store, "get_inbox_messages"):
                getter = store.get_inbox_messages
            elif hasattr(store, "list_inbox_messages"):
                getter = store.list_inbox_messages
        if getter:
            try:
                messages_data = getter(
                    inbox_id=inbox_id,
                    status=status,
                    assigned_to=assigned_to,
                    limit=limit,
                    offset=offset,
                )
                if messages_data is not None:
                    with _storage_lock:
                        has_cached_messages = bool(_inbox_messages.get(inbox_id))
                    if not messages_data and has_cached_messages:
                        messages_data = None

                if messages_data is not None:
                    # Apply tag filter (not in store query)
                    if tag:
                        messages_data = [m for m in messages_data if tag in m.get("tags", [])]

                    # Get total count by querying with no limit
                    # This is more accurate than returning len(messages_data)
                    total_count = len(messages_data)
                    if len(messages_data) == limit or offset > 0:
                        # There might be more messages - query for total
                        try:
                            all_messages = getter(
                                inbox_id=inbox_id,
                                status=status,
                                assigned_to=assigned_to,
                                limit=10000,  # Large limit to get all
                                offset=0,
                            )
                            if all_messages is not None:
                                if tag:
                                    all_messages = [
                                        m for m in all_messages if tag in m.get("tags", [])
                                    ]
                                total_count = len(all_messages)
                        except (OSError, RuntimeError, ValueError, KeyError) as e:
                            logger.error("Error counting messages: %s", e)
                            return {
                                "success": False,
                                "error": "Storage operation failed",
                            }

                    return {
                        "success": True,
                        "messages": messages_data,
                        "total": total_count,
                        "limit": limit,
                        "offset": offset,
                    }
            except (OSError, RuntimeError, ValueError, KeyError) as e:
                logger.error("[SharedInbox] Failed to load messages from store: %s", e)
                return {
                    "success": False,
                    "error": "Storage operation failed",
                }

        # No persistent store available -- use in-memory
        with _storage_lock:
            if inbox_id not in _inbox_messages:
                return {"success": False, "error": "Inbox not found"}

            messages = list(_inbox_messages[inbox_id].values())

        # Filter
        if status:
            messages = [m for m in messages if m.status.value == status]
        if assigned_to:
            messages = [m for m in messages if m.assigned_to == assigned_to]
        if tag:
            messages = [m for m in messages if tag in m.tags]

        # Sort by received_at descending
        messages.sort(key=lambda m: m.received_at, reverse=True)

        # Paginate
        total = len(messages)
        messages = messages[offset : offset + limit]

        return {
            "success": True,
            "messages": [m.to_dict() for m in messages],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    except (KeyError, ValueError, OSError, TypeError, RuntimeError) as e:
        logger.exception("Failed to get inbox messages: %s", e)
        return {
            "success": False,
            "error": "Internal server error",
        }


@track_handler("inbox/shared/messages/assign")
@require_permission("inbox:read")
async def handle_assign_message(
    inbox_id: str,
    message_id: str,
    assigned_to: str,
    assigned_by: str | None = None,
    org_id: str | None = None,
) -> dict[str, Any]:
    """
    Assign a message to a team member.

    POST /api/v1/inbox/shared/:id/messages/:msg_id/assign
    {
        "assigned_to": "user_123"
    }
    """
    try:
        now = datetime.now(timezone.utc)
        new_status = None
        previous_assignee = None

        with _storage_lock:
            messages = _inbox_messages.get(inbox_id, {})
            message = messages.get(message_id)

            if not message:
                return {"success": False, "error": "Message not found"}

            previous_assignee = message.assigned_to
            message.assigned_to = assigned_to
            message.assigned_at = now
            if message.status == MessageStatus.OPEN:
                message.status = MessageStatus.ASSIGNED
                new_status = MessageStatus.ASSIGNED.value

        # Persist to store if available
        store = _get_store()
        if store:
            try:
                if hasattr(store, "update_message_status"):
                    status_value = new_status or message.status.value
                    store.update_message_status(message_id, status_value, assigned_to=assigned_to)
                elif hasattr(store, "update_message"):
                    updates = {
                        "assigned_to": assigned_to,
                        "assigned_at": now.isoformat(),
                    }
                    if new_status:
                        updates["status"] = new_status
                    store.update_message(message_id, updates)
            except (OSError, RuntimeError, ValueError, KeyError) as e:
                logger.warning("[SharedInbox] Failed to persist assignment to store: %s", e)

        logger.info("[SharedInbox] Assigned message %s to %s", message_id, assigned_to)

        # Log activity
        if org_id:
            action = "reassigned" if previous_assignee else "assigned"
            _log_activity(
                inbox_id=inbox_id,
                org_id=org_id,
                actor_id=assigned_by or "system",
                action=action,
                target_id=message_id,
                metadata={
                    "assignee_id": assigned_to,
                    "previous_assignee": previous_assignee,
                },
            )

        return {
            "success": True,
            "message": message.to_dict(),
        }

    except (KeyError, ValueError, OSError, TypeError, RuntimeError) as e:
        logger.exception("Failed to assign message: %s", e)
        return {
            "success": False,
            "error": "Internal server error",
        }


@require_permission("inbox:write")
async def handle_update_message_status(
    inbox_id: str,
    message_id: str,
    status: str,
    updated_by: str | None = None,
    org_id: str | None = None,
) -> dict[str, Any]:
    """
    Update message status.

    POST /api/v1/inbox/shared/:id/messages/:msg_id/status
    {
        "status": "resolved"
    }
    """
    try:
        now = datetime.now(timezone.utc)
        is_resolved = False
        previous_status = None

        with _storage_lock:
            messages = _inbox_messages.get(inbox_id, {})
            message = messages.get(message_id)

            if not message:
                return {"success": False, "error": "Message not found"}

            previous_status = message.status.value
            message.status = MessageStatus(status)

            if message.status == MessageStatus.RESOLVED:
                message.resolved_at = now
                message.resolved_by = updated_by
                is_resolved = True

        # Persist to store if available
        store = _get_store()
        if store:
            try:
                if hasattr(store, "update_message_status"):
                    store.update_message_status(message_id, status)
                elif hasattr(store, "update_message"):
                    updates = {"status": status}
                    if is_resolved:
                        updates["resolved_at"] = now.isoformat()
                        updates["resolved_by"] = updated_by
                    store.update_message(message_id, updates)
            except (OSError, RuntimeError, ValueError, KeyError) as e:
                logger.warning("[SharedInbox] Failed to persist status to store: %s", e)

        logger.info("[SharedInbox] Updated message %s status to %s", message_id, status)

        # Log activity
        if org_id:
            _log_activity(
                inbox_id=inbox_id,
                org_id=org_id,
                actor_id=updated_by or "system",
                action="status_changed",
                target_id=message_id,
                metadata={
                    "from_status": previous_status,
                    "to_status": status,
                },
            )

        return {
            "success": True,
            "message": message.to_dict(),
        }

    except ValueError:
        return {"success": False, "error": f"Invalid status: {status}"}
    except (KeyError, OSError, TypeError, RuntimeError) as e:
        logger.exception("Failed to update message status: %s", e)
        return {
            "success": False,
            "error": "Internal server error",
        }


@require_permission("inbox:write")
async def handle_add_message_tag(
    inbox_id: str,
    message_id: str,
    tag: str,
    added_by: str | None = None,
    org_id: str | None = None,
) -> dict[str, Any]:
    """
    Add a tag to a message.

    POST /api/v1/inbox/shared/:id/messages/:msg_id/tag
    {
        "tag": "urgent"
    }
    """
    try:
        tag_added = False
        with _storage_lock:
            messages = _inbox_messages.get(inbox_id, {})
            message = messages.get(message_id)

            if not message:
                return {"success": False, "error": "Message not found"}

            if tag not in message.tags:
                message.tags.append(tag)
                tag_added = True

        # Log activity if tag was actually added
        if tag_added and org_id:
            _log_activity(
                inbox_id=inbox_id,
                org_id=org_id,
                actor_id=added_by or "system",
                action="tag_added",
                target_id=message_id,
                metadata={"tag": tag},
            )

        return {
            "success": True,
            "message": message.to_dict(),
        }

    except (KeyError, ValueError, OSError, TypeError, RuntimeError) as e:
        logger.exception("Failed to add message tag: %s", e)
        return {
            "success": False,
            "error": "Internal server error",
        }


@require_permission("inbox:write")
async def handle_add_message_to_inbox(
    inbox_id: str,
    email_id: str,
    subject: str,
    from_address: str,
    to_addresses: list[str],
    snippet: str,
    received_at: datetime | None = None,
    thread_id: str | None = None,
    priority: str | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """
    Add a message to a shared inbox (used by sync/routing).

    Internal API - not directly exposed to users.
    """
    try:
        message_id = f"msg_{uuid.uuid4().hex[:12]}"
        actual_received_at = received_at or datetime.now(timezone.utc)

        message = SharedInboxMessage(
            id=message_id,
            inbox_id=inbox_id,
            email_id=email_id,
            subject=subject,
            from_address=from_address,
            to_addresses=to_addresses,
            snippet=snippet,
            received_at=actual_received_at,
            thread_id=thread_id,
            priority=priority,
        )

        # Persist to store if available
        store = _get_store()
        if store:
            try:
                # Get workspace_id from inbox if not provided
                if not workspace_id:
                    inbox_data = store.get_shared_inbox(inbox_id)
                    workspace_id = (
                        inbox_data.get("workspace_id", "default") if inbox_data else "default"
                    )

                store.save_message(
                    message_id=message_id,
                    inbox_id=inbox_id,
                    workspace_id=workspace_id,
                    email_id=email_id,
                    subject=subject,
                    from_address=from_address,
                    to_addresses=to_addresses,
                    snippet=snippet,
                    received_at=actual_received_at,
                    thread_id=thread_id,
                    priority=priority,
                )
            except (OSError, RuntimeError, ValueError, KeyError) as e:
                logger.warning("[SharedInbox] Failed to persist message to store: %s", e)

        # Keep in-memory cache
        with _storage_lock:
            if inbox_id not in _inbox_messages:
                _inbox_messages[inbox_id] = {}

            _inbox_messages[inbox_id][message_id] = message

        return {
            "success": True,
            "message": message.to_dict(),
        }

    except (KeyError, ValueError, OSError, TypeError, RuntimeError) as e:
        logger.exception("Failed to add message to inbox: %s", e)
        return {
            "success": False,
            "error": "Internal server error",
        }


# =============================================================================
# Routing Rule Handlers
# =============================================================================
