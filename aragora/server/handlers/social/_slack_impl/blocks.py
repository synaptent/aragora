"""
Slack Block Kit formatting and message construction.

Builds rich Slack message blocks for debate results, progress updates,
agent responses, and starting messages.
"""

from __future__ import annotations

import logging
from typing import Any

from aragora.rbac.decorators import require_permission

from .config import SLACK_BOT_TOKEN
from .messaging import MessagingMixin

logger = logging.getLogger(__name__)


class BlocksMixin(MessagingMixin):
    """Mixin providing Slack Block Kit message building."""

    def _build_starting_blocks(
        self,
        topic: str,
        user_id: str,
        debate_id: str,
        agents: list[str] | None = None,
        expected_rounds: int | None = None,
    ) -> list[dict[str, Any]]:
        """Build Slack blocks for debate start message."""
        blocks: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "Debate Starting...",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Topic:* {topic}",
                },
            },
        ]

        # Add agents and rounds info if provided
        context_parts = [f"Requested by <@{user_id}> | ID: `{debate_id}`"]
        if agents:
            context_parts.append(f"Agents: {', '.join(agents)}")
        if expected_rounds:
            context_parts.append(f"Rounds: {expected_rounds}")

        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": " | ".join(context_parts),
                    },
                ],
            }
        )

        return blocks

    # Auth context flows from the parent event/command handler that invokes this method.
    @require_permission("slack:write")
    async def _post_round_update(
        self,
        response_url: str,
        topic: str,
        round_num: int,
        total_rounds: int,
        agent: str,
        channel_id: str | None = None,
        thread_ts: str | None = None,
        phase: str = "analyzing",
    ) -> None:
        """Post a round progress update to the thread with visual progress bar.

        Args:
            response_url: Slack response URL (webhook)
            topic: Debate topic
            round_num: Current round number
            total_rounds: Total rounds in debate
            agent: Name of agent that responded
            channel_id: Optional channel ID for Web API posting
            thread_ts: Optional thread timestamp for threaded replies
            phase: Current debate phase (analyzing, critique, voting, complete)
        """
        # Visual progress bar using block characters
        progress_bar = ":black_large_square:" * round_num + ":white_large_square:" * (
            total_rounds - round_num
        )

        # Phase emoji
        phase_emojis = {
            "analyzing": ":mag:",
            "critique": ":speech_balloon:",
            "voting": ":ballot_box:",
            "complete": ":white_check_mark:",
        }
        phase_emoji = phase_emojis.get(phase, ":hourglass_flowing_sand:")

        text = f"Round {round_num}/{total_rounds} complete"
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"{phase_emoji} *Round {round_num}/{total_rounds}*\n"
                        f"`{progress_bar}`\n"
                        f"_{agent} responded_"
                    ),
                },
            },
        ]

        # Use Web API with thread_ts when available for proper threading
        if SLACK_BOT_TOKEN and channel_id and thread_ts:
            await self._post_message_async(
                channel=channel_id,
                text=text,
                thread_ts=thread_ts,
                blocks=blocks,
            )
        else:
            # Fall back to response_url (not threaded)
            await self._post_to_response_url(
                response_url,
                {
                    "response_type": "in_channel",
                    "text": text,
                    "blocks": blocks,
                    "replace_original": False,
                },
            )

    # Auth context flows from the parent event/command handler that invokes this method.
    @require_permission("slack:write")
    async def _post_agent_response(
        self,
        response_url: str,
        agent: str,
        response: str,
        round_num: int,
        channel_id: str | None = None,
        thread_ts: str | None = None,
    ) -> None:
        """Post an individual agent response to the thread.

        Args:
            response_url: Slack response URL (webhook)
            agent: Name of agent that responded
            response: The agent's response content
            round_num: Current round number
            channel_id: Optional channel ID for Web API posting
            thread_ts: Optional thread timestamp for threaded replies
        """
        # Agent emoji mapping for visual distinction
        agent_emojis = {
            "anthropic-api": ":robot_face:",
            "openai-api": ":brain:",
            "gemini": ":gem:",
            "grok": ":zap:",
            "mistral": ":wind_face:",
            "deepseek": ":mag:",
        }
        emoji = agent_emojis.get(agent.lower(), ":speech_balloon:")

        # Truncate response for Slack (max 3000 chars in section)
        truncated = response[:2800] + "..." if len(response) > 2800 else response

        text = f"{agent} (Round {round_num})"
        blocks: list[dict[str, Any]] = [
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"{emoji} *{agent}* | Round {round_num}",
                    }
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": truncated,
                },
            },
            {"type": "divider"},
        ]

        # Use Web API with thread_ts when available for proper threading
        if SLACK_BOT_TOKEN and channel_id and thread_ts:
            await self._post_message_async(
                channel=channel_id,
                text=text,
                thread_ts=thread_ts,
                blocks=blocks,
            )
        else:
            # Fall back to response_url (not threaded)
            await self._post_to_response_url(
                response_url,
                {
                    "response_type": "in_channel",
                    "text": text,
                    "blocks": blocks,
                    "replace_original": False,
                },
            )

    def _build_result_blocks(
        self,
        topic: str,
        result: Any,
        user_id: str,
        receipt_url: str | None = None,
    ) -> list[dict[str, Any]]:
        """Build Slack blocks for debate result message with rich formatting."""
        # Status indicators
        status_emoji = ":white_check_mark:" if result.consensus_reached else ":warning:"
        status_text = "Consensus Reached" if result.consensus_reached else "No Consensus"

        # Confidence visualization (filled/empty circles)
        confidence_filled = int(result.confidence * 5)
        confidence_bar = ":large_blue_circle:" * confidence_filled + ":white_circle:" * (
            5 - confidence_filled
        )

        # Participant names (show up to 4)
        participant_names = result.participants[:4] if result.participants else []
        participants_text = ", ".join(participant_names)
        if len(result.participants) > 4:
            participants_text += f" +{len(result.participants) - 4}"

        blocks: list[dict[str, Any]] = [
            {"type": "divider"},
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{status_emoji} Debate Complete",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Status:*\n{status_text}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Confidence:*\n{confidence_bar} {result.confidence:.0%}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Rounds:*\n{result.rounds_used}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Participants:*\n{participants_text}",
                    },
                ],
            },
        ]

        # Add winner if present
        winner = getattr(result, "winner", None)
        if winner:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f":trophy: *Winner:* {winner}",
                    },
                }
            )

        # Add conclusion/answer
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Answer:*\n{result.final_answer[:500] if result.final_answer else 'No conclusion reached'}",
                },
            }
        )

        # Add action buttons
        action_elements: list[dict[str, Any]] = [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Agree", "emoji": True},
                "action_id": f"vote_{result.id}_agree",
                "value": result.id,
                "style": "primary",
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Disagree", "emoji": True},
                "action_id": f"vote_{result.id}_disagree",
                "value": result.id,
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Details", "emoji": True},
                "action_id": "view_details",
                "value": result.id,
            },
        ]

        # Add receipt link button if available
        if receipt_url:
            action_elements.append(
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View Receipt", "emoji": True},
                    "url": receipt_url,
                    "action_id": f"receipt_{result.id}",
                }
            )

        blocks.append({"type": "actions", "elements": action_elements})

        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Debate ID: `{result.id}` | Requested by <@{user_id}>",
                    },
                ],
            }
        )

        return blocks
