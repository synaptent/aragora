"""
Slack Block Kit formatter for debate results.

Formats debate results using Slack's Block Kit for rich message display.
"""

from __future__ import annotations

from typing import Any

from .debate_formatter import DebateResultFormatter, register_debate_formatter


def _consensus_emoji(consensus: bool, confidence: float) -> str:
    """Return a Slack emoji reflecting consensus status and confidence."""
    if not consensus:
        return ":x:"
    if confidence >= 0.8:
        return ":white_check_mark:"
    return ":warning:"


@register_debate_formatter("slack")
class SlackDebateFormatter(DebateResultFormatter):
    """Format debate results for Slack using Block Kit."""

    def format(
        self,
        result: dict[str, Any],
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return Slack Block Kit payload.

        Blocks produced:
        1. Header with consensus emoji
        2. Section fields: consensus status, confidence %, rounds
        3. Divider
        4. Final answer preview (500-char max)
        5. Context block with agent count and duration
        """
        options = options or {}
        max_answer = options.get("max_answer_length", 500)

        consensus: bool = result.get("consensus_reached", False)
        confidence_raw = result.get("confidence", 0)
        confidence: float = (
            float(confidence_raw) if isinstance(confidence_raw, (int, float)) else 0.0
        )
        rounds = result.get("rounds", result.get("rounds_completed", "N/A"))
        answer = result.get("final_answer", "No conclusion reached.")
        participants = result.get("participants", [])
        duration = result.get("duration_seconds")

        emoji = _consensus_emoji(consensus, confidence)

        blocks: list[dict[str, Any]] = []

        # 1. Header
        blocks.append(
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{emoji} Debate Complete",
                    "emoji": True,
                },
            }
        )

        # 2. Section fields
        consensus_label = "Yes" if consensus else "No"
        blocks.append(
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Consensus:*\n{consensus_label}"},
                    {"type": "mrkdwn", "text": f"*Confidence:*\n{confidence:.0%}"},
                    {"type": "mrkdwn", "text": f"*Rounds:*\n{rounds}"},
                ],
            }
        )

        # 3. Divider
        blocks.append({"type": "divider"})

        # 4. Final answer preview
        preview = str(answer)
        if len(preview) > max_answer:
            preview = preview[: max_answer - 3] + "..."
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Conclusion:*\n{preview}",
                },
            }
        )

        # 5. Context (agents + duration)
        context_parts: list[str] = []
        if participants:
            context_parts.append(f":busts_in_silhouette: {len(participants)} agents")
        if isinstance(duration, (int, float)) and duration > 0:
            context_parts.append(f":stopwatch: {duration:.1f}s")

        if context_parts:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": " | ".join(context_parts)},
                    ],
                }
            )

        return {"blocks": blocks}

    def format_summary(
        self,
        result: dict[str, Any],
        max_length: int = 500,
    ) -> str:
        """Return a compact Slack mrkdwn summary."""
        consensus = result.get("consensus_reached", False)
        confidence_raw = result.get("confidence", 0)
        confidence = float(confidence_raw) if isinstance(confidence_raw, (int, float)) else 0.0
        answer = result.get("final_answer", "No conclusion reached.")

        emoji = _consensus_emoji(consensus, confidence)
        status = "Consensus" if consensus else "No consensus"
        summary = f"{emoji} *{status}* ({confidence:.0%}) - {answer}"
        if len(summary) > max_length:
            summary = summary[: max_length - 3] + "..."
        return summary
