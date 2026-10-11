"""
WhatsApp Business API Connector.

Implements ChatPlatformConnector for WhatsApp using the Cloud API.
Includes circuit breaker protection for resilient API interactions.

Environment Variables:
- WHATSAPP_ACCESS_TOKEN: Permanent access token from Meta
- WHATSAPP_PHONE_NUMBER_ID: Phone number ID from Meta
- WHATSAPP_BUSINESS_ACCOUNT_ID: Business account ID
- WHATSAPP_VERIFY_TOKEN: Webhook verification token
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime
from typing import Any, cast

from aragora.connectors.chat.models import MessageButton

logger = logging.getLogger(__name__)

try:
    import httpx  # type: ignore[import-not-found]

    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

# Distributed tracing support
try:
    from aragora.observability.tracing import build_trace_headers

    TRACING_AVAILABLE = True
except ImportError:
    TRACING_AVAILABLE = False

    def build_trace_headers() -> dict[str, str]:
        return {}


from .base import ChatPlatformConnector
from .models import (
    BotCommand,
    ChatChannel,
    ChatEvidence,
    ChatMessage,
    ChatUser,
    FileAttachment,
    InteractionType,
    MessageType,
    SendMessageResponse,
    UserInteraction,
    VoiceMessage,
    WebhookEvent,
)

# Environment configuration
WHATSAPP_ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_BUSINESS_ACCOUNT_ID = os.environ.get("WHATSAPP_BUSINESS_ACCOUNT_ID", "")
WHATSAPP_VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
WHATSAPP_APP_SECRET = os.environ.get("WHATSAPP_APP_SECRET", "")

# WhatsApp Cloud API
WHATSAPP_API_BASE = "https://graph.facebook.com/v18.0"


class WhatsAppConnector(ChatPlatformConnector):
    """
    WhatsApp connector using Meta Cloud API.

    Includes circuit breaker protection for resilient API interactions.

    Supports:
    - Sending text messages
    - Interactive messages (buttons, lists)
    - Media messages (images, documents, audio)
    - Message templates
    - Reply messages (context)
    - Webhook handling
    """

    def __init__(
        self,
        access_token: str | None = None,
        phone_number_id: str | None = None,
        business_account_id: str | None = None,
        verify_token: str | None = None,
        app_secret: str | None = None,
        **config: Any,
    ):
        """
        Initialize WhatsApp connector.

        Args:
            access_token: Meta Cloud API access token
            phone_number_id: WhatsApp Business phone number ID
            business_account_id: WhatsApp Business account ID
            verify_token: Webhook verification token
            app_secret: App secret for webhook signature verification
            **config: Additional configuration
        """
        super().__init__(
            bot_token=access_token or WHATSAPP_ACCESS_TOKEN,
            signing_secret=app_secret or WHATSAPP_APP_SECRET,
            **config,
        )
        self.phone_number_id = phone_number_id or WHATSAPP_PHONE_NUMBER_ID
        self.business_account_id = business_account_id or WHATSAPP_BUSINESS_ACCOUNT_ID
        self.verify_token = verify_token or WHATSAPP_VERIFY_TOKEN

    async def _whatsapp_api_request(
        self,
        endpoint: str,
        *,
        method: str = "POST",
        payload: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        operation: str = "api_call",
        timeout: float | None = None,
        max_retries: int = 3,
    ) -> tuple[bool, dict[str, Any] | None, str | None]:
        """
        Make a WhatsApp API request with circuit breaker, retry, and timeout.

        Centralizes the resilience pattern for all WhatsApp API calls.

        Args:
            endpoint: Full API endpoint URL
            method: HTTP method (GET, POST)
            payload: JSON payload (for application/json)
            data: Form data (for multipart)
            files: File attachments for upload
            operation: Operation name for logging
            timeout: Custom timeout (uses default if not specified)
            max_retries: Number of retries for transient failures

        Returns:
            Tuple of (success, data_dict, error_message)
        """
        if not HTTPX_AVAILABLE:
            return False, None, "httpx not available"

        can_proceed, cb_error = self._check_circuit_breaker()
        if not can_proceed:
            return False, None, cb_error or "Circuit breaker is open"

        request_timeout = timeout or self._request_timeout
        headers: dict[str, str] = {
            "Authorization": f"Bearer {self.bot_token}",
            **build_trace_headers(),
        }
        if payload and not files:
            headers["Content-Type"] = "application/json"

        last_error: str | None = None

        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=request_timeout) as client:
                    if method == "GET":
                        response = await client.get(endpoint, headers=headers)
                    elif files:
                        response = await client.post(
                            endpoint,
                            data=data,
                            files=files,
                            headers={"Authorization": f"Bearer {self.bot_token}"},
                        )
                    else:
                        response = await client.post(
                            endpoint,
                            json=payload,
                            headers=headers,
                        )

                    result = response.json()

                    # Check for API errors
                    if "error" in result:
                        error = result["error"]
                        error_code = error.get("code", 0)
                        error_msg = error.get("message", "Unknown error")

                        # Rate limit handling (codes 4, 80007, 130429)
                        if error_code in (4, 80007, 130429):
                            self._record_failure(Exception(f"Rate limited: {error_msg}"))
                            # Retry with backoff for rate limits
                            if attempt < max_retries - 1:
                                import asyncio

                                wait_time = (attempt + 1) * 2
                                await asyncio.sleep(wait_time)
                                continue
                            return False, None, f"Rate limited: {error_msg}"

                        # Auth errors - don't retry
                        if error_code in (190, 102):
                            self._record_failure(Exception(f"Auth error: {error_msg}"))
                            return False, None, f"Auth error: {error_msg}"

                        self._record_failure(Exception(error_msg))
                        return False, None, error_msg

                    self._record_success()
                    return True, result, None

            except httpx.TimeoutException as e:
                last_error = f"Request timeout: {e}"
                self._record_failure(e)
                if attempt < max_retries - 1:
                    import asyncio

                    await asyncio.sleep((attempt + 1) * 1)
                    continue
            except httpx.HTTPStatusError as e:
                last_error = f"HTTP error {e.response.status_code}"
                self._record_failure(e)
                # Server errors (5xx) - retry
                if e.response.status_code >= 500 and attempt < max_retries - 1:
                    import asyncio

                    await asyncio.sleep((attempt + 1) * 1)
                    continue
                return False, None, last_error
            except (httpx.RequestError, OSError, ValueError, RuntimeError) as e:
                last_error = "WhatsApp API request failed"
                self._record_failure(e)
                logger.warning("WhatsApp API %s error: %s", operation, e)
                return False, None, last_error

        return False, None, last_error or "Max retries exceeded"

    @property
    def platform_name(self) -> str:
        return "whatsapp"

    @property
    def platform_display_name(self) -> str:
        return "WhatsApp"

    async def send_message(
        self,
        channel_id: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
        thread_id: str | None = None,
        **kwargs: Any,
    ) -> SendMessageResponse:
        """Send a message to a WhatsApp user.

        Uses _whatsapp_api_request for circuit breaker, retry, and timeout handling.
        """
        # Build message payload
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": channel_id,  # Phone number
        }

        # Add context for replies
        if thread_id:
            payload["context"] = {"message_id": thread_id}

        # Check if interactive message (has buttons)
        interactive_blocks = [block for block in blocks or [] if block is not None]
        if interactive_blocks and any(
            block.get("type") in ("button", "list") for block in interactive_blocks
        ):
            payload["type"] = "interactive"
            payload["interactive"] = self._build_interactive(text, interactive_blocks)
        else:
            payload["type"] = "text"
            payload["text"] = {"body": text, "preview_url": True}

        success, data, error = await self._whatsapp_api_request(
            f"{WHATSAPP_API_BASE}/{self.phone_number_id}/messages",
            payload=payload,
            operation="send_message",
        )

        if success and data:
            messages = data.get("messages", [{}])
            return SendMessageResponse(
                success=True,
                message_id=messages[0].get("id") if messages else None,
                channel_id=channel_id,
                timestamp=datetime.now().isoformat(),
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
        """
        Update a message with circuit breaker protection.

        Note: WhatsApp doesn't support editing messages.
        This sends a new message instead.
        """
        logger.warning("WhatsApp doesn't support message editing, sending new message")
        return await self.send_message(
            channel_id,
            text,
            blocks,
            thread_id=message_id,  # Reply to original
        )

    async def delete_message(
        self,
        channel_id: str,
        message_id: str,
        **kwargs: Any,
    ) -> bool:
        """
        Delete a message.

        Note: WhatsApp doesn't support deleting messages via API.
        """
        logger.warning("WhatsApp doesn't support message deletion via API")
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
        """Upload and send a file as a document.

        Uses _whatsapp_api_request for circuit breaker, retry, and timeout handling.

        Args:
            channel_id: Target channel/phone number
            content: File content as bytes
            filename: Name for the file
            content_type: MIME type of the file
            title: Optional title/caption for the file
            thread_id: Ignored (WhatsApp doesn't support threads)
            **kwargs: Additional arguments (ignored)
        """
        # First, upload media from bytes content
        media_id = await self._upload_media_bytes(content, filename, content_type)

        # Then send message with media
        doc_payload: dict[str, Any] = {
            "id": media_id,
            "filename": filename,
        }
        if title:
            doc_payload["caption"] = title

        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": channel_id,
            "type": "document",
            "document": doc_payload,
        }

        success, data, error = await self._whatsapp_api_request(
            f"{WHATSAPP_API_BASE}/{self.phone_number_id}/messages",
            payload=payload,
            operation="upload_file",
        )

        if success:
            return FileAttachment(
                id=media_id,
                filename=filename,
                content_type=content_type,
                size=len(content),
            )

        raise RuntimeError(error or "Upload failed")

    async def _upload_media_bytes(self, content: bytes, filename: str, content_type: str) -> str:
        """Upload media bytes to WhatsApp servers.

        Uses _whatsapp_api_request for circuit breaker, retry, and timeout handling.

        Args:
            content: File content as bytes
            filename: Name for the file
            content_type: MIME type of the content
        """
        files = {"file": (filename, content, content_type)}
        form_data = {
            "messaging_product": "whatsapp",
            "type": content_type,
        }

        success, result, error = await self._whatsapp_api_request(
            f"{WHATSAPP_API_BASE}/{self.phone_number_id}/media",
            data=form_data,
            files=files,
            operation="upload_media_bytes",
        )

        if success and result:
            media_id: str = result.get("id", "")
            return media_id

        raise RuntimeError(error or "Media upload failed")

    async def _upload_media(self, file_path: str, media_type: str) -> str:
        """Upload media to WhatsApp servers.

        Uses _whatsapp_api_request for circuit breaker, retry, and timeout handling.
        """
        import mimetypes

        mime_type, _ = mimetypes.guess_type(file_path)

        with open(file_path, "rb") as f:
            files = {"file": (file_path.split("/")[-1], f.read(), mime_type)}
            form_data = {
                "messaging_product": "whatsapp",
                "type": mime_type or "application/octet-stream",
            }

            success, result, error = await self._whatsapp_api_request(
                f"{WHATSAPP_API_BASE}/{self.phone_number_id}/media",
                data=form_data,
                files=files,
                operation="upload_media",
            )

            if success and result:
                media_id: str = result.get("id", "")
                return media_id

            raise RuntimeError(error or "Media upload failed")

    async def download_file(
        self,
        file_id: str,
        **kwargs: Any,
    ) -> FileAttachment:
        """Download a file by media ID.

        Uses _whatsapp_api_request for circuit breaker, retry, and timeout handling.

        Args:
            file_id: WhatsApp media ID to download
            **kwargs: Additional options (url, filename for hints)

        Returns:
            FileAttachment with content populated
        """
        # Step 1: Get media URL and metadata
        success, data, error = await self._whatsapp_api_request(
            f"{WHATSAPP_API_BASE}/{file_id}",
            method="GET",
            operation="download_file_info",
        )

        if not success or not data:
            raise RuntimeError(error or "Failed to get media info")

        media_url = data.get("url")
        if not media_url:
            raise RuntimeError("No media URL returned")

        # Extract metadata from the response
        mime_type = data.get("mime_type", "application/octet-stream")
        file_size = data.get("file_size", 0)

        # Step 2: Download file content using base class _http_request
        dl_success, content, dl_error = await self._http_request(
            method="GET",
            url=media_url,
            headers={
                "Authorization": f"Bearer {self.bot_token}",
                **build_trace_headers(),
            },
            timeout=self._request_timeout * 2,
            return_raw=True,
            operation="download_file_content",
        )

        if not dl_success or content is None:
            raise RuntimeError(dl_error or "Failed to download file")

        # Use filename hint or generate from mime type
        filename = kwargs.get("filename")
        if not filename:
            ext = ".ogg"  # Default for voice
            if "audio/ogg" in mime_type:
                ext = ".ogg"
            elif "audio/mpeg" in mime_type or "audio/mp3" in mime_type:
                ext = ".mp3"
            elif "audio/aac" in mime_type or "audio/mp4" in mime_type:
                ext = ".m4a"
            elif "audio/wav" in mime_type:
                ext = ".wav"
            filename = f"audio_{file_id[:8]}{ext}"

        return FileAttachment(
            id=file_id,
            filename=filename,
            content_type=mime_type,
            size=file_size or len(content),
            url=media_url,
            content=cast(bytes, content),
            metadata={"whatsapp_mime_type": mime_type},
        )

    async def handle_webhook(
        self,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> WebhookEvent:
        """Process incoming WhatsApp webhook."""
        # Verify signature if app secret is set
        if self.signing_secret and headers:
            signature = headers.get("x-hub-signature-256", "")
            raw_body = kwargs.get("raw_body")
            if not isinstance(raw_body, (bytes, bytearray)):
                logger.warning(
                    "WhatsApp handle_webhook missing raw_body for signature verification"
                )
                return WebhookEvent(
                    event_type="invalid_signature",
                    platform="whatsapp",
                    raw_payload=payload,
                )
            if not self._verify_signature(bytes(raw_body), signature):
                logger.warning("Invalid webhook signature")
                return WebhookEvent(
                    event_type="invalid_signature",
                    platform="whatsapp",
                    raw_payload=payload,
                )

        # Parse webhook structure
        entry = payload.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})

        # Handle message
        messages = value.get("messages", [])
        if messages:
            msg = messages[0]
            value.get("contacts", [{}])[0]
            return WebhookEvent(
                event_type="message",
                platform="whatsapp",
                timestamp=datetime.fromtimestamp(int(msg.get("timestamp", 0))),
                raw_payload=payload,
                metadata={
                    "channel_id": msg.get("from"),
                    "user_id": msg.get("from"),
                    "message_id": msg.get("id"),
                },
            )

        # Handle status updates
        statuses = value.get("statuses", [])
        if statuses:
            status = statuses[0]
            return WebhookEvent(
                event_type=f"status_{status.get('status')}",
                platform="whatsapp",
                timestamp=datetime.fromtimestamp(int(status.get("timestamp", 0))),
                raw_payload=payload,
                metadata={"message_id": status.get("id")},
            )

        return WebhookEvent(
            event_type="unknown",
            platform="whatsapp",
            raw_payload=payload,
        )

    def _verify_signature(self, body: bytes, signature: str) -> bool:
        """Verify webhook signature."""
        if not signature.startswith("sha256="):
            return False
        signing_secret = self.signing_secret
        if not signing_secret:
            logger.warning("Webhook signature verification failed: signing secret not configured")
            return False

        expected_sig = signature[7:]
        computed_sig = hmac.new(
            signing_secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected_sig, computed_sig)

    async def parse_message(
        self,
        payload: dict[str, Any],
        **kwargs: Any,
    ) -> ChatMessage:
        """Parse a WhatsApp message into ChatMessage."""
        entry = payload.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})

        msg = value.get("messages", [{}])[0]
        contact = value.get("contacts", [{}])[0]

        # Determine message type
        msg_type = MessageType.TEXT
        msg_type_str = msg.get("type", "text")
        if msg_type_str == "audio":
            msg_type = MessageType.VOICE
        elif msg_type_str == "document":
            msg_type = MessageType.FILE
        elif msg_type_str == "image":
            msg_type = MessageType.FILE  # Images treated as files

        # Extract text content
        content = ""
        if msg_type_str == "text":
            content = msg.get("text", {}).get("body", "")
        elif msg_type_str == "interactive":
            interactive = msg.get("interactive", {})
            if "button_reply" in interactive:
                content = interactive["button_reply"].get("title", "")
            elif "list_reply" in interactive:
                content = interactive["list_reply"].get("title", "")

        # Build proper ChatChannel and ChatUser objects
        sender_id = msg.get("from", "")
        channel = ChatChannel(
            id=sender_id,
            platform="whatsapp",
            name=contact.get("profile", {}).get("name"),
            is_dm=True,
        )
        author = ChatUser(
            id=sender_id,
            platform="whatsapp",
            username=contact.get("wa_id", ""),
            display_name=contact.get("profile", {}).get("name", ""),
        )

        return ChatMessage(
            id=msg.get("id", ""),
            platform="whatsapp",
            channel=channel,
            author=author,
            content=content,
            message_type=msg_type,
            timestamp=datetime.fromtimestamp(int(msg.get("timestamp", 0))),
            thread_id=msg.get("context", {}).get("id"),
            metadata={"raw_data": msg},
        )

    async def parse_command(
        self,
        payload: dict[str, Any],
        **kwargs: Any,
    ) -> BotCommand | None:
        """
        Parse a command from message.

        Note: WhatsApp doesn't have native commands.
        This looks for messages starting with / or !
        """
        message = await self.parse_message(payload)
        text = message.content

        if not text or not (text.startswith("/") or text.startswith("!")):
            return None

        parts = text[1:].split()
        command_name = parts[0].lower() if parts else ""
        args = parts[1:] if len(parts) > 1 else []

        return BotCommand(
            name=command_name,
            text=text,
            args=args,
            user=message.author,
            channel=message.channel,
            platform="whatsapp",
            metadata={"message_id": message.id},
        )

    async def handle_interaction(
        self,
        payload: dict[str, Any],
        **kwargs: Any,
    ) -> UserInteraction:
        """Handle button click or list selection."""
        message = await self.parse_message(payload)
        msg = message.metadata.get("raw_data", {})

        interactive = msg.get("interactive", {})
        interaction_type = InteractionType.BUTTON_CLICK

        if "button_reply" in interactive:
            action_id = interactive["button_reply"].get("id", "")
            action_value = interactive["button_reply"].get("title", "")
        elif "list_reply" in interactive:
            action_id = interactive["list_reply"].get("id", "")
            action_value = interactive["list_reply"].get("title", "")
            interaction_type = InteractionType.SELECT_MENU
        else:
            action_id = ""
            action_value = ""

        return UserInteraction(
            id=f"interaction-{message.id}",
            interaction_type=interaction_type,
            action_id=action_id,
            value=action_value,
            user=message.author,
            channel=message.channel,
            message_id=message.id,
            platform="whatsapp",
        )

    async def send_voice_message(
        self,
        channel_id: str,
        audio_content: bytes,
        filename: str = "voice.ogg",
        content_type: str = "audio/ogg",
        reply_to: str | None = None,
        **kwargs: Any,
    ) -> SendMessageResponse:
        """Send a voice message.

        Uses _whatsapp_api_request for circuit breaker, retry, and timeout handling.

        Args:
            channel_id: Target channel/phone number
            audio_content: Audio data as bytes
            filename: Name for the audio file
            content_type: MIME type of the audio (default: audio/ogg)
            reply_to: Ignored (WhatsApp handles replies differently)
            **kwargs: Additional arguments (ignored)
        """
        # Step 1: Upload audio first
        files = {"file": (filename, audio_content, content_type)}
        form_data = {"messaging_product": "whatsapp", "type": content_type}

        upload_success, result, upload_error = await self._whatsapp_api_request(
            f"{WHATSAPP_API_BASE}/{self.phone_number_id}/media",
            data=form_data,
            files=files,
            operation="upload_voice_audio",
        )

        if not upload_success or not result:
            return SendMessageResponse(
                success=False,
                error=upload_error or "Audio upload failed",
            )

        media_id = result.get("id")

        # Step 2: Send audio message
        payload = {
            "messaging_product": "whatsapp",
            "to": channel_id,
            "type": "audio",
            "audio": {"id": media_id},
        }

        success, data, error = await self._whatsapp_api_request(
            f"{WHATSAPP_API_BASE}/{self.phone_number_id}/messages",
            payload=payload,
            operation="send_voice_message",
        )

        if success and data:
            messages = data.get("messages", [{}])
            return SendMessageResponse(
                success=True,
                message_id=messages[0].get("id") if messages else None,
                channel_id=channel_id,
                timestamp=datetime.now().isoformat(),
            )

        return SendMessageResponse(success=False, error=error)

    async def download_voice_message(
        self,
        voice_message: VoiceMessage,
        **kwargs: Any,
    ) -> bytes:
        """Download a voice message with circuit breaker protection."""
        attachment = await self.download_file(voice_message.file.id)
        return attachment.content or b""

    async def get_channel_info(
        self,
        channel_id: str,
        **kwargs: Any,
    ) -> ChatChannel:
        """
        Get channel info.

        Note: WhatsApp is 1:1 messaging, so channel = phone number.
        """
        return ChatChannel(
            id=channel_id,
            platform="whatsapp",
            name=channel_id,  # Phone number
            is_dm=True,
        )

    async def get_user_info(
        self,
        user_id: str,
        **kwargs: Any,
    ) -> ChatUser:
        """
        Get user info.

        Note: WhatsApp provides limited user info.
        """
        return ChatUser(
            id=user_id,
            username=user_id,  # Phone number
            platform="whatsapp",
        )

    async def extract_evidence(
        self,
        message: ChatMessage,
        **kwargs: Any,
    ) -> ChatEvidence:
        """Extract evidence from a message for debate."""
        return ChatEvidence(
            id=f"evidence-{message.id}",
            source_id=message.id,
            platform="whatsapp",
            channel_id=message.channel.id,
            content=message.content,
            author_id=message.author.id,
            author_name=message.author.display_name or message.channel.id,
            timestamp=message.timestamp,
            source_message=message,
        )

    def _build_interactive(self, text: str, blocks: list[dict[str, Any]]) -> dict[str, Any]:
        """Build interactive message payload."""
        buttons = []
        list_items = []

        for block in blocks:
            if block.get("type") == "button":
                buttons.append(
                    {
                        "type": "reply",
                        "reply": {
                            "id": block.get("action_id", block.get("value", "")),
                            "title": block.get("text", "")[:20],  # Max 20 chars
                        },
                    }
                )
            elif block.get("type") == "list_item":
                list_items.append(
                    {
                        "id": block.get("action_id", block.get("value", "")),
                        "title": block.get("text", "")[:24],  # Max 24 chars
                        "description": block.get("description", "")[:72],  # Max 72 chars
                    }
                )

        if list_items:
            return {
                "type": "list",
                "header": {"type": "text", "text": "Options"},
                "body": {"text": text},
                "action": {
                    "button": "Select",
                    "sections": [{"title": "Options", "rows": list_items[:10]}],  # Max 10
                },
            }
        elif buttons:
            return {
                "type": "button",
                "body": {"text": text},
                "action": {"buttons": buttons[:3]},  # Max 3 buttons
            }
        else:
            return {"type": "button", "body": {"text": text}, "action": {"buttons": []}}

    async def send_template(
        self,
        channel_id: str,
        template_name: str,
        language_code: str = "en",
        components: list[dict[str, Any] | None] | None = None,
        **kwargs: Any,
    ) -> SendMessageResponse:
        """Send a template message.

        Uses _whatsapp_api_request for circuit breaker, retry, and timeout handling.

        Templates must be pre-approved by WhatsApp.
        """
        template_data: dict[str, Any] = {
            "name": template_name,
            "language": {"code": language_code},
        }
        if components:
            template_data["components"] = [
                component for component in components if component is not None
            ]

        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": channel_id,
            "type": "template",
            "template": template_data,
        }

        success, data, error = await self._whatsapp_api_request(
            f"{WHATSAPP_API_BASE}/{self.phone_number_id}/messages",
            payload=payload,
            operation="send_template",
        )

        if success and data:
            messages = data.get("messages", [{}])
            return SendMessageResponse(
                success=True,
                message_id=messages[0].get("id") if messages else None,
                channel_id=channel_id,
                timestamp=datetime.now().isoformat(),
            )

        return SendMessageResponse(success=False, error=error)

    def verify_webhook(
        self,
        headers: dict[str, str],
        body: bytes,
    ) -> bool:
        """
        Verify webhook signature for POST requests.

        WhatsApp uses X-Hub-Signature-256 header with HMAC-SHA256.

        Args:
            headers: HTTP headers from the webhook request
            body: Raw request body

        Returns:
            True if signature is valid
        """
        if not self.signing_secret:
            env = os.environ.get("ARAGORA_ENV", "production").lower()
            is_production = env not in ("development", "dev", "local", "test")
            if is_production:
                logger.error(
                    "SECURITY: WhatsApp signing_secret not configured in production. "
                    "Rejecting webhook to prevent signature bypass."
                )
                return False
            logger.warning(
                "WhatsApp signing_secret not set - skipping verification. "
                "This is only acceptable in development!"
            )
            return True

        signature = headers.get("X-Hub-Signature-256", headers.get("x-hub-signature-256", ""))
        if not signature.startswith("sha256="):
            logger.warning("Invalid WhatsApp webhook signature format")
            return False

        expected_sig = signature[7:]
        computed_sig = hmac.new(
            self.signing_secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()

        if hmac.compare_digest(computed_sig, expected_sig):
            return True

        logger.warning("WhatsApp webhook signature mismatch")
        return False

    def verify_webhook_subscription(
        self,
        mode: str,
        token: str,
        challenge: str,
    ) -> str | None:
        """
        Verify webhook subscription (GET request).

        This is WhatsApp-specific for initial webhook registration.

        Returns challenge if verification succeeds, None otherwise.
        """
        if (
            mode == "subscribe"
            and self.verify_token
            and hmac.compare_digest(token, self.verify_token)
        ):
            logger.info("WhatsApp webhook verified")
            return challenge
        logger.warning("WhatsApp webhook verification failed")
        return None

    # ==========================================================================
    # Abstract method implementations
    # ==========================================================================

    def format_blocks(
        self,
        title: str | None = None,
        body: str | None = None,
        fields: list[tuple[str, str]] | None = None,
        actions: list[MessageButton] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Format content as WhatsApp-compatible blocks.

        Args:
            title: Section title/header
            body: Main text content
            fields: List of (label, value) tuples for structured data
            actions: List of interactive buttons
            **kwargs: Additional arguments (ignored)
        """
        blocks: list[dict[str, Any]] = []

        if title:
            blocks.append({"type": "header", "text": title})

        if body:
            blocks.append({"type": "body", "text": body})

        if fields:
            for field in fields:
                if field is None:
                    continue
                # Handle tuple format (label, value)
                label, value = field
                blocks.append(
                    {
                        "type": "field",
                        "label": label,
                        "value": value,
                    }
                )

        if actions:
            for btn in actions:
                blocks.append(
                    {
                        "type": "button",
                        "text": btn.text[:20],  # WhatsApp limits to 20 chars
                        "action_id": btn.action_id,
                        "value": btn.value or "",
                    }
                )

        return blocks

    def format_button(
        self,
        text: str,
        action_id: str,
        value: str | None = None,
        style: str | None = None,
        url: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Format a button for WhatsApp interactive message."""
        if url:
            return {"type": "url_button", "text": text, "url": url}
        return {
            "type": "button",
            "text": text[:20],  # WhatsApp limits to 20 chars
            "action_id": action_id,
            "value": value or action_id,
        }

    def parse_webhook_event(
        self,
        headers: dict[str, str],
        body: bytes,
    ) -> WebhookEvent:
        """Parse a WhatsApp webhook payload into a WebhookEvent."""
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return WebhookEvent(
                platform="whatsapp",
                event_type="error",
                raw_payload={},
            )

        # Verify signature if app secret is set
        if self.signing_secret:
            signature = headers.get("X-Hub-Signature-256", "")
            expected = (
                "sha256="
                + hmac.new(
                    self.signing_secret.encode(),
                    body,
                    hashlib.sha256,
                ).hexdigest()
            )
            if not hmac.compare_digest(signature, expected):
                logger.warning("WhatsApp webhook signature mismatch")
                return WebhookEvent(
                    platform="whatsapp",
                    event_type="error",
                    raw_payload={"error": "signature_mismatch"},
                )

        # Extract event from payload
        entry = payload.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})

        # Determine event type
        if "messages" in value:
            messages = value.get("messages", [])
            if messages:
                msg = messages[0]
                msg_type = msg.get("type", "text")

                if msg_type == "interactive":
                    return WebhookEvent(
                        platform="whatsapp",
                        event_type="interaction",
                        raw_payload=payload,
                    )

                return WebhookEvent(
                    platform="whatsapp",
                    event_type="message",
                    raw_payload=payload,
                )

        if "statuses" in value:
            return WebhookEvent(
                platform="whatsapp",
                event_type="status",
                raw_payload=payload,
            )

        return WebhookEvent(
            platform="whatsapp",
            event_type="unknown",
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
        """Respond to a bot command."""
        # WhatsApp doesn't have native commands, so just send a message
        if command.channel:
            return await self.send_message(
                channel_id=command.channel.id,
                text=text,
                blocks=blocks,
                **kwargs,
            )
        return SendMessageResponse(success=False, error="No channel for command response")

    async def respond_to_interaction(
        self,
        interaction: UserInteraction,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
        replace_original: bool = False,
        **kwargs: Any,
    ) -> SendMessageResponse:
        """Respond to a user interaction (button click or list selection)."""
        if interaction.channel:
            return await self.send_message(
                channel_id=interaction.channel.id,
                text=text,
                blocks=blocks,
                **kwargs,
            )
        return SendMessageResponse(success=False, error="No channel for interaction response")


__all__ = ["WhatsAppConnector"]
