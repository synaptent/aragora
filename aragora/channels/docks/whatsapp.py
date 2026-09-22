"""
WhatsApp Dock - Channel dock implementation for WhatsApp.

Handles message delivery to WhatsApp via the Meta Graph API.

Example:
    from aragora.channels.docks.whatsapp import WhatsAppDock

    dock = WhatsAppDock({
        "access_token": "...",
        "phone_number_id": "..."
    })
    await dock.initialize()
    await dock.send_message(phone_number, message)
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

__all__ = ["WhatsAppDock"]


class WhatsAppDock(ChannelDock):
    """
    WhatsApp Business platform dock.

    Supports text messages, voice messages, and file uploads
    via the Meta Graph API.
    """

    PLATFORM = "whatsapp"
    CAPABILITIES = ChannelCapability.VOICE | ChannelCapability.FILES
    # WhatsApp has limited rich text support (no markdown)

    def __init__(self, config: dict[str, Any] | None = None):
        """
        Initialize WhatsApp dock.

        Config options:
            access_token: WhatsApp access token (or WHATSAPP_ACCESS_TOKEN env)
            phone_number_id: WhatsApp phone number ID (or WHATSAPP_PHONE_NUMBER_ID env)
        """
        super().__init__(config)
        self._access_token: str | None = None
        self._phone_number_id: str | None = None

    async def initialize(self) -> bool:
        """Initialize the WhatsApp dock."""
        self._access_token = self.config.get("access_token") or os.environ.get(
            "WHATSAPP_ACCESS_TOKEN", ""
        )
        self._phone_number_id = self.config.get("phone_number_id") or os.environ.get(
            "WHATSAPP_PHONE_NUMBER_ID", ""
        )

        if not self._access_token or not self._phone_number_id:
            logger.warning("WhatsApp credentials not configured")
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
        Send a message to WhatsApp.

        Args:
            channel_id: Recipient phone number
            message: The normalized message to send
            **kwargs: Additional options

        Returns:
            SendResult indicating success or failure
        """
        if not self._access_token or not self._phone_number_id:
            return SendResult.fail(
                error="WhatsApp credentials not configured",
                platform=self.PLATFORM,
                channel_id=channel_id,
            )

        # Check for voice message
        audio = message.get_audio_attachment()
        if audio:
            return await self._send_voice_message(channel_id, audio, message, **kwargs)

        try:
            url = f"https://graph.facebook.com/v18.0/{self._phone_number_id}/messages"
            headers = {
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            }
            payload = self._build_payload(channel_id, message, **kwargs)

            pool = get_http_pool()
            async with pool.get_session("whatsapp") as client:
                response = await client.post(url, json=payload, headers=headers, timeout=30.0)

                if response.status_code == 200:
                    data = response.json()
                    messages = data.get("messages", [])
                    message_id = messages[0].get("id") if messages else None
                    return SendResult.ok(
                        message_id=message_id,
                        platform=self.PLATFORM,
                        channel_id=channel_id,
                    )
                else:
                    error_data = response.json() if response.content else {}
                    error_msg = error_data.get("error", {}).get(
                        "message", f"HTTP {response.status_code}"
                    )
                    return SendResult.fail(
                        error=error_msg,
                        platform=self.PLATFORM,
                        channel_id=channel_id,
                    )

        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.error("WhatsApp send error: %s", e)
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
        """Build WhatsApp API payload from normalized message."""
        # Build text content (WhatsApp has limited formatting)
        text_parts = []
        if message.title:
            text_parts.append(f"*{message.title}*")  # WhatsApp bold
        if message.content:
            text_parts.append(message.to_plain_text())

        text = "\n\n".join(text_parts)

        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": channel_id,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": text[:4096],
            },
        }

        return payload

    async def _send_voice_message(
        self,
        channel_id: str,
        audio: Any,
        message: NormalizedMessage,
        **kwargs: Any,
    ) -> SendResult:
        """Send a voice message to WhatsApp."""
        try:
            from aragora.channels.normalized import MessageAttachment

            # Get audio data
            audio_data = audio.data if isinstance(audio, MessageAttachment) else audio.get("data")

            if not audio_data:
                return SendResult.fail(
                    error="No audio data provided",
                    platform=self.PLATFORM,
                    channel_id=channel_id,
                )

            # Step 1: Upload media to WhatsApp
            upload_url = f"https://graph.facebook.com/v18.0/{self._phone_number_id}/media"
            headers = {
                "Authorization": f"Bearer {self._access_token}",
            }

            pool = get_http_pool()
            async with pool.get_session("whatsapp") as client:
                # Upload audio file
                files = {
                    "file": ("voice.ogg", audio_data, "audio/ogg"),
                }
                data = {
                    "messaging_product": "whatsapp",
                    "type": "audio/ogg",
                }

                upload_response = await client.post(
                    upload_url, data=data, files=files, headers=headers, timeout=60.0
                )

                if upload_response.status_code != 200:
                    return SendResult.fail(
                        error=f"Media upload failed: HTTP {upload_response.status_code}",
                        platform=self.PLATFORM,
                        channel_id=channel_id,
                    )

                media_id = upload_response.json().get("id")
                if not media_id:
                    return SendResult.fail(
                        error="No media ID in upload response",
                        platform=self.PLATFORM,
                        channel_id=channel_id,
                    )

                # Step 2: Send message with media ID
                send_url = f"https://graph.facebook.com/v18.0/{self._phone_number_id}/messages"
                send_payload = {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": channel_id,
                    "type": "audio",
                    "audio": {"id": media_id},
                }

                send_response = await client.post(
                    send_url,
                    json=send_payload,
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "Content-Type": "application/json",
                    },
                    timeout=30.0,
                )

                if send_response.status_code == 200:
                    resp_data = send_response.json()
                    messages = resp_data.get("messages", [])
                    msg_id = messages[0].get("id") if messages else None
                    return SendResult.ok(
                        message_id=msg_id,
                        platform=self.PLATFORM,
                        channel_id=channel_id,
                    )
                else:
                    return SendResult.fail(
                        error=f"HTTP {send_response.status_code}",
                        platform=self.PLATFORM,
                        channel_id=channel_id,
                    )

        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.error("WhatsApp voice send error: %s", e)
            return SendResult.fail(
                error=str(e),
                platform=self.PLATFORM,
                channel_id=channel_id,
            )

    async def send_voice(
        self,
        channel_id: str,
        audio_data: bytes,
        text: str | None = None,
        thread_id: str | None = None,
        **kwargs: Any,
    ) -> SendResult:
        """
        Send a voice message to WhatsApp.

        WhatsApp requires uploading media first, then referencing it.
        """
        from aragora.channels.normalized import NormalizedMessage, MessageAttachment

        message = NormalizedMessage(content=text or "")
        message.attachments.append(MessageAttachment(type="audio", data=audio_data))

        return await self._send_voice_message(channel_id, message.attachments[0], message, **kwargs)
