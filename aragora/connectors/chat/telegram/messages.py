"""
Telegram Bot Connector - Message Operations.

Contains basic messaging functionality: send, update, delete, typing.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from ..models import (
    MessageButton,
    SendMessageResponse,
)

logger = logging.getLogger(__name__)


class TelegramMessagesMixin:
    """Mixin providing message operations for TelegramConnector."""

    if TYPE_CHECKING:
        _telegram_api_request: Any
        _escape_markdown: Any
        parse_mode: Any
        _blocks_to_keyboard: Any

    async def send_message(
        self,
        channel_id: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
        thread_id: str | None = None,
        **kwargs: Any,
    ) -> SendMessageResponse:
        """Send a message to a Telegram chat.

        Uses _telegram_api_request for circuit breaker, retry, and timeout handling.
        """
        payload: dict[str, Any] = {
            "chat_id": channel_id,
            "text": self._escape_markdown(text) if self.parse_mode.startswith("Markdown") else text,
            "parse_mode": self.parse_mode,
        }

        # Reply to specific message (thread)
        if thread_id:
            payload["reply_to_message_id"] = int(thread_id)

        # Convert blocks to inline keyboard
        if blocks:
            keyboard = self._blocks_to_keyboard(blocks)
            if keyboard:
                payload["reply_markup"] = json.dumps(keyboard)

        success, data, error = await self._telegram_api_request(
            "sendMessage",
            payload=payload,
            operation="send_message",
        )

        if success and data:
            result = data.get("result", {})
            return SendMessageResponse(
                success=True,
                message_id=str(result.get("message_id")),
                channel_id=str(result.get("chat", {}).get("id")),
                timestamp=datetime.fromtimestamp(result.get("date", 0)).isoformat(),
            )

        return SendMessageResponse(success=False, error=error)

    async def update_message(
        self,
        channel_id: str,
        message_id: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> SendMessageResponse:
        """Edit an existing message.

        Uses _telegram_api_request for circuit breaker, retry, and timeout handling.
        """
        payload: dict[str, Any] = {
            "chat_id": channel_id,
            "message_id": int(message_id),
            "text": self._escape_markdown(text) if self.parse_mode.startswith("Markdown") else text,
            "parse_mode": self.parse_mode,
        }

        if blocks:
            keyboard = self._blocks_to_keyboard(blocks)
            if keyboard:
                payload["reply_markup"] = json.dumps(keyboard)

        success, _, error = await self._telegram_api_request(
            "editMessageText",
            payload=payload,
            operation="update_message",
        )

        if success:
            return SendMessageResponse(
                success=True,
                message_id=message_id,
                channel_id=channel_id,
            )

        return SendMessageResponse(success=False, error=error)

    async def delete_message(
        self,
        channel_id: str,
        message_id: str,
        **kwargs: Any,
    ) -> bool:
        """Delete a message.

        Uses _telegram_api_request for circuit breaker, retry, and timeout handling.
        """
        success, _, error = await self._telegram_api_request(
            "deleteMessage",
            payload={
                "chat_id": channel_id,
                "message_id": int(message_id),
            },
            operation="delete_message",
        )

        if not success and error:
            logger.warning("Delete message failed: %s", error)

        return success

    async def send_typing_indicator(
        self,
        channel_id: str,
        **kwargs: Any,
    ) -> bool:
        """Send typing indicator (chat action) to a Telegram chat.

        Uses _telegram_api_request for circuit breaker, retry, and timeout handling.
        Typing indicators expire after ~5 seconds.
        """
        success, _, error = await self._telegram_api_request(
            "sendChatAction",
            payload={
                "chat_id": channel_id,
                "action": "typing",
            },
            operation="send_typing_indicator",
            max_retries=1,  # Don't retry typing indicators
        )

        if not success:
            logger.debug("Telegram typing indicator failed: %s", error)

        return success

    def format_blocks(
        self,
        title: str | None = None,
        body: str | None = None,
        fields: list[tuple[str, str]] | None = None,
        actions: list[MessageButton] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Format content as Telegram-compatible blocks.

        Telegram uses inline keyboards for interactive elements.
        This method converts generic block structure to Telegram format.

        Args:
            title: Section title/header (unused in Telegram)
            body: Main text content (unused in Telegram)
            fields: List of (label, value) tuples (unused in Telegram)
            actions: List of interactive buttons
            **kwargs: Platform-specific options (buttons as dict list for backwards compat)
        """
        result: list[dict[str, Any]] = []

        # Telegram doesn't have rich text blocks like Slack
        # We use inline keyboard buttons for interactivity

        # Support legacy 'buttons' kwarg for backwards compatibility
        buttons = kwargs.pop("buttons", None)
        if buttons:
            result.extend(buttons)

        # Convert MessageButton objects to dict format
        if actions:
            for action in actions:
                btn_dict = self.format_button(
                    text=action.text,
                    action_id=action.action_id,
                    value=action.value,
                    style=action.style,
                    url=action.url,
                )
                result.append(btn_dict)

        return result

    def format_button(
        self,
        text: str,
        action_id: str,
        value: str | None = None,
        style: str | None = None,
        url: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Format a button for Telegram inline keyboard."""
        if url:
            return {
                "type": "url_button",
                "text": text,
                "url": url,
            }
        return {
            "type": "button",
            "text": text,
            "action_id": action_id,
            "value": value or action_id,
        }
