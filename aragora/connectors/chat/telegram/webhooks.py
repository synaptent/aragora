"""
Telegram Bot Connector - Webhook Handling.

Contains webhook verification, parsing, and event handling.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime
from typing import TYPE_CHECKING, Any

from ..models import (
    BotCommand,
    ChatChannel,
    ChatEvidence,
    ChatMessage,
    ChatUser,
    InteractionType,
    MessageType,
    SendMessageResponse,
    UserInteraction,
    WebhookEvent,
)

logger = logging.getLogger(__name__)


class TelegramWebhooksMixin:
    """Mixin providing webhook handling for TelegramConnector."""

    if TYPE_CHECKING:
        _telegram_api_request: Any
        send_message: Any
        update_message: Any

    async def handle_webhook(
        self,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> WebhookEvent:
        """Process incoming Telegram webhook update."""
        # Handle message updates
        if "message" in payload:
            msg = payload["message"]
            return WebhookEvent(
                event_type="message",
                platform="telegram",
                timestamp=datetime.fromtimestamp(msg.get("date", 0)),
                raw_payload=payload,
                metadata={
                    "channel_id": str(msg.get("chat", {}).get("id")),
                    "user_id": str(msg.get("from", {}).get("id")),
                    "message_id": str(msg.get("message_id")),
                },
            )

        # Handle callback queries (button clicks)
        if "callback_query" in payload:
            query = payload["callback_query"]
            return WebhookEvent(
                event_type="callback_query",
                platform="telegram",
                timestamp=datetime.now(),
                raw_payload=payload,
                metadata={
                    "channel_id": str(query.get("message", {}).get("chat", {}).get("id")),
                    "user_id": str(query.get("from", {}).get("id")),
                    "message_id": str(query.get("message", {}).get("message_id")),
                },
            )

        return WebhookEvent(
            event_type="unknown",
            platform="telegram",
            raw_payload=payload,
        )

    async def parse_message(
        self,
        payload: dict[str, Any],
        **kwargs: Any,
    ) -> ChatMessage:
        """Parse a Telegram message into ChatMessage."""
        msg = payload.get("message", payload)

        user_data = msg.get("from", {})
        chat_data = msg.get("chat", {})

        # Determine message type
        msg_type = MessageType.TEXT
        if "voice" in msg:
            msg_type = MessageType.VOICE
        elif "document" in msg:
            msg_type = MessageType.FILE
        elif "photo" in msg:
            msg_type = MessageType.FILE  # Images treated as files

        # Build proper ChatChannel and ChatUser objects
        channel = ChatChannel(
            id=str(chat_data.get("id")),
            platform="telegram",
            name=chat_data.get("title") or chat_data.get("username"),
            is_private=chat_data.get("type") == "private",
            is_dm=chat_data.get("type") == "private",
        )
        author = ChatUser(
            id=str(user_data.get("id")),
            platform="telegram",
            username=user_data.get("username", ""),
            display_name=f"{user_data.get('first_name', '')} {user_data.get('last_name', '')}".strip(),
        )

        return ChatMessage(
            id=str(msg.get("message_id")),
            platform="telegram",
            channel=channel,
            author=author,
            content=msg.get("text", msg.get("caption", "")),
            message_type=msg_type,
            timestamp=datetime.fromtimestamp(msg.get("date", 0)),
            thread_id=(
                str(msg.get("reply_to_message", {}).get("message_id"))
                if msg.get("reply_to_message")
                else None
            ),
            metadata={"raw_data": msg},
        )

    async def parse_command(
        self,
        payload: dict[str, Any],
        **kwargs: Any,
    ) -> BotCommand | None:
        """Parse a Telegram command (e.g., /start, /help)."""
        msg = payload.get("message", payload)
        text = msg.get("text", "")

        if not text.startswith("/"):
            return None

        # Parse command and args
        parts = text.split()
        command_name = parts[0][1:]  # Remove leading /

        # Handle @bot suffix (e.g., /help@mybot)
        if "@" in command_name:
            command_name = command_name.split("@")[0]

        args = parts[1:] if len(parts) > 1 else []

        # Build user and channel objects
        user_data = msg.get("from", {})
        chat_data = msg.get("chat", {})
        user = ChatUser(
            id=str(user_data.get("id")),
            platform="telegram",
            username=user_data.get("username", ""),
            display_name=f"{user_data.get('first_name', '')} {user_data.get('last_name', '')}".strip(),
        )
        channel = ChatChannel(
            id=str(chat_data.get("id")),
            platform="telegram",
            name=chat_data.get("title") or chat_data.get("username"),
        )

        return BotCommand(
            name=command_name,
            text=text,
            args=args,
            user=user,
            channel=channel,
            platform="telegram",
            metadata={"message_id": str(msg.get("message_id")), "raw_data": msg},
        )

    async def handle_interaction(
        self,
        payload: dict[str, Any],
        **kwargs: Any,
    ) -> UserInteraction:
        """Handle callback query (button click)."""
        query = payload.get("callback_query", {})
        user_data = query.get("from", {})
        msg = query.get("message", {})
        chat_data = msg.get("chat", {})

        # Build user and channel objects
        user = ChatUser(
            id=str(user_data.get("id")),
            platform="telegram",
            username=user_data.get("username", ""),
            display_name=f"{user_data.get('first_name', '')} {user_data.get('last_name', '')}".strip(),
        )
        channel = ChatChannel(
            id=str(chat_data.get("id")),
            platform="telegram",
            name=chat_data.get("title") or chat_data.get("username"),
        )

        return UserInteraction(
            id=query.get("id", ""),
            interaction_type=InteractionType.BUTTON_CLICK,
            action_id=query.get("data", ""),
            value=query.get("data", ""),
            user=user,
            channel=channel,
            message_id=str(msg.get("message_id")),
            platform="telegram",
            metadata={"raw_data": query},
        )

    async def get_channel_info(
        self,
        channel_id: str,
        **kwargs: Any,
    ) -> ChatChannel:
        """Get information about a chat.

        Uses _telegram_api_request for circuit breaker, retry, and timeout handling.
        """
        success, data, error = await self._telegram_api_request(
            "getChat",
            payload={"chat_id": channel_id},
            method="GET",
            operation="get_channel_info",
        )

        if not success or not data:
            raise RuntimeError(error or "Failed to get chat")

        chat = data.get("result", {})
        chat_type = chat.get("type", "private")
        return ChatChannel(
            id=str(chat.get("id")),
            platform="telegram",
            name=chat.get("title") or chat.get("username") or "",
            is_private=chat_type == "private",
            is_dm=chat_type == "private",
            metadata={"type": chat_type, "member_count": chat.get("member_count")},
        )

    async def get_user_info(
        self,
        user_id: str,
        **kwargs: Any,
    ) -> ChatUser:
        """Get information about a user (limited in Telegram)."""
        # Telegram doesn't have a direct getUser API
        # User info typically comes from message updates
        return ChatUser(
            id=user_id,
            platform="telegram",
        )

    async def extract_evidence(
        self,
        message: ChatMessage,
        **kwargs: Any,
    ) -> ChatEvidence:
        """Extract evidence from a message for debate."""
        # Generate unique ID
        evidence_id = hashlib.sha256(
            f"telegram:{message.channel.id}:{message.id}".encode()
        ).hexdigest()[:16]

        return ChatEvidence(
            id=evidence_id,
            source_type="chat",
            source_id=message.id,
            platform="telegram",
            channel_id=message.channel.id,
            channel_name=message.channel.name,
            content=message.content,
            title=message.content[:100] if message.content else "",
            author_id=message.author.id,
            author_name=message.author.display_name or message.author.username,
            timestamp=message.timestamp,
            source_message=message,
            metadata={
                "raw": message.metadata,
                "permalink": f"https://t.me/c/{message.channel.id}/{message.id}",
            },
        )

    async def answer_callback_query(
        self,
        callback_query_id: str,
        text: str | None = None,
        show_alert: bool = False,
        **kwargs: Any,
    ) -> bool:
        """Answer a callback query (acknowledge button click).

        Uses _telegram_api_request for circuit breaker, retry, and timeout handling.
        """
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        if show_alert:
            payload["show_alert"] = True

        success, _, error = await self._telegram_api_request(
            "answerCallbackQuery",
            payload=payload,
            operation="answer_callback_query",
        )

        if not success and error:
            logger.warning("Failed to answer callback query: %s", error)

        return success

    def verify_webhook(
        self,
        headers: dict[str, str],
        body: bytes,
    ) -> bool:
        """Verify Telegram webhook request.

        Telegram sends the X-Telegram-Bot-Api-Secret-Token header if a
        secret_token was configured when setting the webhook URL via setWebhook.

        SECURITY: Fails closed in production if TELEGRAM_WEBHOOK_SECRET is not configured.
        """
        webhook_secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
        if not webhook_secret:
            env = os.environ.get("ARAGORA_ENV", "production").lower()
            is_production = env not in ("development", "dev", "local", "test")
            if is_production:
                logger.error(
                    "SECURITY: TELEGRAM_WEBHOOK_SECRET not configured in production. "
                    "Rejecting webhook to prevent signature bypass."
                )
                return False
            logger.warning(
                "TELEGRAM_WEBHOOK_SECRET not set - skipping verification. "
                "This is only acceptable in development!"
            )
            return True

        secret_header = headers.get(
            "X-Telegram-Bot-Api-Secret-Token",
            headers.get("x-telegram-bot-api-secret-token", ""),
        )
        return hmac.compare_digest(secret_header, webhook_secret)

    def parse_webhook_event(
        self,
        headers: dict[str, str],
        body: bytes,
    ) -> WebhookEvent:
        """Parse a Telegram webhook payload into a WebhookEvent."""
        payload = json.loads(body) if body else {}

        # Handle message updates
        if "message" in payload:
            msg = payload["message"]
            return WebhookEvent(
                event_type="message",
                platform="telegram",
                timestamp=datetime.fromtimestamp(msg.get("date", 0)),
                raw_payload=payload,
                metadata={
                    "channel_id": str(msg.get("chat", {}).get("id")),
                    "user_id": str(msg.get("from", {}).get("id")),
                    "message_id": str(msg.get("message_id")),
                },
            )

        # Handle edited messages
        if "edited_message" in payload:
            msg = payload["edited_message"]
            return WebhookEvent(
                event_type="message_edited",
                platform="telegram",
                timestamp=datetime.fromtimestamp(msg.get("edit_date", msg.get("date", 0))),
                raw_payload=payload,
                metadata={
                    "channel_id": str(msg.get("chat", {}).get("id")),
                    "user_id": str(msg.get("from", {}).get("id")),
                    "message_id": str(msg.get("message_id")),
                },
            )

        # Handle callback queries (button clicks)
        if "callback_query" in payload:
            query = payload["callback_query"]
            return WebhookEvent(
                event_type="callback_query",
                platform="telegram",
                timestamp=datetime.now(),
                raw_payload=payload,
                metadata={
                    "channel_id": str(query.get("message", {}).get("chat", {}).get("id")),
                    "user_id": str(query.get("from", {}).get("id")),
                    "message_id": str(query.get("message", {}).get("message_id")),
                    "callback_data": query.get("data"),
                },
            )

        # Handle channel posts
        if "channel_post" in payload:
            post = payload["channel_post"]
            return WebhookEvent(
                event_type="channel_post",
                platform="telegram",
                timestamp=datetime.fromtimestamp(post.get("date", 0)),
                raw_payload=payload,
                metadata={
                    "channel_id": str(post.get("chat", {}).get("id")),
                    "message_id": str(post.get("message_id")),
                },
            )

        return WebhookEvent(
            event_type="unknown",
            platform="telegram",
            raw_payload=payload,
        )

    async def respond_to_command(
        self,
        command: BotCommand,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
        ephemeral: bool = False,
        **kwargs: Any,
    ) -> SendMessageResponse:
        """Respond to a bot command.

        Telegram doesn't support ephemeral messages, so the ephemeral
        parameter is ignored. Includes circuit breaker protection via send_message.
        """
        channel_id = command.channel.id if command.channel else kwargs.get("channel_id")
        if not channel_id:
            return SendMessageResponse(
                success=False,
                error="No channel ID available for command response",
            )

        # Get reply_to message_id from command metadata
        reply_to = kwargs.get("reply_to") or command.metadata.get("message_id")

        return await self.send_message(
            channel_id=channel_id,
            text=text,
            blocks=blocks,
            thread_id=reply_to,
        )

    async def respond_to_interaction(
        self,
        interaction: UserInteraction,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
        replace_original: bool = False,
        **kwargs: Any,
    ) -> SendMessageResponse:
        """Respond to a user interaction (button click).

        If replace_original is True, edits the original message.
        Otherwise, answers the callback query with a notification.
        Includes circuit breaker protection via answer_callback_query and update_message.

        Args:
            interaction: The interaction event
            text: Response text
            blocks: Rich content blocks
            replace_original: If True, replace the original message
            **kwargs: Platform-specific options

        Returns:
            SendMessageResponse with status
        """
        # First, acknowledge the callback query
        await self.answer_callback_query(
            interaction.id, text=text if not replace_original else None
        )

        if replace_original and interaction.message_id:
            # Edit the original message
            return await self.update_message(
                channel_id=interaction.channel.id,
                message_id=interaction.message_id,
                text=text,
                blocks=blocks,
            )

        # Return success response for acknowledgment-only case
        return SendMessageResponse(
            success=True,
            message_id=interaction.message_id,
            channel_id=interaction.channel.id if interaction.channel else None,
        )
