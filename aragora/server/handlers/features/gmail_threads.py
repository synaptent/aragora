"""
Gmail Threads and Drafts Management.

Provides REST API endpoints for Gmail thread and draft operations:
- GET /api/v1/gmail/threads - List threads
- GET /api/v1/gmail/threads/:id - Get thread with all messages
- POST /api/v1/gmail/threads/:id/archive - Archive thread
- POST /api/v1/gmail/threads/:id/trash - Trash thread
- POST /api/v1/gmail/threads/:id/labels - Modify thread labels
- POST /api/v1/gmail/drafts - Create draft
- GET /api/v1/gmail/drafts - List drafts
- GET /api/v1/gmail/drafts/:id - Get draft
- PUT /api/v1/gmail/drafts/:id - Update draft
- DELETE /api/v1/gmail/drafts/:id - Delete draft
- POST /api/v1/gmail/drafts/:id/send - Send draft
- GET /api/v1/gmail/messages/:id/attachments/:attachment_id - Get attachment
"""

from __future__ import annotations

import base64
import logging
from typing import Any, cast

from aragora.rbac.decorators import require_permission
from aragora.server.validation.query_params import safe_query_int
from aragora.storage.gmail_token_store import GmailUserState

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


class GmailThreadsHandler(SecureHandler):
    """Handler for Gmail threads and drafts endpoints.

    Requires authentication and gmail:read/gmail:write permissions.
    """

    def __init__(self, ctx: dict | None = None, server_context: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = server_context or ctx or {}

    ROUTES = [
        "/api/v1/gmail/threads",
        "/api/v1/gmail/drafts",
    ]

    ROUTE_PREFIXES = [
        "/api/v1/gmail/threads/",
        "/api/v1/gmail/drafts/",
    ]

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can process the path."""
        if path in self.ROUTES:
            return True
        for prefix in self.ROUTE_PREFIXES:
            if path.startswith(prefix):
                return True
        # Also handle attachment downloads
        if "/attachments/" in path and path.startswith("/api/v1/gmail/messages/"):
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
        state = await get_user_state(user_id)

        if not state or not getattr(state, "refresh_token", None):
            return error_response("Not connected - please authenticate first", 401)

        # Thread operations
        if path == "/api/v1/gmail/threads":
            return await self._list_threads(state, query_params)

        if path.startswith("/api/v1/gmail/threads/"):
            parts = path.split("/")
            thread_id = parts[5] if len(parts) > 5 else None
            if thread_id and len(parts) == 6:
                return await self._get_thread(state, thread_id)

        # Draft operations
        if path == "/api/v1/gmail/drafts":
            return await self._list_drafts(state, query_params)

        if path.startswith("/api/v1/gmail/drafts/"):
            parts = path.split("/")
            draft_id = parts[5] if len(parts) > 5 else None
            if draft_id and len(parts) == 6:
                return await self._get_draft(state, draft_id)

        # Attachment download
        if "/attachments/" in path and path.startswith("/api/v1/gmail/messages/"):
            parts = path.split("/")
            # /api/v1/gmail/messages/{message_id}/attachments/{attachment_id}
            if len(parts) >= 8:
                message_id = parts[5]
                attachment_id = parts[7]
                return await self._get_attachment(state, message_id, attachment_id)

        return error_response("Not found", 404)

    @handle_errors("gmail threads creation")
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

        # Read JSON body from request
        body = self.read_json_body(handler) or {}

        user_id = body.get("user_id", query_params.get("user_id", "default"))
        state = await get_user_state(user_id)

        if not state or not getattr(state, "refresh_token", None):
            return error_response("Not connected - please authenticate first", 401)

        # Thread operations
        if path.startswith("/api/v1/gmail/threads/"):
            parts = path.split("/")
            if len(parts) >= 7:
                thread_id = parts[5]
                action = parts[6]

                if action == "archive":
                    return await self._archive_thread(state, thread_id)
                elif action == "trash":
                    return await self._trash_thread(state, thread_id, body)
                elif action == "labels":
                    return await self._modify_thread_labels(state, thread_id, body)

        # Draft operations
        if path == "/api/v1/gmail/drafts":
            return await self._create_draft(state, body)

        if path.startswith("/api/v1/gmail/drafts/"):
            parts = path.split("/")
            if len(parts) >= 7:
                draft_id = parts[5]
                action = parts[6]

                if action == "send":
                    return await self._send_draft(state, draft_id)

        return error_response("Not found", 404)

    @handle_errors("gmail threads update")
    async def handle_put(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        """Route PUT requests."""
        # RBAC: Require authentication and gmail:write permission
        try:
            auth_context = await self.get_auth_context(handler, require_auth=True)
            self.check_permission(auth_context, GMAIL_WRITE_PERMISSION)
        except UnauthorizedError:
            return error_response("Authentication required", 401)
        except ForbiddenError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Permission denied", 403)

        # Read JSON body from request
        body = self.read_json_body(handler) or {}

        user_id = body.get("user_id", query_params.get("user_id", "default"))
        state = await get_user_state(user_id)

        if not state or not getattr(state, "refresh_token", None):
            return error_response("Not connected", 401)

        # Draft update
        if path.startswith("/api/v1/gmail/drafts/"):
            parts = path.split("/")
            draft_id = parts[4] if len(parts) > 4 else None
            if draft_id and len(parts) == 5:
                return await self._update_draft(state, draft_id, body)

        return error_response("Not found", 404)

    @handle_errors("gmail threads deletion")
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
        state = await get_user_state(user_id)

        if not state or not getattr(state, "refresh_token", None):
            return error_response("Not connected", 401)

        # Draft deletion
        if path.startswith("/api/v1/gmail/drafts/"):
            parts = path.split("/")
            draft_id = parts[4] if len(parts) > 4 else None
            if draft_id and len(parts) == 5:
                return await self._delete_draft(state, draft_id)

        return error_response("Not found", 404)

    # =========================================================================
    # Thread Operations
    # =========================================================================

    async def _list_threads(
        self, state: GmailUserState, query_params: dict[str, Any]
    ) -> HandlerResult:
        """List Gmail threads."""
        query = query_params.get("q", query_params.get("query", ""))
        label_ids = (
            query_params.get("label_ids", "").split(",") if query_params.get("label_ids") else None
        )
        max_results = safe_query_int(query_params, "limit", default=20, max_val=1000)
        page_token = query_params.get("page_token")

        try:
            threads, next_page = await self._api_list_threads(
                state, query, label_ids, max_results, page_token
            )
            return json_response(
                {
                    "threads": threads,
                    "count": len(threads),
                    "next_page_token": next_page,
                }
            )

        except (ConnectionError, TimeoutError, OSError, ValueError, KeyError) as e:
            logger.error("[GmailThreads] List threads failed: %s", e)
            return error_response("Failed to list threads", 500)

    async def _api_list_threads(
        self,
        state: GmailUserState,
        query: str,
        label_ids: list[str] | None,
        max_results: int,
        page_token: str | None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """List threads via Gmail API."""
        from aragora.server.http_client_pool import get_http_pool

        token = state.access_token

        params: dict[str, Any] = {"maxResults": min(max_results, 100)}
        if query:
            params["q"] = query
        if label_ids:
            params["labelIds"] = label_ids
        if page_token:
            params["pageToken"] = page_token

        pool = get_http_pool()
        async with pool.get_session("google") as client:
            response = await client.get(
                "https://gmail.googleapis.com/gmail/v1/users/me/threads",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
            )
            response.raise_for_status()
            data = response.json()

        threads = []
        for t in data.get("threads", []):
            threads.append(
                {
                    "id": t["id"],
                    "snippet": t.get("snippet", ""),
                    "history_id": t.get("historyId"),
                }
            )

        return threads, data.get("nextPageToken")

    async def _get_thread(self, state: GmailUserState, thread_id: str) -> HandlerResult:
        """Get a thread with all messages."""
        try:
            from aragora.connectors.enterprise.communication.gmail import GmailConnector

            connector = cast(type, GmailConnector)()
            connector._access_token = state.access_token
            connector._refresh_token = state.refresh_token
            connector._token_expiry = state.token_expiry

            # Note: get_thread uses Gmail API's threads.get with format=full,
            # which returns all messages and attachment metadata in a single request.
            # The msg.attachments list is pre-populated (not lazy-loaded), so iterating
            # over it does NOT cause N+1 queries.
            thread = await connector.get_thread(thread_id)

            return json_response(
                {
                    "thread": {
                        "id": thread.id,
                        "subject": thread.subject,
                        "snippet": thread.snippet,
                        "message_count": thread.message_count,
                        "participants": thread.participants,
                        "labels": thread.labels,
                        "last_message_date": (
                            thread.last_message_date.isoformat()
                            if thread.last_message_date
                            else None
                        ),
                        "messages": [
                            {
                                "id": msg.id,
                                "subject": msg.subject,
                                "from": msg.from_address,
                                "to": msg.to_addresses,
                                "cc": msg.cc_addresses,
                                "date": msg.date.isoformat() if msg.date else None,
                                "snippet": msg.snippet,
                                "body_text": (msg.body_text[:2000] if msg.body_text else None),
                                "is_read": msg.is_read,
                                "is_starred": msg.is_starred,
                                "labels": msg.labels,
                                "attachments": [
                                    {
                                        "id": a.id,
                                        "filename": a.filename,
                                        "mime_type": a.mime_type,
                                        "size": a.size,
                                    }
                                    for a in msg.attachments
                                ],
                            }
                            for msg in thread.messages
                        ],
                    }
                }
            )

        except (ConnectionError, TimeoutError, OSError, ValueError, KeyError, AttributeError) as e:
            logger.error("[GmailThreads] Get thread failed: %s", e)
            return error_response("Failed to retrieve thread", 500)

    async def _archive_thread(self, state: GmailUserState, thread_id: str) -> HandlerResult:
        """Archive a thread (remove INBOX label from all messages)."""
        return await self._modify_thread_labels(state, thread_id, {"remove": ["INBOX"]})

    async def _trash_thread(
        self, state: GmailUserState, thread_id: str, body: dict[str, Any]
    ) -> HandlerResult:
        """Move thread to trash or restore from trash."""
        to_trash = body.get("trash", True)

        try:
            if to_trash:
                await self._api_trash_thread(state, thread_id)
            else:
                await self._api_untrash_thread(state, thread_id)

            return json_response(
                {
                    "thread_id": thread_id,
                    "trashed": to_trash,
                    "success": True,
                }
            )

        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.error("[GmailThreads] Trash thread failed: %s", e)
            return error_response("Thread trash failed", 500)

    async def _api_trash_thread(self, state: GmailUserState, thread_id: str) -> None:
        """Trash thread via Gmail API."""
        from aragora.server.http_client_pool import get_http_pool

        token = state.access_token

        pool = get_http_pool()
        async with pool.get_session("google") as client:
            response = await client.post(
                f"https://gmail.googleapis.com/gmail/v1/users/me/threads/{thread_id}/trash",
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()

    async def _api_untrash_thread(self, state: GmailUserState, thread_id: str) -> None:
        """Untrash thread via Gmail API."""
        from aragora.server.http_client_pool import get_http_pool

        token = state.access_token

        pool = get_http_pool()
        async with pool.get_session("google") as client:
            response = await client.post(
                f"https://gmail.googleapis.com/gmail/v1/users/me/threads/{thread_id}/untrash",
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()

    async def _modify_thread_labels(
        self,
        state: GmailUserState,
        thread_id: str,
        body: dict[str, Any],
    ) -> HandlerResult:
        """Modify labels on all messages in a thread."""
        add_labels = body.get("add", [])
        remove_labels = body.get("remove", [])

        if not add_labels and not remove_labels:
            return error_response("Must specify labels to add or remove", 400)

        try:
            await self._api_modify_thread_labels(state, thread_id, add_labels, remove_labels)
            return json_response(
                {
                    "thread_id": thread_id,
                    "success": True,
                }
            )

        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.error("[GmailThreads] Modify thread labels failed: %s", e)
            return error_response("Thread label modification failed", 500)

    async def _api_modify_thread_labels(
        self,
        state: GmailUserState,
        thread_id: str,
        add_labels: list[str],
        remove_labels: list[str],
    ) -> dict[str, Any]:
        """Modify thread labels via Gmail API."""
        from aragora.server.http_client_pool import get_http_pool

        token = state.access_token

        pool = get_http_pool()
        async with pool.get_session("google") as client:
            response = await client.post(
                f"https://gmail.googleapis.com/gmail/v1/users/me/threads/{thread_id}/modify",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "addLabelIds": add_labels,
                    "removeLabelIds": remove_labels,
                },
            )
            response.raise_for_status()
            return response.json()

    # =========================================================================
    # Draft Operations
    # =========================================================================

    async def _list_drafts(
        self, state: GmailUserState, query_params: dict[str, Any]
    ) -> HandlerResult:
        """List Gmail drafts."""
        max_results = safe_query_int(query_params, "limit", default=20, max_val=1000)
        page_token = query_params.get("page_token")

        try:
            drafts, next_page = await self._api_list_drafts(state, max_results, page_token)
            return json_response(
                {
                    "drafts": drafts,
                    "count": len(drafts),
                    "next_page_token": next_page,
                }
            )

        except (ConnectionError, TimeoutError, OSError, ValueError, KeyError) as e:
            logger.error("[GmailThreads] List drafts failed: %s", e)
            return error_response("Failed to list drafts", 500)

    async def _api_list_drafts(
        self,
        state: GmailUserState,
        max_results: int,
        page_token: str | None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """List drafts via Gmail API."""
        from aragora.server.http_client_pool import get_http_pool

        token = state.access_token

        params: dict[str, Any] = {"maxResults": min(max_results, 100)}
        if page_token:
            params["pageToken"] = page_token

        pool = get_http_pool()
        async with pool.get_session("google") as client:
            response = await client.get(
                "https://gmail.googleapis.com/gmail/v1/users/me/drafts",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
            )
            response.raise_for_status()
            data = response.json()

        drafts = []
        for d in data.get("drafts", []):
            drafts.append(
                {
                    "id": d["id"],
                    "message_id": d.get("message", {}).get("id"),
                    "thread_id": d.get("message", {}).get("threadId"),
                }
            )

        return drafts, data.get("nextPageToken")

    async def _get_draft(self, state: GmailUserState, draft_id: str) -> HandlerResult:
        """Get a draft with message content."""
        try:
            draft = await self._api_get_draft(state, draft_id)
            return json_response({"draft": draft})

        except (ConnectionError, TimeoutError, OSError, ValueError, KeyError) as e:
            logger.error("[GmailThreads] Get draft failed: %s", e)
            return error_response("Failed to retrieve draft", 500)

    async def _api_get_draft(self, state: GmailUserState, draft_id: str) -> dict[str, Any]:
        """Get draft via Gmail API."""
        from aragora.server.http_client_pool import get_http_pool

        token = state.access_token

        pool = get_http_pool()
        async with pool.get_session("google") as client:
            response = await client.get(
                f"https://gmail.googleapis.com/gmail/v1/users/me/drafts/{draft_id}",
                headers={"Authorization": f"Bearer {token}"},
                params={"format": "full"},
            )
            response.raise_for_status()
            return response.json()

    async def _create_draft(self, state: GmailUserState, body: dict[str, Any]) -> HandlerResult:
        """Create a new draft."""
        to = body.get("to", [])
        subject = body.get("subject", "")
        body_text = body.get("body", "")
        html_body = body.get("html_body")
        reply_to_message_id = body.get("reply_to_message_id")
        thread_id = body.get("thread_id")

        try:
            draft = await self._api_create_draft(
                state, to, subject, body_text, html_body, reply_to_message_id, thread_id
            )
            return json_response({"draft": draft, "success": True})

        except (ConnectionError, TimeoutError, OSError, ValueError, TypeError) as e:
            logger.error("[GmailThreads] Create draft failed: %s", e)
            return error_response("Draft creation failed", 500)

    async def _api_create_draft(
        self,
        state: GmailUserState,
        to: list[str],
        subject: str,
        body_text: str,
        html_body: str | None,
        reply_to_message_id: str | None,
        thread_id: str | None,
    ) -> dict[str, Any]:
        """Create draft via Gmail API."""
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        from aragora.server.http_client_pool import get_http_pool

        token = state.access_token

        # Build MIME message
        message: MIMEMultipart | MIMEText
        if html_body:
            message = MIMEMultipart("alternative")
            message.attach(MIMEText(body_text, "plain"))
            message.attach(MIMEText(html_body, "html"))
        else:
            message = MIMEText(body_text, "plain")

        if to:
            message["To"] = ", ".join(to)
        message["Subject"] = subject

        # Encode message
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

        draft_data: dict[str, Any] = {"message": {"raw": raw_message}}
        if thread_id:
            draft_data["message"]["threadId"] = thread_id

        pool = get_http_pool()
        async with pool.get_session("google") as client:
            response = await client.post(
                "https://gmail.googleapis.com/gmail/v1/users/me/drafts",
                headers={"Authorization": f"Bearer {token}"},
                json=draft_data,
            )
            response.raise_for_status()
            return response.json()

    async def _update_draft(
        self, state: GmailUserState, draft_id: str, body: dict[str, Any]
    ) -> HandlerResult:
        """Update an existing draft."""
        to = body.get("to", [])
        subject = body.get("subject", "")
        body_text = body.get("body", "")
        html_body = body.get("html_body")

        try:
            draft = await self._api_update_draft(state, draft_id, to, subject, body_text, html_body)
            return json_response({"draft": draft, "success": True})

        except (ConnectionError, TimeoutError, OSError, ValueError, TypeError) as e:
            logger.error("[GmailThreads] Update draft failed: %s", e)
            return error_response("Draft update failed", 500)

    async def _api_update_draft(
        self,
        state: GmailUserState,
        draft_id: str,
        to: list[str],
        subject: str,
        body_text: str,
        html_body: str | None,
    ) -> dict[str, Any]:
        """Update draft via Gmail API."""
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        from aragora.server.http_client_pool import get_http_pool

        token = state.access_token

        # Build MIME message
        message: MIMEMultipart | MIMEText
        if html_body:
            message = MIMEMultipart("alternative")
            message.attach(MIMEText(body_text, "plain"))
            message.attach(MIMEText(html_body, "html"))
        else:
            message = MIMEText(body_text, "plain")

        if to:
            message["To"] = ", ".join(to)
        message["Subject"] = subject

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

        pool = get_http_pool()
        async with pool.get_session("google") as client:
            response = await client.put(
                f"https://gmail.googleapis.com/gmail/v1/users/me/drafts/{draft_id}",
                headers={"Authorization": f"Bearer {token}"},
                json={"message": {"raw": raw_message}},
            )
            response.raise_for_status()
            return response.json()

    @require_permission("email:delete")
    async def _delete_draft(self, state: GmailUserState, draft_id: str) -> HandlerResult:
        """Delete a draft."""
        try:
            await self._api_delete_draft(state, draft_id)
            return json_response({"deleted": draft_id, "success": True})

        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.error("[GmailThreads] Delete draft failed: %s", e)
            return error_response("Draft deletion failed", 500)

    async def _api_delete_draft(self, state: GmailUserState, draft_id: str) -> None:
        """Delete draft via Gmail API."""
        from aragora.server.http_client_pool import get_http_pool

        token = state.access_token

        pool = get_http_pool()
        async with pool.get_session("google") as client:
            response = await client.delete(
                f"https://gmail.googleapis.com/gmail/v1/users/me/drafts/{draft_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()

    async def _send_draft(self, state: GmailUserState, draft_id: str) -> HandlerResult:
        """Send a draft."""
        try:
            result = await self._api_send_draft(state, draft_id)
            return json_response(
                {
                    "message_id": result.get("id"),
                    "thread_id": result.get("threadId"),
                    "success": True,
                }
            )

        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.error("[GmailThreads] Send draft failed: %s", e)
            return error_response("Draft send failed", 500)

    async def _api_send_draft(self, state: GmailUserState, draft_id: str) -> dict[str, Any]:
        """Send draft via Gmail API."""
        from aragora.server.http_client_pool import get_http_pool

        token = state.access_token

        pool = get_http_pool()
        async with pool.get_session("google") as client:
            response = await client.post(
                "https://gmail.googleapis.com/gmail/v1/users/me/drafts/send",
                headers={"Authorization": f"Bearer {token}"},
                json={"id": draft_id},
            )
            response.raise_for_status()
            return response.json()

    # =========================================================================
    # Attachment Operations
    # =========================================================================

    async def _get_attachment(
        self,
        state: GmailUserState,
        message_id: str,
        attachment_id: str,
    ) -> HandlerResult:
        """Get attachment data."""
        try:
            attachment = await self._api_get_attachment(state, message_id, attachment_id)
            return json_response(
                {
                    "attachment_id": attachment_id,
                    "message_id": message_id,
                    "data": attachment.get("data"),  # Base64 encoded
                    "size": attachment.get("size"),
                }
            )

        except (ConnectionError, TimeoutError, OSError, ValueError, KeyError) as e:
            logger.error("[GmailThreads] Get attachment failed: %s", e)
            return error_response("Failed to retrieve attachment", 500)

    async def _api_get_attachment(
        self,
        state: GmailUserState,
        message_id: str,
        attachment_id: str,
    ) -> dict[str, Any]:
        """Get attachment via Gmail API."""
        from aragora.server.http_client_pool import get_http_pool

        token = state.access_token

        pool = get_http_pool()
        async with pool.get_session("google") as client:
            response = await client.get(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}/attachments/{attachment_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            return response.json()


# Export for handler registration
__all__ = ["GmailThreadsHandler"]
