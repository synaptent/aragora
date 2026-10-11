"""
Google Chat Connector.

Implements ChatPlatformConnector for Google Chat using
Google Chat API and Cards v2. Includes circuit breaker protection
for resilient API calls.

Environment Variables:
- GOOGLE_CHAT_CREDENTIALS: Path to service account JSON or JSON string
- GOOGLE_CHAT_PROJECT_ID: Google Cloud project ID
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Try to import required libraries
try:
    import httpx

    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

try:
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request

    GOOGLE_AUTH_AVAILABLE = True
except ImportError:
    GOOGLE_AUTH_AVAILABLE = False
    logger.debug("google-auth not available - Google Chat connector limited")

from .base import ChatPlatformConnector
from .models import (
    BotCommand,
    ChatChannel,
    ChatMessage,
    ChatUser,
    FileAttachment,
    InteractionType,
    MessageButton,
    SendMessageResponse,
    UserInteraction,
    WebhookEvent,
)

# Environment configuration
GOOGLE_CHAT_CREDENTIALS = os.environ.get("GOOGLE_CHAT_CREDENTIALS", "")
GOOGLE_CHAT_PROJECT_ID = os.environ.get("GOOGLE_CHAT_PROJECT_ID", "")

# Google Chat API
CHAT_API_BASE = "https://chat.googleapis.com/v1"
CHAT_SCOPES = ["https://www.googleapis.com/auth/chat.bot"]


class GoogleChatConnector(ChatPlatformConnector):
    """
    Google Chat connector using Google Chat API.

    Supports:
    - Sending messages with Cards v2
    - Responding to slash commands
    - Interactive card actions
    - Threaded conversations
    - Circuit breaker protection for resilient API calls
    """

    def __init__(
        self,
        credentials_path: str | None = None,
        credentials_json: str | None = None,
        project_id: str | None = None,
        **config: Any,
    ):
        """
        Initialize Google Chat connector.

        Args:
            credentials_path: Path to service account JSON file
            credentials_json: Service account JSON as string
            project_id: Google Cloud project ID
            **config: Additional configuration
        """
        super().__init__(**config)
        self.project_id = project_id or GOOGLE_CHAT_PROJECT_ID
        self._credentials = None
        self._credentials_path = credentials_path
        self._credentials_json = credentials_json or GOOGLE_CHAT_CREDENTIALS

    @property
    def platform_name(self) -> str:
        return "google_chat"

    @property
    def platform_display_name(self) -> str:
        return "Google Chat"

    def _get_credentials(self):
        """Get or create Google auth credentials."""
        if self._credentials is not None:
            return self._credentials

        if not GOOGLE_AUTH_AVAILABLE:
            raise RuntimeError("google-auth not available")

        # Try credentials path first
        if self._credentials_path and os.path.exists(self._credentials_path):
            self._credentials = service_account.Credentials.from_service_account_file(
                self._credentials_path,
                scopes=CHAT_SCOPES,
            )
        elif self._credentials_json:
            # Try parsing as JSON string
            try:
                creds_dict = json.loads(self._credentials_json)
                self._credentials = service_account.Credentials.from_service_account_info(
                    creds_dict,
                    scopes=CHAT_SCOPES,
                )
            except json.JSONDecodeError:
                # Maybe it's a file path
                if os.path.exists(self._credentials_json):
                    self._credentials = service_account.Credentials.from_service_account_file(
                        self._credentials_json,
                        scopes=CHAT_SCOPES,
                    )
                else:
                    raise ValueError("Invalid credentials JSON")
        else:
            raise ValueError("No credentials configured")

        return self._credentials

    async def _get_access_token(self) -> str:
        """Get access token for API calls."""
        creds = self._get_credentials()

        # Refresh if expired
        if creds.expired or not creds.token:
            creds.refresh(Request())

        return creds.token

    def _get_headers(self, token: str) -> dict[str, str]:
        """Get headers for API requests."""
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def send_message(
        self,
        channel_id: str,
        text: str,
        blocks: list[dict] | None = None,
        thread_id: str | None = None,
        **kwargs: Any,
    ) -> SendMessageResponse:
        """Send message to Google Chat space."""
        if not HTTPX_AVAILABLE or not GOOGLE_AUTH_AVAILABLE:
            return SendMessageResponse(
                success=False,
                error="Required libraries not available",
            )

        # Check circuit breaker
        can_proceed, cb_error = self._check_circuit_breaker()
        if not can_proceed:
            return SendMessageResponse(success=False, error=cb_error)

        try:
            token = await self._get_access_token()

            # Build message payload
            payload: dict[str, Any] = {}

            if text:
                payload["text"] = text

            # Add card if blocks provided
            if blocks:
                payload["cardsV2"] = [
                    {
                        "cardId": "aragora_card",
                        "card": {
                            "sections": blocks,
                        },
                    }
                ]

            # Construct URL
            url = f"{CHAT_API_BASE}/{channel_id}/messages"
            params = {}

            if thread_id:
                params["messageReplyOption"] = "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"
                payload["thread"] = {"name": thread_id}

            async with httpx.AsyncClient(timeout=self._request_timeout) as client:
                response = await client.post(
                    url,
                    headers=self._get_headers(token),
                    params=params,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

                self._record_success()
                return SendMessageResponse(
                    success=True,
                    message_id=data.get("name", "").split("/")[-1],
                    channel_id=channel_id,
                )

        except (httpx.HTTPError, ValueError, RuntimeError, OSError) as e:
            self._record_failure(e)
            logger.error("Google Chat send_message error: %s", e)
            return SendMessageResponse(success=False, error="Message send failed")

    async def update_message(
        self,
        channel_id: str,
        message_id: str,
        text: str,
        blocks: list[dict] | None = None,
        **kwargs: Any,
    ) -> SendMessageResponse:
        """Update a Google Chat message."""
        if not HTTPX_AVAILABLE or not GOOGLE_AUTH_AVAILABLE:
            return SendMessageResponse(success=False, error="Libraries not available")

        # Check circuit breaker
        can_proceed, cb_error = self._check_circuit_breaker()
        if not can_proceed:
            return SendMessageResponse(success=False, error=cb_error)

        try:
            token = await self._get_access_token()

            payload: dict[str, Any] = {}

            if text:
                payload["text"] = text

            if blocks:
                payload["cardsV2"] = [
                    {
                        "cardId": "aragora_card",
                        "card": {
                            "sections": blocks,
                        },
                    }
                ]

            # Message name format: spaces/{space}/messages/{message}
            message_name = f"{channel_id}/messages/{message_id}"

            async with httpx.AsyncClient(timeout=self._request_timeout) as client:
                response = await client.patch(
                    f"{CHAT_API_BASE}/{message_name}",
                    headers=self._get_headers(token),
                    params={"updateMask": "text,cardsV2"},
                    json=payload,
                )
                response.raise_for_status()

                self._record_success()
                return SendMessageResponse(
                    success=True,
                    message_id=message_id,
                    channel_id=channel_id,
                )

        except (httpx.HTTPError, ValueError, RuntimeError, OSError) as e:
            self._record_failure(e)
            logger.error("Google Chat update_message error: %s", e)
            return SendMessageResponse(success=False, error="Message update failed")

    async def delete_message(
        self,
        channel_id: str,
        message_id: str,
        **kwargs: Any,
    ) -> bool:
        """Delete a Google Chat message."""
        if not HTTPX_AVAILABLE or not GOOGLE_AUTH_AVAILABLE:
            return False

        # Check circuit breaker
        can_proceed, cb_error = self._check_circuit_breaker()
        if not can_proceed:
            logger.warning("Google Chat delete_message blocked by circuit breaker: %s", cb_error)
            return False

        try:
            token = await self._get_access_token()
            message_name = f"{channel_id}/messages/{message_id}"

            async with httpx.AsyncClient(timeout=self._request_timeout) as client:
                response = await client.delete(
                    f"{CHAT_API_BASE}/{message_name}",
                    headers=self._get_headers(token),
                )
                if response.status_code in (200, 204):
                    self._record_success()
                    return True
                return False

        except (httpx.HTTPError, ValueError, RuntimeError, OSError) as e:
            self._record_failure(e)
            logger.error("Google Chat delete_message error: %s", e)
            return False

    async def respond_to_command(
        self,
        command: BotCommand,
        text: str,
        blocks: list[dict] | None = None,
        ephemeral: bool = True,
        **kwargs: Any,
    ) -> SendMessageResponse:
        """Respond to a Google Chat slash command."""
        # Google Chat slash commands require synchronous response in webhook
        # Store response for handler to return
        if command.channel:
            return await self.send_message(
                command.channel.id,
                text,
                blocks,
                thread_id=command.metadata.get("thread_name"),
                **kwargs,
            )

        return SendMessageResponse(success=False, error="No channel available")

    async def respond_to_interaction(
        self,
        interaction: UserInteraction,
        text: str,
        blocks: list[dict] | None = None,
        replace_original: bool = False,
        **kwargs: Any,
    ) -> SendMessageResponse:
        """Respond to a Google Chat card action."""
        if replace_original and interaction.message_id and interaction.channel:
            return await self.update_message(
                interaction.channel.id,
                interaction.message_id,
                text,
                blocks,
            )

        if interaction.channel:
            return await self.send_message(
                interaction.channel.id,
                text,
                blocks,
                thread_id=interaction.metadata.get("thread_name"),
            )

        return SendMessageResponse(success=False, error="No response target")

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
        """Upload file to Google Chat (via Drive)."""
        # Google Chat file uploads require Drive API integration
        logger.warning("Google Chat file upload requires Drive API setup")
        return FileAttachment(
            id="",
            filename=filename,
            content_type=content_type,
            size=len(content),
            content=content,
        )

    async def download_file(
        self,
        file_id: str,
        **kwargs: Any,
    ) -> FileAttachment:
        """Download file from Google Chat attachment."""
        logger.warning("Google Chat file download requires Drive API")
        return FileAttachment(
            id=file_id,
            filename="",
            content_type="application/octet-stream",
            size=0,
        )

    def format_blocks(
        self,
        title: str | None = None,
        body: str | None = None,
        fields: list[tuple[str, str]] | None = None,
        actions: list[MessageButton] | None = None,
        **kwargs: Any,
    ) -> list[dict]:
        """Format content as Google Chat Card v2 sections."""
        sections: list[dict] = []

        # Header section
        if title:
            sections.append(
                {
                    "header": title,
                }
            )

        # Body section
        if body:
            sections.append(
                {
                    "widgets": [
                        {
                            "textParagraph": {
                                "text": body,
                            }
                        }
                    ],
                }
            )

        # Fields as decorated text
        if fields:
            widgets = []
            for label, value in fields:
                widgets.append(
                    {
                        "decoratedText": {
                            "topLabel": label,
                            "text": value,
                        }
                    }
                )
            sections.append({"widgets": widgets})

        # Actions as buttons
        if actions:
            buttons = [
                self.format_button(btn.text, btn.action_id, btn.value, btn.style, btn.url)
                for btn in actions
            ]
            sections.append(
                {
                    "widgets": [
                        {
                            "buttonList": {
                                "buttons": buttons,
                            }
                        }
                    ],
                }
            )

        return sections

    def format_button(
        self,
        text: str,
        action_id: str,
        value: str | None = None,
        style: str = "default",
        url: str | None = None,
    ) -> dict:
        """Format a Google Chat button."""
        if url:
            return {
                "text": text,
                "onClick": {
                    "openLink": {
                        "url": url,
                    }
                },
            }

        button: dict[str, Any] = {
            "text": text,
            "onClick": {
                "action": {
                    "function": action_id,
                    "parameters": [
                        {"key": "value", "value": value or ""},
                    ],
                }
            },
        }

        if style == "primary":
            button["color"] = {"red": 0.1, "green": 0.5, "blue": 0.9, "alpha": 1.0}
        elif style == "danger":
            button["color"] = {"red": 0.9, "green": 0.2, "blue": 0.2, "alpha": 1.0}

        return button

    def verify_webhook(
        self,
        headers: dict[str, str],
        body: bytes,
    ) -> bool:
        """
        Verify Google Chat webhook JWT token.

        Uses PyJWT to validate the token against Google's public keys.
        SECURITY: Fails closed in production if PyJWT is not available.
        Uses centralized webhook_security module for production-safe bypass handling.
        """
        from aragora.connectors.chat.webhook_security import should_allow_unverified

        auth_header = headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            logger.warning("Missing Authorization header in Google Chat webhook")
            return False

        # Use JWT verification if available
        try:
            from .jwt_verify import verify_google_chat_webhook, HAS_JWT

            if HAS_JWT:
                return verify_google_chat_webhook(auth_header, self.project_id)
            else:
                # SECURITY: Use centralized bypass check (ignores flag in production)
                if should_allow_unverified("google_chat"):
                    logger.warning(
                        "Google Chat webhook verification skipped - PyJWT not available (dev mode). "
                        "Install PyJWT for secure webhook validation: pip install PyJWT"
                    )
                    return True
                logger.error("Google Chat webhook rejected - PyJWT not available")
                return False
        except ImportError:
            if should_allow_unverified("google_chat"):
                logger.warning("Google Chat JWT verification module not available (dev mode)")
                return True
            logger.error("Google Chat webhook rejected - JWT verification module not available")
            return False

    def parse_webhook_event(
        self,
        headers: dict[str, str],
        body: bytes,
    ) -> WebhookEvent:
        """Parse Google Chat event into WebhookEvent."""
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return WebhookEvent(
                platform=self.platform_name,
                event_type="error",
                raw_payload={},
            )

        event_type = payload.get("type", "")

        # Parse user
        user_data = payload.get("user", {})
        user = ChatUser(
            id=user_data.get("name", "").split("/")[-1],
            platform=self.platform_name,
            display_name=user_data.get("displayName"),
            email=user_data.get("email"),
            avatar_url=user_data.get("avatarUrl"),
            is_bot=user_data.get("type") == "BOT",
        )

        # Parse space (channel)
        space_data = payload.get("space", {})
        channel = ChatChannel(
            id=space_data.get("name", ""),
            platform=self.platform_name,
            name=space_data.get("displayName"),
            is_dm=space_data.get("type") == "DM",
            is_private=space_data.get("spaceType") != "SPACE",
        )

        # Thread info
        thread_data = payload.get("message", {}).get("thread", {})
        thread_name = thread_data.get("name")

        event = WebhookEvent(
            platform=self.platform_name,
            event_type=event_type,
            raw_payload=payload,
            metadata={"thread_name": thread_name},
        )

        if event_type == "MESSAGE":
            # Regular message or slash command
            message_data = payload.get("message", {})
            text = message_data.get("text", "")

            # Check for slash command
            slash_command = message_data.get("slashCommand")
            if slash_command:
                event.command = BotCommand(
                    name=slash_command.get("commandName", "").lstrip("/"),
                    text=text,
                    args=message_data.get("argumentText", "").split(),
                    user=user,
                    channel=channel,
                    platform=self.platform_name,
                    metadata={"thread_name": thread_name},
                )
            else:
                event.message = ChatMessage(
                    id=message_data.get("name", "").split("/")[-1],
                    platform=self.platform_name,
                    channel=channel,
                    author=user,
                    content=text,
                    thread_id=thread_name,
                    metadata={"thread_name": thread_name},
                )

        elif event_type == "CARD_CLICKED":
            # Card action
            action = payload.get("action", {})

            # Parse parameters
            params = {p.get("key"): p.get("value") for p in action.get("parameters", [])}

            event.interaction = UserInteraction(
                id=payload.get("eventTime", ""),
                interaction_type=InteractionType.BUTTON_CLICK,
                action_id=action.get("actionMethodName", ""),
                value=params.get("value"),
                user=user,
                channel=channel,
                message_id=payload.get("message", {}).get("name", "").split("/")[-1],
                platform=self.platform_name,
                metadata={"thread_name": thread_name, "parameters": params},
            )

        elif event_type == "ADDED_TO_SPACE":
            # Bot added to space - respond with welcome message
            event.metadata["welcome"] = True

        elif event_type == "REMOVED_FROM_SPACE":
            # Bot removed - cleanup if needed
            event.metadata["removed"] = True

        return event

    # ==========================================================================
    # Evidence Collection - Limited by Google Chat API
    # ==========================================================================

    async def get_channel_history(
        self,
        channel_id: str,
        limit: int = 100,
        oldest: str | None = None,
        latest: str | None = None,
        **kwargs: Any,
    ) -> list[ChatMessage]:
        """
        Get message history from a Google Chat space.

        Note: Google Chat API does NOT provide a message history endpoint for bots.
        Bots can only receive messages via webhooks or events. This method returns
        any messages that have been cached from webhook events.

        For full message history access, consider:
        1. Using Google Vault API (enterprise compliance feature)
        2. Storing messages in your own database when received via webhooks
        3. Using Google Drive API for exported chat transcripts

        Args:
            channel_id: Space name (e.g., "spaces/XXXXXXX")
            limit: Maximum number of cached messages to return
            oldest: Not supported - ignored
            latest: Not supported - ignored
            **kwargs: Additional options

        Returns:
            List of cached ChatMessage objects (if any)
        """
        logger.info(
            "Google Chat API does not provide message history. "
            "Messages are only available via webhook events."
        )
        # Return empty list - messages must be cached by webhook handler
        return []

    async def collect_evidence(
        self,
        channel_id: str,
        query: str | None = None,
        limit: int = 100,
        include_threads: bool = True,
        min_relevance: float = 0.0,
        **kwargs: Any,
    ) -> list:
        """
        Collect chat messages as evidence from Google Chat.

        Note: Google Chat does not provide message history API for bots.
        This method returns an empty list with a warning log.

        For evidence collection from Google Chat, consider:
        1. Storing messages when received via webhooks
        2. Using Google Vault API (enterprise)
        3. Exporting chat data via Google Admin Console

        Args:
            channel_id: Space name
            query: Search query (not supported)
            limit: Maximum results (not supported)
            include_threads: Include threads (not supported)
            min_relevance: Minimum relevance score (not supported)
            **kwargs: Additional options

        Returns:
            Empty list (Google Chat API limitation)
        """
        logger.warning(
            "Google Chat evidence collection not available - "
            "API does not provide message history for bots. "
            "Consider storing messages from webhook events."
        )
        return []

    async def list_spaces(self) -> list[dict]:
        """
        List all spaces the bot has access to.

        Returns:
            List of space dictionaries with id, name, type, etc.
        """
        if not HTTPX_AVAILABLE or not GOOGLE_AUTH_AVAILABLE:
            return []

        # Check circuit breaker
        can_proceed, cb_error = self._check_circuit_breaker()
        if not can_proceed:
            logger.warning("Google Chat list_spaces blocked by circuit breaker: %s", cb_error)
            return []

        try:
            token = await self._get_access_token()

            async with httpx.AsyncClient(timeout=self._request_timeout) as client:
                response = await client.get(
                    f"{CHAT_API_BASE}/spaces",
                    headers=self._get_headers(token),
                )
                response.raise_for_status()
                data = response.json()

                spaces = []
                for space in data.get("spaces", []):
                    spaces.append(
                        {
                            "id": space.get("name", ""),
                            "display_name": space.get("displayName", ""),
                            "type": space.get("type", ""),
                            "single_user_bot_dm": space.get("singleUserBotDm", False),
                        }
                    )

                self._record_success()
                return spaces

        except (httpx.HTTPError, ValueError, RuntimeError, OSError) as e:
            self._record_failure(e)
            logger.error("Google Chat list_spaces error: %s", e)
            return []
