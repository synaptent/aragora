"""
Messaging Operations Mixin for Chat Platform Connectors.

Contains methods for sending, updating, and deleting messages,
as well as command and interaction handling.
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..models import (
        BotCommand,
        MessageButton,
        SendMessageResponse,
        UserInteraction,
    )

logger = logging.getLogger(__name__)


class MessagingMixin:
    """
    Mixin providing messaging operations for chat connectors.

    Includes:
    - Message sending, updating, deleting
    - Ephemeral messages
    - Typing indicators
    - Command response handling
    - Interaction response handling
    - Rich content formatting
    """

    # These attributes/methods are expected from the base class
    webhook_url: str | None
    _http_request: Any

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Return the platform identifier (e.g., 'slack', 'teams', 'discord')."""
        ...

    # ==========================================================================
    # Message Operations
    # ==========================================================================

    async def send_message(
        self,
        channel_id: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
        thread_id: str | None = None,
        **kwargs: Any,
    ) -> SendMessageResponse:
        """
        Send a message to a channel.

        Default implementation posts to ``webhook_url`` if configured,
        otherwise returns a failure response.  Subclasses should override
        for platform-specific APIs.

        Args:
            channel_id: Target channel/conversation ID
            text: Plain text content (fallback for clients without rich support)
            blocks: Rich content blocks in platform-native format
            thread_id: Optional thread/reply ID for threaded messages
            **kwargs: Platform-specific options

        Returns:
            SendMessageResponse with message ID and status
        """
        from ..models import SendMessageResponse

        if self.webhook_url:
            payload: dict[str, Any] = {
                "channel_id": channel_id,
                "text": text,
            }
            if blocks:
                payload["blocks"] = blocks
            if thread_id:
                payload["thread_id"] = thread_id

            success, data, error = await self._http_request(
                method="POST",
                url=self.webhook_url,
                json=payload,
                operation="send_message",
            )

            if success and isinstance(data, dict):
                return SendMessageResponse(
                    success=True,
                    message_id=data.get("message_id") or data.get("id"),
                    channel_id=channel_id,
                    timestamp=data.get("timestamp"),
                )

            return SendMessageResponse(success=False, error=error or "Send failed")

        logger.warning(
            "%s send_message: no webhook_url configured and no platform-specific override provided",
            self.platform_name,
        )
        return SendMessageResponse(
            success=False,
            error=f"{self.platform_name} send_message not implemented",
        )

    async def update_message(
        self,
        channel_id: str,
        message_id: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> SendMessageResponse:
        """
        Update an existing message.

        Default implementation logs a warning and returns a failure response,
        since not all platforms support message editing.  Subclasses should
        override for platforms that do support it.

        Args:
            channel_id: Channel containing the message
            message_id: ID of message to update
            text: New text content
            blocks: New rich content blocks
            **kwargs: Platform-specific options

        Returns:
            SendMessageResponse with update status
        """
        from ..models import SendMessageResponse

        logger.warning(
            "%s does not implement update_message; message %s in channel %s was not updated",
            self.platform_name,
            message_id,
            channel_id,
        )
        return SendMessageResponse(
            success=False,
            error=f"{self.platform_name} does not support message updates",
        )

    async def delete_message(
        self,
        channel_id: str,
        message_id: str,
        **kwargs: Any,
    ) -> bool:
        """
        Delete a message.

        Default implementation returns False, since not all platforms
        support message deletion via API.  Subclasses should override
        for platforms that do support it.

        Args:
            channel_id: Channel containing the message
            message_id: ID of message to delete
            **kwargs: Platform-specific options

        Returns:
            True if deleted successfully, False otherwise
        """
        logger.warning(
            "%s does not implement delete_message; message %s in channel %s was not deleted",
            self.platform_name,
            message_id,
            channel_id,
        )
        return False

    async def send_ephemeral(
        self,
        channel_id: str,
        user_id: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> SendMessageResponse:
        """
        Send an ephemeral message visible only to one user.

        Not all platforms support this; default implementation sends regular message.

        Args:
            channel_id: Target channel
            user_id: User to show message to
            text: Message text
            blocks: Rich content blocks
            **kwargs: Platform-specific options

        Returns:
            SendMessageResponse with status
        """
        logger.warning("%s does not support ephemeral messages", self.platform_name)
        return await self.send_message(channel_id, text, blocks, **kwargs)

    async def send_typing_indicator(
        self,
        channel_id: str,
        **kwargs: Any,
    ) -> bool:
        """
        Send a typing indicator to show the bot is processing.

        Not all platforms support this; default implementation returns False.
        Typing indicators typically expire after a few seconds.

        Args:
            channel_id: Target channel to show typing in
            **kwargs: Platform-specific options

        Returns:
            True if typing indicator was sent, False if not supported
        """
        logger.debug("%s does not support typing indicators", self.platform_name)
        return False

    # ==========================================================================
    # Command Handling
    # ==========================================================================

    async def respond_to_command(
        self,
        command: BotCommand,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
        ephemeral: bool = True,
        **kwargs: Any,
    ) -> SendMessageResponse:
        """
        Respond to a slash command.

        Default implementation sends a regular message to the command's
        channel (ephemeral flag is ignored unless the subclass handles it).
        If the command has a ``response_url``, the default posts the
        response there.

        Args:
            command: The command that was invoked
            text: Response text
            blocks: Rich content blocks
            ephemeral: If True, only the user sees the response
            **kwargs: Platform-specific options

        Returns:
            SendMessageResponse with status
        """
        from ..models import SendMessageResponse

        # If the platform provides a response URL, use it
        if command.response_url:
            payload: dict[str, Any] = {"text": text}
            if blocks:
                payload["blocks"] = blocks
            if ephemeral:
                payload["response_type"] = "ephemeral"

            success, data, error = await self._http_request(
                method="POST",
                url=command.response_url,
                json=payload,
                operation="respond_to_command",
            )

            if success:
                return SendMessageResponse(success=True)
            return SendMessageResponse(success=False, error=error or "Command response failed")

        # Fall back to sending a regular channel message
        channel_id = command.channel.id if command.channel else kwargs.get("channel_id")
        if not channel_id:
            return SendMessageResponse(
                success=False,
                error="No channel ID or response_url available for command response",
            )

        return await self.send_message(
            channel_id=channel_id,
            text=text,
            blocks=blocks,
            **kwargs,
        )

    # ==========================================================================
    # Interaction Handling
    # ==========================================================================

    async def respond_to_interaction(
        self,
        interaction: UserInteraction,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
        replace_original: bool = False,
        **kwargs: Any,
    ) -> SendMessageResponse:
        """
        Respond to a user interaction (button click, menu select, etc.).

        Default implementation sends a regular message to the interaction's
        channel.  If ``replace_original`` is True and the interaction has a
        ``message_id``, attempts to update the original message; otherwise
        falls back to sending a new message.  If the interaction has a
        ``response_url``, the default posts the response there.

        Args:
            interaction: The interaction event
            text: Response text
            blocks: Rich content blocks
            replace_original: If True, replace the original message
            **kwargs: Platform-specific options

        Returns:
            SendMessageResponse with status
        """
        from ..models import SendMessageResponse

        # If the platform provides a response URL, use it
        if interaction.response_url:
            payload: dict[str, Any] = {"text": text}
            if blocks:
                payload["blocks"] = blocks
            if replace_original:
                payload["replace_original"] = True

            success, data, error = await self._http_request(
                method="POST",
                url=interaction.response_url,
                json=payload,
                operation="respond_to_interaction",
            )

            if success:
                return SendMessageResponse(success=True)
            return SendMessageResponse(success=False, error=error or "Interaction response failed")

        # If replacing the original and we know the channel + message_id, update it
        channel_id = interaction.channel.id if interaction.channel else None
        if replace_original and channel_id and interaction.message_id:
            return await self.update_message(
                channel_id=channel_id,
                message_id=interaction.message_id,
                text=text,
                blocks=blocks,
                **kwargs,
            )

        # Fall back to sending a regular message
        if channel_id:
            return await self.send_message(
                channel_id=channel_id,
                text=text,
                blocks=blocks,
                **kwargs,
            )

        return SendMessageResponse(
            success=False,
            error="No channel or response_url available for interaction response",
        )

    # ==========================================================================
    # Rich Content Formatting
    # ==========================================================================

    def format_blocks(
        self,
        title: str | None = None,
        body: str | None = None,
        fields: list[tuple[str, str]] | None = None,
        actions: list[MessageButton] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """
        Format content into platform-specific rich blocks.

        Default implementation produces a generic block list with
        ``section``, ``fields``, and ``actions`` entries.  Subclasses
        should override for platform-native formatting (Slack blocks,
        Discord embeds, Telegram inline keyboards, etc.).

        Args:
            title: Section title/header
            body: Main text content
            fields: List of (label, value) tuples for structured data
            actions: List of interactive buttons
            **kwargs: Platform-specific options

        Returns:
            List of platform-specific block structures
        """
        blocks: list[dict[str, Any]] = []

        if title:
            blocks.append({"type": "header", "text": title})

        if body:
            blocks.append({"type": "section", "text": body})

        if fields:
            blocks.append(
                {
                    "type": "fields",
                    "items": [
                        {"label": label, "value": value}
                        for label, value in fields
                        if label is not None and value is not None
                    ],
                }
            )

        if actions:
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        self.format_button(
                            text=btn.text,
                            action_id=btn.action_id,
                            value=btn.value,
                            style=btn.style,
                            url=btn.url,
                        )
                        for btn in actions
                    ],
                }
            )

        return blocks

    def format_button(
        self,
        text: str,
        action_id: str,
        value: str | None = None,
        style: str = "default",
        url: str | None = None,
    ) -> dict[str, Any]:
        """
        Format a button element.

        Default implementation returns a generic button dict.  Subclasses
        should override for platform-native button structures.

        Args:
            text: Button label
            action_id: Unique action identifier
            value: Value to pass when clicked
            style: Button style (default, primary, danger)
            url: Optional URL for link buttons

        Returns:
            Platform-specific button structure
        """
        button: dict[str, Any] = {
            "type": "button",
            "text": text,
            "action_id": action_id,
        }
        if value is not None:
            button["value"] = value
        if style != "default":
            button["style"] = style
        if url:
            button["url"] = url
        return button


__all__ = ["MessagingMixin"]
