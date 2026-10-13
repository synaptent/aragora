"""
Signal Messenger Connector.

Implements ChatPlatformConnector for Signal using signal-cli REST API.
Includes circuit breaker protection for fault tolerance.

Requirements:
- signal-cli REST API running (https://github.com/bbernhard/signal-cli-rest-api)
- Registered Signal phone number

Environment Variables:
- SIGNAL_CLI_URL: URL to signal-cli REST API (e.g., http://localhost:8080)
- SIGNAL_PHONE_NUMBER: Registered Signal phone number (e.g., +1234567890)
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
# In production, SIGNAL_CLI_URL must be set explicitly
_signal_cli_default = (
    "http://localhost:8080" if os.environ.get("ARAGORA_ENV", "").lower() != "production" else ""
)
SIGNAL_CLI_URL = os.environ.get("SIGNAL_CLI_URL", _signal_cli_default)
SIGNAL_PHONE_NUMBER = os.environ.get("SIGNAL_PHONE_NUMBER", "")


class SignalConnector(ChatPlatformConnector):
    """
    Signal connector using signal-cli REST API.

    Supports:
    - Sending text messages to individuals and groups
    - Receiving messages via webhook
    - File attachments (images, documents)
    - Voice messages (audio)
    - Reactions (limited - Signal uses emoji reactions)

    Limitations:
    - No message editing (Signal protocol doesn't support it)
    - No rich blocks/buttons (Signal has no interactive elements)
    - Reactions are emoji-only

    All HTTP operations include circuit breaker protection for fault tolerance.
    """

    def __init__(
        self,
        api_url: str | None = None,
        phone_number: str | None = None,
        **config: Any,
    ):
        """
        Initialize Signal connector.

        Args:
            api_url: URL to signal-cli REST API
            phone_number: Registered Signal phone number
            **config: Additional configuration
        """
        self._api_url = (api_url or SIGNAL_CLI_URL).rstrip("/")
        self._phone_number = phone_number or SIGNAL_PHONE_NUMBER

        super().__init__(
            bot_token=self._phone_number,  # Use phone number as "token"
            webhook_url=config.get("webhook_url"),
            **config,
        )

    @property
    def platform_name(self) -> str:
        return "signal"

    @property
    def platform_display_name(self) -> str:
        return "Signal"

    @property
    def is_configured(self) -> bool:
        """Check if the connector has minimum required configuration."""
        return bool(self._api_url and self._phone_number)

    async def send_message(
        self,
        channel_id: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
        thread_id: str | None = None,
        **kwargs: Any,
    ) -> SendMessageResponse:
        """Send a message to a Signal recipient (individual or group).

        Args:
            channel_id: Phone number (e.g., +1234567890) or group ID
            text: Message text
            blocks: Ignored - Signal doesn't support rich blocks
            thread_id: Ignored - Signal doesn't support threads
            **kwargs: Additional options (attachments, mentions)

        Returns:
            SendMessageResponse with status
        """
        if not HTTPX_AVAILABLE:
            raise RuntimeError("httpx is required for Signal connector")

        # Check circuit breaker
        can_proceed, cb_error = self._check_circuit_breaker()
        if not can_proceed:
            return SendMessageResponse(
                success=False,
                error=cb_error,
            )

        # Determine if this is a group or individual
        is_group = channel_id.startswith("group.")

        payload: dict[str, Any] = {
            "message": text,
            "number": self._phone_number,
        }

        if is_group:
            payload["recipients"] = [channel_id]
        else:
            payload["recipients"] = [channel_id]

        # Handle attachments
        attachments = kwargs.get("attachments", [])
        if attachments:
            payload["base64_attachments"] = attachments

        try:
            async with httpx.AsyncClient(timeout=self._request_timeout) as client:
                response = await client.post(
                    f"{self._api_url}/v2/send",
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

                # Signal CLI v2 API returns timestamps
                data = response.json() if response.text else {}
                timestamp = data.get("timestamp", int(datetime.now().timestamp() * 1000))

                return SendMessageResponse(
                    success=True,
                    message_id=str(timestamp),
                    channel_id=channel_id,
                    timestamp=datetime.fromtimestamp(timestamp / 1000).isoformat(),
                )
        except (httpx.HTTPError, httpx.TimeoutException, OSError, json.JSONDecodeError) as e:
            self._record_failure(e)
            raise RuntimeError("Failed to send Signal message") from e

    async def update_message(
        self,
        channel_id: str,
        message_id: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> SendMessageResponse:
        """Update an existing message - NOT SUPPORTED by Signal.

        Signal protocol does not support message editing.
        Returns an error response.
        """
        return SendMessageResponse(
            success=False,
            error="Signal does not support message editing",
        )

    async def delete_message(
        self,
        channel_id: str,
        message_id: str,
        **kwargs: Any,
    ) -> bool:
        """Delete a message - LIMITED SUPPORT.

        Signal supports "delete for everyone" within a time window.
        This is a best-effort operation.
        """
        if not HTTPX_AVAILABLE:
            raise RuntimeError("httpx is required for Signal connector")

        # Check circuit breaker
        can_proceed, cb_error = self._check_circuit_breaker()
        if not can_proceed:
            logger.warning("Circuit breaker open: %s", cb_error)
            return False

        # Signal delete requires target timestamp
        try:
            timestamp = int(message_id)
        except ValueError:
            logger.warning("Invalid message_id for Signal delete: %s", message_id)
            return False

        is_group = channel_id.startswith("group.")

        try:
            async with httpx.AsyncClient(timeout=self._request_timeout) as client:
                payload: dict[str, Any] = {
                    "number": self._phone_number,
                    "target_timestamp": timestamp,
                }

                if is_group:
                    payload["group_id"] = channel_id
                else:
                    payload["recipient"] = channel_id

                response = await client.post(
                    f"{self._api_url}/v1/delete",
                    json=payload,
                )

                if response.status_code < 400:
                    self._record_success()
                    return True
                else:
                    self._record_failure(Exception(f"Delete failed: {response.status_code}"))
                    return False
        except (httpx.HTTPError, httpx.TimeoutException, OSError) as e:
            self._record_failure(e)
            raise RuntimeError("Failed to delete Signal message") from e

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
        """Upload and send a file attachment.

        Signal supports attachments inline with messages.
        """
        import base64

        if not HTTPX_AVAILABLE:
            raise RuntimeError("httpx is required for Signal connector")

        # Check circuit breaker
        can_proceed, cb_error = self._check_circuit_breaker()
        if not can_proceed:
            raise RuntimeError(cb_error)

        # Encode file as base64
        base64_content = base64.b64encode(content).decode("utf-8")
        attachment = f"data:{content_type};filename={filename};base64,{base64_content}"

        try:
            async with httpx.AsyncClient(timeout=self._request_timeout * 2) as client:
                payload: dict[str, Any] = {
                    "message": title or filename,
                    "number": self._phone_number,
                    "recipients": [channel_id],
                    "base64_attachments": [attachment],
                }

                response = await client.post(
                    f"{self._api_url}/v2/send",
                    json=payload,
                )

                if response.status_code >= 400:
                    error_text = response.text[:200]
                    self._record_failure(Exception(f"Upload failed: {error_text}"))
                    raise RuntimeError(f"Upload failed: {error_text}")

                self._record_success()
                data = response.json() if response.text else {}
                timestamp = data.get("timestamp", int(datetime.now().timestamp() * 1000))

                return FileAttachment(
                    id=str(timestamp),
                    filename=filename,
                    content_type=content_type,
                    size=len(content),
                )
        except (httpx.HTTPError, httpx.TimeoutException, OSError, json.JSONDecodeError) as e:
            self._record_failure(e)
            raise RuntimeError("Failed to upload Signal file attachment") from e

    async def download_file(
        self,
        file_id: str,
        **kwargs: Any,
    ) -> FileAttachment:
        """Download a file by ID.

        Signal stores attachments locally after receiving.
        The file_id should be the attachment path.
        """
        if not HTTPX_AVAILABLE:
            raise RuntimeError("httpx is required for Signal connector")

        # Check circuit breaker
        can_proceed, cb_error = self._check_circuit_breaker()
        if not can_proceed:
            raise RuntimeError(cb_error)

        try:
            async with httpx.AsyncClient(timeout=self._request_timeout * 2) as client:
                response = await client.get(
                    f"{self._api_url}/v1/attachments/{file_id}",
                )

                if response.status_code >= 400:
                    self._record_failure(Exception(f"Download failed: {response.status_code}"))
                    raise RuntimeError(f"Download failed: {response.status_code}")

                self._record_success()
                content = response.content

                # Try to determine content type from headers
                content_type = response.headers.get("content-type", "application/octet-stream")
                filename = kwargs.get("filename", f"attachment_{file_id}")

                return FileAttachment(
                    id=file_id,
                    filename=filename,
                    content_type=content_type,
                    size=len(content),
                    content=content,
                )
        except (httpx.HTTPError, httpx.TimeoutException, OSError) as e:
            self._record_failure(e)
            raise RuntimeError("Failed to download Signal attachment") from e

    async def send_voice_message(
        self,
        channel_id: str,
        audio_content: bytes,
        filename: str = "voice.mp3",
        content_type: str = "audio/mpeg",
        reply_to: str | None = None,
        **kwargs: Any,
    ) -> SendMessageResponse:
        """Send a voice message.

        Signal has native voice message support for certain formats.
        """
        try:
            attachment = await self.upload_file(
                channel_id=channel_id,
                content=audio_content,
                filename=filename,
                content_type=content_type,
                title="Voice message",
            )
            return SendMessageResponse(
                success=True,
                message_id=attachment.id,
                channel_id=channel_id,
            )
        except (httpx.HTTPError, httpx.TimeoutException, OSError, RuntimeError) as e:
            logger.error("Failed to send voice message: %s", e)
            return SendMessageResponse(
                success=False,
                error="Voice message send failed",
            )

    async def send_typing_indicator(
        self,
        channel_id: str,
        **kwargs: Any,
    ) -> bool:
        """Send typing indicator.

        Signal supports typing indicators.
        """
        if not HTTPX_AVAILABLE:
            return False

        can_proceed, _ = self._check_circuit_breaker()
        if not can_proceed:
            return False

        try:
            async with httpx.AsyncClient(timeout=self._request_timeout) as client:
                is_group = channel_id.startswith("group.")

                payload: dict[str, Any] = {
                    "number": self._phone_number,
                }

                if is_group:
                    payload["group_id"] = channel_id
                else:
                    payload["recipient"] = channel_id

                response = await client.put(
                    f"{self._api_url}/v1/typing-indicator/{self._phone_number}",
                    json=payload,
                )

                if response.status_code < 400:
                    self._record_success()
                    return True
                return False
        except (httpx.HTTPError, httpx.TimeoutException, OSError) as e:
            logger.debug("Typing indicator error: %s", e)
            return False

    async def send_reaction(
        self,
        channel_id: str,
        message_timestamp: str,
        emoji: str,
        target_author: str,
        remove: bool = False,
        **kwargs: Any,
    ) -> bool:
        """Send or remove a reaction to a message.

        Signal supports emoji reactions.

        Args:
            channel_id: Recipient phone number or group ID
            message_timestamp: Timestamp of the target message
            emoji: Emoji to react with (e.g., "")
            target_author: Phone number of the message author
            remove: If True, removes the reaction
        """
        if not HTTPX_AVAILABLE:
            raise RuntimeError("httpx is required for Signal connector")

        can_proceed, cb_error = self._check_circuit_breaker()
        if not can_proceed:
            logger.warning("Circuit breaker open: %s", cb_error)
            return False

        try:
            async with httpx.AsyncClient(timeout=self._request_timeout) as client:
                is_group = channel_id.startswith("group.")

                payload: dict[str, Any] = {
                    "number": self._phone_number,
                    "reaction": emoji,
                    "target_author": target_author,
                    "target_timestamp": int(message_timestamp),
                    "remove": remove,
                }

                if is_group:
                    payload["group_id"] = channel_id
                else:
                    payload["recipient"] = channel_id

                response = await client.post(
                    f"{self._api_url}/v1/reactions/{self._phone_number}",
                    json=payload,
                )

                if response.status_code < 400:
                    self._record_success()
                    return True
                else:
                    self._record_failure(Exception(f"Reaction failed: {response.status_code}"))
                    return False
        except (httpx.HTTPError, httpx.TimeoutException, OSError, ValueError) as e:
            self._record_failure(e)
            raise RuntimeError("Failed to send Signal reaction") from e

    def verify_webhook(
        self,
        headers: dict[str, str],
        body: bytes,
    ) -> bool:
        """Verify webhook request.

        signal-cli REST API doesn't have built-in webhook signing.
        Verification should be done via network security (e.g., firewall rules).

        SECURITY: In production, returns False unless ARAGORA_ALLOW_UNVERIFIED_WEBHOOKS
        is explicitly set, indicating network-level security is in place.
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
                    "SECURITY: Signal webhook has no cryptographic verification. "
                    "Set ARAGORA_ALLOW_UNVERIFIED_WEBHOOKS=true if network-level security is in place."
                )
                return False
        return True

    def parse_webhook_event(
        self,
        headers: dict[str, str],
        body: bytes,
    ) -> WebhookEvent:
        """Parse a Signal webhook payload into a WebhookEvent."""
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            return WebhookEvent(
                event_type="unknown",
                platform="signal",
                raw_payload={},
            )

        # signal-cli webhook format
        envelope = payload.get("envelope", payload)
        data_message = envelope.get("dataMessage", {})
        receipt_message = envelope.get("receiptMessage", {})
        typing_message = envelope.get("typingMessage", {})

        source = envelope.get("source", envelope.get("sourceNumber", ""))
        timestamp = envelope.get("timestamp", 0)

        # Determine event type
        if data_message:
            # Check if it's a reaction
            if data_message.get("reaction"):
                event_type = "reaction"
            else:
                event_type = "message"
        elif receipt_message:
            if receipt_message.get("isDelivery"):
                event_type = "delivery_receipt"
            elif receipt_message.get("isRead"):
                event_type = "read_receipt"
            else:
                event_type = "receipt"
        elif typing_message:
            event_type = "typing"
        else:
            event_type = "unknown"

        # Determine channel (group or individual)
        group_info = data_message.get("groupInfo", {})
        channel_id = group_info.get("groupId") if group_info else source

        return WebhookEvent(
            event_type=event_type,
            platform="signal",
            timestamp=datetime.fromtimestamp(timestamp / 1000) if timestamp else datetime.now(),
            raw_payload=payload,
            metadata={
                "source": source,
                "channel_id": channel_id,
                "timestamp": timestamp,
                "is_group": bool(group_info),
            },
        )

    async def parse_message(
        self,
        payload: dict[str, Any],
        **kwargs: Any,
    ) -> ChatMessage:
        """Parse a Signal message into ChatMessage."""
        envelope = payload.get("envelope", payload)
        data_message = envelope.get("dataMessage", {})

        source = envelope.get("source", envelope.get("sourceNumber", ""))
        timestamp = envelope.get("timestamp", 0)

        # Group info
        group_info = data_message.get("groupInfo", {})
        is_group = bool(group_info)
        channel_id = group_info.get("groupId", source) if is_group else source

        # Determine message type
        msg_type = MessageType.TEXT
        attachments = data_message.get("attachments", [])
        if attachments:
            first_attachment = attachments[0]
            content_type = first_attachment.get("contentType", "")
            if content_type.startswith("audio/"):
                msg_type = MessageType.VOICE
            else:
                msg_type = MessageType.FILE

        # Build channel and author
        channel = ChatChannel(
            id=channel_id,
            platform="signal",
            name=group_info.get("groupName") if is_group else source,
            is_private=not is_group,
            is_dm=not is_group,
        )

        author = ChatUser(
            id=source,
            platform="signal",
            username=source,
            display_name=envelope.get("sourceName", source),
        )

        return ChatMessage(
            id=str(timestamp),
            platform="signal",
            channel=channel,
            author=author,
            content=data_message.get("message", ""),
            message_type=msg_type,
            timestamp=datetime.fromtimestamp(timestamp / 1000) if timestamp else datetime.now(),
            metadata={
                "attachments": attachments,
                "mentions": data_message.get("mentions", []),
                "quote": data_message.get("quote"),
                "sticker": data_message.get("sticker"),
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

        Signal doesn't have formal slash commands, so this handles
        messages that start with / or are recognized as commands.
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

        Signal doesn't have interactive elements (buttons, etc.).
        This is implemented for interface compatibility but will just send a message.
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

        Signal doesn't support rich text blocks.
        Returns empty list (blocks are ignored).
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

        Signal doesn't have buttons.
        Returns empty dict.
        """
        return {}

    async def get_channel_info(
        self,
        channel_id: str,
        **kwargs: Any,
    ) -> ChatChannel | None:
        """Get information about a channel (group or contact).

        For groups, fetches group info.
        For individuals, returns basic contact info.
        """
        if not HTTPX_AVAILABLE:
            raise RuntimeError("httpx is required for Signal connector")

        can_proceed, cb_error = self._check_circuit_breaker()
        if not can_proceed:
            raise RuntimeError(cb_error)

        is_group = channel_id.startswith("group.")

        try:
            if is_group:
                # Fetch group info
                async with httpx.AsyncClient(timeout=self._request_timeout) as client:
                    response = await client.get(
                        f"{self._api_url}/v1/groups/{self._phone_number}",
                    )

                    if response.status_code >= 400:
                        self._record_failure(Exception("Failed to get groups"))
                        return None

                    self._record_success()
                    groups = response.json()

                    # Find the specific group
                    for group in groups:
                        if group.get("id") == channel_id or group.get("internal_id") == channel_id:
                            return ChatChannel(
                                id=channel_id,
                                platform="signal",
                                name=group.get("name", ""),
                                is_private=False,
                                is_dm=False,
                                metadata={
                                    "members": group.get("members", []),
                                    "internal_id": group.get("internal_id"),
                                },
                            )
                    return None
            else:
                # Individual contact - basic info
                return ChatChannel(
                    id=channel_id,
                    platform="signal",
                    name=channel_id,  # Phone number as name
                    is_private=True,
                    is_dm=True,
                )
        except (httpx.HTTPError, httpx.TimeoutException, OSError, json.JSONDecodeError) as e:
            self._record_failure(e)
            raise RuntimeError("Failed to get Signal channel info") from e

    async def get_user_info(
        self,
        user_id: str,
        **kwargs: Any,
    ) -> ChatUser | None:
        """Get information about a user.

        Signal has limited user info - primarily just phone number and profile.
        """
        if not HTTPX_AVAILABLE:
            return ChatUser(
                id=user_id,
                platform="signal",
                username=user_id,
            )

        can_proceed, _ = self._check_circuit_breaker()
        if not can_proceed:
            return ChatUser(
                id=user_id,
                platform="signal",
                username=user_id,
            )

        try:
            async with httpx.AsyncClient(timeout=self._request_timeout) as client:
                response = await client.get(
                    f"{self._api_url}/v1/profiles/{user_id}",
                )

                if response.status_code >= 400:
                    return ChatUser(
                        id=user_id,
                        platform="signal",
                        username=user_id,
                    )

                self._record_success()
                profile = response.json()

                return ChatUser(
                    id=user_id,
                    platform="signal",
                    username=user_id,
                    display_name=profile.get("name", user_id),
                    avatar_url=profile.get("avatar"),
                    metadata=profile,
                )
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            logger.debug("Signal profile lookup failed for %s: %s", user_id, e)
            return ChatUser(
                id=user_id,
                platform="signal",
                username=user_id,
            )
        except (OSError, json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Unexpected error looking up Signal user %s: %s", user_id, e)
            return ChatUser(
                id=user_id,
                platform="signal",
                username=user_id,
            )

    async def extract_evidence(
        self,
        message: ChatMessage,
        **kwargs: Any,
    ) -> ChatEvidence:
        """Extract evidence from a message for debate."""
        evidence_id = hashlib.sha256(
            f"signal:{message.channel.id}:{message.id}".encode()
        ).hexdigest()[:16]

        return ChatEvidence(
            id=evidence_id,
            source_type="chat",
            source_id=message.id,
            platform="signal",
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
                    metadata={"waveform": kwargs.get("waveform")},
                )
        except (httpx.HTTPError, httpx.TimeoutException, OSError, RuntimeError, KeyError) as e:
            logger.error("Failed to get voice message: %s", e)
        return None

    async def test_connection(self) -> dict[str, Any]:
        """Test the connection to signal-cli REST API."""
        if not HTTPX_AVAILABLE:
            return {
                "platform": self.platform_name,
                "success": False,
                "error": "httpx not available",
            }

        try:
            async with httpx.AsyncClient(timeout=self._request_timeout) as client:
                response = await client.get(f"{self._api_url}/v1/about")

                if response.status_code < 400:
                    about_info = response.json()
                    return {
                        "platform": self.platform_name,
                        "success": True,
                        "api_url": self._api_url,
                        "phone_number": self._phone_number,
                        "version": about_info.get("version"),
                        "build": about_info.get("build"),
                    }
                else:
                    return {
                        "platform": self.platform_name,
                        "success": False,
                        "error": f"HTTP {response.status_code}",
                    }
        except (httpx.HTTPError, httpx.TimeoutException, OSError, json.JSONDecodeError) as e:
            logger.warning("Signal test_connection failed: %s", e)
            return {
                "platform": self.platform_name,
                "success": False,
                "error": "Connection test failed",
            }

    async def list_groups(self) -> list[dict[str, Any]]:
        """List all Signal groups the account is a member of."""
        if not HTTPX_AVAILABLE:
            raise RuntimeError("httpx is required for Signal connector")

        can_proceed, cb_error = self._check_circuit_breaker()
        if not can_proceed:
            raise RuntimeError(cb_error)

        try:
            async with httpx.AsyncClient(timeout=self._request_timeout) as client:
                response = await client.get(
                    f"{self._api_url}/v1/groups/{self._phone_number}",
                )

                if response.status_code >= 400:
                    self._record_failure(Exception("Failed to list groups"))
                    raise RuntimeError(f"Failed to list groups: {response.status_code}")

                self._record_success()
                return response.json()
        except (httpx.HTTPError, httpx.TimeoutException, OSError, json.JSONDecodeError) as e:
            self._record_failure(e)
            raise RuntimeError("Failed to list Signal groups") from e

    async def create_group(
        self,
        name: str,
        members: list[str],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create a new Signal group.

        Args:
            name: Group name
            members: List of phone numbers to add

        Returns:
            Group info dict
        """
        if not HTTPX_AVAILABLE:
            raise RuntimeError("httpx is required for Signal connector")

        can_proceed, cb_error = self._check_circuit_breaker()
        if not can_proceed:
            raise RuntimeError(cb_error)

        try:
            async with httpx.AsyncClient(timeout=self._request_timeout) as client:
                response = await client.post(
                    f"{self._api_url}/v1/groups/{self._phone_number}",
                    json={
                        "name": name,
                        "members": members,
                    },
                )

                if response.status_code >= 400:
                    error_text = response.text[:200]
                    self._record_failure(Exception(f"Failed to create group: {error_text}"))
                    raise RuntimeError(f"Failed to create group: {error_text}")

                self._record_success()
                return response.json()
        except (httpx.HTTPError, httpx.TimeoutException, OSError, json.JSONDecodeError) as e:
            self._record_failure(e)
            raise RuntimeError("Failed to create Signal group") from e


__all__ = ["SignalConnector"]
