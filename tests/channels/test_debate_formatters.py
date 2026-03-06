"""Tests for rich per-channel debate result formatters."""

from __future__ import annotations

import pytest

from aragora.channels.debate_formatter import (
    DebateResultFormatter,
    _DEBATE_FORMATTERS,
    format_result_for_channel,
    get_debate_formatter,
    register_debate_formatter,
)

# Import formatter modules so their @register_debate_formatter decorators execute.
import aragora.channels.slack_debate_formatter  # noqa: F401
import aragora.channels.teams_debate_formatter  # noqa: F401
import aragora.channels.email_debate_formatter  # noqa: F401


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def debate_result() -> dict:
    """Minimal debate result dict exercising every field the formatters read."""
    return {
        "consensus_reached": True,
        "final_answer": "We should adopt the proposal with modifications.",
        "confidence": 0.85,
        "participants": ["claude", "gpt-4", "gemini"],
        "task": "Evaluate the new rate-limiter design",
        "rounds": 3,
        "duration_seconds": 12.4,
    }


@pytest.fixture()
def no_consensus_result() -> dict:
    return {
        "consensus_reached": False,
        "final_answer": "The agents could not reach agreement.",
        "confidence": 0.35,
        "participants": ["claude"],
        "rounds": 5,
    }


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------


class TestRegistry:
    """Tests for the debate formatter registry."""

    def test_slack_registered(self):
        assert "slack" in _DEBATE_FORMATTERS

    def test_teams_registered(self):
        assert "teams" in _DEBATE_FORMATTERS

    def test_email_registered(self):
        assert "email" in _DEBATE_FORMATTERS

    def test_get_debate_formatter_returns_instance(self):
        fmt = get_debate_formatter("slack")
        assert isinstance(fmt, DebateResultFormatter)

    def test_get_debate_formatter_unknown_returns_none(self):
        assert get_debate_formatter("fax_machine") is None

    def test_register_debate_formatter_decorator(self):
        @register_debate_formatter("_test_platform")
        class _TestFormatter(DebateResultFormatter):
            def format(self, result, options=None):
                return {"ok": True}

            def format_summary(self, result, max_length=500):
                return "ok"

        assert "_test_platform" in _DEBATE_FORMATTERS
        inst = get_debate_formatter("_test_platform")
        assert inst is not None
        assert inst.format({}) == {"ok": True}
        # cleanup
        _DEBATE_FORMATTERS.pop("_test_platform", None)


# ---------------------------------------------------------------------------
# format_result_for_channel fallback
# ---------------------------------------------------------------------------


class TestFormatResultForChannel:
    def test_returns_dict_for_known_platform(self, debate_result):
        out = format_result_for_channel("slack", debate_result)
        assert isinstance(out, dict)

    def test_returns_plain_text_for_unknown_platform(self, debate_result):
        out = format_result_for_channel("carrier_pigeon", debate_result)
        assert isinstance(out, str)
        assert "Consensus reached" in out
        assert "85%" in out

    def test_plain_text_no_consensus(self, no_consensus_result):
        out = format_result_for_channel("unknown", no_consensus_result)
        assert isinstance(out, str)
        assert "No consensus" in out


# ---------------------------------------------------------------------------
# Slack formatter
# ---------------------------------------------------------------------------


class TestSlackDebateFormatter:
    def test_format_returns_blocks(self, debate_result):
        fmt = get_debate_formatter("slack")
        assert fmt is not None
        out = fmt.format(debate_result)
        assert "blocks" in out
        blocks = out["blocks"]
        assert isinstance(blocks, list)
        assert len(blocks) >= 4

    def test_header_has_consensus_emoji(self, debate_result):
        fmt = get_debate_formatter("slack")
        out = fmt.format(debate_result)
        header = out["blocks"][0]
        assert header["type"] == "header"
        # High-confidence consensus -> check mark
        assert ":white_check_mark:" in header["text"]["text"]

    def test_no_consensus_emoji(self, no_consensus_result):
        fmt = get_debate_formatter("slack")
        out = fmt.format(no_consensus_result)
        header = out["blocks"][0]
        assert ":x:" in header["text"]["text"]

    def test_warning_emoji_for_low_confidence_consensus(self):
        result = {
            "consensus_reached": True,
            "confidence": 0.55,
            "final_answer": "Maybe.",
        }
        fmt = get_debate_formatter("slack")
        out = fmt.format(result)
        header = out["blocks"][0]
        assert ":warning:" in header["text"]["text"]

    def test_section_fields_present(self, debate_result):
        fmt = get_debate_formatter("slack")
        out = fmt.format(debate_result)
        section = out["blocks"][1]
        assert section["type"] == "section"
        assert "fields" in section
        texts = [f["text"] for f in section["fields"]]
        combined = " ".join(texts)
        assert "Consensus" in combined
        assert "Confidence" in combined
        assert "Rounds" in combined

    def test_divider_present(self, debate_result):
        fmt = get_debate_formatter("slack")
        out = fmt.format(debate_result)
        types = [b["type"] for b in out["blocks"]]
        assert "divider" in types

    def test_answer_preview_truncated(self):
        long_answer = "x" * 1000
        result = {"final_answer": long_answer, "confidence": 0.5}
        fmt = get_debate_formatter("slack")
        out = fmt.format(result)
        # Find the section with the conclusion
        for block in out["blocks"]:
            if block.get("type") == "section" and "Conclusion" in block.get("text", {}).get(
                "text", ""
            ):
                assert len(block["text"]["text"]) <= 520  # header + 500 + "..."
                assert block["text"]["text"].endswith("...")
                break
        else:
            pytest.fail("No conclusion section found")

    def test_context_block_agents_and_duration(self, debate_result):
        fmt = get_debate_formatter("slack")
        out = fmt.format(debate_result)
        context_blocks = [b for b in out["blocks"] if b["type"] == "context"]
        assert len(context_blocks) >= 1
        text = context_blocks[0]["elements"][0]["text"]
        assert "3 agents" in text
        assert "12.4s" in text

    def test_format_summary(self, debate_result):
        fmt = get_debate_formatter("slack")
        summary = fmt.format_summary(debate_result)
        assert isinstance(summary, str)
        assert "Consensus" in summary
        assert "85%" in summary

    def test_format_summary_truncation(self):
        result = {"final_answer": "a" * 600, "confidence": 0.9, "consensus_reached": True}
        fmt = get_debate_formatter("slack")
        summary = fmt.format_summary(result, max_length=100)
        assert len(summary) <= 100
        assert summary.endswith("...")


# ---------------------------------------------------------------------------
# Teams formatter
# ---------------------------------------------------------------------------


class TestTeamsDebateFormatter:
    def test_format_returns_adaptive_card(self, debate_result):
        fmt = get_debate_formatter("teams")
        assert fmt is not None
        out = fmt.format(debate_result)
        assert out["type"] == "AdaptiveCard"
        assert out["version"] == "1.5"
        assert "$schema" in out
        assert isinstance(out["body"], list)

    def test_header_text_block(self, debate_result):
        fmt = get_debate_formatter("teams")
        out = fmt.format(debate_result)
        header = out["body"][0]
        assert header["type"] == "TextBlock"
        assert "Debate Complete" in header["text"]
        assert "Consensus Reached" in header["text"]

    def test_no_consensus_header(self, no_consensus_result):
        fmt = get_debate_formatter("teams")
        out = fmt.format(no_consensus_result)
        header = out["body"][0]
        assert "No Consensus" in header["text"]

    def test_fact_set_present(self, debate_result):
        fmt = get_debate_formatter("teams")
        out = fmt.format(debate_result)
        fact_sets = [b for b in out["body"] if b["type"] == "FactSet"]
        assert len(fact_sets) >= 1
        titles = [f["title"] for f in fact_sets[0]["facts"]]
        assert "Consensus" in titles
        assert "Confidence" in titles
        assert "Rounds" in titles

    def test_agents_in_fact_set(self, debate_result):
        fmt = get_debate_formatter("teams")
        out = fmt.format(debate_result)
        fact_sets = [b for b in out["body"] if b["type"] == "FactSet"]
        titles = [f["title"] for f in fact_sets[0]["facts"]]
        assert "Agents" in titles

    def test_duration_in_fact_set(self, debate_result):
        fmt = get_debate_formatter("teams")
        out = fmt.format(debate_result)
        fact_sets = [b for b in out["body"] if b["type"] == "FactSet"]
        titles = [f["title"] for f in fact_sets[0]["facts"]]
        assert "Duration" in titles

    def test_conclusion_text_block(self, debate_result):
        fmt = get_debate_formatter("teams")
        out = fmt.format(debate_result)
        texts = [b.get("text", "") for b in out["body"] if b["type"] == "TextBlock"]
        assert any("adopt the proposal" in t for t in texts)

    def test_format_summary(self, debate_result):
        fmt = get_debate_formatter("teams")
        summary = fmt.format_summary(debate_result)
        assert isinstance(summary, str)
        assert "Consensus" in summary


# ---------------------------------------------------------------------------
# Email formatter
# ---------------------------------------------------------------------------


class TestEmailDebateFormatter:
    def test_format_returns_html_and_text(self, debate_result):
        fmt = get_debate_formatter("email")
        assert fmt is not None
        out = fmt.format(debate_result)
        assert "html" in out
        assert "text" in out

    def test_html_contains_key_data(self, debate_result):
        fmt = get_debate_formatter("email")
        out = fmt.format(debate_result)
        html = out["html"]
        assert "Debate Complete" in html
        assert "85%" in html
        assert "adopt the proposal" in html
        assert "Aragora" in html

    def test_text_contains_key_data(self, debate_result):
        fmt = get_debate_formatter("email")
        out = fmt.format(debate_result)
        text = out["text"]
        assert "Debate Complete" in text
        assert "85%" in text
        assert "Consensus: Yes" in text

    def test_no_consensus_text(self, no_consensus_result):
        fmt = get_debate_formatter("email")
        out = fmt.format(no_consensus_result)
        assert "Consensus: No" in out["text"]

    def test_html_escapes_special_chars(self):
        result = {
            "final_answer": "<script>alert('xss')</script>",
            "confidence": 0.5,
            "task": 'Topic with "quotes" & <angles>',
        }
        fmt = get_debate_formatter("email")
        out = fmt.format(result)
        assert "<script>" not in out["html"]
        assert "&lt;script&gt;" in out["html"]

    def test_participants_in_html(self, debate_result):
        fmt = get_debate_formatter("email")
        out = fmt.format(debate_result)
        assert "claude" in out["html"]

    def test_duration_in_html(self, debate_result):
        fmt = get_debate_formatter("email")
        out = fmt.format(debate_result)
        assert "12.4s" in out["html"]

    def test_format_summary(self, debate_result):
        fmt = get_debate_formatter("email")
        summary = fmt.format_summary(debate_result)
        assert isinstance(summary, str)
        assert "Consensus" in summary


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_result(self):
        """All formatters handle an empty dict without crashing."""
        for platform in ("slack", "teams", "email"):
            fmt = get_debate_formatter(platform)
            assert fmt is not None
            out = fmt.format({})
            assert out is not None
            summary = fmt.format_summary({})
            assert isinstance(summary, str)

    def test_non_numeric_confidence(self):
        result = {"confidence": "high", "final_answer": "ok"}
        for platform in ("slack", "teams", "email"):
            fmt = get_debate_formatter(platform)
            out = fmt.format(result)
            assert out is not None

    def test_missing_participants(self):
        result = {"confidence": 0.9, "consensus_reached": True, "final_answer": "yes"}
        fmt = get_debate_formatter("slack")
        out = fmt.format(result)
        # No context block when no participants
        context_blocks = [b for b in out["blocks"] if b["type"] == "context"]
        assert len(context_blocks) == 0
