"""
Tests for channel-specific receipt formatters.

Tests Discord, Email, Slack, and Teams receipt formatters that convert
decision receipts into platform-specific payloads.
"""

import pytest
from unittest.mock import MagicMock
from typing import Any


# =============================================================================
# Shared receipt mock factory
# =============================================================================


def _make_receipt(**kwargs):
    """Create a mock receipt with standard fields."""
    receipt = MagicMock()
    receipt.receipt_id = kwargs.get("receipt_id", "r-001")
    receipt.verdict = kwargs.get("verdict", "Approve the proposal")
    receipt.confidence = kwargs.get("confidence", 0.85)
    receipt.confidence_score = kwargs.get("confidence_score", 0.85)
    receipt.topic = kwargs.get("topic", "Should we adopt microservices?")
    receipt.question = kwargs.get("question")
    receipt.decision = kwargs.get("decision", "Approve the proposal")
    receipt.final_answer = kwargs.get("final_answer")
    receipt.input_summary = kwargs.get("input_summary")
    receipt.rounds = kwargs.get("rounds", 3)
    receipt.rounds_completed = kwargs.get("rounds_completed")
    receipt.agents = kwargs.get("agents", ["claude", "gpt-4", "gemini"])
    receipt.agents_involved = kwargs.get("agents_involved")
    receipt.key_arguments = kwargs.get(
        "key_arguments", ["Scalability", "Flexibility", "Team autonomy"]
    )
    receipt.mitigations = kwargs.get("mitigations")
    receipt.risks = kwargs.get("risks", ["Complexity increase", "Network latency"])
    receipt.findings = kwargs.get("findings")
    receipt.dissenting_views = kwargs.get("dissenting_views")
    receipt.evidence = kwargs.get("evidence")
    receipt.timestamp = kwargs.get("timestamp", "2025-01-15T12:00:00Z")
    return receipt


def _make_minimal_receipt():
    """Create a receipt with minimal fields (many None)."""
    receipt = MagicMock()
    receipt.receipt_id = "r-min"
    receipt.verdict = None
    receipt.confidence = None
    receipt.confidence_score = None
    receipt.topic = None
    receipt.question = None
    receipt.decision = None
    receipt.final_answer = None
    receipt.input_summary = None
    receipt.rounds = None
    receipt.rounds_completed = None
    receipt.agents = None
    receipt.agents_involved = []
    receipt.key_arguments = None
    receipt.mitigations = None
    receipt.risks = None
    receipt.findings = None
    receipt.dissenting_views = None
    receipt.evidence = None
    receipt.timestamp = None
    return receipt


# =============================================================================
# Discord Receipt Formatter Tests
# =============================================================================


class TestDiscordReceiptFormatter:
    """Tests for DiscordReceiptFormatter."""

    def _get_formatter(self):
        from aragora.channels.discord_formatter import DiscordReceiptFormatter

        return DiscordReceiptFormatter()

    def test_channel_type(self):
        """Test formatter channel type."""
        fmt = self._get_formatter()
        assert fmt.channel_type == "discord"

    def test_format_basic_receipt(self):
        """Test formatting a standard receipt."""
        fmt = self._get_formatter()
        receipt = _make_receipt()
        result = fmt.format(receipt)
        assert "embeds" in result
        assert len(result["embeds"]) == 1
        embed = result["embeds"][0]
        assert embed["title"] == "Decision Receipt"
        assert "fields" in embed

    def test_format_includes_decision_field(self):
        """Test that the decision field is included."""
        fmt = self._get_formatter()
        receipt = _make_receipt(decision="Go ahead")
        result = fmt.format(receipt)
        fields = result["embeds"][0]["fields"]
        decision_field = next(f for f in fields if f["name"] == "Decision")
        assert "Go ahead" in decision_field["value"]

    def test_format_includes_confidence_field(self):
        """Test that the confidence field is included."""
        fmt = self._get_formatter()
        receipt = _make_receipt()
        result = fmt.format(receipt)
        fields = result["embeds"][0]["fields"]
        confidence_field = next(f for f in fields if f["name"] == "Confidence")
        assert "85%" in confidence_field["value"]

    def test_format_includes_rounds_field(self):
        """Test that rounds field is included."""
        fmt = self._get_formatter()
        receipt = _make_receipt(rounds=5)
        result = fmt.format(receipt)
        fields = result["embeds"][0]["fields"]
        rounds_field = next(f for f in fields if f["name"] == "Rounds")
        assert "5" in rounds_field["value"]

    def test_format_includes_agents(self):
        """Test that agents field is included."""
        fmt = self._get_formatter()
        receipt = _make_receipt(agents=["claude", "gpt-4"])
        result = fmt.format(receipt)
        fields = result["embeds"][0]["fields"]
        agents_field = next(f for f in fields if f["name"] == "Agents")
        assert "claude" in agents_field["value"]
        assert "gpt-4" in agents_field["value"]

    def test_format_agents_overflow(self):
        """Test agents field truncation with many agents."""
        fmt = self._get_formatter()
        agents = [f"agent-{i}" for i in range(8)]
        receipt = _make_receipt(agents=agents)
        result = fmt.format(receipt)
        fields = result["embeds"][0]["fields"]
        agents_field = next(f for f in fields if f["name"] == "Agents")
        assert "(+3)" in agents_field["value"]

    def test_format_compact_skips_details(self):
        """Test compact mode omits key arguments and risks."""
        fmt = self._get_formatter()
        receipt = _make_receipt()
        result = fmt.format(receipt, options={"compact": True})
        fields = result["embeds"][0]["fields"]
        field_names = [f["name"] for f in fields]
        assert "Key Arguments" not in field_names
        assert "Risks" not in field_names

    def test_format_full_includes_key_arguments(self):
        """Test non-compact mode includes key arguments."""
        fmt = self._get_formatter()
        receipt = _make_receipt(key_arguments=["Point A", "Point B"])
        result = fmt.format(receipt)
        fields = result["embeds"][0]["fields"]
        field_names = [f["name"] for f in fields]
        assert "Key Arguments" in field_names

    def test_format_full_includes_risks(self):
        """Test non-compact mode includes risks."""
        fmt = self._get_formatter()
        receipt = _make_receipt(risks=["Risk 1", "Risk 2"])
        result = fmt.format(receipt)
        fields = result["embeds"][0]["fields"]
        field_names = [f["name"] for f in fields]
        assert "Risks" in field_names

    def test_format_dissenting_views_string(self):
        """Test dissenting views with string entries."""
        fmt = self._get_formatter()
        receipt = _make_receipt(dissenting_views=["I disagree because..."])
        result = fmt.format(receipt)
        fields = result["embeds"][0]["fields"]
        field_names = [f["name"] for f in fields]
        assert "Dissenting Views" in field_names

    def test_format_dissenting_views_dict(self):
        """Test dissenting views with dict entries."""
        fmt = self._get_formatter()
        receipt = _make_receipt(
            dissenting_views=[{"agent": "gpt-4", "reasons": ["Too risky", "Too expensive"]}]
        )
        result = fmt.format(receipt)
        fields = result["embeds"][0]["fields"]
        dissent = next(f for f in fields if f["name"] == "Dissenting Views")
        assert "gpt-4" in dissent["value"]

    def test_format_embed_color_high_confidence(self):
        """Test green color for high confidence."""
        fmt = self._get_formatter()
        receipt = _make_receipt(confidence_score=0.9)
        result = fmt.format(receipt)
        assert result["embeds"][0]["color"] == 0x57F287

    def test_format_embed_color_medium_confidence(self):
        """Test yellow color for medium confidence."""
        fmt = self._get_formatter()
        receipt = _make_receipt(confidence_score=0.6)
        result = fmt.format(receipt)
        assert result["embeds"][0]["color"] == 0xFEE75C

    def test_format_embed_color_low_confidence(self):
        """Test red color for low confidence."""
        fmt = self._get_formatter()
        receipt = _make_receipt(confidence_score=0.3)
        result = fmt.format(receipt)
        assert result["embeds"][0]["color"] == 0xED4245

    def test_format_includes_footer(self):
        """Test footer includes receipt ID."""
        fmt = self._get_formatter()
        receipt = _make_receipt(receipt_id="r-foot")
        result = fmt.format(receipt)
        footer = result["embeds"][0]["footer"]["text"]
        assert "r-foot" in footer
        assert "Aragora" in footer

    def test_format_includes_timestamp(self):
        """Test timestamp is included when present."""
        fmt = self._get_formatter()
        receipt = _make_receipt(timestamp="2025-01-15T12:00:00Z")
        result = fmt.format(receipt)
        assert result["embeds"][0]["timestamp"] == "2025-01-15T12:00:00Z"

    def test_format_no_timestamp(self):
        """Test no timestamp field when timestamp is None."""
        fmt = self._get_formatter()
        receipt = _make_receipt(timestamp=None)
        result = fmt.format(receipt)
        assert "timestamp" not in result["embeds"][0]

    def test_format_minimal_receipt(self):
        """Test formatting a receipt with minimal data."""
        fmt = self._get_formatter()
        receipt = _make_minimal_receipt()
        result = fmt.format(receipt)
        assert "embeds" in result
        fields = result["embeds"][0]["fields"]
        decision_field = next(f for f in fields if f["name"] == "Decision")
        assert "No decision reached" in decision_field["value"]

    def test_confidence_bar(self):
        """Test confidence bar generation."""
        fmt = self._get_formatter()
        bar = fmt._make_confidence_bar(0.7, length=10)
        assert len(bar) == 10
        assert bar.count("\u2588") == 7  # filled blocks
        assert bar.count("\u2591") == 3  # empty blocks

    def test_confidence_bar_zero(self):
        """Test confidence bar at 0%."""
        fmt = self._get_formatter()
        bar = fmt._make_confidence_bar(0.0, length=5)
        assert bar == "\u2591" * 5

    def test_confidence_bar_full(self):
        """Test confidence bar at 100%."""
        fmt = self._get_formatter()
        bar = fmt._make_confidence_bar(1.0, length=5)
        assert bar == "\u2588" * 5


# =============================================================================
# Email Receipt Formatter Tests
# =============================================================================


class TestEmailReceiptFormatter:
    """Tests for EmailReceiptFormatter."""

    def _get_formatter(self):
        from aragora.channels.email_formatter import EmailReceiptFormatter

        return EmailReceiptFormatter()

    def test_channel_type(self):
        """Test formatter channel type."""
        fmt = self._get_formatter()
        assert fmt.channel_type == "email"

    def test_format_returns_html(self):
        """Test format returns HTML content."""
        fmt = self._get_formatter()
        receipt = _make_receipt()
        result = fmt.format(receipt)
        assert "html" in result
        assert "Decision Receipt" in result["html"]

    def test_format_returns_subject(self):
        """Test format returns email subject."""
        fmt = self._get_formatter()
        receipt = _make_receipt(topic="Microservices adoption")
        result = fmt.format(receipt)
        assert "subject" in result
        assert "Microservices" in result["subject"]

    def test_format_subject_truncation(self):
        """Test subject is truncated for long topics."""
        fmt = self._get_formatter()
        long_topic = "A" * 100
        receipt = _make_receipt(topic=long_topic)
        result = fmt.format(receipt)
        assert "..." in result["subject"]

    def test_format_includes_plain_text(self):
        """Test format includes plain text version by default."""
        fmt = self._get_formatter()
        receipt = _make_receipt()
        result = fmt.format(receipt)
        assert "plain_text" in result
        assert "DECISION RECEIPT" in result["plain_text"]

    def test_format_no_plain_text_option(self):
        """Test plain text can be disabled."""
        fmt = self._get_formatter()
        receipt = _make_receipt()
        result = fmt.format(receipt, options={"plain_text": False})
        assert "plain_text" not in result

    def test_format_includes_css_by_default(self):
        """Test CSS is included by default."""
        fmt = self._get_formatter()
        receipt = _make_receipt()
        result = fmt.format(receipt)
        assert "<style>" in result["html"]

    def test_format_no_css_option(self):
        """Test CSS can be excluded."""
        fmt = self._get_formatter()
        receipt = _make_receipt()
        result = fmt.format(receipt, options={"include_css": False})
        assert "<style>" not in result["html"]

    def test_format_includes_topic(self):
        """Test topic is in HTML output."""
        fmt = self._get_formatter()
        receipt = _make_receipt(topic="API Design")
        result = fmt.format(receipt)
        assert "API Design" in result["html"]

    def test_format_includes_decision(self):
        """Test decision is in HTML output."""
        fmt = self._get_formatter()
        receipt = _make_receipt(decision="Proceed with caution")
        result = fmt.format(receipt)
        assert "Proceed with caution" in result["html"]

    def test_format_includes_confidence(self):
        """Test confidence is in HTML output."""
        fmt = self._get_formatter()
        receipt = _make_receipt(confidence_score=0.88)
        result = fmt.format(receipt)
        assert "88%" in result["html"]

    def test_format_compact_skips_details(self):
        """Test compact mode omits key arguments and risks."""
        fmt = self._get_formatter()
        receipt = _make_receipt(key_arguments=["A", "B"], risks=["R1"])
        result = fmt.format(receipt, options={"compact": True})
        assert "Key Arguments" not in result["html"]
        assert "Risks" not in result["html"]

    def test_format_full_includes_key_arguments(self):
        """Test full mode includes key arguments."""
        fmt = self._get_formatter()
        receipt = _make_receipt(key_arguments=["Scale better", "Faster deploys"])
        result = fmt.format(receipt)
        assert "Key Arguments" in result["html"]
        assert "Scale better" in result["html"]

    def test_format_full_includes_risks(self):
        """Test full mode includes risks."""
        fmt = self._get_formatter()
        receipt = _make_receipt(risks=["Security gap", "Cost overrun"])
        result = fmt.format(receipt)
        assert "Risks Identified" in result["html"]

    def test_format_dissenting_views(self):
        """Test dissenting views in HTML."""
        fmt = self._get_formatter()
        receipt = _make_receipt(dissenting_views=["Counter argument"])
        result = fmt.format(receipt)
        assert "Dissenting Views" in result["html"]

    def test_format_agents_in_metadata(self):
        """Test agents shown in metadata section."""
        fmt = self._get_formatter()
        receipt = _make_receipt(agents=["claude", "gpt-4"])
        result = fmt.format(receipt)
        assert "claude" in result["html"]
        assert "gpt-4" in result["html"]

    def test_format_timestamp_included(self):
        """Test timestamp in metadata."""
        fmt = self._get_formatter()
        receipt = _make_receipt(timestamp="2025-01-15T12:00:00Z")
        result = fmt.format(receipt)
        assert "2025-01-15T12:00:00Z" in result["html"]

    def test_escape_html(self):
        """Test HTML escaping."""
        fmt = self._get_formatter()
        escaped = fmt._escape_html('<script>alert("XSS")</script>')
        assert "<script>" not in escaped
        assert "&lt;script&gt;" in escaped

    def test_confidence_color_high(self):
        """Test green color for high confidence."""
        fmt = self._get_formatter()
        assert fmt._get_confidence_color(0.9) == "#22c55e"

    def test_confidence_color_medium(self):
        """Test yellow for medium confidence."""
        fmt = self._get_formatter()
        assert fmt._get_confidence_color(0.6) == "#eab308"

    def test_confidence_color_low(self):
        """Test red for low confidence."""
        fmt = self._get_formatter()
        assert fmt._get_confidence_color(0.3) == "#ef4444"

    def test_confidence_label_very_high(self):
        """Test very high confidence label."""
        fmt = self._get_formatter()
        assert fmt._get_confidence_label(0.95) == "Very High"

    def test_confidence_label_high(self):
        """Test high confidence label."""
        fmt = self._get_formatter()
        assert fmt._get_confidence_label(0.75) == "High"

    def test_confidence_label_moderate(self):
        """Test moderate confidence label."""
        fmt = self._get_formatter()
        assert fmt._get_confidence_label(0.55) == "Moderate"

    def test_confidence_label_low(self):
        """Test low confidence label."""
        fmt = self._get_formatter()
        assert fmt._get_confidence_label(0.3) == "Low"

    def test_format_minimal_receipt(self):
        """Test formatting with minimal receipt data."""
        fmt = self._get_formatter()
        receipt = _make_minimal_receipt()
        result = fmt.format(receipt)
        assert "html" in result
        assert "Decision Receipt" in result["html"]


# =============================================================================
# Slack Receipt Formatter Tests
# =============================================================================


class TestSlackReceiptFormatter:
    """Tests for SlackReceiptFormatter."""

    def _get_formatter(self):
        from aragora.channels.slack_formatter import SlackReceiptFormatter

        return SlackReceiptFormatter()

    def test_channel_type(self):
        """Test formatter channel type."""
        fmt = self._get_formatter()
        assert fmt.channel_type == "slack"

    def test_format_returns_blocks(self):
        """Test format returns Slack blocks."""
        fmt = self._get_formatter()
        receipt = _make_receipt()
        result = fmt.format(receipt)
        assert "blocks" in result
        assert isinstance(result["blocks"], list)
        assert len(result["blocks"]) > 0

    def test_format_header_block(self):
        """Test header block is present."""
        fmt = self._get_formatter()
        receipt = _make_receipt()
        result = fmt.format(receipt)
        blocks = result["blocks"]
        header = blocks[0]
        assert header["type"] == "header"
        assert "Decision Receipt" in header["text"]["text"]

    def test_format_topic_block(self):
        """Test topic section is present."""
        fmt = self._get_formatter()
        receipt = _make_receipt(topic="Cloud Migration")
        result = fmt.format(receipt)
        blocks = result["blocks"]
        topic_block = blocks[1]
        assert topic_block["type"] == "section"
        assert "Cloud Migration" in topic_block["text"]["text"]

    def test_format_includes_divider(self):
        """Test dividers are included."""
        fmt = self._get_formatter()
        receipt = _make_receipt()
        result = fmt.format(receipt)
        dividers = [b for b in result["blocks"] if b["type"] == "divider"]
        assert len(dividers) >= 1

    def test_format_decision_with_confidence_button(self):
        """Test decision block has confidence accessory button."""
        fmt = self._get_formatter()
        receipt = _make_receipt()
        result = fmt.format(receipt)
        # Find the decision section (has accessory)
        decision_blocks = [
            b for b in result["blocks"] if b.get("type") == "section" and "accessory" in b
        ]
        assert len(decision_blocks) == 1
        assert "85%" in decision_blocks[0]["accessory"]["text"]["text"]

    def test_format_compact_mode(self):
        """Test compact mode reduces detail blocks."""
        fmt = self._get_formatter()
        receipt = _make_receipt()
        full_result = fmt.format(receipt)
        compact_result = fmt.format(receipt, options={"compact": True})
        assert len(compact_result["blocks"]) <= len(full_result["blocks"])

    def test_format_includes_agents_context(self):
        """Test agents context block."""
        fmt = self._get_formatter()
        receipt = _make_receipt(agents=["claude", "gpt-4"])
        result = fmt.format(receipt)
        context_blocks = [b for b in result["blocks"] if b.get("type") == "context"]
        agent_texts = [
            e["text"]
            for b in context_blocks
            for e in b.get("elements", [])
            if "Agents" in e.get("text", "")
        ]
        assert len(agent_texts) > 0
        assert "claude" in agent_texts[0]

    def test_format_includes_footer(self):
        """Test footer context block with receipt ID."""
        fmt = self._get_formatter()
        receipt = _make_receipt(receipt_id="r-slack-test")
        result = fmt.format(receipt)
        blocks = result["blocks"]
        last_context = [b for b in blocks if b.get("type") == "context"][-1]
        footer_text = last_context["elements"][0]["text"]
        assert "r-slack-test" in footer_text
        assert "Aragora" in footer_text

    def test_format_key_arguments(self):
        """Test key arguments section."""
        fmt = self._get_formatter()
        receipt = _make_receipt(key_arguments=["Speed", "Cost reduction"])
        result = fmt.format(receipt)
        section_texts = [
            b["text"]["text"]
            for b in result["blocks"]
            if b.get("type") == "section" and "Key Arguments" in b.get("text", {}).get("text", "")
        ]
        assert len(section_texts) == 1

    def test_format_risks(self):
        """Test risks section."""
        fmt = self._get_formatter()
        receipt = _make_receipt(risks=["Data loss", "Downtime"])
        result = fmt.format(receipt)
        section_texts = [
            b["text"]["text"]
            for b in result["blocks"]
            if b.get("type") == "section" and "Risks" in b.get("text", {}).get("text", "")
        ]
        assert len(section_texts) == 1

    def test_format_dissenting_views(self):
        """Test dissenting views section."""
        fmt = self._get_formatter()
        receipt = _make_receipt(dissenting_views=["Alternative approach preferred"])
        result = fmt.format(receipt)
        section_texts = [
            b["text"]["text"]
            for b in result["blocks"]
            if b.get("type") == "section" and "Dissenting" in b.get("text", {}).get("text", "")
        ]
        assert len(section_texts) == 1

    def test_confidence_emoji_very_high(self):
        """Test emoji for very high confidence."""
        fmt = self._get_formatter()
        assert fmt._get_confidence_emoji(0.95) == ":white_check_mark:"

    def test_confidence_emoji_high(self):
        """Test emoji for high confidence."""
        fmt = self._get_formatter()
        assert fmt._get_confidence_emoji(0.75) == ":large_green_circle:"

    def test_confidence_emoji_medium(self):
        """Test emoji for medium confidence."""
        fmt = self._get_formatter()
        assert fmt._get_confidence_emoji(0.55) == ":large_yellow_circle:"

    def test_confidence_emoji_low(self):
        """Test emoji for low confidence."""
        fmt = self._get_formatter()
        assert fmt._get_confidence_emoji(0.3) == ":red_circle:"

    def test_format_evidence_section(self):
        """Test evidence section when evidence is present."""
        fmt = self._get_formatter()
        receipt = _make_receipt(evidence=["doc1", "doc2", "doc3"])
        result = fmt.format(receipt)
        context_blocks = [b for b in result["blocks"] if b.get("type") == "context"]
        evidence_texts = [
            e["text"]
            for b in context_blocks
            for e in b.get("elements", [])
            if "evidence" in e.get("text", "")
        ]
        assert len(evidence_texts) > 0
        assert "3" in evidence_texts[0]

    def test_format_no_agents_option(self):
        """Test excluding agents section."""
        fmt = self._get_formatter()
        receipt = _make_receipt()
        result = fmt.format(receipt, options={"include_agents": False})
        context_blocks = [b for b in result["blocks"] if b.get("type") == "context"]
        agent_texts = [
            e["text"]
            for b in context_blocks
            for e in b.get("elements", [])
            if "Agents" in e.get("text", "")
        ]
        assert len(agent_texts) == 0


# =============================================================================
# Teams Receipt Formatter Tests
# =============================================================================


class TestTeamsReceiptFormatter:
    """Tests for TeamsReceiptFormatter."""

    def _get_formatter(self):
        from aragora.channels.teams_formatter import TeamsReceiptFormatter

        return TeamsReceiptFormatter()

    def test_channel_type(self):
        """Test formatter channel type."""
        fmt = self._get_formatter()
        assert fmt.channel_type == "teams"

    def test_format_returns_adaptive_card(self):
        """Test format returns an Adaptive Card structure."""
        fmt = self._get_formatter()
        receipt = _make_receipt()
        result = fmt.format(receipt)
        assert result["type"] == "AdaptiveCard"
        assert result["version"] == "1.4"
        assert "body" in result
        assert "actions" in result

    def test_format_card_schema(self):
        """Test Adaptive Card schema URL."""
        fmt = self._get_formatter()
        receipt = _make_receipt()
        result = fmt.format(receipt)
        assert "adaptivecards.io" in result["$schema"]

    def test_format_header_in_body(self):
        """Test header text block in card body."""
        fmt = self._get_formatter()
        receipt = _make_receipt()
        result = fmt.format(receipt)
        body = result["body"]
        header = body[0]
        assert header["type"] == "TextBlock"
        assert "Decision Receipt" in header["text"]

    def test_format_topic_in_body(self):
        """Test topic text block."""
        fmt = self._get_formatter()
        receipt = _make_receipt(topic="Security Review")
        result = fmt.format(receipt)
        body = result["body"]
        topic_block = body[1]
        assert "Security Review" in topic_block["text"]

    def test_format_confidence_column_set(self):
        """Test confidence is displayed as a ColumnSet."""
        fmt = self._get_formatter()
        receipt = _make_receipt(confidence_score=0.9)
        result = fmt.format(receipt)
        column_sets = [b for b in result["body"] if b.get("type") == "ColumnSet"]
        assert len(column_sets) >= 1
        # First column should have the percentage
        first_col = column_sets[0]["columns"][0]["items"][0]
        assert "90%" in first_col["text"]

    def test_format_decision_text(self):
        """Test decision text block."""
        fmt = self._get_formatter()
        receipt = _make_receipt(decision="Deploy to production")
        result = fmt.format(receipt)
        # Find the decision text block (follows the "Decision" label)
        texts = [b["text"] for b in result["body"] if b.get("type") == "TextBlock"]
        assert any("Deploy to production" in t for t in texts)

    def test_format_compact_mode(self):
        """Test compact mode skips details."""
        fmt = self._get_formatter()
        receipt = _make_receipt(key_arguments=["A"], risks=["B"])
        full = fmt.format(receipt)
        compact = fmt.format(receipt, options={"compact": True})
        assert len(compact["body"]) < len(full["body"])

    def test_format_key_arguments(self):
        """Test key arguments in card body."""
        fmt = self._get_formatter()
        receipt = _make_receipt(key_arguments=["Performance", "Reliability"])
        result = fmt.format(receipt)
        texts = [b.get("text", "") for b in result["body"] if b.get("type") == "TextBlock"]
        assert any("Key Arguments" in t for t in texts)
        assert any("Performance" in t for t in texts)

    def test_format_risks_with_warning_color(self):
        """Test risks displayed with warning color."""
        fmt = self._get_formatter()
        receipt = _make_receipt(risks=["Risk 1"])
        result = fmt.format(receipt)
        risk_blocks = [
            b
            for b in result["body"]
            if b.get("type") == "TextBlock" and b.get("color") == "Warning"
        ]
        assert len(risk_blocks) >= 1

    def test_format_agents_fact_set(self):
        """Test agents shown in FactSet."""
        fmt = self._get_formatter()
        receipt = _make_receipt(agents=["claude", "gpt-4"])
        result = fmt.format(receipt)
        fact_sets = [b for b in result["body"] if b.get("type") == "FactSet"]
        assert len(fact_sets) >= 1
        agents_fact = fact_sets[0]["facts"][0]
        assert agents_fact["title"] == "Agents"
        assert "claude" in agents_fact["value"]

    def test_format_receipt_id_footer(self):
        """Test receipt ID in footer."""
        fmt = self._get_formatter()
        receipt = _make_receipt(receipt_id="r-teams-01")
        result = fmt.format(receipt)
        footer_blocks = [
            b
            for b in result["body"]
            if b.get("type") == "TextBlock" and "Receipt ID" in b.get("text", "")
        ]
        assert len(footer_blocks) == 1
        assert "r-teams-01" in footer_blocks[0]["text"]

    def test_format_action_url(self):
        """Test action URL includes receipt ID."""
        fmt = self._get_formatter()
        receipt = _make_receipt(receipt_id="r-abc")
        result = fmt.format(receipt)
        actions = result["actions"]
        assert len(actions) == 1
        assert "r-abc" in actions[0]["url"]

    def test_confidence_color_good(self):
        """Test Good color for high confidence."""
        fmt = self._get_formatter()
        assert fmt._get_confidence_color(0.85) == "Good"

    def test_confidence_color_warning(self):
        """Test Warning color for medium confidence."""
        fmt = self._get_formatter()
        assert fmt._get_confidence_color(0.6) == "Warning"

    def test_confidence_color_attention(self):
        """Test Attention color for low confidence."""
        fmt = self._get_formatter()
        assert fmt._get_confidence_color(0.3) == "Attention"

    def test_confidence_label_teams(self):
        """Test Teams-specific confidence labels."""
        fmt = self._get_formatter()
        assert fmt._get_confidence_label(0.95) == "Very High"
        assert fmt._get_confidence_label(0.75) == "High"
        assert fmt._get_confidence_label(0.55) == "Moderate"
        assert fmt._get_confidence_label(0.3) == "Low"

    def test_format_minimal_receipt(self):
        """Test formatting with minimal data."""
        fmt = self._get_formatter()
        receipt = _make_minimal_receipt()
        result = fmt.format(receipt)
        assert result["type"] == "AdaptiveCard"
        assert len(result["body"]) > 0


# =============================================================================
# Debate receipts store one mapping per agent
# =============================================================================


DEBATE_AGENTS = [
    {"provider": "openai-api", "model": "gpt-5.5", "name": "gpt55", "role": "proposer"},
    {"provider": "openai-api", "model": "claude-haiku-4-5", "name": "haiku", "role": "critic"},
]


def _debate_receipt():
    from aragora.export.decision_receipt import DecisionReceipt

    return DecisionReceipt(
        receipt_id="r-debate",
        gauntlet_id="debate-1",
        verdict="PASS",
        confidence=0.8,
        input_summary="Ship it?",
        agents_involved=DEBATE_AGENTS,
    )


class TestDebateAgentEntries:
    def test_agent_display_names(self):
        from aragora.export.decision_receipt import agent_display_names

        assert agent_display_names(DEBATE_AGENTS) == ["gpt55", "haiku"]
        assert agent_display_names(["claude", {"model": "m"}, {"x": 1}]) == [
            "claude",
            "m",
            "{'x': 1}",
        ]
        assert agent_display_names(None) == []

    def test_markdown_and_html_name_the_agents(self):
        receipt = _debate_receipt()
        assert "**Agents:** gpt55, haiku" in receipt.to_markdown()
        assert "gpt55, haiku" in receipt.to_html()

    @pytest.mark.parametrize("channel", ["slack", "teams", "discord"])
    def test_channel_formatters_name_the_agents(self, channel):
        import json

        from aragora.channels.formatter import format_receipt_for_channel

        formatted = format_receipt_for_channel(_debate_receipt(), channel, {})
        assert "gpt55, haiku" in json.dumps(formatted)

    def test_plain_text_email_names_the_agents(self):
        from aragora.channels.email_formatter import EmailReceiptFormatter

        receipt = _make_receipt(agents=DEBATE_AGENTS)
        text = EmailReceiptFormatter().format(receipt, {})["plain_text"]
        assert "Agents: gpt55, haiku" in text
