"""
Slack Block Kit formatter for decision receipts.

Formats receipts using Slack's Block Kit for rich message display.
"""

from __future__ import annotations

from typing import Any

from aragora.export.decision_receipt import agent_display_names

from .formatter import ReceiptFormatter, register_formatter


@register_formatter
class SlackReceiptFormatter(ReceiptFormatter):
    """Format decision receipts for Slack using Block Kit."""

    @property
    def channel_type(self) -> str:
        return "slack"

    def format(
        self,
        receipt: Any,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Format receipt as Slack Block Kit blocks.

        Options:
            compact: bool - Use compact format (default: False)
            include_agents: bool - Include agent details (default: True)
            include_evidence: bool - Include evidence section (default: True)
        """
        options = options or {}
        compact = options.get("compact", False)
        include_agents = options.get("include_agents", True)
        include_evidence = options.get("include_evidence", True)

        blocks: list[dict[str, Any]] = []

        # Header
        confidence_raw = getattr(receipt, "confidence_score", None)
        if confidence_raw is None:
            confidence_raw = getattr(receipt, "confidence", None)
        confidence: float = float(confidence_raw) if confidence_raw is not None else 0.0
        confidence_emoji = self._get_confidence_emoji(confidence)

        blocks.append(
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{confidence_emoji} Decision Receipt",
                    "emoji": True,
                },
            }
        )

        # Topic/Question
        topic = (
            getattr(receipt, "topic", None)
            or getattr(receipt, "question", None)
            or getattr(receipt, "input_summary", None)
            or "N/A"
        )
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Topic:* {topic}",
                },
            }
        )

        blocks.append({"type": "divider"})

        # Decision with confidence
        decision_text = (
            getattr(receipt, "decision", None)
            or getattr(receipt, "verdict", None)
            or getattr(receipt, "final_answer", None)
            or "No decision reached"
        )
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Decision:*\n{decision_text}",
                },
                "accessory": {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": f"{confidence:.0%} Confidence",
                        "emoji": True,
                    },
                    "style": "primary" if confidence >= 0.8 else None,
                    "action_id": "view_receipt",
                },
            }
        )

        if not compact:
            # Key Arguments
            key_arguments = getattr(receipt, "key_arguments", None) or getattr(
                receipt, "mitigations", None
            )
            if key_arguments:
                label = (
                    "Key Arguments" if getattr(receipt, "key_arguments", None) else "Mitigations"
                )
                args_text = "\n".join(f"- {arg}" for arg in key_arguments[:5])
                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*{label}:*\n{args_text}",
                        },
                    }
                )

            # Risks
            risks = getattr(receipt, "risks", None)
            if not risks:
                findings = getattr(receipt, "findings", None) or []
                risks = [
                    f"{getattr(f, 'severity', '')}: {getattr(f, 'title', '')}".strip(": ")
                    for f in findings[:3]
                    if getattr(f, "title", None) or getattr(f, "severity", None)
                ]
            if risks:
                risks_text = "\n".join(f"- :warning: {risk}" for risk in risks[:3])
                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Risks Identified:*\n{risks_text}",
                        },
                    }
                )

            # Dissenting Views
            dissenting_views = getattr(receipt, "dissenting_views", None) or []
            if dissenting_views:
                formatted_views = []
                for view in dissenting_views[:3]:
                    if isinstance(view, str):
                        formatted_views.append(view)
                    elif isinstance(view, dict):
                        agent = view.get("agent", "Agent")
                        reasons = view.get("reasons", [])
                        reason_text = ", ".join(reasons[:2]) if reasons else "Dissent noted"
                        formatted_views.append(f"{agent}: {reason_text}")
                    else:
                        agent = getattr(view, "agent", "Agent")
                        reasons = getattr(view, "reasons", [])
                        reason_text = ", ".join(reasons[:2]) if reasons else "Dissent noted"
                        formatted_views.append(f"{agent}: {reason_text}")
                dissent_text = "\n".join(f"- {view}" for view in formatted_views)
                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Dissenting Views:*\n{dissent_text}",
                        },
                    }
                )

        # Agents section
        agents = agent_display_names(
            getattr(receipt, "agents", None) or getattr(receipt, "agents_involved", [])
        )
        if include_agents and agents:
            agent_names = ", ".join(agents[:5])
            if len(agents) > 5:
                agent_names += f" +{len(agents) - 5} more"
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f":robot_face: *Agents:* {agent_names}",
                        },
                    ],
                }
            )

        # Evidence section
        evidence = getattr(receipt, "evidence", None)
        if include_evidence and evidence:
            evidence_count = len(evidence)
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f":bookmark: {evidence_count} evidence sources cited",
                        },
                    ],
                }
            )
        elif include_evidence and getattr(receipt, "findings", None):
            findings_count = len(getattr(receipt, "findings", []))
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f":bookmark: {findings_count} findings reported",
                        },
                    ],
                }
            )

        blocks.append({"type": "divider"})

        # Footer with metadata
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Receipt ID: `{receipt.receipt_id}` | "
                        f"Rounds: {getattr(receipt, 'rounds', None) or getattr(receipt, 'rounds_completed', 'N/A')} | "
                        f"Generated by Aragora",
                    },
                ],
            }
        )

        return {"blocks": blocks}

    def _get_confidence_emoji(self, confidence: float) -> str:
        """Get emoji based on confidence level."""
        if confidence >= 0.9:
            return ":white_check_mark:"
        if confidence >= 0.7:
            return ":large_green_circle:"
        if confidence >= 0.5:
            return ":large_yellow_circle:"
        return ":red_circle:"
