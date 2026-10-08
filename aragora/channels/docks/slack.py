"""
Slack Dock - Channel dock implementation for Slack.

Handles message delivery to Slack workspaces via the Slack API.

Example:
    from aragora.channels.docks.slack import SlackDock

    dock = SlackDock({"token": "xoxb-..."})
    await dock.initialize()
    await dock.send_message(channel_id, message)
"""

from __future__ import annotations

import logging
import os
import re
from typing import TYPE_CHECKING, Any

from aragora.channels.dock import ChannelDock, ChannelCapability, SendResult
from aragora.observability.http_client_pool import get_http_pool

if TYPE_CHECKING:
    from aragora.channels.normalized import NormalizedMessage

logger = logging.getLogger(__name__)

__all__ = ["SlackDock"]


class SlackDock(ChannelDock):
    """
    Slack platform dock.

    Supports rich text formatting, buttons, threads, file uploads,
    and reactions via the Slack API.
    """

    PLATFORM = "slack"
    CAPABILITIES = (
        ChannelCapability.RICH_TEXT
        | ChannelCapability.BUTTONS
        | ChannelCapability.THREADS
        | ChannelCapability.FILES
        | ChannelCapability.REACTIONS
    )

    def __init__(self, config: dict[str, Any] | None = None):
        """
        Initialize Slack dock.

        Config options:
            token: Slack bot token (or use SLACK_BOT_TOKEN env var)
        """
        super().__init__(config)
        self._token: str | None = None

    async def initialize(self) -> bool:
        """Initialize the Slack dock."""
        self._token = self.config.get("token") or os.environ.get("SLACK_BOT_TOKEN", "")
        if not self._token:
            logger.warning("Slack token not configured")
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
        Send a message to Slack.

        Args:
            channel_id: Slack channel ID
            message: The normalized message to send
            **kwargs: Additional options (thread_ts, etc.)

        Returns:
            SendResult indicating success or failure
        """
        if not self._token:
            return SendResult.fail(
                error="Slack token not configured",
                platform=self.PLATFORM,
                channel_id=channel_id,
            )

        try:
            # Build Slack message payload
            payload = self._build_payload(channel_id, message, **kwargs)

            pool = get_http_pool()
            async with pool.get_session("slack") as client:
                response = await client.post(
                    "https://slack.com/api/chat.postMessage",
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=30.0,
                )

                if response.status_code == 200:
                    data = response.json()
                    if data.get("ok"):
                        return SendResult.ok(
                            message_id=data.get("ts"),
                            platform=self.PLATFORM,
                            channel_id=channel_id,
                            thread_ts=data.get("ts"),
                        )
                    else:
                        return SendResult.fail(
                            error=data.get("error", "Unknown Slack error"),
                            platform=self.PLATFORM,
                            channel_id=channel_id,
                        )
                else:
                    return SendResult.fail(
                        error=f"HTTP {response.status_code}",
                        platform=self.PLATFORM,
                        channel_id=channel_id,
                    )

        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.error("Slack send error: %s", e)
            return SendResult.fail(
                error=str(e),
                platform=self.PLATFORM,
                channel_id=channel_id,
            )

    async def send_result(
        self,
        channel_id: str,
        result: dict[str, Any],
        thread_id: str | None = None,
        **kwargs: Any,
    ) -> SendResult:
        """Send a debate result to Slack with debate-specific formatting."""
        from aragora.channels.dock import MessageType
        from aragora.channels.normalized import MessageFormat, NormalizedMessage

        consensus = result.get("consensus_reached", False)
        confidence_raw = result.get("confidence", 0)
        confidence = float(confidence_raw) if isinstance(confidence_raw, (int, float)) else 0.0
        answer = str(result.get("final_answer", "No conclusion reached."))

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

        receipt_url = result.get("receipt_url") or kwargs.get("receipt_url")
        if isinstance(receipt_url, str) and receipt_url.startswith("http"):
            message.with_button("View Full Receipt", receipt_url, style="primary")

        return await self.send_message(channel_id, message, **kwargs)

    async def send_receipt(
        self,
        channel_id: str,
        summary: str,
        receipt_url: str | None = None,
        thread_id: str | None = None,
        **kwargs: Any,
    ) -> SendResult:
        """Send a decision receipt to Slack with a receipt button."""
        from aragora.channels.dock import MessageType
        from aragora.channels.normalized import MessageFormat, NormalizedMessage

        content = summary
        if receipt_url:
            content = re.sub(
                r"\n?• \[View Full Receipt\]\([^)]+\)",
                "",
                content,
            ).strip()

        message = NormalizedMessage(
            content=content,
            message_type=MessageType.RECEIPT,
            format=MessageFormat.MARKDOWN,
            title="Decision Receipt",
            thread_id=thread_id,
        )

        if isinstance(receipt_url, str) and receipt_url.startswith("http"):
            message.with_button("View Full Receipt", receipt_url, style="primary")

        return await self.send_message(channel_id, message, **kwargs)

    def _build_payload(
        self,
        channel_id: str,
        message: NormalizedMessage,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Build Slack API payload from normalized message."""
        from aragora.channels.normalized import MessageFormat

        payload: dict[str, Any] = {
            "channel": channel_id,
        }

        # Handle thread replies
        thread_ts = kwargs.get("thread_ts") or message.thread_id
        if thread_ts:
            payload["thread_ts"] = thread_ts

        # Build blocks for rich formatting
        blocks: list[dict[str, Any]] = []

        # Add title if present
        if message.title:
            blocks.append(
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": message.title[:150]},
                }
            )

        # Add main content
        if message.content:
            # Slack uses mrkdwn format
            text = message.content
            if message.format == MessageFormat.PLAIN:
                # Plain text doesn't need transformation
                pass
            elif message.format == MessageFormat.MARKDOWN:
                # Slack mrkdwn is slightly different from standard markdown
                # Bold: **text** -> *text*
                text = text.replace("**", "*")
                text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r"<\2|\1>", text)

            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": text[:3000]},
                }
            )

            # Also set plain text for notifications
            payload["text"] = message.to_plain_text()[:3000]

        # Add buttons if present
        if message.has_buttons():
            button_elements = []
            for button in message.buttons[:5]:  # Slack limits to 5 buttons
                if isinstance(button, dict):
                    label = button.get("label", "Click")
                    action = button.get("action", "")
                else:
                    label = getattr(button, "label", "Click")
                    action = getattr(button, "action", "")

                if action.startswith("http"):
                    button_elements.append(
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": label[:75]},
                            "url": action,
                        }
                    )
                else:
                    button_elements.append(
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": label[:75]},
                            "action_id": action,
                        }
                    )

            if button_elements:
                blocks.append(
                    {
                        "type": "actions",
                        "elements": button_elements,
                    }
                )

        if blocks:
            payload["blocks"] = blocks

        return payload
