"""
Outlook/Microsoft 365 Enterprise Connector.

Provides full integration with Outlook/M365 mailboxes:
- OAuth2 authentication flow via MSAL
- Message and conversation fetching via Microsoft Graph API
- Folder management
- Incremental sync via Delta Query API
- Search with OData query syntax

Requires Azure AD app registration with Microsoft Graph scopes.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from collections.abc import AsyncIterator

from aragora.connectors.enterprise.base import (
    EnterpriseConnector,
    SyncItem,
    SyncState,
)
from aragora.reasoning.provenance import SourceType

from .models import (
    EmailAttachment,
    EmailMessage,
    EmailThread,
    OutlookFolder,
    OutlookSyncState,
)

logger = logging.getLogger(__name__)

_MAX_PAGES = 1000  # Safety cap for pagination loops

# Microsoft Graph API scopes
OUTLOOK_SCOPES_READONLY = [
    "https://graph.microsoft.com/Mail.Read",
    "https://graph.microsoft.com/User.Read",
]

# Full scopes including send
OUTLOOK_SCOPES_FULL = [
    "https://graph.microsoft.com/Mail.Read",
    "https://graph.microsoft.com/Mail.ReadWrite",
    "https://graph.microsoft.com/Mail.Send",
    "https://graph.microsoft.com/User.Read",
]

# Default to read-only for backward compatibility
OUTLOOK_SCOPES = OUTLOOK_SCOPES_READONLY


class OutlookConnector(EnterpriseConnector):
    """
    Enterprise connector for Outlook/Microsoft 365.

    Features:
    - OAuth2 authentication with MSAL
    - Full message content retrieval via Graph API
    - Conversation-based view
    - Folder filtering
    - Incremental sync via Delta Query API
    - OData search query support

    Authentication:
    - OAuth2 with refresh token (required)

    Usage:
        connector = OutlookConnector(
            folders=["Inbox", "Important"],
            max_results=100,
        )

        # Get OAuth URL for user authorization
        url = connector.get_oauth_url(redirect_uri, state)

        # After user authorizes, exchange code for tokens
        await connector.authenticate(code=auth_code, redirect_uri=redirect_uri)

        # Sync messages
        result = await connector.sync()
    """

    def __init__(
        self,
        folders: list[str] | None = None,
        exclude_folders: list[str] | None = None,
        max_results: int = 100,
        include_deleted: bool = False,
        user_id: str = "me",
        **kwargs: Any,
    ):
        """
        Initialize Outlook connector.

        Args:
            folders: Folders to sync (None = all)
            exclude_folders: Folders to exclude
            max_results: Max messages per sync batch
            include_deleted: Include deleted items folder
            user_id: User ID ("me" for authenticated user)
        """
        super().__init__(connector_id="outlook", **kwargs)

        self.folders = folders
        self.exclude_folders = set(exclude_folders or [])
        self.max_results = max_results
        self.include_deleted = include_deleted
        self.user_id = user_id

        # OAuth tokens (protected by _token_lock for thread-safety)
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._token_expiry: datetime | None = None
        self._token_lock: asyncio.Lock = asyncio.Lock()

        # Outlook-specific state
        self._outlook_state: OutlookSyncState | None = None

    @property
    def source_type(self) -> SourceType:
        return SourceType.DOCUMENT

    @property
    def name(self) -> str:
        return "Outlook"

    @property
    def access_token(self) -> str | None:
        """Expose current access token (if available)."""
        return self._access_token

    @property
    def refresh_token(self) -> str | None:
        """Expose current refresh token (if available)."""
        return self._refresh_token

    @property
    def token_expiry(self) -> datetime | None:
        """Expose access token expiry (if available)."""
        return self._token_expiry

    @property
    def is_configured(self) -> bool:
        """Check if connector has required configuration."""
        import os

        return bool(
            os.environ.get("OUTLOOK_CLIENT_ID")
            or os.environ.get("AZURE_CLIENT_ID")
            or os.environ.get("MICROSOFT_CLIENT_ID")
        )

    def get_oauth_url(self, redirect_uri: str, state: str = "") -> str:
        """
        Generate OAuth2 authorization URL.

        Args:
            redirect_uri: URL to redirect after authorization
            state: Optional state parameter for CSRF protection

        Returns:
            Authorization URL for user to visit
        """
        import os
        from urllib.parse import urlencode

        client_id = (
            os.environ.get("OUTLOOK_CLIENT_ID")
            or os.environ.get("AZURE_CLIENT_ID")
            or os.environ.get("MICROSOFT_CLIENT_ID", "")
        )

        tenant = os.environ.get("OUTLOOK_TENANT_ID", "common")

        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(OUTLOOK_SCOPES + ["offline_access"]),
            "response_mode": "query",
            "prompt": "consent",
        }

        if state:
            params["state"] = state

        return (
            f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize?{urlencode(params)}"
        )

    async def authenticate(
        self,
        code: str | None = None,
        redirect_uri: str | None = None,
        refresh_token: str | None = None,
    ) -> bool:
        """
        Authenticate with Microsoft Graph API.

        Either exchange authorization code for tokens, or use existing refresh token.

        Args:
            code: Authorization code from OAuth callback
            redirect_uri: Redirect URI used in authorization
            refresh_token: Existing refresh token

        Returns:
            True if authentication successful
        """
        import os

        from aragora.observability.http_client_pool import get_http_pool

        client_id = (
            os.environ.get("OUTLOOK_CLIENT_ID")
            or os.environ.get("AZURE_CLIENT_ID")
            or os.environ.get("MICROSOFT_CLIENT_ID", "")
        )
        client_secret = (
            os.environ.get("OUTLOOK_CLIENT_SECRET")
            or os.environ.get("AZURE_CLIENT_SECRET")
            or os.environ.get("MICROSOFT_CLIENT_SECRET", "")
        )

        tenant = os.environ.get("OUTLOOK_TENANT_ID", "common")

        if not client_id or not client_secret:
            logger.error("[Outlook] Missing OAuth credentials")
            return False

        token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

        try:
            pool = get_http_pool()
            async with pool.get_session("outlook") as client:
                if code and redirect_uri:
                    # Exchange code for tokens
                    response = await client.post(
                        token_url,
                        data={
                            "client_id": client_id,
                            "client_secret": client_secret,
                            "code": code,
                            "redirect_uri": redirect_uri,
                            "grant_type": "authorization_code",
                            "scope": " ".join(OUTLOOK_SCOPES + ["offline_access"]),
                        },
                    )
                elif refresh_token:
                    # Use refresh token
                    response = await client.post(
                        token_url,
                        data={
                            "client_id": client_id,
                            "client_secret": client_secret,
                            "refresh_token": refresh_token,
                            "grant_type": "refresh_token",
                            "scope": " ".join(OUTLOOK_SCOPES + ["offline_access"]),
                        },
                    )
                else:
                    logger.error("[Outlook] No code or refresh_token provided")
                    return False

                response.raise_for_status()
                data = response.json()

            self._access_token = data["access_token"]
            self._refresh_token = data.get("refresh_token", refresh_token)

            expires_in = data.get("expires_in", 3600)
            from datetime import timedelta

            self._token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)

            logger.info("[Outlook] Authentication successful")
            return True

        except (OSError, ConnectionError, TimeoutError, ValueError, KeyError, RuntimeError) as e:
            logger.error("[Outlook] Authentication failed: %s", e)
            return False

    async def _refresh_access_token(self) -> str:
        """Refresh the access token using refresh token."""
        import os

        from aragora.observability.http_client_pool import get_http_pool

        if not self._refresh_token:
            raise ValueError("No refresh token available")

        client_id = (
            os.environ.get("OUTLOOK_CLIENT_ID")
            or os.environ.get("AZURE_CLIENT_ID")
            or os.environ.get("MICROSOFT_CLIENT_ID", "")
        )
        client_secret = (
            os.environ.get("OUTLOOK_CLIENT_SECRET")
            or os.environ.get("AZURE_CLIENT_SECRET")
            or os.environ.get("MICROSOFT_CLIENT_SECRET", "")
        )

        tenant = os.environ.get("OUTLOOK_TENANT_ID", "common")
        token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

        pool = get_http_pool()
        async with pool.get_session("outlook") as client:
            response = await client.post(
                token_url,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": self._refresh_token,
                    "grant_type": "refresh_token",
                    "scope": " ".join(OUTLOOK_SCOPES + ["offline_access"]),
                },
            )
            response.raise_for_status()
            data = response.json()

        self._access_token = data["access_token"]
        self._refresh_token = data.get("refresh_token", self._refresh_token)

        expires_in = data.get("expires_in", 3600)
        from datetime import timedelta

        self._token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)

        return self._access_token

    async def _get_access_token(self) -> str:
        """Get valid access token, refreshing if needed.

        Thread-safe: Uses _token_lock to prevent concurrent refresh attempts.
        """
        async with self._token_lock:
            now = datetime.now(timezone.utc)

            if self._access_token and self._token_expiry and now < self._token_expiry:
                return self._access_token

            if self._refresh_token:
                return await self._refresh_access_token()

            raise ValueError("No valid access token and no refresh token available")

    async def _api_request(
        self,
        endpoint: str,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a request to Microsoft Graph API with circuit breaker protection."""
        import httpx

        from aragora.observability.http_client_pool import get_http_pool

        # Check circuit breaker first
        if not self.check_circuit_breaker():
            cb_status = self.get_circuit_breaker_status()
            raise ConnectionError(
                f"Circuit breaker open for Outlook. Cooldown: {cb_status.get('cooldown_seconds', 60)}s"
            )

        token = await self._get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        # Handle relative vs absolute URLs (for delta links)
        if endpoint.startswith("https://"):
            url = endpoint
        else:
            url = f"https://graph.microsoft.com/v1.0/{self.user_id}{endpoint}"

        try:
            pool = get_http_pool()
            async with pool.get_session("outlook") as client:
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json_data,
                    timeout=60,
                )
                if response.status_code >= 400:
                    # Log the full error response for debugging
                    logger.error("Outlook API error %s: %s", response.status_code, response.text)
                    # Record failure for circuit breaker on 5xx errors or rate limits
                    if response.status_code >= 500 or response.status_code == 429:
                        self.record_failure()
                response.raise_for_status()
                self.record_success()
                return response.json() if response.content else {}
        except httpx.TimeoutException as e:
            self.record_failure()
            logger.error("Outlook API timeout: %s", e)
            raise
        except httpx.HTTPStatusError:
            # Already handled above
            raise
        except (OSError, ConnectionError) as e:
            self.record_failure()
            logger.error("Outlook API error: %s", e)
            raise

    def _get_client(self) -> Any:
        """Get HTTP client context manager for API requests.

        Note: This method is deprecated. Use get_http_pool().get_session('outlook') instead.
        """
        import httpx

        return httpx.AsyncClient(timeout=60)

    async def get_user_info(self) -> dict[str, Any]:
        """Get authenticated user's profile."""
        return await self._api_request("/")

    async def list_folders(self) -> list[OutlookFolder]:
        """List all mail folders."""
        data = await self._api_request("/mailFolders", params={"$top": 100})

        folders = []
        for item in data.get("value", []):
            folders.append(
                OutlookFolder(
                    id=item["id"],
                    display_name=item.get("displayName", item["id"]),
                    parent_folder_id=item.get("parentFolderId"),
                    child_folder_count=item.get("childFolderCount", 0),
                    unread_item_count=item.get("unreadItemCount", 0),
                    total_item_count=item.get("totalItemCount", 0),
                    is_hidden=item.get("isHidden", False),
                )
            )

        return folders

    async def list_messages(
        self,
        folder_id: str | None = None,
        query: str = "",
        page_token: str | None = None,
        max_results: int = 100,
    ) -> tuple[list[str], str | None]:
        """
        List message IDs matching criteria.

        Args:
            folder_id: Filter by folder ID
            query: OData $filter query
            page_token: Pagination URL (next link)
            max_results: Max messages to return

        Returns:
            Tuple of (message_ids, next_page_url)
        """
        if page_token:
            # Use existing next link
            data = await self._api_request(page_token)
        else:
            params: dict[str, Any] = {
                "$top": min(max_results, 100),
                "$select": "id",
                "$orderby": "receivedDateTime desc",
            }

            if query:
                params["$filter"] = query

            endpoint = f"/mailFolders/{folder_id}/messages" if folder_id else "/messages"
            data = await self._api_request(endpoint, params=params)

        message_ids = [m["id"] for m in data.get("value", [])]
        next_link = data.get("@odata.nextLink")

        return message_ids, next_link

    async def get_message(
        self,
        message_id: str,
        include_body: bool = True,
    ) -> EmailMessage:
        """
        Get a single message by ID.

        Args:
            message_id: Message ID
            include_body: Whether to include full body content

        Returns:
            EmailMessage object
        """
        select_fields = [
            "id",
            "conversationId",
            "subject",
            "from",
            "toRecipients",
            "ccRecipients",
            "bccRecipients",
            "receivedDateTime",
            "bodyPreview",
            "isRead",
            "flag",
            "importance",
            "hasAttachments",
            "internetMessageHeaders",
            "parentFolderId",
        ]

        if include_body:
            select_fields.append("body")

        params = {"$select": ",".join(select_fields)}
        data = await self._api_request(f"/messages/{message_id}", params=params)

        return self._parse_message(data)

    def _parse_message(self, data: dict[str, Any]) -> EmailMessage:
        """Parse Microsoft Graph message response into EmailMessage."""
        # Parse from address
        from_data = data.get("from", {}).get("emailAddress", {})
        from_addr = from_data.get("address", "")

        # Parse recipient lists
        to_addrs = [
            r.get("emailAddress", {}).get("address", "") for r in data.get("toRecipients", [])
        ]
        cc_addrs = [
            r.get("emailAddress", {}).get("address", "") for r in data.get("ccRecipients", [])
        ]
        bcc_addrs = [
            r.get("emailAddress", {}).get("address", "") for r in data.get("bccRecipients", [])
        ]

        # Parse date
        date_str = data.get("receivedDateTime", "")
        try:
            date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            logger.debug("Failed to parse date string '%s'", date_str)
            date = datetime.now(timezone.utc)

        # Extract body
        body_data = data.get("body", {})
        body_text = ""
        body_html = ""

        if body_data.get("contentType") == "text":
            body_text = body_data.get("content", "")
        elif body_data.get("contentType") == "html":
            body_html = body_data.get("content", "")

        # Extract headers into dict
        headers = {}
        for header in data.get("internetMessageHeaders", []):
            name = header.get("name", "").lower()
            value = header.get("value", "")
            headers[name] = value

        # Labels/folders - use parent folder ID
        labels = []
        if data.get("parentFolderId"):
            labels.append(data["parentFolderId"])

        # Flags
        is_read = data.get("isRead", False)
        is_starred = data.get("flag", {}).get("flagStatus") == "flagged"
        is_important = data.get("importance") == "high"

        return EmailMessage(
            id=data["id"],
            thread_id=data.get("conversationId", data["id"]),
            subject=data.get("subject", "(No Subject)"),
            from_address=from_addr,
            to_addresses=[a for a in to_addrs if a],
            cc_addresses=[a for a in cc_addrs if a],
            bcc_addresses=[a for a in bcc_addrs if a],
            date=date,
            body_text=body_text,
            body_html=body_html,
            snippet=data.get("bodyPreview", ""),
            labels=labels,
            headers=headers,
            attachments=[],  # Loaded on demand
            is_read=is_read,
            is_starred=is_starred,
            is_important=is_important,
        )

    async def get_message_attachments(self, message_id: str) -> list[EmailAttachment]:
        """Get attachments for a message."""
        data = await self._api_request(f"/messages/{message_id}/attachments")

        attachments = []
        for item in data.get("value", []):
            attachments.append(
                EmailAttachment(
                    id=item["id"],
                    filename=item.get("name", "attachment"),
                    mime_type=item.get("contentType", "application/octet-stream"),
                    size=item.get("size", 0),
                )
            )

        return attachments

    async def get_conversation(self, conversation_id: str, max_messages: int = 50) -> EmailThread:
        """Get a conversation thread with all messages."""
        params = {
            "$filter": f"conversationId eq '{conversation_id}'",
            "$top": max_messages,
            "$orderby": "receivedDateTime asc",
        }
        data = await self._api_request("/messages", params=params)

        messages = [self._parse_message(m) for m in data.get("value", [])]

        # Collect participants
        participants = set()
        for msg in messages:
            participants.add(msg.from_address)
            participants.update(msg.to_addresses)
            participants.update(msg.cc_addresses)

        # Get thread subject from first message
        subject = messages[0].subject if messages else ""

        return EmailThread(
            id=conversation_id,
            subject=subject,
            messages=messages,
            participants=list(participants),
            labels=list(set(label for msg in messages for label in msg.labels)),
            last_message_date=messages[-1].date if messages else None,
            snippet=messages[-1].snippet if messages else "",
            message_count=len(messages),
        )

    async def get_delta(
        self,
        delta_link: str | None = None,
        folder_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None, str | None]:
        """
        Get message changes using Delta Query API.

        Args:
            delta_link: Previous delta link for incremental sync
            folder_id: Folder to track (if starting fresh)

        Returns:
            Tuple of (changes, next_link, new_delta_link)
        """
        if delta_link:
            # Continue from previous delta
            data = await self._api_request(delta_link)
        else:
            # Start new delta tracking
            endpoint = (
                f"/mailFolders/{folder_id}/messages/delta" if folder_id else "/messages/delta"
            )
            params = {"$select": "id,receivedDateTime"}
            data = await self._api_request(endpoint, params=params)

        changes = data.get("value", [])
        next_link = data.get("@odata.nextLink")
        new_delta_link = data.get("@odata.deltaLink")

        return changes, next_link, new_delta_link

    async def search(
        self,
        query: str,
        limit: int = 10,
        **kwargs: Any,
    ) -> list[Any]:
        """Search Outlook messages."""
        from aragora.connectors.base import Evidence

        # Use OData $search for free-text search
        params = {
            "$search": f'"{query}"',
            "$top": limit,
            "$select": "id,subject,from,bodyPreview,receivedDateTime,parentFolderId",
        }
        data = await self._api_request("/messages", params=params)

        results = []
        for item in data.get("value", []):
            from_data = item.get("from", {}).get("emailAddress", {})

            results.append(
                Evidence(
                    id=f"outlook-{item['id']}",
                    source_type=self.source_type,
                    source_id=item["id"],
                    content=item.get("bodyPreview", ""),
                    title=item.get("subject", "(No Subject)"),
                    url=f"https://outlook.office.com/mail/inbox/id/{item['id']}",
                    author=from_data.get("address", ""),
                    confidence=0.8,
                    metadata={
                        "received_at": item.get("receivedDateTime"),
                        "folder_id": item.get("parentFolderId"),
                    },
                )
            )

        return results

    async def fetch(self, evidence_id: str) -> Any | None:
        """Fetch a specific email by ID."""
        from aragora.connectors.base import Evidence

        # Extract message ID
        if evidence_id.startswith("outlook-"):
            message_id = evidence_id[8:]
        else:
            message_id = evidence_id

        try:
            msg = await self.get_message(message_id)

            return Evidence(
                id=f"outlook-{msg.id}",
                source_type=self.source_type,
                source_id=msg.id,
                content=msg.body_text or msg.snippet,
                title=msg.subject,
                url=f"https://outlook.office.com/mail/inbox/id/{msg.id}",
                author=msg.from_address,
                confidence=0.85,
                metadata={
                    "thread_id": msg.thread_id,
                    "date": msg.date.isoformat() if msg.date else None,
                    "folder_id": msg.labels[0] if msg.labels else None,
                    "to": msg.to_addresses,
                    "cc": msg.cc_addresses,
                    "is_read": msg.is_read,
                    "is_starred": msg.is_starred,
                },
            )

        except (OSError, ConnectionError, TimeoutError, ValueError, KeyError, RuntimeError) as e:
            logger.error("[Outlook] Fetch failed: %s", e)
            return None

    async def sync_items(
        self,
        state: SyncState,
        batch_size: int = 100,
    ) -> AsyncIterator[SyncItem]:
        """
        Yield Outlook messages for syncing.

        Uses Delta Query API for incremental sync when cursor is available.
        """
        items_yielded = 0

        # Check for incremental sync via delta link
        if state.cursor:
            logger.info("[Outlook] Starting incremental sync with delta link...")

            delta_link = state.cursor
            new_message_ids = set()

            while delta_link:
                changes, next_link, new_delta_link = await self.get_delta(delta_link=delta_link)

                if not changes and not next_link:
                    # No changes
                    if new_delta_link:
                        state.cursor = new_delta_link
                    return

                # Collect changed message IDs
                for change in changes:
                    # Check if deleted
                    if change.get("@removed"):
                        continue
                    new_message_ids.add(change["id"])

                if next_link:
                    delta_link = next_link
                else:
                    if new_delta_link:
                        state.cursor = new_delta_link
                    break

            # Fetch and yield changed messages
            for msg_id in new_message_ids:
                try:
                    msg = await self.get_message(msg_id)

                    # Skip excluded folders
                    if self.exclude_folders and any(
                        folder in self.exclude_folders for folder in msg.labels
                    ):
                        continue

                    yield self._message_to_sync_item(msg)
                    items_yielded += 1

                    if items_yielded >= batch_size:
                        await asyncio.sleep(0)

                except (OSError, ValueError, KeyError, RuntimeError) as e:
                    logger.warning("[Outlook] Failed to fetch message %s: %s", msg_id, e)

            return

        # Full sync
        logger.info("[Outlook] Starting full sync...")

        # Get folders to sync
        folders_to_sync = []
        if self.folders:
            all_folders = await self.list_folders()
            folders_to_sync = [
                f
                for f in all_folders
                if f.display_name in self.folders and f.display_name not in self.exclude_folders
            ]
        else:
            # Sync Inbox by default
            all_folders = await self.list_folders()
            folders_to_sync = [f for f in all_folders if f.display_name == "Inbox"]

        # Get delta link for future incremental syncs
        if folders_to_sync:
            _, _, delta_link = await self.get_delta(folder_id=folders_to_sync[0].id)
            if delta_link:
                state.cursor = delta_link

        # Iterate through folders
        for folder in folders_to_sync:
            if not self.include_deleted and folder.display_name == "Deleted Items":
                continue

            page_token = None
            for _page in range(_MAX_PAGES):
                message_ids, page_token = await self.list_messages(
                    folder_id=folder.id,
                    max_results=min(self.max_results, batch_size),
                    page_token=page_token,
                )

                for msg_id in message_ids:
                    try:
                        msg = await self.get_message(msg_id)

                        yield self._message_to_sync_item(msg)
                        items_yielded += 1

                        if items_yielded >= batch_size:
                            await asyncio.sleep(0)

                        if items_yielded >= self.max_results:
                            return

                    except (OSError, ValueError, KeyError, RuntimeError) as e:
                        logger.warning("[Outlook] Failed to fetch message %s: %s", msg_id, e)

                if not page_token:
                    break

    async def send_message(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        reply_to: str | None = None,
        html_body: str | None = None,
    ) -> dict[str, Any]:
        """
        Send an email message.

        Requires Mail.Send scope to be authorized.

        Args:
            to: List of recipient email addresses
            subject: Email subject line
            body: Plain text body
            cc: Optional CC recipients
            bcc: Optional BCC recipients
            reply_to: Optional reply-to address
            html_body: Optional HTML body

        Returns:
            Dict with message_id of sent message
        """
        # Build message
        message = {
            "subject": subject,
            "body": {
                "contentType": "html" if html_body else "text",
                "content": html_body or body,
            },
            "toRecipients": [{"emailAddress": {"address": addr}} for addr in to],
        }

        if cc:
            message["ccRecipients"] = [{"emailAddress": {"address": addr}} for addr in cc]
        if bcc:
            message["bccRecipients"] = [{"emailAddress": {"address": addr}} for addr in bcc]
        if reply_to:
            message["replyTo"] = [{"emailAddress": {"address": reply_to}}]

        # Check circuit breaker first
        if not self.check_circuit_breaker():
            cb_status = self.get_circuit_breaker_status()
            raise ConnectionError(
                f"Circuit breaker open for Outlook. Cooldown: {cb_status.get('cooldown_seconds', 60)}s"
            )

        # Send via Graph API
        try:
            await self._api_request(
                "/sendMail",
                method="POST",
                json_data={"message": message, "saveToSentItems": True},
            )

            logger.info("[Outlook] Message sent successfully")

            return {
                "success": True,
                "message": "Message sent",
            }
        except (OSError, ConnectionError, TimeoutError, ValueError, KeyError) as e:
            raise RuntimeError(f"Failed to send email: {e}") from e

    async def reply_to_message(
        self,
        original_message_id: str,
        body: str,
        cc: list[str] | None = None,
        html_body: str | None = None,
        reply_all: bool = False,
    ) -> dict[str, Any]:
        """
        Reply to an existing email message.

        Args:
            original_message_id: Message ID to reply to
            body: Reply body text
            cc: Optional additional CC recipients
            html_body: Optional HTML body
            reply_all: If True, reply to all recipients

        Returns:
            Dict with success status
        """
        # Build reply
        comment = html_body or body

        # Check circuit breaker first
        if not self.check_circuit_breaker():
            cb_status = self.get_circuit_breaker_status()
            raise ConnectionError(
                f"Circuit breaker open for Outlook. Cooldown: {cb_status.get('cooldown_seconds', 60)}s"
            )

        # Use appropriate endpoint
        endpoint = (
            f"/messages/{original_message_id}/replyAll"
            if reply_all
            else f"/messages/{original_message_id}/reply"
        )

        try:
            await self._api_request(
                endpoint,
                method="POST",
                json_data={"comment": comment},
            )

            logger.info("[Outlook] Sent reply to message %s", original_message_id)

            return {
                "success": True,
                "in_reply_to": original_message_id,
            }
        except (OSError, ConnectionError, TimeoutError, ValueError, KeyError) as e:
            raise RuntimeError(f"Failed to send reply: {e}") from e

    def _message_to_sync_item(self, msg: EmailMessage) -> SyncItem:
        """Convert EmailMessage to SyncItem for Knowledge Mound ingestion."""
        # Build content with context
        content_parts = [
            f"Subject: {msg.subject}",
            f"From: {msg.from_address}",
            f"To: {', '.join(msg.to_addresses)}",
            f"Date: {msg.date.isoformat() if msg.date else 'Unknown'}",
            "",
            msg.body_text or msg.snippet,
        ]

        if msg.cc_addresses:
            content_parts.insert(3, f"CC: {', '.join(msg.cc_addresses)}")

        return SyncItem(
            id=f"outlook-{msg.id}",
            content="\n".join(content_parts)[:50000],
            source_type="email",
            source_id=f"outlook/{msg.id}",
            title=msg.subject,
            url=f"https://outlook.office.com/mail/inbox/id/{msg.id}",
            author=msg.from_address,
            created_at=msg.date,
            updated_at=msg.date,
            domain="enterprise/outlook",
            confidence=0.85,
            metadata={
                "message_id": msg.id,
                "conversation_id": msg.thread_id,
                "folder_id": msg.labels[0] if msg.labels else None,
                "to_addresses": msg.to_addresses,
                "cc_addresses": msg.cc_addresses,
                "is_read": msg.is_read,
                "is_starred": msg.is_starred,
                "is_important": msg.is_important,
                "has_attachments": len(msg.attachments) > 0,
            },
        )


__all__ = [
    "OutlookConnector",
    "OutlookFolder",
    "OutlookSyncState",
    "OUTLOOK_SCOPES",
    "OUTLOOK_SCOPES_READONLY",
    "OUTLOOK_SCOPES_FULL",
]
