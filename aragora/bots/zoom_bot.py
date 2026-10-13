"""
Zoom bot implementation for Aragora.

Provides Zoom integration for running debates in meeting chats
and receiving post-meeting summaries.

Environment Variables:
- ZOOM_CLIENT_ID - Required for OAuth
- ZOOM_CLIENT_SECRET - Required for OAuth
- ZOOM_BOT_JID - Bot's JID for chat
- ZOOM_VERIFICATION_TOKEN - Webhook verification

Usage:
    from aragora.bots.zoom_bot import AragoraZoomBot
    bot = AragoraZoomBot(...)
    response = await bot.handle_event(event_data)
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from datetime import datetime, timezone
from typing import Any

from aragora.bots.base import (
    BotChannel,
    BotConfig,
    BotMessage,
    BotUser,
    CommandContext,
    Platform,
)
from aragora.bots.commands import get_default_registry

logger = logging.getLogger(__name__)

# Environment variables
ZOOM_CLIENT_ID = os.environ.get("ZOOM_CLIENT_ID", "")
ZOOM_CLIENT_SECRET = os.environ.get("ZOOM_CLIENT_SECRET", "")
ZOOM_BOT_JID = os.environ.get("ZOOM_BOT_JID", "")
ZOOM_VERIFICATION_TOKEN = os.environ.get("ZOOM_VERIFICATION_TOKEN", "")
ZOOM_SECRET_TOKEN = os.environ.get("ZOOM_SECRET_TOKEN", "")

# API base for Aragora backend (validated at bot initialization, not import time)
# The BotClient base class validates api_base in __init__ and provides appropriate
# error messages for production environments.
API_BASE = os.environ.get("ARAGORA_API_BASE", "")


class ZoomOAuthManager:
    """Manages Zoom OAuth tokens."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self._access_token: str | None = None
        self._token_expires: datetime | None = None

    async def get_access_token(self) -> str | None:
        """Get a valid access token, refreshing if needed."""
        if self._access_token and self._token_expires:
            if datetime.now(timezone.utc) < self._token_expires:
                return self._access_token

        # Fetch new token using client credentials
        try:
            import base64

            from aragora.observability.http_client_pool import get_http_pool

            auth_str = f"{self.client_id}:{self.client_secret}"
            auth_bytes = base64.b64encode(auth_str.encode()).decode()

            pool = get_http_pool()
            async with pool.get_session("zoom") as client:
                resp = await client.post(
                    "https://zoom.us/oauth/token",
                    headers={
                        "Authorization": f"Basic {auth_bytes}",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                    data={"grant_type": "client_credentials"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    self._access_token = data.get("access_token")
                    expires_in = data.get("expires_in", 3600)
                    from datetime import timedelta

                    self._token_expires = datetime.now(timezone.utc) + timedelta(
                        seconds=expires_in - 60  # Buffer
                    )
                    return self._access_token
                else:
                    logger.error("Failed to get Zoom token: %s", resp.status_code)
                    return None
        except ImportError:
            logger.warning("httpx not installed for Zoom OAuth")
            return None
        except OSError as e:
            logger.error("Zoom OAuth error: %s", e)
            return None


class AragoraZoomBot:
    """Zoom bot for Aragora platform integration.

    This bot handles:
    - Chat messages in Zoom meetings
    - /aragora slash commands
    - Post-meeting summary integration
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        bot_jid: str | None = None,
        verification_token: str | None = None,
        secret_token: str | None = None,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.bot_jid = bot_jid
        self.verification_token = verification_token
        self.secret_token = secret_token
        self.oauth = ZoomOAuthManager(client_id, client_secret)
        self.config = BotConfig(
            platform=Platform.ZOOM,
            token=client_secret,
            app_id=client_id,
            api_base=API_BASE,
        )
        self.registry = get_default_registry()

    def verify_webhook(
        self,
        payload: bytes,
        timestamp: str,
        signature: str,
    ) -> bool:
        """Verify Zoom webhook signature.

        Zoom uses HMAC-SHA256 for webhook verification.
        """
        if not self.secret_token:
            logger.warning("ZOOM_SECRET_TOKEN not configured, rejecting webhook")
            return False

        try:
            message = f"v0:{timestamp}:{payload.decode('utf-8')}"
            expected = (
                "v0="
                + hmac.new(
                    self.secret_token.encode(),
                    message.encode(),
                    hashlib.sha256,
                ).hexdigest()
            )

            return hmac.compare_digest(expected, signature)
        except (ValueError, UnicodeDecodeError) as e:
            logger.error("Zoom signature verification error: %s", e)
            return False

    async def handle_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Handle incoming Zoom event.

        Returns response dict to send back to Zoom.
        """
        event_type = event.get("event", "")
        payload = event.get("payload", {})

        # URL validation challenge
        if event_type == "endpoint.url_validation":
            plain_token = payload.get("plainToken", "")
            if self.secret_token:
                encrypted = hmac.new(
                    self.secret_token.encode(),
                    plain_token.encode(),
                    hashlib.sha256,
                ).hexdigest()
                return {
                    "plainToken": plain_token,
                    "encryptedToken": encrypted,
                }
            return {"plainToken": plain_token}

        # Bot installed
        if event_type == "bot_installed":
            logger.info("Zoom bot installed: %s", payload)
            return {"status": "ok"}

        # Chat message
        if event_type == "bot_notification":
            return await self._handle_chat_message(payload)

        # Meeting ended - could trigger summary
        if event_type == "meeting.ended":
            return await self._handle_meeting_ended(payload)

        logger.debug("Unhandled Zoom event: %s", event_type)
        return {"status": "ok"}

    async def _handle_chat_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle incoming chat message."""
        payload.get("robotJid", "")
        payload.get("userJid", "")
        account_id = payload.get("accountId", "")
        payload.get("channelName", "")
        to_jid = payload.get("toJid", "")

        # Get message content
        cmd = payload.get("cmd", "")  # Command text after bot mention

        if not cmd:
            return await self._send_chat_message(
                to_jid,
                account_id,
                'Hi! I\'m Aragora. Try `/aragora help` or `/aragora debate "topic"` to get started.',
            )

        # Parse command
        parts = cmd.strip().split(maxsplit=1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        # Create context
        ctx = self._create_context(payload, command, args)
        result = await self.registry.execute(ctx)

        # Send response
        message = result.message or result.error or "Command executed"
        return await self._send_chat_message(to_jid, account_id, message)

    async def _handle_meeting_ended(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle meeting ended event.

        Could be used to send debate summaries or meeting analysis.
        """
        meeting_id = payload.get("object", {}).get("id", "")
        host_email = payload.get("object", {}).get("host_email", "")

        # Log without exposing full email address
        host_masked = host_email[:2] + "***" if host_email else "unknown"
        logger.info("Meeting ended: %s (host: %s)", meeting_id, host_masked)

        # Trigger post-meeting summary generation if configured
        if getattr(self.config, "enable_post_meeting_summary", False):
            await self._generate_post_meeting_summary(meeting_id, host_email, payload)

        return {"status": "ok"}

    async def _generate_post_meeting_summary(
        self,
        meeting_id: str,
        host_email: str,
        payload: dict[str, Any],
    ) -> None:
        """Generate and send post-meeting summary using debate analysis."""
        try:
            from aragora.observability.http_client_pool import get_http_pool

            meeting_data = payload.get("object", {})
            topic = meeting_data.get("topic", "Untitled Meeting")
            duration = meeting_data.get("duration", 0)
            participant_count = meeting_data.get("participant_count", 0)

            # Request summary generation from Aragora API
            pool = get_http_pool()
            async with pool.get_session("aragora") as client:
                resp = await client.post(
                    f"{API_BASE}/api/v1/meetings/summary",
                    json={
                        "meeting_id": meeting_id,
                        "topic": topic,
                        "duration_minutes": duration,
                        "participant_count": participant_count,
                        "host_email": host_email,
                        "platform": "zoom",
                    },
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code == 200:
                    logger.info("Post-meeting summary generated for %s", meeting_id)
                else:
                    logger.warning(
                        "Failed to generate summary for %s: %s", meeting_id, resp.status_code
                    )
        except ImportError:
            logger.warning("httpx not available for post-meeting summary")
        except OSError as e:
            logger.error("Error generating post-meeting summary: %s", e)

    async def _send_chat_message(
        self,
        to_jid: str,
        account_id: str,
        message: str,
    ) -> dict[str, Any]:
        """Send a chat message via Zoom API."""
        try:
            from aragora.observability.http_client_pool import get_http_pool

            token = await self.oauth.get_access_token()
            if not token:
                logger.error("No Zoom access token available")
                return {"status": "error", "message": "Authentication failed"}

            payload = {
                "robot_jid": self.bot_jid,
                "to_jid": to_jid,
                "account_id": account_id,
                "content": {
                    "head": {
                        "text": "Aragora",
                    },
                    "body": [
                        {
                            "type": "message",
                            "text": message,
                        }
                    ],
                },
            }

            pool = get_http_pool()
            async with pool.get_session("zoom") as client:
                resp = await client.post(
                    "https://api.zoom.us/v2/im/chat/messages",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                if resp.status_code in (200, 201):
                    return {"status": "ok"}
                else:
                    text = resp.text
                    logger.error("Zoom send failed: %s - %s", resp.status_code, text)
                    return {"status": "error", "message": text[:100]}

        except ImportError:
            logger.warning("httpx not installed for Zoom API calls")
            return {"status": "error", "message": "httpx not installed"}
        except OSError as e:
            logger.error("Zoom send error: %s", e)
            return {"status": "error", "message": "Failed to send message"}

    def _create_context(
        self,
        payload: dict[str, Any],
        command: str,
        args: str,
    ) -> CommandContext:
        """Create CommandContext from Zoom payload."""
        user_jid = payload.get("userJid", "unknown")
        user_name = payload.get("userName", "unknown")

        user = BotUser(
            id=user_jid,
            username=user_name,
            display_name=user_name,
            platform=Platform.ZOOM,
        )

        to_jid = payload.get("toJid", "unknown")
        channel_name = payload.get("channelName", "")

        channel = BotChannel(
            id=to_jid,
            name=channel_name or None,
            is_dm=not channel_name,
            platform=Platform.ZOOM,
        )

        message = BotMessage(
            id=payload.get("messageId", "unknown"),
            text=f"/{command} {args}".strip(),
            user=user,
            channel=channel,
            timestamp=datetime.now(timezone.utc),
            platform=Platform.ZOOM,
        )

        return CommandContext(
            message=message,
            user=user,
            channel=channel,
            platform=Platform.ZOOM,
            args=[command] + (args.split() if args else []),
            raw_args=args,
            metadata={
                "api_base": self.config.api_base,
                "account_id": payload.get("accountId"),
            },
        )


def create_zoom_bot(
    client_id: str | None = None,
    client_secret: str | None = None,
    bot_jid: str | None = None,
    verification_token: str | None = None,
    secret_token: str | None = None,
) -> AragoraZoomBot:
    """Create an Aragora Zoom bot instance.

    Args:
        client_id: Zoom app client ID (defaults to ZOOM_CLIENT_ID env var)
        client_secret: Zoom app client secret (defaults to ZOOM_CLIENT_SECRET env var)
        bot_jid: Bot's JID (defaults to ZOOM_BOT_JID env var)
        verification_token: Webhook verification token (defaults to ZOOM_VERIFICATION_TOKEN)
        secret_token: Secret token for signatures (defaults to ZOOM_SECRET_TOKEN)

    Returns:
        Configured AragoraZoomBot instance
    """
    client_id = client_id or ZOOM_CLIENT_ID
    client_secret = client_secret or ZOOM_CLIENT_SECRET
    bot_jid = bot_jid or ZOOM_BOT_JID
    verification_token = verification_token or ZOOM_VERIFICATION_TOKEN
    secret_token = secret_token or ZOOM_SECRET_TOKEN

    if not client_id or not client_secret:
        raise ValueError(
            "Zoom credentials required. Set ZOOM_CLIENT_ID and ZOOM_CLIENT_SECRET env vars."
        )

    return AragoraZoomBot(
        client_id=client_id,
        client_secret=client_secret,
        bot_jid=bot_jid,
        verification_token=verification_token,
        secret_token=secret_token,
    )


__all__ = [
    "AragoraZoomBot",
    "ZoomOAuthManager",
    "create_zoom_bot",
]
