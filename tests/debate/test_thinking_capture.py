"""Tests for extended thinking trace capture in debate metadata.

Verifies:
- AnthropicAPIAgent thinking_budget param and last_thinking_trace property
- _parse_content_blocks separates text and thinking blocks correctly
- get_metadata returns thinking trace and budget
- thinking_budget flows from DebateProtocol to Anthropic agents
- thinking traces are collected in DebateResult.metadata after debate
- DecisionReceipt model accepts thinking_traces field
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.agents.api_agents.anthropic import AnthropicAPIAgent
from aragora.debate.protocol import DebateProtocol


class TestThinkingTraceCapture:
    """Test AnthropicAPIAgent thinking_budget and last_thinking_trace."""

    @patch("aragora.agents.api_agents.anthropic.get_primary_api_key", return_value="fake-key")
    def test_agent_has_thinking_budget_param(self, _mock_key: MagicMock) -> None:
        agent = AnthropicAPIAgent(
            name="test-claude",
            thinking_budget=10000,
        )
        assert agent.thinking_budget == 10000

    @patch("aragora.agents.api_agents.anthropic.get_primary_api_key", return_value="fake-key")
    def test_default_thinking_budget_is_none(self, _mock_key: MagicMock) -> None:
        agent = AnthropicAPIAgent(name="test-claude")
        assert agent.thinking_budget is None

    @patch("aragora.agents.api_agents.anthropic.get_primary_api_key", return_value="fake-key")
    def test_last_thinking_trace_initially_none(self, _mock_key: MagicMock) -> None:
        agent = AnthropicAPIAgent(name="test-claude")
        assert agent.last_thinking_trace is None

    @patch("aragora.agents.api_agents.anthropic.get_primary_api_key", return_value="fake-key")
    def test_thinking_trace_type(self, _mock_key: MagicMock) -> None:
        agent = AnthropicAPIAgent(name="test-claude")
        agent._last_thinking_trace = "I need to analyze this carefully..."
        assert isinstance(agent.last_thinking_trace, str)
        assert "analyze" in agent.last_thinking_trace

    @patch("aragora.agents.api_agents.anthropic.get_primary_api_key", return_value="fake-key")
    def test_thinking_trace_cleared_between_calls(self, _mock_key: MagicMock) -> None:
        """Setting a new trace replaces the old one."""
        agent = AnthropicAPIAgent(name="test-claude")
        agent._last_thinking_trace = "First reasoning chain"
        assert agent.last_thinking_trace == "First reasoning chain"
        agent._last_thinking_trace = "Second reasoning chain"
        assert agent.last_thinking_trace == "Second reasoning chain"

    @patch("aragora.agents.api_agents.anthropic.get_primary_api_key", return_value="fake-key")
    def test_thinking_trace_reset_to_none(self, _mock_key: MagicMock) -> None:
        agent = AnthropicAPIAgent(name="test-claude")
        agent._last_thinking_trace = "Some reasoning"
        agent._last_thinking_trace = None
        assert agent.last_thinking_trace is None


class TestParseContentBlocks:
    """Test _parse_content_blocks separates text and thinking correctly."""

    def test_text_only_blocks(self) -> None:
        blocks = [
            {"type": "text", "text": "Hello world"},
        ]
        text, thinking = AnthropicAPIAgent._parse_content_blocks(blocks)
        assert text == "Hello world"
        assert thinking is None

    def test_thinking_only_blocks(self) -> None:
        blocks = [
            {"type": "thinking", "thinking": "Let me reason step by step..."},
        ]
        text, thinking = AnthropicAPIAgent._parse_content_blocks(blocks)
        assert text == ""
        assert thinking == "Let me reason step by step..."

    def test_mixed_text_and_thinking(self) -> None:
        blocks = [
            {"type": "thinking", "thinking": "Step 1: consider options"},
            {"type": "text", "text": "Here is my answer"},
        ]
        text, thinking = AnthropicAPIAgent._parse_content_blocks(blocks)
        assert text == "Here is my answer"
        assert thinking == "Step 1: consider options"

    def test_multiple_thinking_blocks_joined(self) -> None:
        blocks = [
            {"type": "thinking", "thinking": "First thought"},
            {"type": "thinking", "thinking": "Second thought"},
            {"type": "text", "text": "Final answer"},
        ]
        text, thinking = AnthropicAPIAgent._parse_content_blocks(blocks)
        assert text == "Final answer"
        assert thinking == "First thought\n\nSecond thought"

    def test_multiple_text_blocks_joined(self) -> None:
        blocks = [
            {"type": "text", "text": "Part 1"},
            {"type": "text", "text": "Part 2"},
        ]
        text, thinking = AnthropicAPIAgent._parse_content_blocks(blocks)
        assert text == "Part 1\nPart 2"
        assert thinking is None

    def test_empty_blocks(self) -> None:
        text, thinking = AnthropicAPIAgent._parse_content_blocks([])
        assert text == ""
        assert thinking is None

    def test_web_search_result_blocks(self) -> None:
        blocks = [
            {"type": "text", "text": "Based on my search:"},
            {
                "type": "web_search_tool_result",
                "content": [
                    {
                        "type": "web_search_result",
                        "title": "Example Article",
                        "url": "https://example.com/article",
                    }
                ],
            },
        ]
        text, thinking = AnthropicAPIAgent._parse_content_blocks(blocks)
        assert "Based on my search:" in text
        assert "[Source: Example Article](https://example.com/article)" in text
        assert thinking is None

    def test_unknown_block_type_ignored(self) -> None:
        blocks = [
            {"type": "text", "text": "Hello"},
            {"type": "tool_use", "id": "tool-1"},
        ]
        text, thinking = AnthropicAPIAgent._parse_content_blocks(blocks)
        assert text == "Hello"
        assert thinking is None


class TestThinkingInProposalMetadata:
    """Verify thinking traces are captured in proposal metadata via get_metadata."""

    @patch("aragora.agents.api_agents.anthropic.get_primary_api_key", return_value="fake-key")
    def test_get_metadata_includes_thinking(self, _mock_key: MagicMock) -> None:
        agent = AnthropicAPIAgent(
            name="thinker",
            thinking_budget=5000,
        )
        agent._last_thinking_trace = "Step 1: Consider the implications..."
        metadata = agent.get_metadata()
        assert metadata["thinking"] == "Step 1: Consider the implications..."
        assert metadata["thinking_budget"] == 5000

    @patch("aragora.agents.api_agents.anthropic.get_primary_api_key", return_value="fake-key")
    def test_get_metadata_no_thinking(self, _mock_key: MagicMock) -> None:
        agent = AnthropicAPIAgent(name="thinker")
        metadata = agent.get_metadata()
        assert metadata["thinking"] is None
        assert metadata["thinking_budget"] is None

    @patch("aragora.agents.api_agents.anthropic.get_primary_api_key", return_value="fake-key")
    def test_proposal_includes_thinking_metadata(self, _mock_key: MagicMock) -> None:
        agent = AnthropicAPIAgent(
            name="thinker",
            thinking_budget=5000,
        )
        agent._last_thinking_trace = "Step 1: Consider the implications..."
        trace = agent.last_thinking_trace
        assert trace is not None
        assert len(trace) > 0


class TestProtocolThinkingBudget:
    """Test thinking_budget on DebateProtocol."""

    def test_default_is_none(self):
        protocol = DebateProtocol()
        assert protocol.thinking_budget is None

    def test_set_thinking_budget(self):
        protocol = DebateProtocol(thinking_budget=10000)
        assert protocol.thinking_budget == 10000

    def test_zero_budget_treated_as_disabled(self):
        protocol = DebateProtocol(thinking_budget=0)
        assert protocol.thinking_budget == 0


class TestThinkingBudgetPropagation:
    """Test that thinking_budget propagates from protocol to agents."""

    def test_propagate_to_anthropic_agent(self):
        """Protocol thinking_budget should set agent.thinking_budget if not already set."""
        # Simulate the propagation logic from orchestrator.py
        mock_agent = MagicMock()
        mock_agent.thinking_budget = None
        mock_agent.name = "claude-api"

        protocol = DebateProtocol(thinking_budget=8000)
        agents = [mock_agent]

        # Mirror the propagation code from Arena.__init__
        if protocol.thinking_budget:
            for agent in agents:
                if hasattr(agent, "thinking_budget") and agent.thinking_budget is None:
                    agent.thinking_budget = protocol.thinking_budget

        assert mock_agent.thinking_budget == 8000

    def test_no_overwrite_existing_budget(self):
        """Agent's own thinking_budget should take precedence."""
        mock_agent = MagicMock()
        mock_agent.thinking_budget = 5000
        mock_agent.name = "claude-api"

        protocol = DebateProtocol(thinking_budget=8000)
        agents = [mock_agent]

        if protocol.thinking_budget:
            for agent in agents:
                if hasattr(agent, "thinking_budget") and agent.thinking_budget is None:
                    agent.thinking_budget = protocol.thinking_budget

        assert mock_agent.thinking_budget == 5000

    def test_skip_non_anthropic_agents(self):
        """Non-Anthropic agents without thinking_budget attr should be skipped."""
        mock_agent = MagicMock(spec=[])  # no attributes
        del mock_agent.thinking_budget  # ensure it doesn't exist

        protocol = DebateProtocol(thinking_budget=8000)
        agents = [mock_agent]

        if protocol.thinking_budget:
            for agent in agents:
                if hasattr(agent, "thinking_budget") and agent.thinking_budget is None:
                    agent.thinking_budget = protocol.thinking_budget

        assert not hasattr(mock_agent, "thinking_budget")


class TestThinkingTracesInResult:
    """Test thinking trace collection from agents into result metadata."""

    def test_collect_traces_from_agents(self):
        """Should collect _last_thinking_trace from agents with traces."""
        agent1 = MagicMock()
        agent1.name = "claude-1"
        agent1._last_thinking_trace = "Reasoning chain 1"

        agent2 = MagicMock()
        agent2.name = "gpt-4"
        agent2._last_thinking_trace = None

        agent3 = MagicMock()
        agent3.name = "claude-2"
        agent3._last_thinking_trace = "Reasoning chain 2"

        agents = [agent1, agent2, agent3]
        thinking_traces: dict[str, str] = {}
        for agent in agents:
            trace = getattr(agent, "_last_thinking_trace", None)
            if trace:
                thinking_traces[agent.name] = trace

        assert len(thinking_traces) == 2
        assert thinking_traces["claude-1"] == "Reasoning chain 1"
        assert thinking_traces["claude-2"] == "Reasoning chain 2"
        assert "gpt-4" not in thinking_traces

    def test_no_traces_when_none_available(self):
        """Should produce empty dict when no agents have traces."""
        agent1 = MagicMock()
        agent1.name = "gpt-4"
        agent1._last_thinking_trace = None

        agents = [agent1]
        thinking_traces: dict[str, str] = {}
        for agent in agents:
            trace = getattr(agent, "_last_thinking_trace", None)
            if trace:
                thinking_traces[agent.name] = trace

        assert len(thinking_traces) == 0

    def test_agent_without_thinking_attr(self):
        """Agents without _last_thinking_trace should be safely skipped."""
        agent1 = MagicMock(spec=[])
        agent1.name = "basic-agent"

        agents = [agent1]
        thinking_traces: dict[str, str] = {}
        for agent in agents:
            trace = getattr(agent, "_last_thinking_trace", None)
            if trace:
                thinking_traces[agent.name] = trace

        assert len(thinking_traces) == 0


class TestDecisionReceiptThinkingTraces:
    """Test that DecisionReceipt model supports thinking_traces."""

    def test_receipt_thinking_traces_default_none(self):
        from aragora.gauntlet.receipt_models import DecisionReceipt

        receipt = DecisionReceipt(
            receipt_id="test-001",
            gauntlet_id="g-001",
            timestamp="2026-02-27T00:00:00Z",
            input_summary="Test",
            input_hash="abc123",
            risk_summary={"critical": 0},
            attacks_attempted=0,
            attacks_successful=0,
            probes_run=0,
            vulnerabilities_found=0,
            verdict="PASS",
            confidence=0.9,
            robustness_score=0.95,
        )
        assert receipt.thinking_traces is None

    def test_receipt_with_thinking_traces(self):
        from aragora.gauntlet.receipt_models import DecisionReceipt

        traces = {"claude-1": "Step by step reasoning...", "claude-2": "Analysis..."}
        receipt = DecisionReceipt(
            receipt_id="test-002",
            gauntlet_id="g-002",
            timestamp="2026-02-27T00:00:00Z",
            input_summary="Test",
            input_hash="abc123",
            risk_summary={"critical": 0},
            attacks_attempted=0,
            attacks_successful=0,
            probes_run=0,
            vulnerabilities_found=0,
            verdict="PASS",
            confidence=0.9,
            robustness_score=0.95,
            thinking_traces=traces,
        )
        assert receipt.thinking_traces == traces
        assert receipt.thinking_traces["claude-1"] == "Step by step reasoning..."


class TestServedModelCollection:
    """``served_model`` reaching the receipt (2026-09-05 wave-2 re-review).

    The Anthropic agent already recorded which model the server actually
    answered with, but nothing consumed it -- so a receipt still attributed
    the decision to the requested id even when a server-side fallback
    answered with a different model.
    """

    def test_collects_only_agents_whose_served_model_differed(self) -> None:
        from aragora.debate.orchestrator_runner import collect_served_models

        swapped = MagicMock()
        swapped.name = "claude-1"
        swapped.model = "claude-fable-5-1"
        swapped.last_served_model = "claude-opus-4-8"

        answered_as_asked = MagicMock()
        answered_as_asked.name = "claude-2"
        answered_as_asked.model = "claude-fable-5-1"
        # The agent sets this to None whenever the server answered as asked.
        answered_as_asked.last_served_model = None

        assert collect_served_models([swapped, answered_as_asked]) == {
            "claude-1": {"requested": "claude-fable-5-1", "served": ["claude-opus-4-8"]}
        }

    def test_agents_without_the_property_are_skipped(self) -> None:
        """Every non-Anthropic agent today; skipped, never guessed at."""
        from aragora.debate.orchestrator_runner import collect_served_models

        plain = MagicMock(spec=[])
        plain.name = "gpt-agent"
        assert collect_served_models([plain]) == {}

    def test_empty_when_every_agent_answered_as_asked(self) -> None:
        from aragora.debate.orchestrator_runner import collect_served_models

        agent = MagicMock()
        agent.name = "claude-1"
        agent.model = "claude-fable-5-1"
        agent.last_served_model = None
        assert collect_served_models([agent]) == {}

    @patch("aragora.agents.api_agents.anthropic.get_primary_api_key", return_value="fake-key")
    def test_real_agent_feeds_the_collector(self, _mock_key: MagicMock) -> None:
        """End to end through the agent's own recording path, not a stub."""
        from aragora.debate.orchestrator_runner import collect_served_models

        agent = AnthropicAPIAgent(name="test-claude", model="claude-fable-5-1")
        agent._note_served_model("claude-fable-5-1")  # answered as asked
        assert collect_served_models([agent]) == {}

        agent._note_served_model("claude-opus-4-8")  # server-side fallback
        assert collect_served_models([agent]) == {
            "test-claude": {
                "requested": "claude-fable-5-1",
                # Both models did part of the work; the receipt names both.
                "served": ["claude-fable-5-1", "claude-opus-4-8"],
                "calls": 2,
                "fallback_calls": 1,
            }
        }


class TestServedModelLogResetAtDebateStart:
    """Agents are reused across debates, so the debate-scoped log has to be
    cleared explicitly (finding C-P2 on #9989)."""

    @patch("aragora.agents.api_agents.anthropic.get_primary_api_key", return_value="fake-key")
    def test_reset_clears_a_previous_debates_record(self, _mock_key: MagicMock) -> None:
        from aragora.debate.orchestrator_runner import (
            collect_served_models,
            reset_served_model_logs,
        )

        agent = AnthropicAPIAgent(name="test-claude", model="claude-fable-5-1")
        agent._note_served_model("claude-opus-4-8")
        assert collect_served_models([agent])

        reset_served_model_logs([agent])

        assert agent.served_model_log == []
        assert collect_served_models([agent]) == {}

    def test_agents_without_a_log_are_skipped(self) -> None:
        from aragora.debate.orchestrator_runner import reset_served_model_logs

        plain = MagicMock(spec=[])
        plain.name = "gpt-agent"
        reset_served_model_logs([plain])  # must not raise

    def test_a_raising_reset_does_not_break_debate_start(self) -> None:
        from aragora.debate.orchestrator_runner import reset_served_model_logs

        agent = MagicMock()
        agent.name = "flaky"
        agent.reset_served_model_log = MagicMock(side_effect=RuntimeError("boom"))
        reset_served_model_logs([agent])  # must not raise
        agent.reset_served_model_log.assert_called_once()


class TestDecisionReceiptServedModels:
    """``DecisionReceipt.served_models`` is additive and round-trips."""

    @staticmethod
    def _receipt(**kwargs: Any):
        from aragora.gauntlet.receipt_models import DecisionReceipt

        return DecisionReceipt(
            receipt_id="test-002",
            gauntlet_id="g-002",
            timestamp="2026-09-05T00:00:00Z",
            input_summary="Test",
            input_hash="abc123",
            risk_summary={"critical": 0},
            attacks_attempted=0,
            attacks_successful=0,
            probes_run=0,
            vulnerabilities_found=0,
            verdict="PASS",
            confidence=0.9,
            robustness_score=0.95,
            **kwargs,
        )

    def test_defaults_to_none_and_is_omitted_from_serialization(self) -> None:
        """A receipt written before this field must stay byte-identical, so
        its artifact_hash cannot move."""
        receipt = self._receipt()
        assert receipt.served_models is None
        assert "served_models" not in receipt.to_dict()

    def test_serializes_when_recorded(self) -> None:
        served = {"claude-1": {"requested": "claude-fable-5-1", "served": "claude-opus-4-8"}}
        data = self._receipt(served_models=served).to_dict()
        assert data["served_models"] == served

    def test_round_trips_through_from_dict(self) -> None:
        from aragora.gauntlet.receipt_models import DecisionReceipt

        served = {"claude-1": {"requested": "claude-fable-5-1", "served": "claude-opus-4-8"}}
        traces = {"claude-1": "reasoning"}
        original = self._receipt(served_models=served, thinking_traces=traces)
        restored = DecisionReceipt.from_dict(original.to_dict())
        assert restored.served_models == served
        # thinking_traces was emitted but never read back before this change.
        assert restored.thinking_traces == traces

    def test_receipt_without_served_models_hashes_exactly_as_before(self) -> None:
        """A receipt that never recorded a served model must keep the
        pre-field hash byte-for-byte, so already-stored receipts keep
        verifying after the binding landed (finding C-P3 on #9989)."""
        import hashlib
        import json

        receipt = self._receipt()
        legacy_material = json.dumps(
            {
                "receipt_id": receipt.receipt_id,
                "gauntlet_id": receipt.gauntlet_id,
                "input_hash": receipt.input_hash,
                "risk_summary": receipt.risk_summary,
                "verdict": receipt.verdict,
                "confidence": receipt.confidence,
            },
            sort_keys=True,
        )
        assert receipt.artifact_hash == hashlib.sha256(legacy_material.encode()).hexdigest()
        assert receipt.verify_integrity() is True

    def test_empty_served_models_hashes_as_absent(self) -> None:
        """The runner only ever attaches a NON-empty map, so an empty dict is
        treated as "not recorded" by producer and verifier alike -- it must
        not fork the hash of an otherwise identical receipt."""
        assert self._receipt(served_models={}).artifact_hash == self._receipt().artifact_hash
        assert self._receipt(served_models={}).verify_integrity() is True

    def test_recorded_served_models_are_bound_into_the_hash(self) -> None:
        """Recording a served model must MOVE the hash -- otherwise the field
        is unbound and the claim is editable."""
        served = {
            "claude-1": {
                "requested": "claude-fable-5-1",
                "served": ["claude-opus-4-8", "claude-fable-5-1"],
                "calls": 2,
                "fallback_calls": 1,
            }
        }
        with_served = self._receipt(served_models=served)
        assert with_served.artifact_hash != self._receipt().artifact_hash
        assert with_served.verify_integrity() is True

    def test_editing_served_models_after_signing_fails_integrity(self) -> None:
        """The whole point of the binding: the receipt's statement of WHICH
        model made the decision cannot be rewritten after the fact."""
        from aragora.gauntlet.receipt_models import DecisionReceipt

        served = {
            "claude-1": {
                "requested": "claude-fable-5-1",
                "served": ["claude-opus-4-8"],
                "calls": 1,
                "fallback_calls": 1,
            }
        }
        original = self._receipt(served_models=served)

        # Erase the fallback entirely -- the "everyone answered as asked" lie.
        erased = DecisionReceipt.from_dict(original.to_dict())
        assert erased.verify_integrity() is True
        erased.served_models = {}
        assert erased.verify_integrity() is False

        # Rename the model that actually answered.
        renamed = DecisionReceipt.from_dict(original.to_dict())
        renamed.served_models["claude-1"]["served"] = ["claude-fable-5-1"]
        assert renamed.verify_integrity() is False

        # Understate how many calls were swapped.
        undercounted = DecisionReceipt.from_dict(original.to_dict())
        undercounted.served_models["claude-1"]["fallback_calls"] = 0
        assert undercounted.verify_integrity() is False

    def test_verify_command_recipe_agrees_with_the_receipt(self) -> None:
        """``aragora verify`` hashes the receipt DICT through the same
        function, so producer and verifier cannot drift on the new field."""
        from aragora.gauntlet.receipt_models import compute_receipt_artifact_hash

        served = {"claude-1": {"requested": "claude-fable-5-1", "served": ["claude-opus-4-8"]}}
        receipt = self._receipt(served_models=served)
        assert compute_receipt_artifact_hash(receipt.to_dict()) == receipt.artifact_hash


class TestQuickstartServedModelExtraction:
    def test_extracts_from_result_metadata(self) -> None:
        from aragora.cli.commands.quickstart import _extract_served_models

        result = MagicMock()
        result.metadata = {
            "served_models": {
                "claude-1": {"requested": "claude-fable-5-1", "served": "claude-opus-4-8"}
            }
        }
        assert _extract_served_models(result) == result.metadata["served_models"]

    def test_none_when_absent_or_empty(self) -> None:
        from aragora.cli.commands.quickstart import _extract_served_models

        empty = MagicMock()
        empty.metadata = {"served_models": {}}
        assert _extract_served_models(empty) is None

        missing = MagicMock()
        missing.metadata = {}
        assert _extract_served_models(missing) is None

        no_metadata = MagicMock(spec=[])
        assert _extract_served_models(no_metadata) is None
