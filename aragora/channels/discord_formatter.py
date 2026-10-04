"""
Discord embed formatter for decision receipts.

Formats receipts using Discord's embed format for rich message display.
"""

from __future__ import annotations

from typing import Any

from aragora.export.decision_receipt import agent_display_names

from .formatter import ReceiptFormatter, register_formatter


@register_formatter
class DiscordReceiptFormatter(ReceiptFormatter):
    """Format decision receipts for Discord using embeds."""

    @property
    def channel_type(self) -> str:
        return "discord"

    def format(
        self,
        receipt: Any,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Format receipt as Discord embed.

        Options:
            compact: bool - Use compact format (default: False)
        """
        options = options or {}
        compact = options.get("compact", False)

        confidence_raw = getattr(receipt, "confidence_score", None)
        if confidence_raw is None:
            confidence_raw = getattr(receipt, "confidence", None)
        confidence: float = float(confidence_raw) if confidence_raw is not None else 0.0
        color = self._get_embed_color(confidence)

        fields: list[dict[str, Any]] = []

        # Decision field
        decision_text = (
            getattr(receipt, "decision", None)
            or getattr(receipt, "verdict", None)
            or getattr(receipt, "final_answer", None)
            or "No decision reached"
        )
        fields.append(
            {
                "name": "Decision",
                "value": decision_text[:1024],
                "inline": False,
            }
        )

        # Confidence field
        confidence_bar = self._make_confidence_bar(confidence)
        fields.append(
            {
                "name": "Confidence",
                "value": f"{confidence_bar} {confidence:.0%}",
                "inline": True,
            }
        )

        # Rounds field
        fields.append(
            {
                "name": "Rounds",
                "value": str(
                    getattr(receipt, "rounds", None) or getattr(receipt, "rounds_completed", "N/A")
                ),
                "inline": True,
            }
        )

        # Agents field
        agents = agent_display_names(
            getattr(receipt, "agents", None) or getattr(receipt, "agents_involved", [])
        )
        if agents:
            agent_list = ", ".join(agents[:5])
            if len(agents) > 5:
                agent_list += f" (+{len(agents) - 5})"
            fields.append(
                {
                    "name": "Agents",
                    "value": agent_list,
                    "inline": True,
                }
            )

        if not compact:
            # Key Arguments
            key_arguments = getattr(receipt, "key_arguments", None)
            mitigations = getattr(receipt, "mitigations", None)
            key_points = key_arguments or mitigations
            if key_points:
                label = "Key Arguments" if key_arguments else "Mitigations"
                args_text = "\n".join(f"- {arg[:100]}" for arg in key_points[:3])
                fields.append(
                    {
                        "name": label,
                        "value": args_text[:1024],
                        "inline": False,
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
                risks_text = "\n".join(f"- {risk[:100]}" for risk in risks[:3])
                fields.append(
                    {
                        "name": "Risks",
                        "value": risks_text[:1024],
                        "inline": False,
                    }
                )

            # Dissenting Views
            dissenting_views = getattr(receipt, "dissenting_views", None) or []
            if dissenting_views:
                formatted_views = []
                for view in dissenting_views[:2]:
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
                dissent_text = "\n".join(f"- {view[:100]}" for view in formatted_views)
                fields.append(
                    {
                        "name": "Dissenting Views",
                        "value": dissent_text[:1024],
                        "inline": False,
                    }
                )

        description = (
            getattr(receipt, "topic", None)
            or getattr(receipt, "question", None)
            or getattr(receipt, "input_summary", None)
            or ""
        )
        embed = {
            "title": "Decision Receipt",
            "description": description[:4096],
            "color": color,
            "fields": fields,
            "footer": {
                "text": f"Receipt ID: {receipt.receipt_id} | Powered by Aragora",
            },
        }

        if receipt.timestamp:
            embed["timestamp"] = receipt.timestamp

        return {"embeds": [embed]}

    def _get_embed_color(self, confidence: float) -> int:
        """Get Discord embed color based on confidence."""
        if confidence >= 0.8:
            return 0x57F287  # Green
        if confidence >= 0.5:
            return 0xFEE75C  # Yellow
        return 0xED4245  # Red

    def _make_confidence_bar(self, confidence: float, length: int = 10) -> str:
        """Create a visual confidence bar using Discord formatting."""
        filled = int(confidence * length)
        empty = length - filled
        return "█" * filled + "░" * empty
