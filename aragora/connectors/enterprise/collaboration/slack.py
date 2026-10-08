"""
Slack Enterprise Connector.

Provides full integration with Slack workspaces:
- Channel message indexing
- Thread extraction
- File attachment handling
- User mention resolution
- Incremental sync via timestamps
- Webhook/Events API support

Requires Slack Bot Token with appropriate scopes.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from collections.abc import AsyncIterator

from aragora.connectors.enterprise.base import (
    EnterpriseConnector,
    SyncItem,
    SyncState,
)
from aragora.reasoning.provenance import SourceType

logger = logging.getLogger(__name__)

_MAX_PAGES = 1000  # Safety cap for pagination loops


@dataclass
class SlackChannel:
    """A Slack channel."""

    id: str
    name: str
    is_private: bool = False
    is_archived: bool = False
    topic: str = ""
    purpose: str = ""
    member_count: int = 0
    created: datetime | None = None


@dataclass
class SlackMessage:
    """A Slack message."""

    ts: str  # Timestamp (unique ID)
    channel_id: str
    text: str
    user_id: str = ""
    user_name: str = ""
    thread_ts: str | None = None
    reply_count: int = 0
    reactions: list[dict[str, Any]] = field(default_factory=list)
    files: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime | None = None


@dataclass
class SlackUser:
    """A Slack user."""

    id: str
    name: str
    real_name: str = ""
    display_name: str = ""
    email: str = ""
    is_bot: bool = False


class SlackConnector(EnterpriseConnector):
    """
    Enterprise connector for Slack workspaces.

    Features:
    - Public and private channel indexing
    - Message and thread extraction
    - File metadata indexing
    - User mention resolution
    - Reaction tracking
    - Incremental sync via message timestamps
    - Real-time updates via Events API

    Authentication:
    - Bot Token with scopes:
      - channels:history, channels:read
      - groups:history, groups:read (for private channels)
      - users:read
      - files:read

    Usage:
        connector = SlackConnector(
            workspace_name="MyCompany",
            channels=["engineering", "general"],  # Optional: specific channels
        )
        result = await connector.sync()
    """

    def __init__(
        self,
        workspace_name: str = "default",
        channels: list[str] | None = None,
        include_private: bool = False,
        include_archived: bool = False,
        include_threads: bool = True,
        include_files: bool = True,
        exclude_bots: bool = True,
        max_messages_per_channel: int = 1000,
        **kwargs: Any,
    ):
        """
        Initialize Slack connector.

        Args:
            workspace_name: Name for identification
            channels: Specific channel names to sync (None = all accessible)
            include_private: Whether to include private channels
            include_archived: Whether to include archived channels
            include_threads: Whether to fetch thread replies
            include_files: Whether to index file metadata
            exclude_bots: Whether to exclude bot messages
            max_messages_per_channel: Maximum messages to fetch per channel
        """
        connector_id = f"slack_{workspace_name.lower().replace(' ', '_')}"
        super().__init__(connector_id=connector_id, **kwargs)

        self.workspace_name = workspace_name
        self.channels = set(channels) if channels else None
        self.include_private = include_private
        self.include_archived = include_archived
        self.include_threads = include_threads
        self.include_files = include_files
        self.exclude_bots = exclude_bots
        self.max_messages_per_channel = max_messages_per_channel

        # Cache
        self._users_cache: dict[str, SlackUser] = {}
        self._channels_cache: dict[str, SlackChannel] = {}

    @property
    def source_type(self) -> SourceType:
        return SourceType.SYNTHESIS  # Conversations combine multiple contributors

    @property
    def name(self) -> str:
        return f"Slack ({self.workspace_name})"

    async def _get_auth_header(self) -> dict[str, str]:
        """Get authentication header."""
        token = await self.credentials.get_credential("SLACK_BOT_TOKEN")

        if not token:
            raise ValueError("Slack credentials not configured. Set SLACK_BOT_TOKEN")

        return {"Authorization": f"Bearer {token}"}

    async def _api_request(
        self,
        endpoint: str,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a request to Slack Web API."""
        from aragora.server.http_client_pool import get_http_pool

        headers = await self._get_auth_header()
        headers["Content-Type"] = "application/json; charset=utf-8"

        url = f"https://slack.com/api/{endpoint}"

        pool = get_http_pool()
        async with pool.get_session("slack") as client:
            if method == "GET":
                response = await client.get(url, headers=headers, params=params, timeout=60)
            else:
                response = await client.post(
                    url, headers=headers, json=json_data or params, timeout=60
                )

            response.raise_for_status()
            data = response.json()

            if not data.get("ok"):
                error = data.get("error", "Unknown error")
                raise RuntimeError(f"Slack API error: {error}")

            return data

    async def _get_channels(self) -> list[SlackChannel]:
        """Get all accessible channels."""
        channels = []
        cursor = None

        for _page in range(_MAX_PAGES):
            params: dict[str, Any] = {
                "limit": 200,
                "exclude_archived": not self.include_archived,
            }

            if cursor:
                params["cursor"] = cursor

            # Get public channels
            data = await self._api_request("conversations.list", params=params)

            for item in data.get("channels", []):
                channel_name = item.get("name", "")

                # Filter to specific channels if configured
                if self.channels and channel_name not in self.channels:
                    continue

                # Skip private channels if not included
                if item.get("is_private") and not self.include_private:
                    continue

                channel = SlackChannel(
                    id=item.get("id", ""),
                    name=channel_name,
                    is_private=item.get("is_private", False),
                    is_archived=item.get("is_archived", False),
                    topic=item.get("topic", {}).get("value", ""),
                    purpose=item.get("purpose", {}).get("value", ""),
                    member_count=item.get("num_members", 0),
                    created=(
                        datetime.fromtimestamp(item.get("created", 0), tz=timezone.utc)
                        if item.get("created")
                        else None
                    ),
                )
                channels.append(channel)
                self._channels_cache[channel.id] = channel

            # Check pagination
            cursor = data.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

        return channels

    async def _get_user(self, user_id: str) -> SlackUser | None:
        """Get user info by ID."""
        if user_id in self._users_cache:
            return self._users_cache[user_id]

        try:
            data = await self._api_request("users.info", params={"user": user_id})
            user_data = data.get("user", {})

            user = SlackUser(
                id=user_data.get("id", ""),
                name=user_data.get("name", ""),
                real_name=user_data.get("real_name", ""),
                display_name=user_data.get("profile", {}).get("display_name", ""),
                email=user_data.get("profile", {}).get("email", ""),
                is_bot=user_data.get("is_bot", False),
            )
            self._users_cache[user_id] = user
            return user

        except (RuntimeError, ValueError, KeyError) as e:
            logger.warning("[%s] Failed to get user %s: %s", self.name, user_id, e)
            return None

    async def _get_messages(
        self,
        channel_id: str,
        oldest: str | None = None,
        limit: int = 100,
    ) -> tuple[list[SlackMessage], bool]:
        """Get messages from a channel."""
        params: dict[str, Any] = {
            "channel": channel_id,
            "limit": min(limit, 200),
        }

        if oldest:
            params["oldest"] = oldest

        data = await self._api_request("conversations.history", params=params)

        messages = []
        for item in data.get("messages", []):
            # Skip bot messages if configured
            if self.exclude_bots and (item.get("bot_id") or item.get("subtype") == "bot_message"):
                continue

            # Parse timestamp to datetime
            ts = item.get("ts", "")
            created_at = None
            if ts:
                try:
                    created_at = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                except (ValueError, TypeError) as e:
                    logger.debug("Invalid Slack timestamp format: %s", e)

            message = SlackMessage(
                ts=ts,
                channel_id=channel_id,
                text=item.get("text", ""),
                user_id=item.get("user", ""),
                thread_ts=item.get("thread_ts") if item.get("reply_count") else None,
                reply_count=item.get("reply_count", 0),
                reactions=item.get("reactions", []),
                files=item.get("files", []),
                created_at=created_at,
            )
            messages.append(message)

        has_more = data.get("has_more", False)
        return messages, has_more

    async def _get_thread_replies(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> list[SlackMessage]:
        """Get replies in a thread."""
        if not self.include_threads:
            return []

        try:
            params = {
                "channel": channel_id,
                "ts": thread_ts,
                "limit": 100,
            }

            data = await self._api_request("conversations.replies", params=params)

            replies = []
            for item in data.get("messages", [])[1:]:  # Skip first (parent)
                if self.exclude_bots and (
                    item.get("bot_id") or item.get("subtype") == "bot_message"
                ):
                    continue

                ts = item.get("ts", "")
                created_at = None
                if ts:
                    try:
                        created_at = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                    except (ValueError, TypeError) as e:
                        logger.debug("Invalid Slack thread timestamp: %s", e)

                replies.append(
                    SlackMessage(
                        ts=ts,
                        channel_id=channel_id,
                        text=item.get("text", ""),
                        user_id=item.get("user", ""),
                        thread_ts=thread_ts,
                        created_at=created_at,
                    )
                )

            return replies

        except (RuntimeError, ValueError, KeyError) as e:
            logger.warning("[%s] Failed to get thread replies: %s", self.name, e)
            return []

    async def _resolve_mentions(self, text: str) -> str:
        """Resolve user mentions in text."""
        # Find all user mentions
        mentions = re.findall(r"<@([A-Z0-9]+)>", text)

        for user_id in set(mentions):
            user = await self._get_user(user_id)
            if user:
                display_name = user.display_name or user.real_name or user.name
                text = text.replace(f"<@{user_id}>", f"@{display_name}")

        # Clean up channel mentions
        text = re.sub(r"<#([A-Z0-9]+)\|([^>]+)>", r"#\2", text)

        # Clean up URLs
        text = re.sub(r"<(https?://[^|>]+)\|([^>]+)>", r"\2 (\1)", text)
        text = re.sub(r"<(https?://[^>]+)>", r"\1", text)

        return text

    def _format_message_content(
        self,
        message: SlackMessage,
        channel: SlackChannel,
        user: SlackUser | None,
        replies: list[SlackMessage] | None = None,
    ) -> str:
        """Format a message with context."""
        parts = []

        # Header
        user_name = ""
        if user:
            user_name = user.display_name or user.real_name or user.name
        timestamp = message.created_at.strftime("%Y-%m-%d %H:%M") if message.created_at else ""

        parts.append(f"#{channel.name} | {user_name} | {timestamp}")
        parts.append("")
        parts.append(message.text)

        # Reactions
        if message.reactions:
            reaction_strs = []
            for reaction in message.reactions:
                emoji = reaction.get("name", "")
                count = reaction.get("count", 1)
                reaction_strs.append(f":{emoji}: ({count})")
            parts.append(f"\nReactions: {' '.join(reaction_strs)}")

        # Files
        if message.files and self.include_files:
            parts.append("\nAttachments:")
            for f in message.files:
                name = f.get("name", "file")
                filetype = f.get("filetype", "")
                parts.append(f"  - {name} ({filetype})")

        # Thread replies
        if replies:
            parts.append(f"\nThread ({len(replies)} replies):")
            for reply in replies[:10]:  # Limit to 10 replies
                reply_user = self._users_cache.get(reply.user_id)
                reply_name = ""
                if reply_user:
                    reply_name = reply_user.display_name or reply_user.real_name or reply_user.name
                parts.append(f"  {reply_name}: {reply.text[:200]}")

        return "\n".join(parts)

    async def sync_items(
        self,
        state: SyncState,
        batch_size: int = 100,
    ) -> AsyncIterator[SyncItem]:
        """
        Yield Slack messages for syncing.
        """
        # Parse last sync timestamp from cursor
        oldest_ts = state.cursor

        # Get all channels
        channels = await self._get_channels()
        state.items_total = len(channels)

        items_yielded = 0

        for channel in channels:
            logger.info("[%s] Syncing channel: #%s", self.name, channel.name)

            messages_fetched = 0
            current_oldest = oldest_ts

            while messages_fetched < self.max_messages_per_channel:
                messages, has_more = await self._get_messages(
                    channel.id,
                    oldest=current_oldest,
                    limit=min(100, self.max_messages_per_channel - messages_fetched),
                )

                if not messages:
                    break

                for message in messages:
                    # Get user info
                    user = None
                    if message.user_id:
                        user = await self._get_user(message.user_id)
                        message.user_name = user.display_name if user else ""

                    # Resolve mentions in text
                    resolved_text = await self._resolve_mentions(message.text)
                    message.text = resolved_text

                    # Get thread replies if this is a parent message
                    replies = []
                    if message.thread_ts == message.ts and message.reply_count > 0:
                        replies = await self._get_thread_replies(channel.id, message.ts)

                    # Format content
                    content = self._format_message_content(message, channel, user, replies)

                    yield SyncItem(
                        id=f"slack-{channel.id}-{message.ts}",
                        content=content[:50000],
                        source_type="discussion",
                        source_id=f"slack/{self.workspace_name}/{channel.name}/{message.ts}",
                        title=f"#{channel.name} - {message.user_name}",
                        url=f"https://slack.com/archives/{channel.id}/p{message.ts.replace('.', '')}",
                        author=message.user_name,
                        created_at=message.created_at,
                        domain="enterprise/slack",
                        confidence=0.75,
                        metadata={
                            "channel_id": channel.id,
                            "channel_name": channel.name,
                            "user_id": message.user_id,
                            "ts": message.ts,
                            "thread_ts": message.thread_ts,
                            "reply_count": message.reply_count,
                            "reaction_count": sum(r.get("count", 0) for r in message.reactions),
                            "file_count": len(message.files),
                        },
                    )

                    items_yielded += 1

                    # Update cursor to latest timestamp
                    if not state.cursor or message.ts > state.cursor:
                        state.cursor = message.ts

                messages_fetched += len(messages)

                if not has_more:
                    break

                # Update oldest for next batch
                if messages:
                    current_oldest = messages[-1].ts

                await asyncio.sleep(0.5)  # Rate limiting

    async def search(
        self,
        query: str,
        limit: int = 10,
        **kwargs: Any,
    ) -> list:
        """Search Slack messages."""
        from aragora.connectors.base import Evidence

        try:
            data = await self._api_request(
                "search.messages",
                params={
                    "query": query,
                    "count": limit,
                    "sort": "score",
                },
            )

            results = []
            for match in data.get("messages", {}).get("matches", []):
                channel_id = match.get("channel", {}).get("id", "")
                channel_name = match.get("channel", {}).get("name", "")
                ts = match.get("ts", "")
                user_name = match.get("username", "")

                results.append(
                    Evidence(
                        id=f"slack-{channel_id}-{ts}",
                        source_type=self.source_type,
                        source_id=f"slack/{channel_name}/{ts}",
                        content=match.get("text", "")[:2000],
                        title=f"#{channel_name} - {user_name}",
                        url=match.get("permalink", ""),
                        author=user_name,
                        confidence=0.75,
                        metadata={
                            "channel_id": channel_id,
                            "channel_name": channel_name,
                            "score": match.get("score", 0),
                        },
                    )
                )

            return results

        except (RuntimeError, ValueError, KeyError) as e:
            logger.error("[%s] Search failed: %s", self.name, e)
            return []

    async def fetch(self, evidence_id: str) -> Any | None:
        """Fetch a specific Slack message."""
        from aragora.connectors.base import Evidence

        # Parse evidence_id: slack-{channel_id}-{ts}
        parts = evidence_id.split("-")
        if len(parts) < 3:
            return None

        channel_id = parts[1]
        ts = "-".join(parts[2:])  # Timestamp may contain dashes

        try:
            data = await self._api_request(
                "conversations.history",
                params={
                    "channel": channel_id,
                    "latest": ts,
                    "inclusive": True,
                    "limit": 1,
                },
            )

            messages = data.get("messages", [])
            if not messages:
                return None

            message = messages[0]
            text = await self._resolve_mentions(message.get("text", ""))

            channel = self._channels_cache.get(channel_id)
            channel_name = channel.name if channel else channel_id

            return Evidence(
                id=evidence_id,
                source_type=self.source_type,
                source_id=f"slack/{channel_name}/{ts}",
                content=text,
                title=f"#{channel_name}",
                url=f"https://slack.com/archives/{channel_id}/p{ts.replace('.', '')}",
                author=message.get("user", ""),
                confidence=0.75,
            )

        except (RuntimeError, ValueError, KeyError) as e:
            logger.error("[%s] Fetch failed: %s", self.name, e)
            return None

    async def handle_webhook(self, payload: dict[str, Any]) -> bool:
        """Handle Slack Events API webhook."""
        # URL verification challenge
        if payload.get("type") == "url_verification":
            return True

        # Event callback
        if payload.get("type") == "event_callback":
            event = payload.get("event", {})
            event_type = event.get("type", "")

            logger.info("[%s] Webhook event: %s", self.name, event_type)

            if event_type in ["message", "message.channels", "message.groups"]:
                # New message - trigger incremental sync
                asyncio.create_task(self.sync(max_items=10))
                return True

        return False

    # =========================================================================
    # Methods for CrossChannelContextService Integration
    # =========================================================================

    async def get_user_presence(self, user_id: str) -> dict[str, Any]:
        """
        Get user presence/status.

        Args:
            user_id: Slack user ID

        Returns:
            Dict with presence info: {"presence": "active"|"away", "online": bool}
        """
        try:
            data = await self._api_request(
                "users.getPresence",
                params={"user": user_id},
            )
            return {
                "presence": data.get("presence", "away"),
                "online": data.get("online", False),
                "auto_away": data.get("auto_away", False),
                "manual_away": data.get("manual_away", False),
                "connection_count": data.get("connection_count", 0),
            }
        except (RuntimeError, ValueError, KeyError) as e:
            logger.debug("[%s] Failed to get presence for %s: %s", self.name, user_id, e)
            return {"presence": "away", "online": False}

    async def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        """
        Look up a Slack user by email address.

        Args:
            email: Email address to look up

        Returns:
            User dict with id, name, real_name, etc. or None if not found
        """
        try:
            data = await self._api_request(
                "users.lookupByEmail",
                params={"email": email},
            )
            user_data = data.get("user", {})
            return {
                "id": user_data.get("id", ""),
                "name": user_data.get("name", ""),
                "real_name": user_data.get("real_name", ""),
                "display_name": user_data.get("profile", {}).get("display_name", ""),
                "email": user_data.get("profile", {}).get("email", ""),
                "is_bot": user_data.get("is_bot", False),
                "team_id": user_data.get("team_id", ""),
                "tz": user_data.get("tz", ""),
            }
        except RuntimeError as e:
            # Slack returns error if user not found
            if "users_not_found" in str(e):
                return None
            logger.debug("[%s] Failed to lookup user by email: %s", self.name, e)
            return None
        except (ValueError, KeyError) as e:
            logger.debug("[%s] Failed to lookup user by email: %s", self.name, e)
            return None

    async def search_messages(
        self,
        query: str,
        count: int = 20,
        sort: str = "timestamp",
        sort_dir: str = "desc",
    ) -> list[dict[str, Any]]:
        """
        Search for messages matching a query.

        Args:
            query: Search query (supports Slack search operators)
            count: Maximum number of results
            sort: Sort field (timestamp or score)
            sort_dir: Sort direction (asc or desc)

        Returns:
            List of message dicts with text, channel, ts, user, etc.
        """
        try:
            data = await self._api_request(
                "search.messages",
                params={
                    "query": query,
                    "count": min(count, 100),
                    "sort": sort,
                    "sort_dir": sort_dir,
                },
            )

            messages = []
            for match in data.get("messages", {}).get("matches", []):
                messages.append(
                    {
                        "text": match.get("text", ""),
                        "channel": match.get("channel", {}).get("id", ""),
                        "channel_name": match.get("channel", {}).get("name", ""),
                        "ts": match.get("ts", ""),
                        "user": match.get("user", ""),
                        "username": match.get("username", ""),
                        "permalink": match.get("permalink", ""),
                        "team": match.get("team", ""),
                        "type": match.get("type", "message"),
                    }
                )

            return messages

        except (RuntimeError, ValueError, KeyError) as e:
            logger.debug("[%s] Message search failed: %s", self.name, e)
            return []

    async def authenticate(self, token: str | None = None) -> bool:
        """
        Authenticate with Slack using a bot token.

        Args:
            token: Slack bot token (if not set via credentials)

        Returns:
            True if authentication successful
        """
        if token:
            # Store token for later use
            await self.credentials.set_credential("SLACK_BOT_TOKEN", token)

        try:
            # Test authentication
            data = await self._api_request("auth.test")
            logger.info(
                "[%s] Authenticated as %s in workspace %s",
                self.name,
                data.get("user"),
                data.get("team"),
            )
            return True
        except (RuntimeError, ValueError, OSError) as e:
            logger.error("[%s] Authentication failed: %s", self.name, e)
            return False

    async def get_channels_for_user(
        self,
        user_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Get channels that a user is a member of.

        Args:
            user_id: Slack user ID
            limit: Maximum number of channels to return

        Returns:
            List of channel dicts
        """
        try:
            data = await self._api_request(
                "users.conversations",
                params={
                    "user": user_id,
                    "limit": limit,
                    "exclude_archived": True,
                },
            )

            channels = []
            for channel in data.get("channels", []):
                channels.append(
                    {
                        "id": channel.get("id", ""),
                        "name": channel.get("name", ""),
                        "is_private": channel.get("is_private", False),
                        "is_member": channel.get("is_member", True),
                    }
                )

            return channels

        except (RuntimeError, ValueError, KeyError) as e:
            logger.debug("[%s] Failed to get channels for user %s: %s", self.name, user_id, e)
            return []

    async def post_message(
        self,
        channel: str,
        text: str,
        thread_ts: str | None = None,
        blocks: list[dict[str, Any]] | None = None,
    ) -> str | None:
        """
        Post a message to a channel.

        Args:
            channel: Channel ID or name
            text: Message text
            thread_ts: Thread timestamp to reply in
            blocks: Optional Block Kit blocks

        Returns:
            Message timestamp if successful, None otherwise
        """
        try:
            params: dict[str, Any] = {
                "channel": channel,
                "text": text,
            }

            if thread_ts:
                params["thread_ts"] = thread_ts

            if blocks:
                params["blocks"] = blocks

            data = await self._api_request(
                "chat.postMessage",
                method="POST",
                json_data=params,
            )

            return data.get("ts")

        except (RuntimeError, ValueError, OSError) as e:
            logger.error("[%s] Failed to post message: %s", self.name, e)
            return None


__all__ = ["SlackConnector", "SlackChannel", "SlackMessage", "SlackUser"]
