"""
Microsoft Teams Dock - Channel dock implementation for Teams.

Handles message delivery to Microsoft Teams via webhooks and Adaptive Cards.

Example:
    from aragora.channels.docks.teams import TeamsDock

    dock = TeamsDock()
    await dock.initialize()
    await dock.send_message(channel_id, message, webhook_url="https://...")
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from aragora.channels.dock import ChannelDock, ChannelCapability, SendResult
from aragora.observability.http_client_pool import get_http_pool

if TYPE_CHECKING:
    from aragora.channels.normalized import NormalizedMessage

logger = logging.getLogger(__name__)

__all__ = ["TeamsDock"]


class TeamsDock(ChannelDock):
    """
    Microsoft Teams platform dock.

    Supports Adaptive Cards, file uploads, and webhook-based delivery.
    Teams uses incoming webhooks for sending messages rather than a bot token.
    """

    PLATFORM = "teams"
    CAPABILITIES = (
        ChannelCapability.RICH_TEXT
        | ChannelCapability.BUTTONS
        | ChannelCapability.THREADS
        | ChannelCapability.FILES
        | ChannelCapability.CARDS
    )

    def __init__(self, config: dict[str, Any] | None = None):
        """
        Initialize Teams dock.

        Config options:
            webhook_url: Default webhook URL for sending messages
        """
        super().__init__(config)
        self._default_webhook: str | None = None

    async def initialize(self) -> bool:
        """Initialize the Teams dock."""
        self._default_webhook = self.config.get("webhook_url")
        # Teams doesn't require initialization - webhooks are per-channel
        self._initialized = True
        return True

    async def send_message(
        self,
        channel_id: str,
        message: NormalizedMessage,
        **kwargs: Any,
    ) -> SendResult:
        """
        Send a message to Microsoft Teams.

        Args:
            channel_id: Teams channel identifier (may be webhook URL)
            message: The normalized message to send
            **kwargs: Additional options including webhook_url

        Returns:
            SendResult indicating success or failure
        """
        # Get webhook URL from kwargs, config, or channel_id
        webhook_url = kwargs.get("webhook_url") or self._default_webhook or channel_id

        if not webhook_url or not webhook_url.startswith("http"):
            return SendResult.fail(
                error="Teams webhook URL not configured",
                platform=self.PLATFORM,
                channel_id=channel_id,
            )

        try:
            payload = self._build_payload(channel_id, message, **kwargs)

            pool = get_http_pool()
            async with pool.get_session("teams") as client:
                response = await client.post(webhook_url, json=payload, timeout=30.0)

                if response.status_code == 200:
                    return SendResult.ok(
                        platform=self.PLATFORM,
                        channel_id=channel_id,
                    )
                else:
                    return SendResult.fail(
                        error=f"HTTP {response.status_code}: {response.text[:200]}",
                        platform=self.PLATFORM,
                        channel_id=channel_id,
                    )

        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.error("Teams send error: %s", e)
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
        """Build Teams Adaptive Card payload from normalized message."""
        # Build card body
        body: list[dict[str, Any]] = []

        # Add title
        if message.title:
            body.append(
                {
                    "type": "TextBlock",
                    "text": message.title[:150],
                    "weight": "Bolder",
                    "size": "Large",
                }
            )

        # Add main content
        if message.content:
            body.append(
                {
                    "type": "TextBlock",
                    "text": message.to_plain_text()[:3000],
                    "wrap": True,
                }
            )

        # Add buttons as actions
        actions: list[dict[str, Any]] = []
        if message.has_buttons():
            for button in message.buttons[:5]:  # Teams limits actions
                if isinstance(button, dict):
                    label = button.get("label", "Click")
                    action = button.get("action", "")
                else:
                    label = getattr(button, "label", "Click")
                    action = getattr(button, "action", "")

                if action.startswith("http"):
                    actions.append(
                        {
                            "type": "Action.OpenUrl",
                            "title": label[:50],
                            "url": action,
                        }
                    )

        # Build Adaptive Card structure
        card: dict[str, Any] = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": body,
                    },
                }
            ],
        }

        # Add actions to card if present
        if actions:
            card["attachments"][0]["content"]["actions"] = actions

        return card

    async def send_result(
        self,
        channel_id: str,
        result: dict[str, Any],
        thread_id: str | None = None,
        **kwargs: Any,
    ) -> SendResult:
        """Send a debate result to Teams with rich formatting."""
        from aragora.channels.normalized import NormalizedMessage, MessageFormat
        from aragora.channels.dock import MessageType

        consensus = result.get("consensus_reached", False)
        confidence = result.get("confidence", 0)
        answer = result.get("final_answer", "No conclusion reached.")

        # Build rich content
        status = "Consensus Reached" if consensus else "No Consensus"
        confidence_bar = "█" * int(confidence * 10) + "░" * (10 - int(confidence * 10))

        content = (
            f"**Status:** {status}\n"
            f"**Confidence:** {confidence_bar} {confidence:.0%}\n\n"
            f"**Conclusion:**\n{answer[:2000]}"
        )

        message = NormalizedMessage(
            content=content,
            message_type=MessageType.RESULT,
            format=MessageFormat.MARKDOWN,
            title="Aragora Debate Complete",
            thread_id=thread_id,
        )

        # Add view details button if we have a receipt URL
        receipt_url = result.get("receipt_url") or kwargs.get("receipt_url")
        if receipt_url:
            message.with_button("View Details", receipt_url)

        return await self.send_message(channel_id, message, **kwargs)
