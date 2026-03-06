"""
Gmail Labels and Filters Management.

Provides REST API endpoints for Gmail label and filter operations:
- POST /api/v1/gmail/labels - Create label
- GET /api/v1/gmail/labels - List labels
- PATCH /api/v1/gmail/labels/:id - Update label
- DELETE /api/v1/gmail/labels/:id - Delete label
- POST /api/v1/gmail/messages/:id/labels - Modify message labels
- POST /api/v1/gmail/messages/:id/read - Mark as read/unread
- POST /api/v1/gmail/messages/:id/star - Star/unstar message
- POST /api/v1/gmail/messages/:id/archive - Archive message
- POST /api/v1/gmail/messages/:id/trash - Trash/untrash message
- POST /api/v1/gmail/filters - Create filter
- GET /api/v1/gmail/filters - List filters
- DELETE /api/v1/gmail/filters/:id - Delete filter
"""

from __future__ import annotations

import logging
from typing import Any, cast

from aragora.rbac.decorators import require_permission

from ..base import (
    HandlerResult,
    error_response,
    json_response,
    handle_errors,
)
from ..secure import ForbiddenError, SecureHandler, UnauthorizedError
from .gmail_ingest import get_user_state

logger = logging.getLogger(__name__)

# Gmail permissions
GMAIL_READ_PERMISSION = "gmail:read"
GMAIL_WRITE_PERMISSION = "gmail:write"


class GmailLabelsHandler(SecureHandler):
    """Handler for Gmail labels and message modification endpoints.

    Requires authentication and gmail:read/gmail:write permissions.
    """

    def __init__(self, ctx: dict | None = None, server_context: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = server_context or ctx or {}

    ROUTES = [
        "/api/v1/gmail/labels",
        "/api/v1/gmail/filters",
    ]

    ROUTE_PREFIXES = [
        "/api/v1/gmail/labels/",
        "/api/v1/gmail/messages/",
        "/api/v1/gmail/filters/",
    ]

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can process the path."""
        if path in self.ROUTES:
            return True
        for prefix in self.ROUTE_PREFIXES:
            if path.startswith(prefix):
                return True
        return False

    async def handle(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        """Route GET requests."""
        # RBAC: Require authentication and gmail:read permission
        try:
            auth_context = await self.get_auth_context(handler, require_auth=True)
            self.check_permission(auth_context, GMAIL_READ_PERMISSION)
        except UnauthorizedError:
            return error_response("Authentication required", 401)
        except ForbiddenError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Permission denied", 403)

        user_id = query_params.get("user_id", "default")
        state = get_user_state(user_id)

        if not state or not getattr(state, "refresh_token", None):
            return error_response("Not connected - please authenticate first", 401)

        if path == "/api/v1/gmail/labels":
            return await self._list_labels(state)

        if path == "/api/v1/gmail/filters":
            return await self._list_filters(state)

        return error_response("Not found", 404)

    @handle_errors("gmail labels creation")
    async def handle_post(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        """Route POST requests."""
        # RBAC: Require authentication and gmail:write permission
        try:
            auth_context = await self.get_auth_context(handler, require_auth=True)
            self.check_permission(auth_context, GMAIL_WRITE_PERMISSION)
        except UnauthorizedError:
            return error_response("Authentication required", 401)
        except ForbiddenError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Permission denied", 403)

        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid JSON body", 400)

        user_id = body.get("user_id", "default")
        state = get_user_state(user_id)

        if not state or not getattr(state, "refresh_token", None):
            return error_response("Not connected - please authenticate first", 401)

        # Label creation
        if path == "/api/v1/gmail/labels":
            return await self._create_label(state, body)

        # Filter creation
        if path == "/api/v1/gmail/filters":
            return await self._create_filter(state, body)

        # Message modifications
        if path.startswith("/api/v1/gmail/messages/"):
            parts = path.split("/")
            if len(parts) >= 7:
                message_id = parts[5]
                action = parts[6]

                if action == "labels":
                    return await self._modify_message_labels(state, message_id, body)
                elif action == "read":
                    return await self._mark_read(state, message_id, body)
                elif action == "star":
                    return await self._star_message(state, message_id, body)
                elif action == "archive":
                    return await self._archive_message(state, message_id)
                elif action == "trash":
                    return await self._trash_message(state, message_id, body)

        return error_response("Not found", 404)

    @handle_errors("gmail labels modification")
    async def handle_patch(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        """Route PATCH requests."""
        # RBAC: Require authentication and gmail:write permission
        try:
            auth_context = await self.get_auth_context(handler, require_auth=True)
            self.check_permission(auth_context, GMAIL_WRITE_PERMISSION)
        except UnauthorizedError:
            return error_response("Authentication required", 401)
        except ForbiddenError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Permission denied", 403)

        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid JSON body", 400)

        user_id = body.get("user_id", "default")
        state = get_user_state(user_id)

        if not state or not getattr(state, "refresh_token", None):
            return error_response("Not connected", 401)

        # Label update
        if path.startswith("/api/v1/gmail/labels/"):
            label_id = path.split("/")[-1]
            return await self._update_label(state, label_id, body)

        return error_response("Not found", 404)

    @handle_errors("gmail labels deletion")
    async def handle_delete(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        """Route DELETE requests."""
        # RBAC: Require authentication and gmail:write permission
        try:
            auth_context = await self.get_auth_context(handler, require_auth=True)
            self.check_permission(auth_context, GMAIL_WRITE_PERMISSION)
        except UnauthorizedError:
            return error_response("Authentication required", 401)
        except ForbiddenError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Permission denied", 403)

        user_id = query_params.get("user_id", "default")
        state = get_user_state(user_id)

        if not state or not getattr(state, "refresh_token", None):
            return error_response("Not connected", 401)

        # Label deletion
        if path.startswith("/api/v1/gmail/labels/"):
            label_id = path.split("/")[-1]
            return await self._delete_label(state, label_id)

        # Filter deletion
        if path.startswith("/api/v1/gmail/filters/"):
            filter_id = path.split("/")[-1]
            return await self._delete_filter(state, filter_id)

        return error_response("Not found", 404)

    # =========================================================================
    # Label Operations
    # =========================================================================

    async def _list_labels(self, state: Any) -> HandlerResult:
        """List all Gmail labels."""
        try:
            from aragora.connectors.enterprise.communication.gmail import GmailConnector

            connector = cast(type, GmailConnector)()
            connector._access_token = state.access_token
            connector._refresh_token = state.refresh_token
            connector._token_expiry = state.token_expiry

            labels = await connector.list_labels()

            return json_response(
                {
                    "labels": [
                        {
                            "id": lbl.id,
                            "name": lbl.name,
                            "type": lbl.type,
                            "message_list_visibility": lbl.message_list_visibility,
                            "label_list_visibility": lbl.label_list_visibility,
                        }
                        for lbl in labels
                    ],
                    "count": len(labels),
                }
            )

        except (ConnectionError, TimeoutError, OSError, ValueError, AttributeError) as e:
            logger.error("[GmailLabels] List labels failed: %s", e)
            return error_response("Failed to list labels", 500)

    async def _create_label(self, state: Any, body: dict[str, Any]) -> HandlerResult:
        """Create a new Gmail label."""
        name = body.get("name")
        if not name:
            return error_response("Label name is required", 400)

        try:
            label = await self._api_create_label(state, name, body)
            return json_response({"label": label, "success": True})

        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.error("[GmailLabels] Create label failed: %s", e)
            return error_response("Label creation failed", 500)

    async def _api_create_label(
        self,
        state: Any,
        name: str,
        options: dict[str, Any],
    ) -> dict[str, Any]:
        """Create label via Gmail API."""
        from aragora.server.http_client_pool import get_http_pool

        token = state.access_token

        label_data = {
            "name": name,
            "labelListVisibility": options.get("label_list_visibility", "labelShow"),
            "messageListVisibility": options.get("message_list_visibility", "show"),
        }

        # Optional color
        if options.get("background_color") or options.get("text_color"):
            label_data["color"] = {
                "backgroundColor": options.get("background_color", "#000000"),
                "textColor": options.get("text_color", "#ffffff"),
            }

        pool = get_http_pool()
        async with pool.get_session("google") as client:
            response = await client.post(
                "https://gmail.googleapis.com/gmail/v1/users/me/labels",
                headers={"Authorization": f"Bearer {token}"},
                json=label_data,
            )
            response.raise_for_status()
            return response.json()

    async def _update_label(self, state: Any, label_id: str, body: dict[str, Any]) -> HandlerResult:
        """Update a Gmail label."""
        try:
            label = await self._api_update_label(state, label_id, body)
            return json_response({"label": label, "success": True})

        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.error("[GmailLabels] Update label failed: %s", e)
            return error_response("Label update failed", 500)

    async def _api_update_label(
        self,
        state: Any,
        label_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """Update label via Gmail API."""
        from aragora.server.http_client_pool import get_http_pool

        token = state.access_token

        label_data: dict[str, Any] = {}
        if "name" in updates:
            label_data["name"] = updates["name"]
        if "label_list_visibility" in updates:
            label_data["labelListVisibility"] = updates["label_list_visibility"]
        if "message_list_visibility" in updates:
            label_data["messageListVisibility"] = updates["message_list_visibility"]
        if "background_color" in updates or "text_color" in updates:
            label_data["color"] = {
                "backgroundColor": updates.get("background_color", "#000000"),
                "textColor": updates.get("text_color", "#ffffff"),
            }

        pool = get_http_pool()
        async with pool.get_session("google") as client:
            response = await client.patch(
                f"https://gmail.googleapis.com/gmail/v1/users/me/labels/{label_id}",
                headers={"Authorization": f"Bearer {token}"},
                json=label_data,
            )
            response.raise_for_status()
            return response.json()

    @require_permission("email:delete")
    async def _delete_label(self, state: Any, label_id: str) -> HandlerResult:
        """Delete a Gmail label."""
        try:
            await self._api_delete_label(state, label_id)
            return json_response({"deleted": label_id, "success": True})

        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.error("[GmailLabels] Delete label failed: %s", e)
            return error_response("Label deletion failed", 500)

    async def _api_delete_label(self, state: Any, label_id: str) -> None:
        """Delete label via Gmail API."""
        from aragora.server.http_client_pool import get_http_pool

        token = state.access_token

        pool = get_http_pool()
        async with pool.get_session("google") as client:
            response = await client.delete(
                f"https://gmail.googleapis.com/gmail/v1/users/me/labels/{label_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()

    # =========================================================================
    # Message Modifications
    # =========================================================================

    async def _modify_message_labels(
        self,
        state: Any,
        message_id: str,
        body: dict[str, Any],
    ) -> HandlerResult:
        """Add/remove labels from a message."""
        add_labels = body.get("add", [])
        remove_labels = body.get("remove", [])

        if not add_labels and not remove_labels:
            return error_response("Must specify labels to add or remove", 400)

        try:
            result = await self._api_modify_labels(state, message_id, add_labels, remove_labels)
            return json_response(
                {
                    "message_id": message_id,
                    "labels": result.get("labelIds", []),
                    "success": True,
                }
            )

        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.error("[GmailLabels] Modify labels failed: %s", e)
            return error_response("Label modification failed", 500)

    async def _api_modify_labels(
        self,
        state: Any,
        message_id: str,
        add_labels: list[str],
        remove_labels: list[str],
    ) -> dict[str, Any]:
        """Modify message labels via Gmail API."""
        from aragora.server.http_client_pool import get_http_pool

        token = state.access_token

        pool = get_http_pool()
        async with pool.get_session("google") as client:
            response = await client.post(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}/modify",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "addLabelIds": add_labels,
                    "removeLabelIds": remove_labels,
                },
            )
            response.raise_for_status()
            return response.json()

    async def _mark_read(
        self,
        state: Any,
        message_id: str,
        body: dict[str, Any],
    ) -> HandlerResult:
        """Mark message as read or unread."""
        is_read = body.get("read", True)

        add_labels = [] if is_read else ["UNREAD"]
        remove_labels = ["UNREAD"] if is_read else []

        try:
            await self._api_modify_labels(state, message_id, add_labels, remove_labels)
            return json_response(
                {
                    "message_id": message_id,
                    "is_read": is_read,
                    "success": True,
                }
            )

        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.error("[GmailLabels] Mark read failed: %s", e)
            return error_response("Mark as read failed", 500)

    async def _star_message(
        self,
        state: Any,
        message_id: str,
        body: dict[str, Any],
    ) -> HandlerResult:
        """Star or unstar a message."""
        is_starred = body.get("starred", True)

        add_labels = ["STARRED"] if is_starred else []
        remove_labels = [] if is_starred else ["STARRED"]

        try:
            await self._api_modify_labels(state, message_id, add_labels, remove_labels)
            return json_response(
                {
                    "message_id": message_id,
                    "is_starred": is_starred,
                    "success": True,
                }
            )

        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.error("[GmailLabels] Star message failed: %s", e)
            return error_response("Star operation failed", 500)

    async def _archive_message(self, state: Any, message_id: str) -> HandlerResult:
        """Archive a message (remove INBOX label)."""
        try:
            await self._api_modify_labels(state, message_id, [], ["INBOX"])
            return json_response(
                {
                    "message_id": message_id,
                    "archived": True,
                    "success": True,
                }
            )

        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.error("[GmailLabels] Archive failed: %s", e)
            return error_response("Archive operation failed", 500)

    async def _trash_message(
        self,
        state: Any,
        message_id: str,
        body: dict[str, Any],
    ) -> HandlerResult:
        """Move message to trash or restore from trash."""
        to_trash = body.get("trash", True)

        try:
            if to_trash:
                await self._api_trash_message(state, message_id)
            else:
                await self._api_untrash_message(state, message_id)

            return json_response(
                {
                    "message_id": message_id,
                    "trashed": to_trash,
                    "success": True,
                }
            )

        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.error("[GmailLabels] Trash failed: %s", e)
            return error_response("Trash operation failed", 500)

    async def _api_trash_message(self, state: Any, message_id: str) -> None:
        """Move message to trash via Gmail API."""
        from aragora.server.http_client_pool import get_http_pool

        token = state.access_token

        pool = get_http_pool()
        async with pool.get_session("google") as client:
            response = await client.post(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}/trash",
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()

    async def _api_untrash_message(self, state: Any, message_id: str) -> None:
        """Remove message from trash via Gmail API."""
        from aragora.server.http_client_pool import get_http_pool

        token = state.access_token

        pool = get_http_pool()
        async with pool.get_session("google") as client:
            response = await client.post(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}/untrash",
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()

    # =========================================================================
    # Filter Operations
    # =========================================================================

    async def _list_filters(self, state: Any) -> HandlerResult:
        """List all Gmail filters."""
        try:
            filters = await self._api_list_filters(state)
            return json_response(
                {
                    "filters": filters,
                    "count": len(filters),
                }
            )

        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.error("[GmailLabels] List filters failed: %s", e)
            return error_response("Failed to list filters", 500)

    async def _api_list_filters(self, state: Any) -> list[dict[str, Any]]:
        """List filters via Gmail API."""
        from aragora.server.http_client_pool import get_http_pool

        token = state.access_token

        pool = get_http_pool()
        async with pool.get_session("google") as client:
            response = await client.get(
                "https://gmail.googleapis.com/gmail/v1/users/me/settings/filters",
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            data = response.json()
            return data.get("filter", [])

    async def _create_filter(self, state: Any, body: dict[str, Any]) -> HandlerResult:
        """Create a Gmail filter."""
        criteria = body.get("criteria", {})
        action = body.get("action", {})

        if not criteria:
            return error_response("Filter criteria is required", 400)
        if not action:
            return error_response("Filter action is required", 400)

        try:
            filter_result = await self._api_create_filter(state, criteria, action)
            return json_response({"filter": filter_result, "success": True})

        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.error("[GmailLabels] Create filter failed: %s", e)
            return error_response("Filter creation failed", 500)

    async def _api_create_filter(
        self,
        state: Any,
        criteria: dict[str, Any],
        action: dict[str, Any],
    ) -> dict[str, Any]:
        """Create filter via Gmail API."""
        from aragora.server.http_client_pool import get_http_pool

        token = state.access_token

        # Build criteria
        filter_criteria: dict[str, Any] = {}
        if "from" in criteria:
            filter_criteria["from"] = criteria["from"]
        if "to" in criteria:
            filter_criteria["to"] = criteria["to"]
        if "subject" in criteria:
            filter_criteria["subject"] = criteria["subject"]
        if "query" in criteria:
            filter_criteria["query"] = criteria["query"]
        if "has_attachment" in criteria:
            filter_criteria["hasAttachment"] = criteria["has_attachment"]
        if "exclude_chats" in criteria:
            filter_criteria["excludeChats"] = criteria["exclude_chats"]
        if "size" in criteria:
            filter_criteria["size"] = criteria["size"]
            filter_criteria["sizeComparison"] = criteria.get("size_comparison", "larger")

        # Build action
        filter_action: dict[str, Any] = {}
        if "add_labels" in action:
            filter_action["addLabelIds"] = action["add_labels"]
        if "remove_labels" in action:
            filter_action["removeLabelIds"] = action["remove_labels"]
        if action.get("star"):
            filter_action["addLabelIds"] = filter_action.get("addLabelIds", []) + ["STARRED"]
        if action.get("important"):
            filter_action["addLabelIds"] = filter_action.get("addLabelIds", []) + ["IMPORTANT"]
        if action.get("archive"):
            filter_action["removeLabelIds"] = filter_action.get("removeLabelIds", []) + ["INBOX"]
        if action.get("delete"):
            filter_action["addLabelIds"] = filter_action.get("addLabelIds", []) + ["TRASH"]
        if action.get("mark_read"):
            filter_action["removeLabelIds"] = filter_action.get("removeLabelIds", []) + ["UNREAD"]
        if "forward" in action:
            filter_action["forward"] = action["forward"]

        pool = get_http_pool()
        async with pool.get_session("google") as client:
            response = await client.post(
                "https://gmail.googleapis.com/gmail/v1/users/me/settings/filters",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "criteria": filter_criteria,
                    "action": filter_action,
                },
            )
            response.raise_for_status()
            return response.json()

    @require_permission("email:delete")
    async def _delete_filter(self, state: Any, filter_id: str) -> HandlerResult:
        """Delete a Gmail filter."""
        try:
            await self._api_delete_filter(state, filter_id)
            return json_response({"deleted": filter_id, "success": True})

        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.error("[GmailLabels] Delete filter failed: %s", e)
            return error_response("Filter deletion failed", 500)

    async def _api_delete_filter(self, state: Any, filter_id: str) -> None:
        """Delete filter via Gmail API."""
        from aragora.server.http_client_pool import get_http_pool

        token = state.access_token

        pool = get_http_pool()
        async with pool.get_session("google") as client:
            response = await client.delete(
                f"https://gmail.googleapis.com/gmail/v1/users/me/settings/filters/{filter_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()


# Export for handler registration
__all__ = ["GmailLabelsHandler"]
