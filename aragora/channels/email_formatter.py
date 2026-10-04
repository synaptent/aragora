"""
Email HTML formatter for decision receipts.

Formats receipts as HTML emails for delivery via email channels.
"""

from __future__ import annotations

from typing import Any

from aragora.export.decision_receipt import agent_display_names

from .formatter import ReceiptFormatter, register_formatter


@register_formatter
class EmailReceiptFormatter(ReceiptFormatter):
    """Format decision receipts as HTML emails."""

    @property
    def channel_type(self) -> str:
        return "email"

    def format(
        self,
        receipt: Any,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Format receipt as HTML email.

        Options:
            compact: bool - Use compact format (default: False)
            include_css: bool - Include inline CSS (default: True)
            plain_text: bool - Also generate plain text version (default: True)
        """
        options = options or {}
        compact = options.get("compact", False)
        include_css = options.get("include_css", True)
        plain_text_opt = options.get("plain_text", True)

        confidence_raw = getattr(receipt, "confidence_score", None)
        if confidence_raw is None:
            confidence_raw = getattr(receipt, "confidence", None)
        confidence: float = float(confidence_raw) if confidence_raw is not None else 0.0
        confidence_color = self._get_confidence_color(confidence)

        # Build HTML content
        html_parts: list[str] = []

        # CSS styles
        if include_css:
            html_parts.append(self._get_css_styles())

        # Header
        html_parts.append(f"""
<div class="receipt-container">
    <div class="header">
        <h1>Decision Receipt</h1>
        <span class="receipt-id">ID: {receipt.receipt_id}</span>
    </div>
""")

        # Topic
        topic = (
            getattr(receipt, "topic", None)
            or getattr(receipt, "question", None)
            or getattr(receipt, "input_summary", None)
            or "N/A"
        )
        html_parts.append(f"""
    <div class="topic">
        <h2>{self._escape_html(topic)}</h2>
    </div>
""")

        # Confidence indicator
        html_parts.append(f"""
    <div class="confidence" style="border-left-color: {confidence_color};">
        <div class="confidence-value" style="color: {confidence_color};">
            {confidence:.0%}
        </div>
        <div class="confidence-label">
            Confidence Level: {self._get_confidence_label(confidence)}
        </div>
    </div>
""")

        # Decision
        decision = (
            getattr(receipt, "decision", None)
            or getattr(receipt, "verdict", None)
            or getattr(receipt, "final_answer", None)
            or "No decision reached"
        )
        html_parts.append(f"""
    <div class="section">
        <h3>Decision</h3>
        <p class="decision-text">{self._escape_html(decision)}</p>
    </div>
""")

        if not compact:
            # Key Arguments
            key_arguments = getattr(receipt, "key_arguments", None)
            mitigations = getattr(receipt, "mitigations", None)
            key_points = key_arguments or mitigations
            if key_points:
                label = "Key Arguments" if key_arguments else "Mitigations"
                html_parts.append(f"""
    <div class="section">
        <h3>{label}</h3>
        <ul>
""")
                for arg in key_points[:5]:
                    html_parts.append(f"            <li>{self._escape_html(arg)}</li>\n")
                html_parts.append("""        </ul>
    </div>
""")

            # Risks
            risks = getattr(receipt, "risks", None)
            if not risks:
                findings = getattr(receipt, "findings", None) or []
                risks = [
                    f"{getattr(f, 'severity', '')}: {getattr(f, 'title', '')}".strip(": ")
                    for f in findings[:5]
                    if getattr(f, "title", None) or getattr(f, "severity", None)
                ]
            if risks:
                html_parts.append("""
    <div class="section risks">
        <h3>Risks Identified</h3>
        <ul>
""")
                for risk in risks[:5]:
                    html_parts.append(f"            <li>{self._escape_html(risk)}</li>\n")
                html_parts.append("""        </ul>
    </div>
""")

            # Dissenting Views
            dissenting_views = getattr(receipt, "dissenting_views", None) or []
            if dissenting_views:
                html_parts.append("""
    <div class="section dissent">
        <h3>Dissenting Views</h3>
        <ul>
""")
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
                for view in formatted_views:
                    html_parts.append(f"            <li>{self._escape_html(view)}</li>\n")
                html_parts.append("""        </ul>
    </div>
""")

        # Metadata
        agents = agent_display_names(
            getattr(receipt, "agents", None) or getattr(receipt, "agents_involved", [])
        )
        agents_str = ", ".join(agents[:5]) if agents else "N/A"
        if agents and len(agents) > 5:
            agents_str += f" (+{len(agents) - 5} more)"

        html_parts.append(f"""
    <div class="metadata">
        <table>
            <tr>
                <td><strong>Agents</strong></td>
                <td>{self._escape_html(agents_str)}</td>
            </tr>
            <tr>
                <td><strong>Rounds</strong></td>
                <td>{getattr(receipt, "rounds", None) or getattr(receipt, "rounds_completed", "N/A")}</td>
            </tr>
""")
        if receipt.timestamp:
            html_parts.append(f"""            <tr>
                <td><strong>Timestamp</strong></td>
                <td>{receipt.timestamp}</td>
            </tr>
""")
        html_parts.append("""        </table>
    </div>
""")

        # Footer
        html_parts.append("""
    <div class="footer">
        <p>Generated by <strong>Aragora</strong> - Multi-Agent Vetted Decisionmaking Platform</p>
    </div>
</div>
""")

        html_content = "".join(html_parts)

        result: dict[str, Any] = {
            "html": html_content,
            "subject": f"Decision Receipt: {topic[:50]}{'...' if len(topic) > 50 else ''}",
        }

        # Generate plain text version
        if plain_text_opt:
            result["plain_text"] = self._generate_plain_text(receipt, compact)

        return result

    def _get_css_styles(self) -> str:
        """Get inline CSS styles for the email."""
        return """<style>
    .receipt-container {
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
        max-width: 600px;
        margin: 0 auto;
        padding: 20px;
        background: #ffffff;
        border: 1px solid #e0e0e0;
        border-radius: 8px;
    }
    .header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 2px solid #6366f1;
        padding-bottom: 15px;
        margin-bottom: 20px;
    }
    .header h1 {
        margin: 0;
        color: #1f2937;
        font-size: 24px;
    }
    .receipt-id {
        color: #6b7280;
        font-size: 12px;
        font-family: monospace;
    }
    .topic h2 {
        color: #374151;
        font-size: 18px;
        margin: 0 0 20px 0;
    }
    .confidence {
        background: #f9fafb;
        padding: 15px;
        border-radius: 6px;
        border-left: 4px solid;
        margin-bottom: 20px;
    }
    .confidence-value {
        font-size: 32px;
        font-weight: bold;
    }
    .confidence-label {
        color: #6b7280;
        font-size: 14px;
    }
    .section {
        margin-bottom: 20px;
    }
    .section h3 {
        color: #374151;
        font-size: 16px;
        margin: 0 0 10px 0;
        border-bottom: 1px solid #e5e7eb;
        padding-bottom: 5px;
    }
    .section ul {
        margin: 0;
        padding-left: 20px;
    }
    .section li {
        margin-bottom: 5px;
        color: #4b5563;
    }
    .decision-text {
        color: #1f2937;
        line-height: 1.6;
    }
    .risks h3 {
        color: #d97706;
    }
    .risks li {
        color: #92400e;
    }
    .dissent h3 {
        color: #6b7280;
    }
    .metadata {
        background: #f3f4f6;
        padding: 15px;
        border-radius: 6px;
        margin-bottom: 20px;
    }
    .metadata table {
        width: 100%;
        border-collapse: collapse;
    }
    .metadata td {
        padding: 5px 10px;
        font-size: 14px;
    }
    .metadata td:first-child {
        width: 100px;
        color: #6b7280;
    }
    .footer {
        text-align: center;
        color: #9ca3af;
        font-size: 12px;
        padding-top: 15px;
        border-top: 1px solid #e5e7eb;
    }
</style>
"""

    def _get_confidence_color(self, confidence: float) -> str:
        """Get color based on confidence level."""
        if confidence >= 0.8:
            return "#22c55e"  # Green
        if confidence >= 0.5:
            return "#eab308"  # Yellow
        return "#ef4444"  # Red

    def _get_confidence_label(self, confidence: float) -> str:
        """Get human-readable confidence label."""
        if confidence >= 0.9:
            return "Very High"
        if confidence >= 0.7:
            return "High"
        if confidence >= 0.5:
            return "Moderate"
        return "Low"

    def _escape_html(self, text: str) -> str:
        """Escape HTML special characters."""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#x27;")
        )

    def _generate_plain_text(self, receipt: Any, compact: bool) -> str:
        """Generate plain text version of the receipt."""
        lines: list[str] = []

        lines.append("=" * 50)
        lines.append("DECISION RECEIPT")
        lines.append("=" * 50)
        lines.append("")

        topic = receipt.topic or receipt.question or "N/A"
        lines.append(f"Topic: {topic}")
        lines.append("")

        confidence = receipt.confidence_score or 0
        lines.append(f"Confidence: {confidence:.0%} ({self._get_confidence_label(confidence)})")
        lines.append("")

        lines.append("-" * 50)
        lines.append("DECISION")
        lines.append("-" * 50)
        lines.append(receipt.decision or "No decision reached")
        lines.append("")

        if not compact:
            if receipt.key_arguments:
                lines.append("-" * 50)
                lines.append("KEY ARGUMENTS")
                lines.append("-" * 50)
                for arg in receipt.key_arguments[:5]:
                    lines.append(f"  - {arg}")
                lines.append("")

            if receipt.risks:
                lines.append("-" * 50)
                lines.append("RISKS IDENTIFIED")
                lines.append("-" * 50)
                for risk in receipt.risks[:5]:
                    lines.append(f"  ! {risk}")
                lines.append("")

            if receipt.dissenting_views:
                lines.append("-" * 50)
                lines.append("DISSENTING VIEWS")
                lines.append("-" * 50)
                for view in receipt.dissenting_views[:3]:
                    lines.append(f"  * {view}")
                lines.append("")

        lines.append("-" * 50)
        lines.append("METADATA")
        lines.append("-" * 50)

        agents = agent_display_names(receipt.agents)
        if agents:
            agents_str = ", ".join(agents[:5])
            if len(agents) > 5:
                agents_str += f" (+{len(agents) - 5} more)"
            lines.append(f"Agents: {agents_str}")

        lines.append(f"Rounds: {receipt.rounds or 'N/A'}")
        lines.append(f"Receipt ID: {receipt.receipt_id}")

        if receipt.timestamp:
            lines.append(f"Timestamp: {receipt.timestamp}")

        lines.append("")
        lines.append("=" * 50)
        lines.append("Generated by Aragora - Multi-Agent Vetted Decisionmaking Platform")
        lines.append("=" * 50)

        return "\n".join(lines)
