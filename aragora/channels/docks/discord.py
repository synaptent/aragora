"""
Discord Dock - Channel dock implementation for Discord.

Handles message delivery to Discord servers via the Discord API.

Example:
    from aragora.channels.docks.discord import DiscordDock

    dock = DiscordDock({"token": "Bot xxx..."})
    await dock.initialize()
    await dock.send_message(channel_id, message)
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from aragora.channels.dock import ChannelDock, ChannelCapability, SendResult
from aragora.observability.http_client_pool import get_http_pool

if TYPE_CHECKING:
    from aragora.channels.normalized import NormalizedMessage

logger = logging.getLogger(__name__)

__all__ = ["DiscordDock"]


class DiscordDock(ChannelDock):
    """
    Discord platform dock.

    Supports markdown formatting, embeds, threads, file uploads,
    and reactions via the Discord API.
    """

    PLATFORM = "discord"
    CAPABILITIES = (
        ChannelCapability.RICH_TEXT
        | ChannelCapability.THREADS
        | ChannelCapability.FILES
        | ChannelCapability.REACTIONS
        | ChannelCapability.INLINE_IMAGES
    )

    def __init__(self, config: dict[str, Any] | None = None):
        """
        Initialize Discord dock.

        Config options:
            token: Discord bot token (or use DISCORD_BOT_TOKEN env var)
        """
        super().__init__(config)
        self._token: str | None = None

    async def initialize(self) -> bool:
        """Initialize the Discord dock."""
        self._token = self.config.get("token") or os.environ.get("DISCORD_BOT_TOKEN", "")
        if not self._token:
            logger.warning("Discord token not configured")
            return False

        self._initialized = True
        return True

    async def send_message(
        self,
        channel_id: str,
        message: NormalizedMessage,
        **kwargs: Any,
    ) -> SendResult:
        """
        Send a message to Discord.

        Args:
            channel_id: Discord channel ID
            message: The normalized message to send
            **kwargs: Additional options (message_reference, etc.)

        Returns:
            SendResult indicating success or failure
        """
        if not self._token:
            return SendResult.fail(
                error="Discord token not configured",
                platform=self.PLATFORM,
                channel_id=channel_id,
            )

        try:
            url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
            headers = {
                "Authorization": f"Bot {self._token}",
                "Content-Type": "application/json",
            }
            payload = self._build_payload(channel_id, message, **kwargs)

            pool = get_http_pool()
            async with pool.get_session("discord") as client:
                response = await client.post(url, json=payload, headers=headers, timeout=30.0)

                if response.status_code in (200, 201):
                    data = response.json()
                    return SendResult.ok(
                        message_id=data.get("id"),
                        platform=self.PLATFORM,
                        channel_id=channel_id,
                    )
                else:
                    error_data = response.json() if response.content else {}
                    return SendResult.fail(
                        error=error_data.get("message", f"HTTP {response.status_code}"),
                        platform=self.PLATFORM,
                        channel_id=channel_id,
                    )

        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.error("Discord send error: %s", e)
            return SendResult.fail(
                error=str(e),
                platform=self.PLATFORM,
                channel_id=channel_id,
            )

    def _build_payload(
        self,
        channel_id: str,
        message: NormalizedMessage,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Build Discord API payload from normalized message."""
        from aragora.channels.normalized import MessageFormat

        payload: dict[str, Any] = {}

        # Build content
        content_parts = []
        if message.title:
            content_parts.append(f"**{message.title}**")
        if message.content:
            content_parts.append(message.content)

        content = "\n\n".join(content_parts)

        # Discord supports markdown natively
        if message.format == MessageFormat.PLAIN:
            payload["content"] = content[:2000]
        else:
            # Discord markdown is similar to standard markdown
            payload["content"] = content[:2000]

        # Handle reply to message
        reply_to = kwargs.get("message_reference") or kwargs.get("reply_to") or message.reply_to
        if reply_to:
            payload["message_reference"] = {"message_id": reply_to}

        # Build embeds if we have rich content
        if message.title or message.has_attachments():
            embed: dict[str, Any] = {}

            if message.title:
                embed["title"] = message.title[:256]

            if message.content:
                embed["description"] = message.content[:4096]

            # Add image attachments to embed
            for attachment in message.attachments:
                if isinstance(attachment, dict):
                    att_type = attachment.get("type", "")
                    att_url = attachment.get("url", "")
                else:
                    att_type = getattr(attachment, "type", "")
                    att_url = getattr(attachment, "url", "")

                if att_type == "image" and att_url:
                    embed["image"] = {"url": att_url}
                    break  # Discord embeds support one image

            if embed:
                payload["embeds"] = [embed]

        return payload

    async def send_voice(
        self,
        channel_id: str,
        audio_data: bytes,
        text: str | None = None,
        thread_id: str | None = None,
        **kwargs: Any,
    ) -> SendResult:
        """
        Send a voice file to Discord.

        Discord doesn't have native voice messages like Telegram,
        but we can send audio files as attachments.
        """
        if not self._token:
            return SendResult.fail(
                error="Discord token not configured",
                platform=self.PLATFORM,
                channel_id=channel_id,
            )

        try:
            url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
            headers = {
                "Authorization": f"Bot {self._token}",
            }

            # Prepare multipart form data
            files = {
                "file": ("voice.ogg", audio_data, "audio/ogg"),
            }
            data: dict[str, Any] = {}
            if text:
                data["content"] = text[:2000]

            pool = get_http_pool()
            async with pool.get_session("discord") as client:
                response = await client.post(
                    url, data=data, files=files, headers=headers, timeout=60.0
                )

                if response.status_code in (200, 201):
                    resp_data = response.json()
                    return SendResult.ok(
                        message_id=resp_data.get("id"),
                        platform=self.PLATFORM,
                        channel_id=channel_id,
                    )
                else:
                    return SendResult.fail(
                        error=f"HTTP {response.status_code}",
                        platform=self.PLATFORM,
                        channel_id=channel_id,
                    )

        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.error("Discord voice send error: %s", e)
            return SendResult.fail(
                error=str(e),
                platform=self.PLATFORM,
                channel_id=channel_id,
            )
