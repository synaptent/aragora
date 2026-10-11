"""
Channel and User Operations Mixin for Chat Platform Connectors.

Contains methods for channel/user info, DMs, reactions, pinning, threading,
slash command handling, and message streaming.
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..models import (
        BotCommand,
        ChatChannel,
        ChatMessage,
        ChatUser,
        SendMessageResponse,
        VoiceMessage,
    )

logger = logging.getLogger(__name__)


class ChannelUserMixin:
    """
    Mixin providing channel and user operations for chat connectors.

    Includes:
    - Channel and user info retrieval
    - Channel creation
    - Direct messages
    - Message reactions
    - Message pinning
    - Threading
    - Slash command handling
    - Message streaming/receiving
    """

    # These attributes/methods are expected from the base class
    send_message: Any

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Return the platform identifier."""
        ...

    # ==========================================================================
    # Voice Message Handling
    # ==========================================================================

    async def get_voice_message(
        self,
        file_id: str,
        **kwargs: Any,
    ) -> VoiceMessage | None:
        """
        Retrieve a voice message for transcription.

        Args:
            file_id: ID of the voice message file
            **kwargs: Platform-specific options

        Returns:
            VoiceMessage with audio content, or None if not supported
        """
        logger.info("%s voice messages not implemented", self.platform_name)
        return None

    # ==========================================================================
    # Channel/User Operations
    # ==========================================================================

    async def get_channel_info(
        self,
        channel_id: str,
        **kwargs: Any,
    ) -> ChatChannel | None:
        """
        Get information about a channel.

        Args:
            channel_id: Channel ID to look up
            **kwargs: Platform-specific options

        Returns:
            ChatChannel info or None
        """
        logger.debug("%s get_channel_info not implemented", self.platform_name)
        return None

    async def get_user_info(
        self,
        user_id: str,
        **kwargs: Any,
    ) -> ChatUser | None:
        """
        Get information about a user.

        Args:
            user_id: User ID to look up
            **kwargs: Platform-specific options

        Returns:
            ChatUser info or None
        """
        logger.debug("%s get_user_info not implemented", self.platform_name)
        return None

    async def get_user_profile(
        self,
        user_id: str,
        **kwargs: Any,
    ) -> ChatUser | None:
        """
        Get detailed user profile information.

        This is an alias for get_user_info() for API consistency.
        Override in subclasses if the platform provides separate
        profile endpoints with more detailed information.

        Args:
            user_id: User ID to look up
            **kwargs: Platform-specific options

        Returns:
            ChatUser info or None
        """
        return await self.get_user_info(user_id, **kwargs)

    async def list_users(
        self,
        channel_id: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
        **kwargs: Any,
    ) -> tuple[list[ChatUser], str | None]:
        """
        List users in a channel or workspace.

        If channel_id is provided, lists members of that channel.
        Otherwise, lists members of the workspace (if supported).

        Args:
            channel_id: Optional channel to list members of
            limit: Maximum number of users to return (default 100)
            cursor: Pagination cursor for subsequent requests
            **kwargs: Platform-specific options

        Returns:
            Tuple of (list of ChatUser, next_cursor or None)

        Note:
            Default implementation returns empty list. Override in
            subclasses for platform-specific user enumeration.
        """
        logger.debug("%s list_users not implemented", self.platform_name)
        return [], None

    async def create_channel(
        self,
        name: str,
        is_private: bool = False,
        description: str | None = None,
        **kwargs: Any,
    ) -> ChatChannel | None:
        """
        Create a new channel.

        Args:
            name: Name for the new channel
            is_private: Whether the channel should be private (default False)
            description: Optional channel description/topic
            **kwargs: Platform-specific options (e.g., team_id, user_ids)

        Returns:
            ChatChannel if created successfully, None otherwise

        Note:
            Default implementation returns None. Override in subclasses
            for platforms that support channel creation via API.
        """
        logger.debug("%s create_channel not implemented", self.platform_name)
        return None

    async def send_dm(
        self,
        user_id: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> SendMessageResponse:
        """
        Send a direct message to a user.

        This opens or retrieves a DM channel with the user and sends
        the message. For platforms that don't distinguish between
        channels and DMs (like WhatsApp), this delegates to send_message.

        Args:
            user_id: Target user ID
            text: Message text
            blocks: Optional rich content blocks
            **kwargs: Platform-specific options

        Returns:
            SendMessageResponse with message ID and status

        Note:
            Default implementation delegates to send_message with user_id
            as the channel_id. Override if the platform requires opening
            a DM channel first.
        """
        logger.debug("%s send_dm using user_id as channel_id", self.platform_name)
        return await self.send_message(
            channel_id=user_id,
            text=text,
            blocks=blocks,
            **kwargs,
        )

    # ==========================================================================
    # Message Reactions
    # ==========================================================================

    async def react_to_message(
        self,
        channel_id: str,
        message_id: str,
        reaction: str,
        **kwargs: Any,
    ) -> bool:
        """
        Add a reaction to a message.

        Args:
            channel_id: Channel containing the message
            message_id: ID of the message to react to
            reaction: Reaction emoji or identifier (e.g., "thumbsup", ":+1:")
            **kwargs: Platform-specific options

        Returns:
            True if reaction was added successfully, False otherwise

        Note:
            Default implementation returns False. Override in subclasses
            for platforms that support message reactions.
        """
        logger.debug("%s react_to_message not implemented", self.platform_name)
        return False

    async def remove_reaction(
        self,
        channel_id: str,
        message_id: str,
        reaction: str,
        **kwargs: Any,
    ) -> bool:
        """
        Remove a reaction from a message.

        Args:
            channel_id: Channel containing the message
            message_id: ID of the message to remove reaction from
            reaction: Reaction emoji or identifier to remove
            **kwargs: Platform-specific options

        Returns:
            True if reaction was removed successfully, False otherwise

        Note:
            Default implementation returns False. Override in subclasses
            for platforms that support message reactions.
        """
        logger.debug("%s remove_reaction not implemented", self.platform_name)
        return False

    # ==========================================================================
    # Message Pinning
    # ==========================================================================

    async def pin_message(
        self,
        channel_id: str,
        message_id: str,
        **kwargs: Any,
    ) -> bool:
        """
        Pin a message to a channel.

        Pinned messages are highlighted and easily accessible in most
        chat platforms, useful for important announcements or decisions.

        Args:
            channel_id: Channel containing the message
            message_id: ID of the message to pin
            **kwargs: Platform-specific options

        Returns:
            True if message was pinned successfully, False otherwise

        Note:
            Default implementation returns False. Override in subclasses
            for platforms that support message pinning.
        """
        logger.debug("%s pin_message not implemented", self.platform_name)
        return False

    async def unpin_message(
        self,
        channel_id: str,
        message_id: str,
        **kwargs: Any,
    ) -> bool:
        """
        Unpin a previously pinned message.

        Args:
            channel_id: Channel containing the message
            message_id: ID of the message to unpin
            **kwargs: Platform-specific options

        Returns:
            True if message was unpinned successfully, False otherwise

        Note:
            Default implementation returns False. Override in subclasses
            for platforms that support message pinning.
        """
        logger.debug("%s unpin_message not implemented", self.platform_name)
        return False

    async def get_pinned_messages(
        self,
        channel_id: str,
        **kwargs: Any,
    ) -> list[ChatMessage]:
        """
        Get all pinned messages in a channel.

        Args:
            channel_id: Channel to get pinned messages from
            **kwargs: Platform-specific options

        Returns:
            List of pinned ChatMessage objects

        Note:
            Default implementation returns empty list. Override in
            subclasses for platforms that support message pinning.
        """
        logger.debug("%s get_pinned_messages not implemented", self.platform_name)
        return []

    # ==========================================================================
    # Threading
    # ==========================================================================

    async def create_thread(
        self,
        channel_id: str,
        message_id: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
        thread_name: str | None = None,
        **kwargs: Any,
    ) -> SendMessageResponse:
        """
        Create a thread reply to a message.

        This sends a reply that creates or continues a thread on the
        specified message. For platforms that don't distinguish threads
        from regular replies, this delegates to send_message with thread_id.

        Args:
            channel_id: Channel containing the parent message
            message_id: ID of the message to create thread on
            text: Thread reply text
            blocks: Optional rich content blocks
            thread_name: Optional name for the thread (if platform supports)
            **kwargs: Platform-specific options

        Returns:
            SendMessageResponse with the thread reply message ID

        Note:
            Default implementation delegates to send_message with
            message_id as thread_id. Override if platform has special
            thread creation APIs.
        """
        return await self.send_message(
            channel_id=channel_id,
            text=text,
            blocks=blocks,
            thread_id=message_id,
            **kwargs,
        )

    # ==========================================================================
    # Slash Command Handling
    # ==========================================================================

    async def handle_slash_command(
        self,
        command_name: str,
        channel_id: str,
        user_id: str,
        text: str = "",
        response_url: str | None = None,
        **kwargs: Any,
    ) -> BotCommand:
        """
        Handle an incoming slash command.

        This parses and structures an incoming slash command for processing.
        Use respond_to_command() to send a response back to the user.

        Args:
            command_name: Name of the command (without leading /)
            channel_id: Channel where command was invoked
            user_id: User who invoked the command
            text: Additional text after the command
            response_url: URL for async responses (if provided by platform)
            **kwargs: Platform-specific options and raw payload data

        Returns:
            BotCommand object representing the parsed command

        Example:
            # User types: /debate Should we use React or Vue?
            cmd = await connector.handle_slash_command(
                command_name="debate",
                channel_id="C123",
                user_id="U456",
                text="Should we use React or Vue?",
            )
            # cmd.name == "debate"
            # cmd.args == ["Should", "we", "use", "React", "or", "Vue?"]
        """
        from ..models import BotCommand, ChatChannel, ChatUser

        # Parse arguments from text
        args = text.split() if text else []

        # Build user and channel objects
        user = ChatUser(
            id=user_id,
            platform=self.platform_name,
        )
        channel = ChatChannel(
            id=channel_id,
            platform=self.platform_name,
        )

        return BotCommand(
            name=command_name,
            text=f"/{command_name} {text}".strip(),
            args=args,
            user=user,
            channel=channel,
            platform=self.platform_name,
            response_url=response_url,
            metadata=kwargs,
        )

    # ==========================================================================
    # Message Streaming / Receiving
    # ==========================================================================

    async def receive_messages(
        self,
        channel_id: str,
        timeout: float | None = None,
        **kwargs: Any,
    ):
        """
        Async generator that yields incoming messages from a channel.

        This provides a streaming interface for receiving messages in
        real-time. For webhook-based platforms, this may poll or use
        long-polling. For WebSocket-based platforms, this yields messages
        as they arrive.

        Args:
            channel_id: Channel to receive messages from
            timeout: Optional timeout in seconds for the stream
            **kwargs: Platform-specific options

        Yields:
            ChatMessage objects as they are received

        Note:
            Default implementation yields nothing (not supported).
            Override in subclasses for platforms with real-time
            message streaming capabilities.

        Example:
            async for message in connector.receive_messages("C123"):
                print(f"{message.author.username}: {message.content}")
                if message.content == "/stop":
                    break
        """
        logger.debug("%s receive_messages not implemented", self.platform_name)
        # Default implementation: empty async generator
        return
        yield  # This makes it a generator  # noqa: B901


__all__ = ["ChannelUserMixin"]
