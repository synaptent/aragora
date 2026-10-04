"""
Microsoft Teams Adaptive Cards formatter for decision receipts.

Formats receipts using Teams' Adaptive Cards for rich message display.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from aragora.export.decision_receipt import agent_display_names
from aragora.utils.public_urls import public_receipt_url

from .formatter import ReceiptFormatter, register_formatter

if TYPE_CHECKING:
    from aragora.receipts import DecisionReceipt


@register_formatter
class TeamsReceiptFormatter(ReceiptFormatter):
    """Format decision receipts for Microsoft Teams using Adaptive Cards."""

    @property
    def channel_type(self) -> str:
        return "teams"

    def format(
        self,
        receipt: DecisionReceipt,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Format receipt as Teams Adaptive Card.

        Options:
            compact: bool - Use compact format (default: False)
            include_agents: bool - Include agent details (default: True)
        """
        # Cast receipt to Any to allow flexible attribute access since DecisionReceipt
        # may have different attributes depending on context/version
        r: Any = receipt
        options = options or {}
        compact = options.get("compact", False)

        confidence_raw = getattr(r, "confidence_score", None) or getattr(r, "confidence", None)
        confidence: float = float(confidence_raw) if confidence_raw is not None else 0.0
        confidence_color = self._get_confidence_color(confidence)

        body: list[dict[str, Any]] = []

        # Header with topic
        body.append(
            {
                "type": "TextBlock",
                "size": "Large",
                "weight": "Bolder",
                "text": "Decision Receipt",
                "color": "Accent",
            }
        )

        body.append(
            {
                "type": "TextBlock",
                "text": getattr(r, "topic", None)
                or getattr(r, "question", None)
                or getattr(r, "input_summary", "N/A"),
                "wrap": True,
                "weight": "Bolder",
            }
        )

        # Confidence indicator
        body.append(
            {
                "type": "ColumnSet",
                "columns": [
                    {
                        "type": "Column",
                        "width": "auto",
                        "items": [
                            {
                                "type": "TextBlock",
                                "text": f"{confidence:.0%}",
                                "size": "ExtraLarge",
                                "weight": "Bolder",
                                "color": confidence_color,
                            },
                        ],
                    },
                    {
                        "type": "Column",
                        "width": "stretch",
                        "items": [
                            {
                                "type": "TextBlock",
                                "text": "Confidence",
                                "size": "Small",
                                "color": "Dark",
                            },
                            {
                                "type": "TextBlock",
                                "text": self._get_confidence_label(confidence),
                                "weight": "Bolder",
                            },
                        ],
                    },
                ],
            }
        )

        # Decision
        body.append(
            {
                "type": "TextBlock",
                "text": "Decision",
                "weight": "Bolder",
                "spacing": "Medium",
            }
        )
        body.append(
            {
                "type": "TextBlock",
                "text": getattr(r, "decision", None)
                or getattr(r, "verdict", "No decision reached"),
                "wrap": True,
            }
        )

        key_arguments = getattr(r, "key_arguments", None)
        mitigations = getattr(r, "mitigations", None)
        key_points = key_arguments or mitigations or []
        risks = getattr(r, "risks", None)
        if not risks:
            findings = getattr(r, "findings", None) or []
            risks = [
                f"{getattr(f, 'severity', '')}: {getattr(f, 'title', '')}".strip(": ")
                for f in findings[:3]
                if getattr(f, "title", None) or getattr(f, "severity", None)
            ]
        risks = risks or []

        if not compact:
            # Key Arguments
            if key_points:
                body.append(
                    {
                        "type": "TextBlock",
                        "text": "Key Arguments" if key_arguments else "Mitigations",
                        "weight": "Bolder",
                        "spacing": "Medium",
                    }
                )
                for arg in key_points[:5]:
                    body.append(
                        {
                            "type": "TextBlock",
                            "text": f"- {arg}",
                            "wrap": True,
                            "spacing": "None",
                        }
                    )

            # Risks
            if risks:
                body.append(
                    {
                        "type": "TextBlock",
                        "text": "Risks Identified",
                        "weight": "Bolder",
                        "spacing": "Medium",
                        "color": "Warning",
                    }
                )
                for risk in risks[:3]:
                    body.append(
                        {
                            "type": "TextBlock",
                            "text": f"- {risk}",
                            "wrap": True,
                            "spacing": "None",
                            "color": "Warning",
                        }
                    )

        # Agents
        agents = agent_display_names(
            getattr(r, "agents", None) or getattr(r, "agents_involved", [])
        )
        if agents:
            body.append(
                {
                    "type": "FactSet",
                    "facts": [
                        {
                            "title": "Agents",
                            "value": ", ".join(agents[:5]),
                        },
                        {
                            "title": "Rounds",
                            "value": str(
                                getattr(r, "rounds", None) or getattr(r, "rounds_completed", "N/A")
                            ),
                        },
                    ],
                    "spacing": "Medium",
                }
            )

        # Footer
        receipt_id = getattr(r, "receipt_id", "unknown")
        body.append(
            {
                "type": "TextBlock",
                "text": f"Receipt ID: {receipt_id}",
                "size": "Small",
                "color": "Dark",
                "spacing": "Medium",
            }
        )

        return {
            "type": "AdaptiveCard",
            "$schema": "https://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.4",
            "body": body,
            "actions": [
                {
                    "type": "Action.OpenUrl",
                    "title": "View Full Receipt",
                    "url": public_receipt_url(receipt_id),
                },
            ],
        }

    def _get_confidence_color(self, confidence: float) -> str:
        """Get Adaptive Card color based on confidence."""
        if confidence >= 0.8:
            return "Good"
        if confidence >= 0.5:
            return "Warning"
        return "Attention"

    def _get_confidence_label(self, confidence: float) -> str:
        """Get human-readable confidence label."""
        if confidence >= 0.9:
            return "Very High"
        if confidence >= 0.7:
            return "High"
        if confidence >= 0.5:
            return "Moderate"
        return "Low"
