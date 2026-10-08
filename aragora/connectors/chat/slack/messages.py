"""
Slack message operations: send, update, delete, format, upload/download files.

Contains message-related methods extracted from SlackConnector as mixin methods,
plus formatting helpers (Block Kit, buttons, mentions).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

try:
    import httpx

    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

from aragora.connectors.chat.models import (
    ChatChannel,
    ChatEvidence,
    ChatMessage,
    ChatUser,
    FileAttachment,
    MessageButton,
    SendMessageResponse,
)

from .client import (
    SLACK_API_BASE,
    _exponential_backoff,
    _is_retryable_error,
)


class SlackMessagesMixin:
    """Mixin providing message send/update/delete, formatting, and file operations.

    This mixin expects to be combined with SlackConnector which provides
    the declared attributes and methods below.
    """

    # Declare expected attributes from the concrete class for type checking
    bot_token: str | None
    _circuit_breaker: Any
    _max_retries: int
    _timeout: float

    # Type-only declarations. At runtime these would sit ahead of
    # HTTPResilienceMixin in SlackConnector's MRO and shadow the real
    # _http_request with a stub that returns None.
    if TYPE_CHECKING:

        @property
        def platform_name(self) -> str: ...

        def _get_headers(self) -> dict[str, str]: ...

        async def _slack_api_request(
            self,
            endpoint: str,
            payload: dict[str, Any] | None = None,
            operation: str = "api_call",
            *,
            method: str = "POST",
            params: dict[str, Any] | None = None,
            json_data: dict[str, Any] | None = None,
            form_data: dict[str, Any] | None = None,
            files: dict[str, Any] | None = None,
            timeout: float | None = None,
            max_retries: int | None = None,
        ) -> tuple[bool, dict[str, Any] | None, str | None]: ...

        async def _http_request(
            self,
            method: str,
            url: str,
            headers: dict[str, str] | None = None,
            json: dict[str, Any] | None = None,
            data: Any | None = None,
            content: bytes | None = None,
            files: dict[str, Any] | None = None,
            max_retries: int = 3,
            base_delay: float = 1.0,
            timeout: float | None = None,
            return_raw: bool = False,
            operation: str = "http_request",
        ) -> tuple[bool, dict[str, Any] | bytes | None, str | None]: ...

    def _compute_message_relevance(
        self,
        message: ChatMessage,
        query: str | None = None,
    ) -> float:
        """Compute a simple relevance score for a message."""
        if not query:
            return 1.0

        query_lower = query.lower()
        text_lower = (message.content or "").lower()

        keywords = query_lower.split()
        if not keywords or not text_lower:
            return 0.0

        matches = sum(1 for kw in keywords if kw in text_lower)
        return matches / len(keywords)

    async def send_message(
        self,
        channel_id: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
        thread_id: str | None = None,
        **kwargs: Any,
    ) -> SendMessageResponse:
        """Send message to Slack channel with retry and circuit breaker."""
        payload: dict[str, Any] = {
            "channel": channel_id,
            "text": text,
        }

        if blocks:
            payload["blocks"] = blocks

        if thread_id:
            payload["thread_ts"] = thread_id

        # Optional: unfurl links/media
        if "unfurl_links" in kwargs:
            payload["unfurl_links"] = kwargs["unfurl_links"]
        if "unfurl_media" in kwargs:
            payload["unfurl_media"] = kwargs["unfurl_media"]

        success, data, error = await self._slack_api_request(
            "chat.postMessage", payload, "send_message"
        )

        if success and data:
            return SendMessageResponse(
                success=True,
                message_id=data.get("ts"),
                channel_id=data.get("channel"),
                timestamp=data.get("ts"),
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
        """Update a Slack message with retry and circuit breaker."""
        payload: dict[str, Any] = {
            "channel": channel_id,
            "ts": message_id,
            "text": text,
        }

        if blocks:
            payload["blocks"] = blocks

        success, data, error = await self._slack_api_request(
            "chat.update", payload, "update_message"
        )

        if success and data:
            return SendMessageResponse(
                success=True,
                message_id=data.get("ts"),
                channel_id=data.get("channel"),
            )
        return SendMessageResponse(success=False, error=error)

    async def delete_message(
        self,
        channel_id: str,
        message_id: str,
        **kwargs: Any,
    ) -> bool:
        """Delete a Slack message with retry and circuit breaker."""
        payload = {
            "channel": channel_id,
            "ts": message_id,
        }

        success, _, _ = await self._slack_api_request("chat.delete", payload, "delete_message")
        return success

    async def send_ephemeral(
        self,
        channel_id: str,
        user_id: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> SendMessageResponse:
        """Send ephemeral message visible only to one user with retry."""
        if not HTTPX_AVAILABLE:
            return SendMessageResponse(success=False, error="httpx not available")

        if self._circuit_breaker and not self._circuit_breaker.can_proceed():
            return SendMessageResponse(success=False, error="Circuit breaker open")

        payload: dict[str, Any] = {
            "channel": channel_id,
            "user": user_id,
            "text": text,
        }

        if blocks:
            payload["blocks"] = blocks

        last_error: str | None = None

        for attempt in range(self._max_retries):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(
                        f"{SLACK_API_BASE}/chat.postEphemeral",
                        headers=self._get_headers(),
                        json=payload,
                    )
                    data = response.json()

                    if data.get("ok"):
                        if self._circuit_breaker:
                            self._circuit_breaker.record_success()
                        return SendMessageResponse(success=True)

                    error = data.get("error", "Unknown error")
                    last_error = error

                    if _is_retryable_error(response.status_code, error):
                        if attempt < self._max_retries - 1:
                            await _exponential_backoff(attempt)
                            continue

                    if self._circuit_breaker:
                        self._circuit_breaker.record_failure()
                    return SendMessageResponse(success=False, error=error)

            except httpx.TimeoutException:
                last_error = "Request timeout"
                if attempt < self._max_retries - 1:
                    logger.warning(
                        "[slack] send_ephemeral timeout (attempt %s/%s)",
                        attempt + 1,
                        self._max_retries,
                    )
                    await _exponential_backoff(attempt)
                    continue
                logger.error("[slack] send_ephemeral timeout after all retries")

            except httpx.ConnectError as e:
                last_error = f"Connection error: {e}"
                if attempt < self._max_retries - 1:
                    logger.warning(
                        "[slack] send_ephemeral network error (attempt %s/%s)",
                        attempt + 1,
                        self._max_retries,
                    )
                    await _exponential_backoff(attempt)
                    continue
                logger.error("[slack] send_ephemeral network error after all retries: %s", e)

            except (RuntimeError, OSError, ValueError, TypeError) as e:
                last_error = "Unexpected error"
                logger.exception("[slack] send_ephemeral unexpected error: %s", e)
                # Don't retry unexpected errors
                break

        if self._circuit_breaker:
            self._circuit_breaker.record_failure()
        return SendMessageResponse(success=False, error=last_error)

    async def respond_to_command(
        self,
        command: Any,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
        ephemeral: bool = True,
        **kwargs: Any,
    ) -> SendMessageResponse:
        """Respond to a Slack slash command."""
        # Use response_url for async response
        if command.response_url:
            return await self._send_to_response_url(
                command.response_url,
                text,
                blocks,
                response_type="ephemeral" if ephemeral else "in_channel",
            )

        # Fallback to regular message
        if command.channel and command.user:
            if ephemeral:
                return await self.send_ephemeral(
                    command.channel.id,
                    command.user.id,
                    text,
                    blocks,
                )
            else:
                return await self.send_message(
                    command.channel.id,
                    text,
                    blocks,
                )

        return SendMessageResponse(success=False, error="No response target")

    async def respond_to_interaction(
        self,
        interaction: Any,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
        replace_original: bool = False,
        **kwargs: Any,
    ) -> SendMessageResponse:
        """Respond to a Slack interaction."""
        if interaction.response_url:
            return await self._send_to_response_url(
                interaction.response_url,
                text,
                blocks,
                replace_original=replace_original,
            )

        if interaction.channel and interaction.message_id and replace_original:
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
            )

        return SendMessageResponse(success=False, error="No response target")

    async def _send_to_response_url(
        self,
        response_url: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
        response_type: str = "ephemeral",
        replace_original: bool = False,
    ) -> SendMessageResponse:
        """Send response to Slack response_url with timeout and retries."""
        if not HTTPX_AVAILABLE:
            return SendMessageResponse(success=False, error="httpx not available")

        payload: dict[str, Any] = {
            "text": text,
            "response_type": response_type,
        }

        if blocks:
            payload["blocks"] = blocks

        if replace_original:
            payload["replace_original"] = True

        # Response URLs have shorter validity, use fewer retries
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(response_url, json=payload)
                    if response.status_code == 200:
                        return SendMessageResponse(success=True)

                    # Retry on 5xx errors
                    if 500 <= response.status_code < 600 and attempt == 0:
                        await _exponential_backoff(0, base=0.5)
                        continue

                    return SendMessageResponse(
                        success=False,
                        error=f"HTTP {response.status_code}",
                    )

            except httpx.TimeoutException:
                if attempt == 0:
                    logger.warning("[slack] response_url timeout, retrying")
                    await _exponential_backoff(0, base=0.5)
                    continue
                logger.error("[slack] response_url timeout after retries")
                return SendMessageResponse(success=False, error="Request timeout")

            except httpx.ConnectError as e:
                if attempt == 0:
                    logger.warning("[slack] response_url network error, retrying")
                    await _exponential_backoff(0, base=0.5)
                    continue
                logger.error("[slack] response_url network error: %s", e)
                return SendMessageResponse(success=False, error="Connection error")

            except (RuntimeError, OSError, ValueError, TypeError) as e:
                logger.exception("[slack] response_url unexpected error: %s", e)
                return SendMessageResponse(success=False, error="Unexpected error")

        return SendMessageResponse(success=False, error="Request failed")

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
        """Upload file to Slack with timeout and retry.

        Uses _slack_api_request for circuit breaker, retry, and timeout handling.
        """
        files = {"file": (filename, content, content_type)}
        form_data: dict[str, Any] = {
            "channels": channel_id,
            "filename": filename,
        }

        if title:
            form_data["title"] = title

        if thread_id:
            form_data["thread_ts"] = thread_id

        # Use 2x timeout for file uploads
        success, data, error = await self._slack_api_request(
            "files.upload",
            operation="upload_file",
            form_data=form_data,
            files=files,
            timeout=self._timeout * 2,
        )

        if success and data:
            file_data = data.get("file", {})
            return FileAttachment(
                id=file_data.get("id", ""),
                filename=file_data.get("name", filename),
                content_type=file_data.get("mimetype", content_type),
                size=file_data.get("size", len(content)),
                url=file_data.get("url_private"),
            )

        return FileAttachment(
            id="",
            filename=filename,
            content_type=content_type,
            size=len(content),
        )

    async def download_file(
        self,
        file_id: str,
        **kwargs: Any,
    ) -> FileAttachment:
        """Download file from Slack with timeout and retry.

        Uses _slack_api_request for file info and _http_request for binary download.
        """
        # Step 1: Get file info
        success, info, error = await self._slack_api_request(
            "files.info",
            operation="download_file_info",
            method="GET",
            params={"file": file_id},
            timeout=self._timeout * 2,
        )

        if not success or not info:
            return FileAttachment(
                id=file_id,
                filename="",
                content_type="application/octet-stream",
                size=0,
            )

        file_data = info.get("file", {})
        url = file_data.get("url_private_download") or file_data.get("url_private")

        if not url:
            return FileAttachment(
                id=file_id,
                filename=file_data.get("name", ""),
                content_type=file_data.get("mimetype", "application/octet-stream"),
                size=file_data.get("size", 0),
            )

        # Step 2: Download the binary content
        dl_success, content, dl_error = await self._http_request(
            method="GET",
            url=url,
            headers={"Authorization": f"Bearer {self.bot_token}"},
            timeout=self._timeout * 2,
            return_raw=True,
            operation="download_file_content",
        )

        if dl_success and isinstance(content, bytes):
            return FileAttachment(
                id=file_id,
                filename=file_data.get("name", ""),
                content_type=file_data.get("mimetype", "application/octet-stream"),
                size=len(content),
                url=url,
                content=content,
            )

        return FileAttachment(
            id=file_id,
            filename=file_data.get("name", ""),
            content_type=file_data.get("mimetype", "application/octet-stream"),
            size=file_data.get("size", 0),
        )

    # ==========================================================================
    # Channel and User Info (implements abstract methods)
    # ==========================================================================

    async def get_channel_info(self, channel_id: str, **kwargs: Any) -> ChatChannel | None:
        """Get channel information from Slack with retry and circuit breaker."""
        success, data, error = await self._slack_api_request(
            "conversations.info",
            operation="get_channel_info",
            method="GET",
            params={"channel": channel_id},
        )

        if success and data:
            channel_data = data.get("channel", {})
            return ChatChannel(
                id=channel_id,
                platform=self.platform_name,
                name=channel_data.get("name"),
                team_id=channel_data.get("context_team_id"),
                is_private=channel_data.get("is_private", False),
                metadata={
                    "topic": channel_data.get("topic", {}).get("value", ""),
                    "purpose": channel_data.get("purpose", {}).get("value", ""),
                    "num_members": channel_data.get("num_members", 0),
                },
            )

        if error:
            logger.debug("get_channel_info failed: %s", error)
        return None

    async def get_user_info(self, user_id: str, **kwargs: Any) -> ChatUser | None:
        """Get user information from Slack with retry and circuit breaker."""
        success, data, error = await self._slack_api_request(
            "users.info",
            operation="get_user_info",
            method="GET",
            params={"user": user_id},
        )

        if success and data:
            user_data = data.get("user", {})
            profile = user_data.get("profile", {})
            return ChatUser(
                id=user_id,
                platform=self.platform_name,
                username=user_data.get("name"),
                display_name=profile.get("display_name") or profile.get("real_name"),
                email=profile.get("email"),
                is_bot=user_data.get("is_bot", False),
                metadata={
                    "title": profile.get("title", ""),
                    "team_id": user_data.get("team_id"),
                    "tz": user_data.get("tz"),
                },
            )

        if error:
            logger.debug("get_user_info failed: %s", error)
        return None

    def format_blocks(
        self,
        title: str | None = None,
        body: str | None = None,
        fields: list[tuple[str, str]] | None = None,
        actions: list[MessageButton] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Format content as Slack Block Kit blocks."""
        blocks: list[dict[str, Any]] = []

        if title:
            blocks.append(
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": title,
                        "emoji": True,
                    },
                }
            )

        if body:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": body,
                    },
                }
            )

        if fields:
            field_elements = []
            for label, value in fields:
                field_elements.append(
                    {
                        "type": "mrkdwn",
                        "text": f"*{label}*\n{value}",
                    }
                )
            blocks.append(
                {
                    "type": "section",
                    "fields": field_elements,
                }
            )

        if actions:
            action_elements = [
                self.format_button(btn.text, btn.action_id, btn.value, btn.style, btn.url)
                for btn in actions
            ]
            blocks.append(
                {
                    "type": "actions",
                    "elements": action_elements,
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
        """Format a Slack button element."""
        if url:
            return {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": text,
                    "emoji": True,
                },
                "url": url,
            }

        button: dict[str, Any] = {
            "type": "button",
            "text": {
                "type": "plain_text",
                "text": text,
                "emoji": True,
            },
            "action_id": action_id,
            "value": value or action_id,
        }

        if style == "primary":
            button["style"] = "primary"
        elif style == "danger":
            button["style"] = "danger"

        return button

    # =========================================================================
    # Reactions / Emoji Support
    # =========================================================================

    async def add_reaction(
        self,
        channel_id: str,
        message_id: str,
        emoji: str,
        **kwargs: Any,
    ) -> bool:
        """Add an emoji reaction to a message.

        Uses _slack_api_request for circuit breaker, retry, and timeout handling.

        Args:
            channel_id: Channel containing the message
            message_id: Timestamp of the message (Slack uses ts as message ID)
            emoji: Emoji name without colons (e.g., "thumbsup" not ":thumbsup:")
            **kwargs: Additional parameters

        Returns:
            True if successful, False otherwise
        """
        success, data, error = await self._slack_api_request(
            "reactions.add",
            operation="add_reaction",
            json_data={
                "channel": channel_id,
                "timestamp": message_id,
                "name": emoji.strip(":"),
            },
        )

        # "already_reacted" is not really a failure
        if not success and error == "already_reacted":
            return True

        return success

    async def remove_reaction(
        self,
        channel_id: str,
        message_id: str,
        reaction: str | None = None,
        emoji: str | None = None,
        **kwargs: Any,
    ) -> bool:
        """Remove an emoji reaction from a message.

        Uses _slack_api_request for circuit breaker, retry, and timeout handling.

        Args:
            channel_id: Channel containing the message
            message_id: Timestamp of the message
            reaction: Emoji name without colons (e.g., "thumbsup" not ":thumbsup:")
            **kwargs: Additional parameters

        Returns:
            True if successful, False otherwise
        """
        reaction_name = reaction or emoji or kwargs.get("reaction") or kwargs.get("emoji")
        if not reaction_name:
            return False

        success, data, error = await self._slack_api_request(
            "reactions.remove",
            operation="remove_reaction",
            json_data={
                "channel": channel_id,
                "timestamp": message_id,
                "name": reaction_name.strip(":"),
            },
        )

        # "no_reaction" is not really a failure
        if not success and error == "no_reaction":
            return True

        return success

    # =========================================================================
    # Channel & User Discovery
    # =========================================================================

    async def list_channels(
        self,
        exclude_archived: bool = True,
        types: str = "public_channel,private_channel",
        limit: int = 100,
        **kwargs: Any,
    ) -> list[ChatChannel]:
        """List channels in the workspace.

        Uses _slack_api_request for circuit breaker, retry, and timeout handling.

        Args:
            exclude_archived: Whether to exclude archived channels
            types: Comma-separated channel types (public_channel, private_channel)
            limit: Maximum number of channels to return
            **kwargs: Additional parameters

        Returns:
            List of ChatChannel objects
        """
        success, data, error = await self._slack_api_request(
            "conversations.list",
            operation="list_channels",
            method="GET",
            params={
                "exclude_archived": str(exclude_archived).lower(),
                "types": types,
                "limit": limit,
            },
        )

        if not success or not data:
            if error:
                logger.error("Slack list_channels error: %s", error)
            return []

        channels = []
        for ch in data.get("channels", []):
            channels.append(
                ChatChannel(
                    id=ch.get("id", ""),
                    platform=self.platform_name,
                    name=ch.get("name"),
                    metadata={
                        "is_private": ch.get("is_private", False),
                        "is_archived": ch.get("is_archived", False),
                        "is_member": ch.get("is_member", False),
                        "num_members": ch.get("num_members", 0),
                        "topic": ch.get("topic", {}).get("value"),
                        "purpose": ch.get("purpose", {}).get("value"),
                    },
                )
            )
        return channels

    async def list_users(
        self,
        channel_id: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
        **kwargs: Any,
    ) -> tuple[list[ChatUser], str | None]:
        """List users in a channel or workspace.

        Uses _slack_api_request for circuit breaker, retry, and timeout handling.

        Args:
            channel_id: Optional channel to list members of. If provided,
                lists members of that channel. Otherwise lists workspace members.
            limit: Maximum number of users to return
            cursor: Pagination cursor for subsequent requests
            **kwargs: Additional parameters (include_bots: bool to include bot users)

        Returns:
            Tuple of (list of ChatUser, next_cursor or None)
        """
        include_bots = kwargs.get("include_bots", False)

        if channel_id:
            # List channel members
            params: dict[str, Any] = {"channel": channel_id, "limit": limit}
            if cursor:
                params["cursor"] = cursor

            success, data, error = await self._slack_api_request(
                "conversations.members",
                operation="list_channel_members",
                method="GET",
                params=params,
            )

            if not success or not data:
                if error:
                    logger.error("Slack list_users (channel members) error: %s", error)
                return [], None

            # Get user info for each member
            users = []
            for user_id in data.get("members", []):
                user_info = await self.get_user_info(user_id)
                if user_info:
                    # Skip bots if not requested
                    if not include_bots and user_info.is_bot:
                        continue
                    users.append(user_info)

            next_cursor = data.get("response_metadata", {}).get("next_cursor") or None
            return users, next_cursor

        # List workspace users
        params = {"limit": limit}
        if cursor:
            params["cursor"] = cursor

        success, data, error = await self._slack_api_request(
            "users.list",
            operation="list_users",
            method="GET",
            params=params,
        )

        if not success or not data:
            if error:
                logger.error("Slack list_users error: %s", error)
            return [], None

        users = []
        for member in data.get("members", []):
            # Skip bots if not requested
            if not include_bots and member.get("is_bot", False):
                continue
            # Skip deleted users
            if member.get("deleted", False):
                continue

            profile = member.get("profile", {})
            users.append(
                ChatUser(
                    id=member.get("id", ""),
                    platform=self.platform_name,
                    username=member.get("name"),
                    display_name=profile.get("display_name") or profile.get("real_name"),
                    avatar_url=profile.get("image_72"),
                    metadata={
                        "email": profile.get("email"),
                        "title": profile.get("title"),
                        "is_admin": member.get("is_admin", False),
                        "is_owner": member.get("is_owner", False),
                        "tz": member.get("tz"),
                    },
                )
            )

        next_cursor = data.get("response_metadata", {}).get("next_cursor") or None
        return users, next_cursor

    # =========================================================================
    # User Mention Helpers
    # =========================================================================

    @staticmethod
    def format_user_mention(user_id: str) -> str:
        """Format a user mention for Slack messages.

        Args:
            user_id: The Slack user ID (e.g., "U123ABC")

        Returns:
            Formatted mention string (e.g., "<@U123ABC>")
        """
        return f"<@{user_id}>"

    @staticmethod
    def format_channel_mention(channel_id: str) -> str:
        """Format a channel mention for Slack messages.

        Args:
            channel_id: The Slack channel ID (e.g., "C123ABC")

        Returns:
            Formatted mention string (e.g., "<#C123ABC>")
        """
        return f"<#{channel_id}>"

    # =========================================================================
    # Modal / View Support
    # =========================================================================

    async def open_modal(
        self,
        trigger_id: str,
        view: dict[str, Any],
        **kwargs: Any,
    ) -> str | None:
        """Open a modal view.

        Uses _slack_api_request for circuit breaker, retry, and timeout handling.

        Args:
            trigger_id: Trigger ID from interaction payload (valid for 3 seconds)
            view: Modal view payload following Slack Block Kit spec
            **kwargs: Additional parameters

        Returns:
            View ID if successful, None otherwise
        """
        success, data, error = await self._slack_api_request(
            "views.open",
            operation="open_modal",
            json_data={
                "trigger_id": trigger_id,
                "view": view,
            },
        )

        if success and data:
            view_id: str | None = data.get("view", {}).get("id")
            return view_id

        if error:
            logger.error("Slack open_modal error: %s", error)
        return None

    async def update_modal(
        self,
        view_id: str,
        view: dict[str, Any],
        view_hash: str | None = None,
        **kwargs: Any,
    ) -> bool:
        """Update an existing modal view.

        Uses _slack_api_request for circuit breaker, retry, and timeout handling.

        Args:
            view_id: ID of the view to update
            view: Updated view payload
            view_hash: Optional view hash for optimistic locking
            **kwargs: Additional parameters

        Returns:
            True if successful, False otherwise
        """
        payload: dict[str, Any] = {
            "view_id": view_id,
            "view": view,
        }
        if view_hash:
            payload["hash"] = view_hash

        success, _, error = await self._slack_api_request(
            "views.update",
            operation="update_modal",
            json_data=payload,
        )

        if not success and error:
            logger.error("Slack update_modal error: %s", error)
        return success

    # =========================================================================
    # Pinned Messages
    # =========================================================================

    async def pin_message(
        self,
        channel_id: str,
        message_id: str,
        **kwargs: Any,
    ) -> bool:
        """Pin a message to a channel.

        Uses _slack_api_request for circuit breaker, retry, and timeout handling.

        Args:
            channel_id: Channel ID
            message_id: Message timestamp
            **kwargs: Additional parameters

        Returns:
            True if successful, False otherwise
        """
        success, _, error = await self._slack_api_request(
            "pins.add",
            operation="pin_message",
            json_data={
                "channel": channel_id,
                "timestamp": message_id,
            },
        )

        # "already_pinned" is not really a failure
        if not success and error == "already_pinned":
            return True

        return success

    async def unpin_message(
        self,
        channel_id: str,
        message_id: str,
        **kwargs: Any,
    ) -> bool:
        """Unpin a message from a channel.

        Uses _slack_api_request for circuit breaker, retry, and timeout handling.

        Args:
            channel_id: Channel ID
            message_id: Message timestamp
            **kwargs: Additional parameters

        Returns:
            True if successful, False otherwise
        """
        success, _, error = await self._slack_api_request(
            "pins.remove",
            operation="unpin_message",
            json_data={
                "channel": channel_id,
                "timestamp": message_id,
            },
        )

        # "no_pin" is not really a failure
        if not success and error == "no_pin":
            return True

        return success

    async def get_pinned_messages(
        self,
        channel_id: str,
        **kwargs: Any,
    ) -> list[ChatMessage]:
        """Get pinned messages in a channel.

        Uses _slack_api_request for circuit breaker, retry, and timeout handling.

        Args:
            channel_id: Channel ID
            **kwargs: Additional parameters

        Returns:
            List of pinned ChatMessage objects
        """
        success, data, error = await self._slack_api_request(
            "pins.list",
            operation="get_pinned_messages",
            method="GET",
            params={"channel": channel_id},
        )

        if not success or not data:
            if error:
                logger.error("Slack get_pinned_messages error: %s", error)
            return []

        messages = []
        for item in data.get("items", []):
            if item.get("type") != "message":
                continue
            msg_data = item.get("message", {})
            channel = ChatChannel(
                id=channel_id,
                platform=self.platform_name,
            )
            user = ChatUser(
                id=msg_data.get("user", ""),
                platform=self.platform_name,
            )
            messages.append(
                ChatMessage(
                    id=msg_data.get("ts", ""),
                    platform=self.platform_name,
                    channel=channel,
                    author=user,
                    content=msg_data.get("text", ""),
                    timestamp=datetime.fromtimestamp(float(msg_data.get("ts", "0").split(".")[0])),
                    metadata={"pinned": True},
                )
            )
        return messages

    # =========================================================================
    # Evidence Collection
    # =========================================================================

    async def get_channel_history(
        self,
        channel_id: str,
        limit: int = 100,
        oldest: str | None = None,
        latest: str | None = None,
        **kwargs: Any,
    ) -> list[ChatMessage]:
        """
        Get message history from a Slack channel with timeout.

        Uses _slack_api_request for circuit breaker, retry, and timeout handling.

        Args:
            channel_id: Channel ID to get history from
            limit: Maximum number of messages (max 1000)
            oldest: Oldest timestamp to include
            latest: Latest timestamp to include
            **kwargs: Additional API parameters

        Returns:
            List of ChatMessage objects
        """
        params: dict[str, Any] = {
            "channel": channel_id,
            "limit": min(limit, 1000),  # Slack API max
        }

        if oldest:
            params["oldest"] = oldest
        if latest:
            params["latest"] = latest

        # Include thread replies if requested
        if kwargs.get("include_all_metadata", True):
            params["include_all_metadata"] = True

        success, data, error = await self._slack_api_request(
            "conversations.history",
            operation="get_channel_history",
            method="GET",
            params=params,
        )

        if not success or not data:
            if error:
                logger.error("Slack API error: %s", error)
            return []

        messages: list[ChatMessage] = []
        channel_info = await self.get_channel_info(channel_id)
        channel = channel_info or ChatChannel(
            id=channel_id,
            platform=self.platform_name,
        )

        for msg in data.get("messages", []):
            # Skip bot messages if configured
            if kwargs.get("skip_bots", True) and msg.get("bot_id"):
                continue

            user = ChatUser(
                id=msg.get("user", msg.get("bot_id", "")),
                platform=self.platform_name,
                is_bot=bool(msg.get("bot_id")),
            )

            chat_msg = ChatMessage(
                id=msg.get("ts", ""),
                platform=self.platform_name,
                channel=channel,
                author=user,
                content=msg.get("text", ""),
                thread_id=msg.get("thread_ts"),
                timestamp=datetime.fromtimestamp(float(msg.get("ts", "0").split(".")[0])),
                metadata={
                    "reply_count": msg.get("reply_count", 0),
                    "reactions": msg.get("reactions", []),
                },
            )
            messages.append(chat_msg)

        return messages

    async def collect_evidence(
        self,
        channel_id: str,
        query: str | None = None,
        limit: int = 100,
        include_threads: bool = True,
        min_relevance: float = 0.0,
        **kwargs: Any,
    ) -> list[ChatEvidence]:
        """
        Collect chat messages as evidence for debates.

        Retrieves messages from a Slack channel, filters by relevance,
        and converts to ChatEvidence format with provenance tracking.

        Args:
            channel_id: Slack channel ID
            query: Optional search query to filter messages
            limit: Maximum number of messages to retrieve
            include_threads: Whether to include threaded replies
            min_relevance: Minimum relevance score for inclusion (0-1)
            **kwargs: Additional options

        Returns:
            List of ChatEvidence objects with relevance scoring
        """
        # Get channel history
        messages = await self.get_channel_history(
            channel_id=channel_id,
            limit=limit,
            **kwargs,
        )

        if not messages:
            return []

        # Convert to evidence with relevance scoring
        evidence_list: list[ChatEvidence] = []

        for msg in messages:
            # Calculate relevance
            relevance = self._compute_message_relevance(msg, query)

            # Skip low-relevance messages
            if relevance < min_relevance:
                continue

            # Create evidence
            evidence = ChatEvidence.from_message(
                message=msg,
                query=query,
                relevance_score=relevance,
            )

            evidence_list.append(evidence)

        # Sort by relevance (highest first)
        evidence_list.sort(key=lambda e: e.relevance_score, reverse=True)

        # Optionally fetch thread replies for high-relevance messages
        if include_threads:
            await self._enrich_with_threads(evidence_list, limit=5, **kwargs)

        logger.info(
            "Collected %s evidence items from Slack channel %s", len(evidence_list), channel_id
        )

        return evidence_list

    async def _enrich_with_threads(
        self,
        evidence_list: list[ChatEvidence],
        limit: int = 5,
        **kwargs: Any,
    ) -> None:
        """Enrich evidence with thread reply information.

        Uses _slack_api_request for circuit breaker, retry, and timeout handling.
        """
        for evidence in evidence_list[:limit]:
            # Only enrich if this is a thread root with replies
            reply_count = evidence.metadata.get("reply_count", 0)
            if not evidence.is_thread_root or reply_count == 0:
                continue

            success, data, error = await self._slack_api_request(
                "conversations.replies",
                operation="enrich_threads",
                method="GET",
                params={
                    "channel": evidence.channel_id,
                    "ts": evidence.source_id,
                    "limit": 10,
                },
            )

            if success and data:
                replies = data.get("messages", [])[1:]  # Skip root
                evidence.reply_count = len(replies)
                evidence.metadata["thread_replies"] = [
                    {
                        "text": r.get("text", "")[:200],
                        "user": r.get("user", ""),
                        "ts": r.get("ts", ""),
                    }
                    for r in replies
                ]

    async def search_messages(
        self,
        query: str,
        channel_id: str | None = None,
        limit: int = 20,
        **kwargs: Any,
    ) -> list[ChatEvidence]:
        """
        Search for messages across Slack workspace with timeout.

        Uses _slack_api_request for circuit breaker, retry, and timeout handling.

        Args:
            query: Search query
            channel_id: Optional channel to restrict search
            limit: Maximum results to return
            **kwargs: Additional search parameters

        Returns:
            List of ChatEvidence from matching messages
        """
        search_query = query
        if channel_id:
            search_query = f"in:<#{channel_id}> {query}"

        success, data, error = await self._slack_api_request(
            "search.messages",
            operation="search_messages",
            method="GET",
            params={
                "query": search_query,
                "count": limit,
                "sort": kwargs.get("sort", "score"),
            },
        )

        if not success or not data:
            if error:
                logger.error("Slack search error: %s", error)
            return []

        matches = data.get("messages", {}).get("matches", [])
        evidence_list: list[ChatEvidence] = []

        for match in matches:
            channel = ChatChannel(
                id=match.get("channel", {}).get("id", ""),
                platform=self.platform_name,
                name=match.get("channel", {}).get("name"),
            )

            user = ChatUser(
                id=match.get("user", ""),
                platform=self.platform_name,
                username=match.get("username"),
            )

            msg = ChatMessage(
                id=match.get("ts", ""),
                platform=self.platform_name,
                channel=channel,
                author=user,
                content=match.get("text", ""),
                timestamp=datetime.fromtimestamp(float(match.get("ts", "0").split(".")[0])),
                metadata={
                    "permalink": match.get("permalink"),
                    "score": match.get("score"),
                },
            )

            evidence = ChatEvidence.from_message(
                message=msg,
                query=query,
                relevance_score=match.get("score", 1.0) / 100,  # Normalize
            )
            evidence.metadata["permalink"] = match.get("permalink")

            evidence_list.append(evidence)

        return evidence_list

    def _format_timestamp_for_api(self, timestamp: Any) -> str | None:
        """
        Format a datetime for Slack's API (Unix timestamp).

        Slack uses Unix timestamps (seconds since epoch) for
        the oldest/latest parameters in conversations.history.
        """
        if timestamp is None:
            return None

        if isinstance(timestamp, datetime):
            return str(timestamp.timestamp())

        return str(timestamp)
