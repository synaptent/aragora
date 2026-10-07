"""
iMessage Connector via BlueBubbles.

Implements ChatPlatformConnector for iMessage using BlueBubbles server.
Includes circuit breaker protection for fault tolerance.

Requirements:
- BlueBubbles server running (https://bluebubbles.app/)
- Mac with Messages.app configured
- BlueBubbles server URL and password

Environment Variables:
- BLUEBUBBLES_URL: URL to BlueBubbles server (e.g., http://localhost:1234)
- BLUEBUBBLES_PASSWORD: Server password
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

try:
    import httpx

    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

from .base import ChatPlatformConnector
from .models import (
    BotCommand,
    ChatChannel,
    ChatEvidence,
    ChatMessage,
    ChatUser,
    FileAttachment,
    MessageType,
    SendMessageResponse,
    UserInteraction,
    VoiceMessage,
    WebhookEvent,
)

# Environment configuration
# In production, BLUEBUBBLES_URL must be set explicitly
_bluebubbles_default = (
    "http://localhost:1234" if os.environ.get("ARAGORA_ENV", "").lower() != "production" else ""
)
BLUEBUBBLES_URL = os.environ.get("BLUEBUBBLES_URL", _bluebubbles_default)
BLUEBUBBLES_PASSWORD = os.environ.get("BLUEBUBBLES_PASSWORD", "")


class IMessageConnector(ChatPlatformConnector):
    """
    iMessage connector using BlueBubbles server.

    BlueBubbles is a server that runs on macOS and provides a REST API
    for sending and receiving iMessages. This enables cross-platform
    iMessage access.

    Supports:
    - Sending text messages
    - Receiving messages via webhook
    - File attachments (images, documents)
    - Tapbacks/reactions
    - Read receipts
    - Typing indicators

    Limitations:
    - Requires BlueBubbles server on a Mac
    - No rich blocks/buttons (iMessage has limited interactive elements)
    - Message editing not supported

    All HTTP operations include circuit breaker protection for fault tolerance.
    """

    def __init__(
        self,
        server_url: str | None = None,
        password: str | None = None,
        **config: Any,
    ):
        """
        Initialize iMessage connector.

        Args:
            server_url: URL to BlueBubbles server
            password: BlueBubbles server password
            **config: Additional configuration
        """
        self._server_url = (server_url or BLUEBUBBLES_URL).rstrip("/")
        self._password = password or BLUEBUBBLES_PASSWORD

        super().__init__(
            bot_token=self._password,  # Use password as "token"
            webhook_url=config.get("webhook_url"),
            **config,
        )

    @property
    def platform_name(self) -> str:
        return "imessage"

    @property
    def platform_display_name(self) -> str:
        return "iMessage"

    @property
    def is_configured(self) -> bool:
        """Check if the connector has minimum required configuration."""
        return bool(self._server_url and self._password)

    def _get_headers(self) -> dict[str, str]:
        """Get headers for BlueBubbles API requests."""
        return {
            "Content-Type": "application/json",
        }

    def _get_params(self) -> dict[str, str]:
        """Get query parameters for BlueBubbles API requests."""
        return {
            "password": self._password,
        }

    async def send_message(
        self,
        channel_id: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
        thread_id: str | None = None,
        **kwargs: Any,
    ) -> SendMessageResponse:
        """Send a message to an iMessage chat.

        Args:
            channel_id: Chat GUID (e.g., iMessage;-;+1234567890)
            text: Message text
            blocks: Ignored - iMessage doesn't support rich blocks
            thread_id: Ignored - iMessage doesn't have threads
            **kwargs: Additional options

        Returns:
            SendMessageResponse with status
        """
        if not HTTPX_AVAILABLE:
            raise RuntimeError("httpx is required for iMessage connector")

        # Check circuit breaker
        can_proceed, cb_error = self._check_circuit_breaker()
        if not can_proceed:
            return SendMessageResponse(
                success=False,
                error=cb_error,
            )

        payload = {
            "chatGuid": channel_id,
            "message": text,
            "method": "private-api",  # Use private API for better reliability
        }

        # Add subject if provided
        if kwargs.get("subject"):
            payload["subject"] = kwargs["subject"]

        # Add effect if provided (e.g., slam, loud, gentle)
        if kwargs.get("effect"):
            payload["effectId"] = kwargs["effect"]

        try:
            async with httpx.AsyncClient(timeout=self._request_timeout) as client:
                response = await client.post(
                    f"{self._server_url}/api/v1/message/text",
                    headers=self._get_headers(),
                    params=self._get_params(),
                    json=payload,
                )

                if response.status_code == 429:
                    self._record_failure(Exception("Rate limit exceeded (429)"))
                    return SendMessageResponse(
                        success=False,
                        error="Rate limit exceeded",
                    )

                if response.status_code >= 400:
                    error_text = response.text[:200]
                    self._record_failure(Exception(f"HTTP {response.status_code}: {error_text}"))
                    return SendMessageResponse(
                        success=False,
                        error=f"HTTP {response.status_code}: {error_text}",
                    )

                self._record_success()
                data = response.json() if response.text else {}
                message_data = data.get("data", {})

                return SendMessageResponse(
                    success=True,
                    message_id=message_data.get("guid", str(datetime.now().timestamp())),
                    channel_id=channel_id,
                    timestamp=datetime.now().isoformat(),
                )
        except (httpx.HTTPError, OSError) as e:
            self._record_failure(e)
            raise RuntimeError(f"Failed to send iMessage to chat {channel_id}") from e

    async def update_message(
        self,
        channel_id: str,
        message_id: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> SendMessageResponse:
        """Update an existing message - NOT SUPPORTED by iMessage.

        iMessage does not support message editing.
        Returns an error response.
        """
        return SendMessageResponse(
            success=False,
            error="iMessage does not support message editing",
        )

    async def delete_message(
        self,
        channel_id: str,
        message_id: str,
        **kwargs: Any,
    ) -> bool:
        """Delete a message - NOT SUPPORTED by iMessage.

        iMessage does not support message deletion.
        Returns False.
        """
        logger.warning("iMessage does not support message deletion")
        return False

    async def upload_file(
        self,
        channel_id: str,
        content: bytes,
        filename: str,
        content_type: str = "application/octet-stream",
        title: str | None = None,
        thread_id: str | None = None,
        **kwargs: Any,
    ) -> FileAttachment:
        """Upload and send a file attachment."""
        import base64

        if not HTTPX_AVAILABLE:
            raise RuntimeError("httpx is required for iMessage connector")

        # Check circuit breaker
        can_proceed, cb_error = self._check_circuit_breaker()
        if not can_proceed:
            raise RuntimeError(cb_error)

        # BlueBubbles accepts base64-encoded attachments
        base64_content = base64.b64encode(content).decode("utf-8")

        payload = {
            "chatGuid": channel_id,
            "attachment": {
                "data": base64_content,
                "name": filename,
            },
            "method": "private-api",
        }

        if title:
            payload["message"] = title

        try:
            async with httpx.AsyncClient(timeout=self._request_timeout * 2) as client:
                response = await client.post(
                    f"{self._server_url}/api/v1/message/attachment",
                    headers=self._get_headers(),
                    params=self._get_params(),
                    json=payload,
                )

                if response.status_code >= 400:
                    error_text = response.text[:200]
                    self._record_failure(Exception(f"Upload failed: {error_text}"))
                    raise RuntimeError(f"Upload failed: {error_text}")

                self._record_success()
                data = response.json() if response.text else {}
                message_data = data.get("data", {})

                return FileAttachment(
                    id=message_data.get("guid", str(datetime.now().timestamp())),
                    filename=filename,
                    content_type=content_type,
                    size=len(content),
                )
        except (httpx.HTTPError, OSError) as e:
            self._record_failure(e)
            raise RuntimeError(
                f"Failed to upload iMessage attachment {filename!r} to chat {channel_id}"
            ) from e

    async def download_file(
        self,
        file_id: str,
        **kwargs: Any,
    ) -> FileAttachment:
        """Download an attachment by ID."""
        if not HTTPX_AVAILABLE:
            raise RuntimeError("httpx is required for iMessage connector")

        # Check circuit breaker
        can_proceed, cb_error = self._check_circuit_breaker()
        if not can_proceed:
            raise RuntimeError(cb_error)

        try:
            async with httpx.AsyncClient(timeout=self._request_timeout * 2) as client:
                response = await client.get(
                    f"{self._server_url}/api/v1/attachment/{file_id}/download",
                    params=self._get_params(),
                )

                if response.status_code >= 400:
                    self._record_failure(Exception(f"Download failed: {response.status_code}"))
                    raise RuntimeError(f"Download failed: {response.status_code}")

                self._record_success()
                content = response.content
                content_type = response.headers.get("content-type", "application/octet-stream")
                filename = kwargs.get("filename", f"attachment_{file_id}")

                return FileAttachment(
                    id=file_id,
                    filename=filename,
                    content_type=content_type,
                    size=len(content),
                    content=content,
                )
        except (httpx.HTTPError, OSError) as e:
            self._record_failure(e)
            raise RuntimeError(f"Failed to download iMessage attachment {file_id}") from e

    async def send_typing_indicator(
        self,
        channel_id: str,
        **kwargs: Any,
    ) -> bool:
        """Send typing indicator.

        iMessage supports typing indicators via BlueBubbles.
        """
        if not HTTPX_AVAILABLE:
            return False

        can_proceed, _ = self._check_circuit_breaker()
        if not can_proceed:
            return False

        try:
            async with httpx.AsyncClient(timeout=self._request_timeout) as client:
                response = await client.post(
                    f"{self._server_url}/api/v1/chat/{channel_id}/typing",
                    params=self._get_params(),
                )

                if response.status_code < 400:
                    self._record_success()
                    return True
                return False
        except (httpx.HTTPError, OSError) as e:
            logger.debug("Typing indicator error: %s", e)
            return False

    async def send_tapback(
        self,
        channel_id: str,
        message_id: str,
        tapback_type: str,
        **kwargs: Any,
    ) -> bool:
        """Send a tapback (reaction) to a message.

        Args:
            channel_id: Chat GUID
            message_id: Message GUID to react to
            tapback_type: One of: love, like, dislike, laugh, emphasize, question
        """
        if not HTTPX_AVAILABLE:
            raise RuntimeError("httpx is required for iMessage connector")

        can_proceed, cb_error = self._check_circuit_breaker()
        if not can_proceed:
            logger.warning("Circuit breaker open: %s", cb_error)
            return False

        # Map tapback types to BlueBubbles API values
        tapback_map = {
            "love": 2000,
            "like": 2001,
            "dislike": 2002,
            "laugh": 2003,
            "emphasize": 2004,
            "question": 2005,
        }

        tapback_value = tapback_map.get(tapback_type.lower())
        if tapback_value is None:
            logger.warning("Unknown tapback type: %s", tapback_type)
            return False

        try:
            async with httpx.AsyncClient(timeout=self._request_timeout) as client:
                response = await client.post(
                    f"{self._server_url}/api/v1/message/{message_id}/tapback",
                    headers=self._get_headers(),
                    params=self._get_params(),
                    json={
                        "chatGuid": channel_id,
                        "tapback": tapback_value,
                    },
                )

                if response.status_code < 400:
                    self._record_success()
                    return True
                else:
                    self._record_failure(Exception(f"Tapback failed: {response.status_code}"))
                    return False
        except (httpx.HTTPError, OSError) as e:
            self._record_failure(e)
            raise RuntimeError(
                f"Failed to send iMessage tapback {tapback_type!r} for message {message_id}"
            ) from e

    async def mark_read(
        self,
        channel_id: str,
        **kwargs: Any,
    ) -> bool:
        """Mark a chat as read."""
        if not HTTPX_AVAILABLE:
            return False

        can_proceed, _ = self._check_circuit_breaker()
        if not can_proceed:
            return False

        try:
            async with httpx.AsyncClient(timeout=self._request_timeout) as client:
                response = await client.post(
                    f"{self._server_url}/api/v1/chat/{channel_id}/read",
                    params=self._get_params(),
                )

                if response.status_code < 400:
                    self._record_success()
                    return True
                return False
        except (httpx.HTTPError, OSError) as e:
            logger.debug("Mark read error: %s", e)
            return False

    def verify_webhook(
        self,
        headers: dict[str, str],
        body: bytes,
    ) -> bool:
        """Verify webhook request.

        BlueBubbles webhooks can be verified via the password parameter
        or custom headers configured in the server.

        Note: BlueBubbles is a local-only service. Verification relies on
        network-level security. In production, this returns False unless
        ARAGORA_ALLOW_UNVERIFIED_WEBHOOKS is explicitly set.
        """
        env = os.environ.get("ARAGORA_ENV", "production").lower()
        is_production = env not in ("development", "dev", "local", "test")
        if is_production:
            if os.environ.get("ARAGORA_ALLOW_UNVERIFIED_WEBHOOKS", "").lower() not in (
                "1",
                "true",
                "yes",
            ):
                logger.error(
                    "SECURITY: iMessage/BlueBubbles webhook has no cryptographic verification. "
                    "Set ARAGORA_ALLOW_UNVERIFIED_WEBHOOKS=true if network-level security is in place."
                )
                return False
        return True

    def parse_webhook_event(
        self,
        headers: dict[str, str],
        body: bytes,
    ) -> WebhookEvent:
        """Parse a BlueBubbles webhook payload into a WebhookEvent."""
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            return WebhookEvent(
                event_type="unknown",
                platform="imessage",
                raw_payload={},
            )

        event_type = payload.get("type", "unknown")
        data = payload.get("data", {})

        # Map BlueBubbles event types to our event types
        if event_type == "new-message":
            event_type = "message"
        elif event_type == "updated-message":
            event_type = "message_updated"
        elif event_type == "typing-indicator":
            event_type = "typing"

        # Extract message info
        chat_guid = data.get("chats", [{}])[0].get("guid", "") if data.get("chats") else ""
        sender = data.get("handle", {}).get("id", "") if data.get("handle") else ""

        return WebhookEvent(
            event_type=event_type,
            platform="imessage",
            timestamp=(
                datetime.fromtimestamp(data.get("dateCreated", 0) / 1000)
                if data.get("dateCreated")
                else datetime.now()
            ),
            raw_payload=payload,
            metadata={
                "chat_guid": chat_guid,
                "sender": sender,
                "message_guid": data.get("guid"),
            },
        )

    async def parse_message(
        self,
        payload: dict[str, Any],
        **kwargs: Any,
    ) -> ChatMessage:
        """Parse a BlueBubbles message into ChatMessage."""
        data = payload.get("data", payload)

        # Get chat info
        chats = data.get("chats", [])
        chat = chats[0] if chats else {}
        chat_guid = chat.get("guid", "")

        # Get sender info
        handle = data.get("handle", {})
        sender_id = handle.get("id", "")
        sender_name = handle.get("firstName") or handle.get("id", "Unknown")

        # Determine message type
        msg_type = MessageType.TEXT
        attachments = data.get("attachments", [])
        if attachments:
            first_attachment = attachments[0]
            mime_type = first_attachment.get("mimeType", "")
            if mime_type.startswith("audio/"):
                msg_type = MessageType.VOICE
            else:
                msg_type = MessageType.FILE

        # Build channel and author
        channel = ChatChannel(
            id=chat_guid,
            platform="imessage",
            name=chat.get("displayName") or chat_guid,
            is_private=not chat.get("isGroup", False),
            is_dm=not chat.get("isGroup", False),
        )

        author = ChatUser(
            id=sender_id,
            platform="imessage",
            username=sender_id,
            display_name=sender_name,
        )

        return ChatMessage(
            id=data.get("guid", ""),
            platform="imessage",
            channel=channel,
            author=author,
            content=data.get("text", ""),
            message_type=msg_type,
            timestamp=(
                datetime.fromtimestamp(data.get("dateCreated", 0) / 1000)
                if data.get("dateCreated")
                else datetime.now()
            ),
            metadata={
                "attachments": attachments,
                "subject": data.get("subject"),
                "is_from_me": data.get("isFromMe", False),
                "date_read": data.get("dateRead"),
                "date_delivered": data.get("dateDelivered"),
            },
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

        iMessage doesn't have formal slash commands, so this handles
        messages that are recognized as commands.
        """
        channel_id = command.channel.id if command.channel else kwargs.get("channel_id")
        if not channel_id:
            return SendMessageResponse(
                success=False,
                error="No channel ID available for command response",
            )

        return await self.send_message(
            channel_id=channel_id,
            text=text,
            blocks=blocks,
        )

    async def respond_to_interaction(
        self,
        interaction: UserInteraction,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
        replace_original: bool = False,
        **kwargs: Any,
    ) -> SendMessageResponse:
        """Respond to a user interaction.

        iMessage has limited interactive elements.
        This is implemented for interface compatibility.
        """
        channel_id = interaction.channel.id if interaction.channel else kwargs.get("channel_id")
        if not channel_id:
            return SendMessageResponse(
                success=False,
                error="No channel ID available for interaction response",
            )

        return await self.send_message(
            channel_id=channel_id,
            text=text,
            blocks=blocks,
        )

    def format_blocks(
        self,
        title: str | None = None,
        body: str | None = None,
        fields: list[tuple[str, str]] | None = None,
        actions: list[Any] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Format content as blocks - NOT SUPPORTED.

        iMessage doesn't support rich text blocks.
        Returns empty list.
        """
        return []

    def format_button(
        self,
        text: str,
        action_id: str,
        value: str | None = None,
        style: str = "default",
        url: str | None = None,
    ) -> dict[str, Any]:
        """Format a button - NOT SUPPORTED.

        iMessage doesn't have buttons.
        Returns empty dict.
        """
        return {}

    async def get_channel_info(
        self,
        channel_id: str,
        **kwargs: Any,
    ) -> ChatChannel | None:
        """Get information about a chat."""
        if not HTTPX_AVAILABLE:
            raise RuntimeError("httpx is required for iMessage connector")

        can_proceed, cb_error = self._check_circuit_breaker()
        if not can_proceed:
            raise RuntimeError(cb_error)

        try:
            async with httpx.AsyncClient(timeout=self._request_timeout) as client:
                response = await client.get(
                    f"{self._server_url}/api/v1/chat/{channel_id}",
                    params=self._get_params(),
                )

                if response.status_code >= 400:
                    self._record_failure(Exception("Failed to get chat"))
                    return None

                self._record_success()
                data = response.json()
                chat = data.get("data", {})

                return ChatChannel(
                    id=channel_id,
                    platform="imessage",
                    name=chat.get("displayName") or channel_id,
                    is_private=not chat.get("isGroup", False),
                    is_dm=not chat.get("isGroup", False),
                    metadata={
                        "participants": chat.get("participants", []),
                        "chat_identifier": chat.get("chatIdentifier"),
                    },
                )
        except (httpx.HTTPError, OSError) as e:
            self._record_failure(e)
            raise RuntimeError(f"Failed to get iMessage chat info for {channel_id}") from e

    async def get_user_info(
        self,
        user_id: str,
        **kwargs: Any,
    ) -> ChatUser | None:
        """Get information about a user (contact)."""
        if not HTTPX_AVAILABLE:
            return ChatUser(
                id=user_id,
                platform="imessage",
                username=user_id,
            )

        can_proceed, _ = self._check_circuit_breaker()
        if not can_proceed:
            return ChatUser(
                id=user_id,
                platform="imessage",
                username=user_id,
            )

        try:
            async with httpx.AsyncClient(timeout=self._request_timeout) as client:
                response = await client.get(
                    f"{self._server_url}/api/v1/handle/{user_id}",
                    params=self._get_params(),
                )

                if response.status_code >= 400:
                    return ChatUser(
                        id=user_id,
                        platform="imessage",
                        username=user_id,
                    )

                self._record_success()
                data = response.json()
                handle = data.get("data", {})

                return ChatUser(
                    id=user_id,
                    platform="imessage",
                    username=user_id,
                    display_name=handle.get("firstName") or user_id,
                    metadata=handle,
                )
        except (httpx.HTTPError, OSError) as e:
            logger.warning("Failed to get user info for %s, returning default: %s", user_id, e)
            return ChatUser(
                id=user_id,
                platform="imessage",
                username=user_id,
            )

    async def extract_evidence(
        self,
        message: ChatMessage,
        **kwargs: Any,
    ) -> ChatEvidence:
        """Extract evidence from a message for debate."""
        evidence_id = hashlib.sha256(
            f"imessage:{message.channel.id}:{message.id}".encode()
        ).hexdigest()[:16]

        return ChatEvidence(
            id=evidence_id,
            source_type="chat",
            source_id=message.id,
            platform="imessage",
            channel_id=message.channel.id,
            channel_name=message.channel.name,
            content=message.content,
            title=message.content[:100] if message.content else "",
            author_id=message.author.id,
            author_name=message.author.display_name or message.author.username,
            timestamp=message.timestamp,
            source_message=message,
            metadata=message.metadata,
        )

    async def get_voice_message(
        self,
        file_id: str,
        **kwargs: Any,
    ) -> VoiceMessage | None:
        """Retrieve a voice message for transcription."""
        try:
            attachment = await self.download_file(file_id)
            if attachment.content:
                # VoiceMessage requires context data (id, channel, author) from kwargs
                return VoiceMessage(
                    id=kwargs.get("id", file_id),
                    channel=kwargs["channel"],  # Required from caller
                    author=kwargs["author"],  # Required from caller
                    duration_seconds=kwargs.get("duration", 0.0),
                    file=attachment,
                )
        except (httpx.HTTPError, OSError, KeyError) as e:
            logger.error("Failed to get voice message: %s", e)
        return None

    async def test_connection(self) -> dict[str, Any]:
        """Test the connection to BlueBubbles server."""
        if not HTTPX_AVAILABLE:
            return {
                "platform": self.platform_name,
                "success": False,
                "error": "httpx not available",
            }

        try:
            async with httpx.AsyncClient(timeout=self._request_timeout) as client:
                response = await client.get(
                    f"{self._server_url}/api/v1/server/info",
                    params=self._get_params(),
                )

                if response.status_code < 400:
                    data = response.json()
                    server_info = data.get("data", {})
                    return {
                        "platform": self.platform_name,
                        "success": True,
                        "server_url": self._server_url,
                        "os_version": server_info.get("os_version"),
                        "server_version": server_info.get("server_version"),
                        "private_api": server_info.get("private_api"),
                    }
                else:
                    return {
                        "platform": self.platform_name,
                        "success": False,
                        "error": f"HTTP {response.status_code}",
                    }
        except (httpx.HTTPError, OSError) as e:
            logger.warning("iMessage health check failed: %s", e)
            return {
                "platform": self.platform_name,
                "success": False,
                "error": "Health check failed",
            }

    async def list_chats(
        self,
        limit: int = 25,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List recent chats."""
        if not HTTPX_AVAILABLE:
            raise RuntimeError("httpx is required for iMessage connector")

        can_proceed, cb_error = self._check_circuit_breaker()
        if not can_proceed:
            raise RuntimeError(cb_error)

        try:
            async with httpx.AsyncClient(timeout=self._request_timeout) as client:
                response = await client.get(
                    f"{self._server_url}/api/v1/chat",
                    params={
                        **self._get_params(),
                        "limit": str(limit),
                        "offset": str(offset),
                        "sort": "lastmessage",
                    },
                )

                if response.status_code >= 400:
                    self._record_failure(Exception("Failed to list chats"))
                    raise RuntimeError(f"Failed to list chats: {response.status_code}")

                self._record_success()
                data = response.json()
                return data.get("data", [])
        except (httpx.HTTPError, OSError) as e:
            self._record_failure(e)
            raise RuntimeError("Failed to list iMessage chats") from e

    async def get_messages(
        self,
        channel_id: str,
        limit: int = 25,
        offset: int = 0,
    ) -> list[ChatMessage]:
        """Get messages from a chat."""
        if not HTTPX_AVAILABLE:
            raise RuntimeError("httpx is required for iMessage connector")

        can_proceed, cb_error = self._check_circuit_breaker()
        if not can_proceed:
            raise RuntimeError(cb_error)

        try:
            async with httpx.AsyncClient(timeout=self._request_timeout) as client:
                response = await client.get(
                    f"{self._server_url}/api/v1/chat/{channel_id}/message",
                    params={
                        **self._get_params(),
                        "limit": str(limit),
                        "offset": str(offset),
                        "sort": "DESC",
                    },
                )

                if response.status_code >= 400:
                    self._record_failure(Exception("Failed to get messages"))
                    raise RuntimeError(f"Failed to get messages: {response.status_code}")

                self._record_success()
                data = response.json()
                messages_data = data.get("data", [])

                messages = []
                for msg_data in messages_data:
                    msg = await self.parse_message({"data": msg_data})
                    messages.append(msg)

                return messages
        except (httpx.HTTPError, OSError) as e:
            self._record_failure(e)
            raise RuntimeError(f"Failed to get iMessage messages for chat {channel_id}") from e


__all__ = ["IMessageConnector"]
