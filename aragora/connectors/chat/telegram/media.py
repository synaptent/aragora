"""
Telegram Bot Connector - Rich Media Operations.

Contains photo, video, animation, and media group functionality.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from ..models import SendMessageResponse

logger = logging.getLogger(__name__)


class TelegramMediaMixin:
    """Mixin providing rich media operations for TelegramConnector."""

    if TYPE_CHECKING:
        _escape_markdown: Any
        parse_mode: Any
        _blocks_to_keyboard: Any
        _telegram_api_request: Any

    async def send_photo(
        self,
        channel_id: str,
        photo: str | bytes,
        caption: str | None = None,
        thread_id: str | None = None,
        blocks: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> SendMessageResponse:
        """Send a photo to a Telegram chat.

        Uses _telegram_api_request for circuit breaker, retry, and timeout handling.

        Args:
            channel_id: Target chat ID
            photo: File path, URL, or bytes of the photo
            caption: Optional caption for the photo
            thread_id: Reply to specific message
            blocks: Inline keyboard buttons
            **kwargs: Additional parameters

        Returns:
            SendMessageResponse with success status
        """
        payload: dict[str, Any] = {"chat_id": channel_id}

        if caption:
            payload["caption"] = (
                self._escape_markdown(caption)
                if self.parse_mode.startswith("Markdown")
                else caption
            )
            payload["parse_mode"] = self.parse_mode

        if thread_id:
            payload["reply_to_message_id"] = int(thread_id)

        if blocks:
            keyboard = self._blocks_to_keyboard(blocks)
            if keyboard:
                payload["reply_markup"] = json.dumps(keyboard)

        # Determine how to send the photo
        files = None
        if isinstance(photo, bytes):
            files = {"photo": ("photo.jpg", photo, "image/jpeg")}
        else:
            # URL or file_id
            payload["photo"] = photo

        success, data, error = await self._telegram_api_request(
            "sendPhoto",
            payload=payload,
            files=files,
            operation="send_photo",
        )

        if success and data:
            msg = data.get("result", {})
            return SendMessageResponse(
                success=True,
                message_id=str(msg.get("message_id")),
                channel_id=str(msg.get("chat", {}).get("id")),
                timestamp=datetime.fromtimestamp(msg.get("date", 0)).isoformat(),
            )

        return SendMessageResponse(success=False, error=error)

    async def send_video(
        self,
        channel_id: str,
        video: str | bytes,
        caption: str | None = None,
        thread_id: str | None = None,
        duration: int | None = None,
        width: int | None = None,
        height: int | None = None,
        supports_streaming: bool = True,
        blocks: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> SendMessageResponse:
        """Send a video to a Telegram chat.

        Uses _telegram_api_request for circuit breaker, retry, and timeout handling.

        Args:
            channel_id: Target chat ID
            video: File path, URL, or bytes of the video
            caption: Optional caption for the video
            thread_id: Reply to specific message
            duration: Video duration in seconds
            width: Video width
            height: Video height
            supports_streaming: Whether the video supports streaming
            blocks: Inline keyboard buttons
            **kwargs: Additional parameters

        Returns:
            SendMessageResponse with success status
        """
        payload: dict[str, Any] = {
            "chat_id": channel_id,
            "supports_streaming": supports_streaming,
        }

        if caption:
            payload["caption"] = (
                self._escape_markdown(caption)
                if self.parse_mode.startswith("Markdown")
                else caption
            )
            payload["parse_mode"] = self.parse_mode

        if thread_id:
            payload["reply_to_message_id"] = int(thread_id)
        if duration:
            payload["duration"] = duration
        if width:
            payload["width"] = width
        if height:
            payload["height"] = height

        if blocks:
            keyboard = self._blocks_to_keyboard(blocks)
            if keyboard:
                payload["reply_markup"] = json.dumps(keyboard)

        # Determine how to send the video
        files = None
        if isinstance(video, bytes):
            files = {"video": ("video.mp4", video, "video/mp4")}
        else:
            # URL or file_id
            payload["video"] = video

        success, data, error = await self._telegram_api_request(
            "sendVideo",
            payload=payload,
            files=files,
            operation="send_video",
        )

        if success and data:
            msg = data.get("result", {})
            return SendMessageResponse(
                success=True,
                message_id=str(msg.get("message_id")),
                channel_id=str(msg.get("chat", {}).get("id")),
                timestamp=datetime.fromtimestamp(msg.get("date", 0)).isoformat(),
            )

        return SendMessageResponse(success=False, error=error)

    async def send_animation(
        self,
        channel_id: str,
        animation: str | bytes,
        caption: str | None = None,
        thread_id: str | None = None,
        blocks: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> SendMessageResponse:
        """Send an animation (GIF) to a Telegram chat.

        Uses _telegram_api_request for circuit breaker, retry, and timeout handling.

        Args:
            channel_id: Target chat ID
            animation: File path, URL, or bytes of the animation
            caption: Optional caption
            thread_id: Reply to specific message
            blocks: Inline keyboard buttons
            **kwargs: Additional parameters

        Returns:
            SendMessageResponse with success status
        """
        payload: dict[str, Any] = {"chat_id": channel_id}

        if caption:
            payload["caption"] = (
                self._escape_markdown(caption)
                if self.parse_mode.startswith("Markdown")
                else caption
            )
            payload["parse_mode"] = self.parse_mode

        if thread_id:
            payload["reply_to_message_id"] = int(thread_id)

        if blocks:
            keyboard = self._blocks_to_keyboard(blocks)
            if keyboard:
                payload["reply_markup"] = json.dumps(keyboard)

        # Handle bytes input (file upload) vs URL/file_id
        files: dict[str, Any] | None = None
        if isinstance(animation, bytes):
            files = {"animation": ("animation.gif", animation, "image/gif")}
        else:
            payload["animation"] = animation

        success, data, error = await self._telegram_api_request(
            "sendAnimation",
            payload=payload,
            files=files,
            operation="send_animation",
        )

        if success and data:
            msg = data.get("result", {})
            return SendMessageResponse(
                success=True,
                message_id=str(msg.get("message_id")),
                channel_id=str(msg.get("chat", {}).get("id")),
                timestamp=datetime.fromtimestamp(msg.get("date", 0)).isoformat(),
            )

        return SendMessageResponse(success=False, error=error)

    async def send_media_group(
        self,
        channel_id: str,
        media: list[dict[str, Any]],
        thread_id: str | None = None,
        **kwargs: Any,
    ) -> list[SendMessageResponse]:
        """Send a group of photos or videos as an album.

        Uses _telegram_api_request for circuit breaker, retry, and timeout handling.

        Args:
            channel_id: Target chat ID
            media: List of media items, each with:
                - type: "photo" or "video"
                - media: URL or file_id
                - caption: Optional caption (only first item shown)
            thread_id: Reply to specific message
            **kwargs: Additional parameters

        Returns:
            List of SendMessageResponse for each sent message
        """
        # Format media for API
        formatted_media = []
        for item in media:
            media_item = {
                "type": item.get("type", "photo"),
                "media": item.get("media"),
            }
            if "caption" in item:
                caption = item["caption"]
                media_item["caption"] = (
                    self._escape_markdown(caption)
                    if self.parse_mode.startswith("Markdown")
                    else caption
                )
                media_item["parse_mode"] = self.parse_mode
            formatted_media.append(media_item)

        payload: dict[str, Any] = {
            "chat_id": channel_id,
            "media": json.dumps(formatted_media),
        }

        if thread_id:
            payload["reply_to_message_id"] = int(thread_id)

        success, data, error = await self._telegram_api_request(
            "sendMediaGroup",
            payload=payload,
            operation="send_media_group",
        )

        if success and data:
            messages = data.get("result", [])
            return [
                SendMessageResponse(
                    success=True,
                    message_id=str(msg.get("message_id")),
                    channel_id=str(msg.get("chat", {}).get("id")),
                    timestamp=datetime.fromtimestamp(msg.get("date", 0)).isoformat(),
                )
                for msg in messages
            ]

        return [SendMessageResponse(success=False, error=error)]
