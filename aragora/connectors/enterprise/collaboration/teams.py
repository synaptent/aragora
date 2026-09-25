"""
Microsoft Teams Enterprise Connector.

Provides full integration with Microsoft Teams via Graph API:
- Team and channel enumeration
- Channel message history extraction
- File content from SharePoint-backed storage
- Meeting transcripts and recordings
- Incremental sync via delta queries

Requires Microsoft Graph API credentials with Teams permissions.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any
from collections.abc import AsyncIterator

from aragora.connectors.enterprise.base import (
    EnterpriseConnector,
    SyncItem,
    SyncState,
)
from aragora.reasoning.provenance import SourceType

import httpx

logger = logging.getLogger(__name__)

_MAX_PAGES = 1000  # Safety cap for pagination loops


@dataclass
class TeamsTeam:
    """A Microsoft Teams team."""

    id: str
    display_name: str
    description: str = ""
    visibility: str = "private"
    created_at: datetime | None = None
    web_url: str = ""


@dataclass
class TeamsChannel:
    """A Microsoft Teams channel."""

    id: str
    team_id: str
    display_name: str
    description: str = ""
    membership_type: str = "standard"
    created_at: datetime | None = None
    web_url: str = ""


@dataclass
class TeamsMessage:
    """A Microsoft Teams message."""

    id: str
    team_id: str
    channel_id: str
    content: str
    content_type: str = "text"
    sender_name: str = ""
    sender_email: str = ""
    created_at: datetime | None = None
    last_modified: datetime | None = None
    reply_to_id: str | None = None
    attachments: list[dict[str, Any]] = field(default_factory=list)
    reactions: list[dict[str, Any]] = field(default_factory=list)
    web_url: str = ""


@dataclass
class TeamsFile:
    """A file in Teams/SharePoint."""

    id: str
    name: str
    size: int
    mime_type: str = ""
    created_at: datetime | None = None
    modified_at: datetime | None = None
    download_url: str = ""
    web_url: str = ""


class TeamsEnterpriseConnector(EnterpriseConnector):
    """
    Enterprise connector for Microsoft Teams content syncing.

    Features:
    - Team and channel discovery
    - Full message history extraction
    - Reply thread support
    - File and attachment access via SharePoint
    - Meeting recordings and transcripts
    - Incremental sync via delta tokens
    - Pagination for large channels

    Authentication:
    - OAuth2: Client credentials flow (app-only)
    - Delegated: User consent with refresh token

    Permissions Required:
    - Team.ReadBasic.All
    - Channel.ReadBasic.All
    - ChannelMessage.Read.All
    - Files.Read.All
    - OnlineMeetingTranscript.Read.All (optional)

    Usage:
        connector = TeamsEnterpriseConnector(
            team_ids=["team-id-1", "team-id-2"],  # Optional: specific teams
            include_files=True,
            include_replies=True,
        )
        result = await connector.sync()
    """

    # Microsoft Graph API endpoints
    GRAPH_BASE = "https://graph.microsoft.com/v1.0"
    GRAPH_BETA = "https://graph.microsoft.com/beta"
    TOKEN_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"  # noqa: S105 -- OAuth endpoint URL

    def __init__(
        self,
        team_ids: list[str] | None = None,
        channel_ids: list[str] | None = None,
        include_files: bool = True,
        include_replies: bool = True,
        include_reactions: bool = False,
        include_private_channels: bool = False,
        exclude_system_messages: bool = True,
        messages_per_channel: int = 1000,
        use_delta_sync: bool = True,
        tenant_id: str | None = None,
        **kwargs: Any,
    ):
        """
        Initialize Teams enterprise connector.

        Args:
            team_ids: Specific team IDs to sync (syncs all if not specified)
            channel_ids: Specific channel IDs to sync
            include_files: Include files from channel file tabs
            include_replies: Include reply messages in threads
            include_reactions: Include message reactions
            include_private_channels: Include private channels (requires elevated permissions)
            exclude_system_messages: Skip system/event messages
            messages_per_channel: Maximum messages to sync per channel
            use_delta_sync: Use delta queries for incremental sync
            tenant_id: Azure AD tenant ID
        """
        super().__init__(connector_id="teams-enterprise", **kwargs)

        self.team_ids = team_ids or []
        self.channel_ids = channel_ids or []
        self.include_files = include_files
        self.include_replies = include_replies
        self.include_reactions = include_reactions
        self.include_private_channels = include_private_channels
        self.exclude_system_messages = exclude_system_messages
        self.messages_per_channel = messages_per_channel
        self.use_delta_sync = use_delta_sync
        self.tenant_id = tenant_id

        self._access_token: str | None = None
        self._token_expiry: datetime | None = None
        self._delta_links: dict[str, str] = {}

    @property
    def source_type(self) -> SourceType:
        return SourceType.EXTERNAL_API

    @property
    def name(self) -> str:
        return "Microsoft Teams"

    async def _get_access_token(self) -> str:
        """Get valid access token, refreshing if needed."""
        import httpx

        now = datetime.now(timezone.utc)

        if self._access_token and self._token_expiry and now < self._token_expiry:
            return self._access_token

        # Get credentials
        tenant_id = self.tenant_id or await self.credentials.get_credential("TEAMS_TENANT_ID")
        client_id = await self.credentials.get_credential("TEAMS_CLIENT_ID")
        client_secret = await self.credentials.get_credential("TEAMS_CLIENT_SECRET")

        if not all([tenant_id, client_id, client_secret]):
            raise ValueError(
                "Teams credentials not configured. "
                "Set TEAMS_TENANT_ID, TEAMS_CLIENT_ID, and TEAMS_CLIENT_SECRET"
            )

        token_url = self.TOKEN_URL.format(tenant_id=tenant_id)

        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "scope": "https://graph.microsoft.com/.default",
                },
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()

        self._access_token = data["access_token"]
        expires_in = data.get("expires_in", 3600)
        self._token_expiry = now + timedelta(seconds=expires_in - 60)

        return self._access_token

    async def _api_request(
        self,
        endpoint: str,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        use_beta: bool = False,
    ) -> dict[str, Any]:
        """Make a request to Microsoft Graph API."""
        from aragora.observability.http_client_pool import get_http_pool

        token = await self._get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        base = self.GRAPH_BETA if use_beta else self.GRAPH_BASE
        url = f"{base}{endpoint}"

        pool = get_http_pool()
        async with pool.get_session("teams") as client:
            response = await client.request(
                method,
                url,
                headers=headers,
                params=params,
                timeout=60,
            )
            response.raise_for_status()
            return response.json() if response.content else {}

    async def _paginate(
        self,
        endpoint: str,
        key: str = "value",
        max_items: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Paginate through Graph API results."""
        from aragora.observability.http_client_pool import get_http_pool

        items_yielded = 0
        next_link = None

        for _page in range(_MAX_PAGES):
            if next_link:
                # Use full URL for pagination
                token = await self._get_access_token()
                pool = get_http_pool()
                async with pool.get_session("teams") as client:
                    response = await client.get(
                        next_link,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Accept": "application/json",
                        },
                        timeout=60,
                    )
                    response.raise_for_status()
                    data = response.json()
            else:
                data = await self._api_request(endpoint)

            for item in data.get(key, []):
                yield item
                items_yielded += 1
                if max_items and items_yielded >= max_items:
                    return

            next_link = data.get("@odata.nextLink")
            if not next_link:
                break
        else:
            logger.warning("Pagination safety cap reached for Teams Graph API")

    async def _list_teams(self) -> AsyncIterator[TeamsTeam]:
        """List all teams the app has access to."""
        if self.team_ids:
            # Fetch specific teams
            for team_id in self.team_ids:
                try:
                    data = await self._api_request(f"/teams/{team_id}")
                    yield TeamsTeam(
                        id=data["id"],
                        display_name=data.get("displayName", ""),
                        description=data.get("description", ""),
                        visibility=data.get("visibility", "private"),
                        web_url=data.get("webUrl", ""),
                    )
                except (
                    httpx.HTTPStatusError,
                    httpx.TimeoutException,
                    httpx.ConnectError,
                    KeyError,
                    ValueError,
                    OSError,
                ) as e:
                    logger.warning("[%s] Failed to fetch team %s: %s", self.name, team_id, e)
        else:
            # List all teams
            async for team in self._paginate("/teams"):
                yield TeamsTeam(
                    id=team["id"],
                    display_name=team.get("displayName", ""),
                    description=team.get("description", ""),
                    visibility=team.get("visibility", "private"),
                    web_url=team.get("webUrl", ""),
                )

    async def _list_channels(self, team_id: str) -> AsyncIterator[TeamsChannel]:
        """List channels in a team."""
        endpoint = f"/teams/{team_id}/channels"
        if self.include_private_channels:
            endpoint += "?$filter=membershipType eq 'standard' or membershipType eq 'private'"

        async for channel in self._paginate(endpoint):
            membership_type = channel.get("membershipType", "standard")
            if not self.include_private_channels and membership_type == "private":
                continue

            yield TeamsChannel(
                id=channel["id"],
                team_id=team_id,
                display_name=channel.get("displayName", ""),
                description=channel.get("description", ""),
                membership_type=membership_type,
                web_url=channel.get("webUrl", ""),
            )

    async def _get_channel_messages(
        self,
        team_id: str,
        channel_id: str,
        since: datetime | None = None,
    ) -> AsyncIterator[TeamsMessage]:
        """Get messages from a channel."""
        endpoint = f"/teams/{team_id}/channels/{channel_id}/messages"

        # Add filter for incremental sync
        params = {}
        if since:
            iso_time = since.strftime("%Y-%m-%dT%H:%M:%SZ")
            params["$filter"] = f"lastModifiedDateTime gt {iso_time}"

        messages_count = 0
        async for msg in self._paginate(endpoint, max_items=self.messages_per_channel):
            # Skip system messages if configured
            msg_type = msg.get("messageType", "message")
            if self.exclude_system_messages and msg_type != "message":
                continue

            # Parse sender info
            sender = msg.get("from", {})
            user = sender.get("user", {})
            sender_name = user.get("displayName", "")
            sender_email = user.get("email", "")

            # Parse timestamps
            created = self._parse_datetime(msg.get("createdDateTime"))
            modified = self._parse_datetime(msg.get("lastModifiedDateTime"))

            # Parse body content
            body = msg.get("body", {})
            content = body.get("content", "")
            content_type = body.get("contentType", "text")

            # Strip HTML if needed
            if content_type == "html":
                content = self._strip_html(content)

            message = TeamsMessage(
                id=msg["id"],
                team_id=team_id,
                channel_id=channel_id,
                content=content,
                content_type=content_type,
                sender_name=sender_name,
                sender_email=sender_email,
                created_at=created,
                last_modified=modified,
                attachments=msg.get("attachments", []),
                reactions=msg.get("reactions", []) if self.include_reactions else [],
                web_url=msg.get("webUrl", ""),
            )

            yield message
            messages_count += 1

            # Get replies if configured
            if self.include_replies:
                async for reply in self._get_message_replies(team_id, channel_id, msg["id"]):
                    yield reply
                    messages_count += 1
                    if messages_count >= self.messages_per_channel:
                        return

    async def _get_message_replies(
        self,
        team_id: str,
        channel_id: str,
        message_id: str,
    ) -> AsyncIterator[TeamsMessage]:
        """Get replies to a message."""
        endpoint = f"/teams/{team_id}/channels/{channel_id}/messages/{message_id}/replies"

        try:
            async for reply in self._paginate(endpoint, max_items=100):
                sender = reply.get("from", {})
                user = sender.get("user", {})

                body = reply.get("body", {})
                content = body.get("content", "")
                if body.get("contentType") == "html":
                    content = self._strip_html(content)

                yield TeamsMessage(
                    id=reply["id"],
                    team_id=team_id,
                    channel_id=channel_id,
                    content=content,
                    content_type=body.get("contentType", "text"),
                    sender_name=user.get("displayName", ""),
                    sender_email=user.get("email", ""),
                    created_at=self._parse_datetime(reply.get("createdDateTime")),
                    last_modified=self._parse_datetime(reply.get("lastModifiedDateTime")),
                    reply_to_id=message_id,
                    attachments=reply.get("attachments", []),
                    web_url=reply.get("webUrl", ""),
                )
        except (
            httpx.HTTPStatusError,
            httpx.TimeoutException,
            httpx.ConnectError,
            KeyError,
            OSError,
        ) as e:
            logger.debug("[%s] Failed to get replies for %s: %s", self.name, message_id, e)

    async def _get_channel_files(
        self,
        team_id: str,
        channel_id: str,
    ) -> AsyncIterator[TeamsFile]:
        """Get files from a channel's file tab (SharePoint)."""
        endpoint = f"/teams/{team_id}/channels/{channel_id}/filesFolder"

        try:
            folder = await self._api_request(endpoint)
            drive_id = folder.get("parentReference", {}).get("driveId")
            folder_id = folder.get("id")

            if drive_id and folder_id:
                files_endpoint = f"/drives/{drive_id}/items/{folder_id}/children"
                async for item in self._paginate(files_endpoint):
                    if "file" in item:  # Skip folders
                        yield TeamsFile(
                            id=item["id"],
                            name=item.get("name", ""),
                            size=item.get("size", 0),
                            mime_type=item.get("file", {}).get("mimeType", ""),
                            created_at=self._parse_datetime(item.get("createdDateTime")),
                            modified_at=self._parse_datetime(item.get("lastModifiedDateTime")),
                            download_url=item.get("@microsoft.graph.downloadUrl", ""),
                            web_url=item.get("webUrl", ""),
                        )
        except (
            httpx.HTTPStatusError,
            httpx.TimeoutException,
            httpx.ConnectError,
            KeyError,
            OSError,
        ) as e:
            logger.warning("[%s] Failed to get files for channel %s: %s", self.name, channel_id, e)

    def _parse_datetime(self, value: str | None) -> datetime | None:
        """Parse Microsoft Graph datetime string."""
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _strip_html(self, html: str) -> str:
        """Strip HTML tags from content."""
        import re

        # Remove HTML tags
        text = re.sub(r"<[^>]+>", " ", html)
        # Decode common HTML entities
        text = text.replace("&nbsp;", " ")
        text = text.replace("&lt;", "<")
        text = text.replace("&gt;", ">")
        text = text.replace("&amp;", "&")
        text = text.replace("&quot;", '"')
        # Normalize whitespace
        text = " ".join(text.split())
        return text.strip()

    def _message_to_text(
        self,
        message: TeamsMessage,
        team_name: str,
        channel_name: str,
    ) -> str:
        """Convert a message to text representation."""
        lines = []

        # Header
        timestamp = (
            message.created_at.strftime("%Y-%m-%d %H:%M") if message.created_at else "Unknown"
        )
        lines.append(f"[{timestamp}] {message.sender_name}:")
        lines.append("")
        lines.append(message.content)

        if message.attachments:
            lines.append("")
            lines.append(f"Attachments: {len(message.attachments)}")

        return "\n".join(lines)

    async def sync_items(
        self,
        state: SyncState,
        batch_size: int = 100,
    ) -> AsyncIterator[SyncItem]:
        """
        Yield Teams messages and files for syncing.

        Syncs all accessible teams and channels with incremental support.
        """
        items_yielded = 0

        # Parse last sync time from cursor
        last_sync = None
        if state.cursor:
            try:
                last_sync = datetime.fromisoformat(state.cursor)
            except ValueError as e:
                logger.debug("Failed to parse datetime value: %s", e)

        async for team in self._list_teams():
            logger.info("[%s] Syncing team: %s", self.name, team.display_name)

            async for channel in self._list_channels(team.id):
                logger.debug("[%s] Syncing channel: %s", self.name, channel.display_name)

                # Sync messages
                try:
                    async for message in self._get_channel_messages(
                        team.id, channel.id, since=last_sync
                    ):
                        yield SyncItem(
                            id=f"teams-msg-{message.id}",
                            content=self._message_to_text(
                                message, team.display_name, channel.display_name
                            )[:50000],
                            source_type="message",
                            source_id=f"teams/{team.id}/{channel.id}/{message.id}",
                            title=f"{team.display_name} / {channel.display_name}",
                            url=message.web_url,
                            author=message.sender_name,
                            created_at=message.created_at,
                            updated_at=message.last_modified,
                            domain="enterprise/teams",
                            confidence=0.9,
                            metadata={
                                "team_id": team.id,
                                "team_name": team.display_name,
                                "channel_id": channel.id,
                                "channel_name": channel.display_name,
                                "message_type": "reply" if message.reply_to_id else "message",
                                "reply_to": message.reply_to_id,
                                "has_attachments": len(message.attachments) > 0,
                            },
                        )

                        items_yielded += 1
                        if items_yielded % batch_size == 0:
                            await asyncio.sleep(0)

                except (
                    httpx.HTTPStatusError,
                    httpx.TimeoutException,
                    httpx.ConnectError,
                    KeyError,
                    ValueError,
                    OSError,
                ) as e:
                    logger.error(
                        "[%s] Failed to sync messages for %s: %s",
                        self.name,
                        channel.display_name,
                        e,
                    )

                # Sync files if configured
                if self.include_files:
                    try:
                        async for file in self._get_channel_files(team.id, channel.id):
                            yield SyncItem(
                                id=f"teams-file-{file.id}",
                                content=f"# {file.name}\n\nFile in {team.display_name} / {channel.display_name}",
                                source_type="document",
                                source_id=f"teams/files/{file.id}",
                                title=file.name,
                                url=file.web_url,
                                created_at=file.created_at,
                                updated_at=file.modified_at,
                                domain="enterprise/teams/files",
                                confidence=0.85,
                                metadata={
                                    "team_id": team.id,
                                    "channel_id": channel.id,
                                    "file_name": file.name,
                                    "mime_type": file.mime_type,
                                    "size": file.size,
                                    "download_url": file.download_url,
                                },
                            )

                            items_yielded += 1

                    except (
                        httpx.HTTPStatusError,
                        httpx.TimeoutException,
                        httpx.ConnectError,
                        KeyError,
                        OSError,
                    ) as e:
                        logger.error(
                            "[%s] Failed to sync files for %s: %s",
                            self.name,
                            channel.display_name,
                            e,
                        )

        # Update cursor for next sync
        state.cursor = datetime.now(timezone.utc).isoformat()
        state.items_total = items_yielded

    async def search(
        self,
        query: str,
        limit: int = 25,
        team_ids: list[str] | None = None,
        **kwargs: Any,
    ) -> list:
        """Search Teams messages using Microsoft Search API."""
        from aragora.connectors.base import Evidence
        from aragora.observability.http_client_pool import get_http_pool

        # Build search request
        search_request = {
            "requests": [
                {
                    "entityTypes": ["chatMessage"],
                    "query": {"queryString": query},
                    "from": 0,
                    "size": limit,
                }
            ]
        }

        try:
            token = await self._get_access_token()
            pool = get_http_pool()
            async with pool.get_session("teams") as client:
                response = await client.post(
                    f"{self.GRAPH_BASE}/search/query",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json=search_request,
                    timeout=60,
                )
                response.raise_for_status()
                data = response.json()

            results = []
            for response_item in data.get("value", []):
                for hit in response_item.get("hitsContainers", [{}])[0].get("hits", []):
                    resource = hit.get("resource", {})
                    summary = hit.get("summary", "")

                    results.append(
                        Evidence(
                            id=f"teams-search-{resource.get('id', '')}",
                            source_type=self.source_type,
                            source_id=resource.get("id", ""),
                            content=summary,
                            title=resource.get("subject", "Teams Message"),
                            url=resource.get("webLink", ""),
                            confidence=0.8,
                            metadata={
                                "from": resource.get("from", {}).get("emailAddress", {}),
                            },
                        )
                    )

            return results

        except (
            httpx.HTTPStatusError,
            httpx.TimeoutException,
            httpx.ConnectError,
            KeyError,
            ValueError,
            OSError,
        ) as e:
            logger.error("[%s] Search failed: %s", self.name, e)
            return []

    async def fetch(self, evidence_id: str) -> Any | None:
        """Fetch a specific Teams message."""

        # Parse evidence ID: teams-msg-{message_id}
        if not evidence_id.startswith("teams-msg-"):
            return None

        # Note: Fetching individual messages requires knowing team and channel IDs
        # which aren't encoded in the evidence_id. This would need enhancement
        # to support full fetch capability.
        logger.warning("[%s] Individual message fetch not fully implemented", self.name)
        return None


__all__ = [
    "TeamsEnterpriseConnector",
    "TeamsTeam",
    "TeamsChannel",
    "TeamsMessage",
    "TeamsFile",
]
