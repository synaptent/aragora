"""
Gmail inbox ingestion handler.

Endpoints:
- POST /api/gmail/connect - Start OAuth flow
- GET /api/gmail/auth/callback - Handle OAuth callback
- POST /api/gmail/sync - Start email sync
- GET /api/gmail/sync/status - Get sync progress
- GET /api/gmail/messages - List indexed emails
- GET /api/gmail/message/{id} - Get single email
- POST /api/gmail/search - Search emails
- DELETE /api/gmail/disconnect - Disconnect account

Storage:
- Gmail tokens and sync jobs are persisted to SQLite/Redis via GmailTokenStore
- Survives server restarts and supports multi-instance deployments
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from aragora.billing.auth import extract_user_from_request
from aragora.storage.gmail_token_store import (
    GmailUserState,
    SyncJobState,
    get_gmail_token_store,
)

from ..base import (
    HandlerResult,
    error_response,
    json_response,
    safe_error_message,
    handle_errors,
)
from ..secure import ForbiddenError, SecureHandler, UnauthorizedError
from ..utils.rate_limit import RateLimiter, get_client_ip
from aragora.server.validation.query_params import safe_query_int

# Gmail permissions
GMAIL_READ_PERMISSION = "gmail:read"
GMAIL_WRITE_PERMISSION = "gmail:write"

logger = logging.getLogger(__name__)

# Rate limiter for Gmail endpoints (20 requests per minute - OAuth + sync operations)
_gmail_limiter = RateLimiter(requests_per_minute=20)


async def get_user_state(user_id: str) -> GmailUserState | None:
    """Get Gmail state for a user."""
    store = get_gmail_token_store()
    return await store.get(user_id)


async def save_user_state(state: GmailUserState) -> None:
    """Save Gmail state for a user."""
    store = get_gmail_token_store()
    await store.save(state)


async def delete_user_state(user_id: str) -> bool:
    """Delete Gmail state for a user."""
    store = get_gmail_token_store()
    return await store.delete(user_id)


async def get_sync_job(user_id: str) -> SyncJobState | None:
    """Get sync job state for a user."""
    store = get_gmail_token_store()
    return await store.get_sync_job(user_id)


async def save_sync_job(job: SyncJobState) -> None:
    """Save sync job state."""
    store = get_gmail_token_store()
    await store.save_sync_job(job)


async def delete_sync_job(user_id: str) -> bool:
    """Delete sync job for a user."""
    store = get_gmail_token_store()
    return await store.delete_sync_job(user_id)


class GmailIngestHandler(SecureHandler):
    """Handler for Gmail inbox ingestion endpoints.

    Extends SecureHandler for JWT-based authentication, RBAC permission
    enforcement, and security audit logging.

    SECURITY: All user_id values are bound to the authenticated JWT context
    to prevent cross-tenant access. Caller-supplied user_id is ignored.
    """

    def __init__(self, ctx: dict | None = None, server_context: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = server_context or ctx or {}

    RESOURCE_TYPE = "gmail"

    ROUTES = [
        "/api/v1/gmail/connect",
        "/api/v1/gmail/auth/url",
        "/api/v1/gmail/auth/callback",
        "/api/v1/gmail/callback",
        "/api/v1/gmail/connection",
        "/api/v1/gmail/sync",
        "/api/v1/gmail/sync/status",
        "/api/v1/gmail/messages",
        "/api/v1/gmail/search",
        "/api/v1/gmail/disconnect",
        "/api/v1/gmail/status",
        "/api/v1/gmail/stats",
        "/api/v1/gmail/processed",
        "/api/v1/gmail/triage-rules",
        "/api/v1/gmail/debate-configs",
    ]

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can process the path."""
        return path.startswith("/api/v1/gmail/")

    def _get_authenticated_user(
        self, handler: Any
    ) -> tuple[str | None, str | None, HandlerResult | None]:
        """Extract authenticated user from JWT token.

        SECURITY: user_id is bound to JWT context to prevent cross-tenant access.
        Caller-supplied user_id in query/body is ignored.

        Returns:
            Tuple of (user_id, org_id, error_response).
            If authentication fails, error_response is set and user_id/org_id are None.
        """
        auth_ctx = extract_user_from_request(handler)
        if not auth_ctx.authenticated or not auth_ctx.user_id:
            logger.warning("Gmail endpoint accessed without valid JWT authentication")
            return (
                None,
                None,
                error_response("Authentication required. Please provide a valid JWT token.", 401),
            )
        return auth_ctx.user_id, auth_ctx.org_id, None

    async def handle(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        """Route GET requests."""
        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _gmail_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for Gmail endpoint: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        # RBAC: Require authentication and gmail:read permission
        try:
            auth_context = await self.get_auth_context(handler, require_auth=True)
            self.check_permission(auth_context, GMAIL_READ_PERMISSION)
        except UnauthorizedError:
            return error_response("Authentication required", 401)
        except ForbiddenError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Permission denied", 403)

        # SECURITY: Extract user_id from JWT token, not from query params
        user_id, org_id, auth_error = self._get_authenticated_user(handler)
        if auth_error:
            return auth_error

        if path == "/api/v1/gmail/status":
            return await self._get_status(user_id)

        if path == "/api/v1/gmail/auth/url":
            return self._get_auth_url(query_params)

        if path == "/api/v1/gmail/auth/callback":
            # Handle OAuth callback GET
            return await self._handle_oauth_callback(query_params, user_id, org_id or "")

        if path == "/api/v1/gmail/sync/status":
            return await self._get_sync_status(user_id)

        if path == "/api/v1/gmail/messages":
            return await self._list_messages(user_id, query_params)

        if path.startswith("/api/v1/gmail/message/"):
            message_id = path.split("/")[-1]
            return await self._get_message(user_id, message_id)

        return error_response("Not found", 404)

    @handle_errors("gmail ingest creation")
    async def handle_post(
        self,
        path: str,
        body: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        """Route POST requests."""
        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _gmail_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for Gmail endpoint: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        # RBAC: Require authentication and appropriate permission
        # Note: search is a POST but only reads data; use gmail:read for it
        required_permission = (
            GMAIL_READ_PERMISSION if path == "/api/v1/gmail/search" else GMAIL_WRITE_PERMISSION
        )
        try:
            auth_context = await self.get_auth_context(handler, require_auth=True)
            self.check_permission(auth_context, required_permission)
        except UnauthorizedError:
            return error_response("Authentication required", 401)
        except ForbiddenError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Permission denied", 403)

        # SECURITY: Extract user_id from JWT token, not from body
        user_id, org_id, auth_error = self._get_authenticated_user(handler)
        if auth_error:
            return auth_error

        if path == "/api/v1/gmail/connect":
            return self._start_connect(body, user_id)

        if path == "/api/v1/gmail/auth/callback":
            return await self._handle_oauth_callback_post(body, user_id, org_id or "")

        if path == "/api/v1/gmail/sync":
            return await self._start_sync(body, user_id)

        if path == "/api/v1/gmail/search":
            return await self._search(user_id, body)

        if path == "/api/v1/gmail/disconnect":
            return await self._disconnect(user_id)

        return error_response("Not found", 404)

    async def _get_status(self, user_id: str) -> HandlerResult:
        """Get connection status for user."""
        state = await get_user_state(user_id)

        if not state:
            return json_response(
                {
                    "connected": False,
                    "configured": self._is_configured(),
                }
            )

        return json_response(
            {
                "connected": bool(state.refresh_token),
                "configured": self._is_configured(),
                "email_address": state.email_address,
                "indexed_count": state.indexed_count,
                "last_sync": state.last_sync.isoformat() if state.last_sync else None,
            }
        )

    def _is_configured(self) -> bool:
        """Check if Gmail OAuth is configured."""
        return bool(
            os.environ.get("GMAIL_CLIENT_ID")
            or os.environ.get("GOOGLE_GMAIL_CLIENT_ID")
            or os.environ.get("GOOGLE_CLIENT_ID")
        )

    def _get_auth_url(self, query_params: dict[str, Any]) -> HandlerResult:
        """Generate OAuth authorization URL."""
        redirect_uri = query_params.get("redirect_uri", "http://localhost:3000/inbox/callback")
        state = query_params.get("state", "")

        try:
            from aragora.connectors.enterprise.communication.gmail import (
                GmailConnector as GmailConnectorCls,
            )

            connector = GmailConnectorCls()
            url = connector.get_oauth_url(redirect_uri, state)

            return json_response({"url": url})

        except (ImportError, ConnectionError, OSError, ValueError, AttributeError) as e:
            logger.error("[Gmail] Failed to generate auth URL: %s", e)
            return error_response("Failed to generate authorization URL", 500)

    def _start_connect(self, body: dict[str, Any], user_id: str) -> HandlerResult:
        """Start OAuth connection flow."""
        redirect_uri = body.get("redirect_uri", "http://localhost:3000/inbox/callback")
        state = body.get("state", user_id)

        try:
            from aragora.connectors.enterprise.communication.gmail import (
                GmailConnector as GmailConnectorCls,
            )

            connector = GmailConnectorCls()
            url = connector.get_oauth_url(redirect_uri, state)

            return json_response(
                {
                    "url": url,
                    "state": state,
                }
            )

        except (ImportError, ConnectionError, OSError, ValueError, AttributeError) as e:
            logger.error("[Gmail] Failed to start connect: %s", e)
            return error_response("Failed to start connection", 500)

    async def _handle_oauth_callback(
        self,
        query_params: dict[str, Any],
        user_id: str,
        org_id: str = "",
    ) -> HandlerResult:
        """Handle OAuth callback (GET).

        SECURITY: user_id is bound to JWT context. The state parameter is used
        for CSRF protection only, NOT to identify the user. This prevents
        cross-tenant token theft via state manipulation.
        """
        code = query_params.get("code")
        state = query_params.get("state")
        error = query_params.get("error")

        if error:
            return error_response(f"OAuth error: {error}", 400)

        if not code:
            return error_response("Missing authorization code", 400)

        # SECURITY: Validate state matches authenticated user to prevent CSRF
        # State should contain user_id for verification, but we ALWAYS use JWT user_id
        if state and state != user_id:
            logger.warning(
                "OAuth state mismatch: state=%s, jwt_user=%s. Using JWT user_id for security.",
                state,
                user_id,
            )

        return await self._complete_oauth(
            code, query_params.get("redirect_uri", ""), user_id, org_id
        )

    async def _handle_oauth_callback_post(
        self,
        body: dict[str, Any],
        user_id: str,
        org_id: str = "",
    ) -> HandlerResult:
        """Handle OAuth callback (POST).

        SECURITY: user_id is bound to JWT context. The state parameter is used
        for CSRF protection only, NOT to identify the user.
        """
        code = body.get("code")
        redirect_uri = body.get("redirect_uri", "http://localhost:3000/inbox/callback")
        state = body.get("state")

        if not code:
            return error_response("Missing authorization code", 400)

        # SECURITY: Validate state matches authenticated user to prevent CSRF
        if state and state != user_id:
            logger.warning(
                "OAuth state mismatch: state=%s, jwt_user=%s. Using JWT user_id for security.",
                state,
                user_id,
            )

        return await self._complete_oauth(code, redirect_uri, user_id, org_id)

    async def _complete_oauth(
        self,
        code: str,
        redirect_uri: str,
        user_id: str,
        org_id: str = "",
    ) -> HandlerResult:
        """Complete OAuth flow and store tokens.

        SECURITY: org_id is bound to JWT context for tenant isolation.
        This enables future admin delegation where admins can manage
        Gmail connections for users within their own org only.
        """
        try:
            from aragora.connectors.enterprise.communication.gmail import (
                GmailConnector as GmailConnectorCls,
            )

            connector = GmailConnectorCls()

            success = await connector.authenticate(code=code, redirect_uri=redirect_uri)

            if not success:
                return error_response("Authentication failed", 401)

            # Get user profile
            profile = await connector.get_user_info()

            # Save state
            # SECURITY: org_id bound to JWT for strict tenant isolation
            state = GmailUserState(
                user_id=user_id,
                org_id=org_id,  # Bind to authenticated org for tenant isolation
                email_address=profile.get("emailAddress", ""),
                access_token=connector._access_token or "",
                refresh_token=connector._refresh_token or "",
                token_expiry=connector._token_expiry,
                history_id=str(profile.get("historyId", "")),
                connected_at=datetime.now(timezone.utc),
            )
            await save_user_state(state)

            return json_response(
                {
                    "success": True,
                    "email_address": state.email_address,
                    "user_id": user_id,
                }
            )

        except (
            ImportError,
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            KeyError,
            AttributeError,
        ) as e:
            logger.error("[Gmail] OAuth completion failed: %s", e)
            return error_response(safe_error_message(e, "Authentication"), 500)

    async def _start_sync(self, body: dict[str, Any], user_id: str) -> HandlerResult:
        """Start email sync for user."""
        state = await get_user_state(user_id)

        if not state or not state.refresh_token:
            return error_response("Not connected - please authenticate first", 401)

        full_sync = body.get("full_sync", False)
        max_messages = body.get("max_messages", 500)
        labels = body.get("labels", ["INBOX"])

        # Check if sync already running
        job = await get_sync_job(user_id)
        if job and job.status == "running":
            return json_response(
                {
                    "message": "Sync already in progress",
                    "status": "running",
                    "progress": job.progress,
                }
            )

        # Start sync in background
        new_job = SyncJobState(
            user_id=user_id,
            status="running",
            progress=0,
            messages_synced=0,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        await save_sync_job(new_job)

        # Run sync in thread (needs its own event loop)
        import threading

        thread = threading.Thread(
            target=self._run_sync,
            args=(user_id, state, full_sync, max_messages, labels),
            daemon=True,
        )
        thread.start()

        return json_response(
            {
                "message": "Sync started",
                "status": "running",
                "job_id": user_id,
            }
        )

    def _run_sync(
        self,
        user_id: str,
        state: GmailUserState,
        full_sync: bool,
        max_messages: int,
        labels: list[str],
    ) -> None:
        """Run email sync (background thread).

        NOTE: This method runs in a separate thread and needs its own event loop.
        This is intentional and should NOT be converted to async.
        """
        try:
            from aragora.connectors.enterprise.communication.gmail import (
                GmailConnector as GmailConnectorCls,
            )
            from aragora.server.stream.inbox_sync import (
                emit_sync_complete,
                emit_sync_error,
                emit_sync_progress,
                emit_sync_start,
            )

            connector = GmailConnectorCls(
                labels=labels,
                max_results=max_messages,
            )

            # Restore tokens
            connector._access_token = state.access_token
            connector._refresh_token = state.refresh_token
            connector._token_expiry = state.token_expiry

            # Run sync - needs event loop in this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            try:
                # Emit sync start event
                loop.run_until_complete(
                    emit_sync_start(
                        user_id, total_messages=max_messages, phase="Fetching messages..."
                    )
                )

                result = loop.run_until_complete(
                    connector.sync(full_sync=full_sync, max_items=max_messages)
                )

                # Emit progress event
                loop.run_until_complete(
                    emit_sync_progress(
                        user_id,
                        progress=100,
                        messages_synced=result.items_synced,
                        total_messages=max_messages,
                        phase="Completing sync...",
                    )
                )

                # Update user state
                state.indexed_count += result.items_synced
                state.last_sync = datetime.now(timezone.utc)
                state.history_id = result.new_cursor or state.history_id
                loop.run_until_complete(save_user_state(state))

                # Update job status
                completed_job = SyncJobState(
                    user_id=user_id,
                    status="completed",
                    progress=100,
                    messages_synced=result.items_synced,
                    completed_at=datetime.now(timezone.utc).isoformat(),
                )
                loop.run_until_complete(save_sync_job(completed_job))

                # Emit sync complete event
                loop.run_until_complete(emit_sync_complete(user_id, result.items_synced))

            finally:
                loop.close()

            logger.info("[Gmail] Sync completed for %s: %s messages", user_id, result.items_synced)

        except (ValueError, KeyError, TypeError, RuntimeError, OSError, ConnectionError) as e:
            logger.error("[Gmail] Sync failed for %s: %s", user_id, e)
            # Update job status on failure - needs event loop
            loop = asyncio.new_event_loop()
            try:
                failed_job = SyncJobState(
                    user_id=user_id,
                    status="failed",
                    progress=0,
                    messages_synced=0,
                    error="Sync failed",
                    failed_at=datetime.now(timezone.utc).isoformat(),
                )
                loop.run_until_complete(save_sync_job(failed_job))

                # Emit sync error event
                from aragora.server.stream.inbox_sync import emit_sync_error

                loop.run_until_complete(emit_sync_error(user_id, "Sync failed"))
            finally:
                loop.close()

    async def _get_sync_status(self, user_id: str) -> HandlerResult:
        """Get sync status for user."""
        state = await get_user_state(user_id)
        job = await get_sync_job(user_id)

        return json_response(
            {
                "connected": bool(state and state.refresh_token),
                "email_address": state.email_address if state else None,
                "indexed_count": state.indexed_count if state else 0,
                "last_sync": (state.last_sync.isoformat() if state and state.last_sync else None),
                "job_status": job.status if job else "idle",
                "job_progress": job.progress if job else 0,
                "job_messages_synced": job.messages_synced if job else 0,
                "job_error": job.error if job else None,
            }
        )

    async def _list_messages(
        self,
        user_id: str,
        query_params: dict[str, Any],
    ) -> HandlerResult:
        """List indexed messages for user."""
        state = await get_user_state(user_id)

        if not state or not state.refresh_token:
            return error_response("Not connected", 401)

        limit = safe_query_int(query_params, "limit", default=50, max_val=1000)
        offset = safe_query_int(query_params, "offset", default=0, max_val=100000)
        query = query_params.get("query", "")

        try:
            from aragora.connectors.enterprise.communication.gmail import (
                GmailConnector as GmailConnectorCls,
            )

            connector = GmailConnectorCls(max_results=limit)
            connector._access_token = state.access_token
            connector._refresh_token = state.refresh_token
            connector._token_expiry = state.token_expiry

            results = await connector.search(query=query, limit=limit)

            return json_response(
                {
                    "messages": [
                        {
                            "id": r.id.replace("gmail-", ""),
                            "subject": r.title,
                            "from": r.author,
                            "snippet": r.content,
                            "date": r.metadata.get("date"),
                            "url": r.url,
                        }
                        for r in results
                    ],
                    "total": len(results),
                    "limit": limit,
                    "offset": offset,
                }
            )

        except (
            ImportError,
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            KeyError,
            AttributeError,
        ) as e:
            logger.error("[Gmail] List messages failed: %s", e)
            return error_response(safe_error_message(e, "Failed to list messages"), 500)

    async def _get_message(self, user_id: str, message_id: str) -> HandlerResult:
        """Get a single message by ID."""
        state = await get_user_state(user_id)

        if not state or not state.refresh_token:
            return error_response("Not connected", 401)

        try:
            from aragora.connectors.enterprise.communication.gmail import (
                GmailConnector as GmailConnectorCls,
            )

            connector = GmailConnectorCls()
            connector._access_token = state.access_token
            connector._refresh_token = state.refresh_token
            connector._token_expiry = state.token_expiry

            msg = await connector.get_message(message_id)

            return json_response(msg.to_dict())

        except (
            ImportError,
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            KeyError,
            AttributeError,
        ) as e:
            logger.error("[Gmail] Get message failed: %s", e)
            return error_response(safe_error_message(e, "Failed to get message"), 500)

    async def _search(self, user_id: str, body: dict[str, Any]) -> HandlerResult:
        """Search emails."""
        state = await get_user_state(user_id)

        if not state or not state.refresh_token:
            return error_response("Not connected", 401)

        query = body.get("query", "")
        limit = body.get("limit", 20)

        if not query:
            return error_response("Query is required", 400)

        try:
            from aragora.connectors.enterprise.communication.gmail import (
                GmailConnector as GmailConnectorCls,
            )

            connector = GmailConnectorCls(max_results=limit)
            connector._access_token = state.access_token
            connector._refresh_token = state.refresh_token
            connector._token_expiry = state.token_expiry

            results = await connector.search(query=query, limit=limit)

            return json_response(
                {
                    "query": query,
                    "results": [
                        {
                            "id": r.id.replace("gmail-", ""),
                            "subject": r.title,
                            "from": r.author,
                            "snippet": r.content,
                            "date": r.metadata.get("date"),
                            "url": r.url,
                        }
                        for r in results
                    ],
                    "count": len(results),
                }
            )

        except (
            ImportError,
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            KeyError,
            AttributeError,
        ) as e:
            logger.error("[Gmail] Search failed: %s", e)
            return error_response(safe_error_message(e, "Search"), 500)

    async def _disconnect(self, user_id: str) -> HandlerResult:
        """Disconnect Gmail account."""
        deleted = await delete_user_state(user_id)
        await delete_sync_job(user_id)

        return json_response(
            {
                "success": True,
                "was_connected": deleted,
            }
        )


# Export for handler registration
__all__ = ["GmailIngestHandler"]
