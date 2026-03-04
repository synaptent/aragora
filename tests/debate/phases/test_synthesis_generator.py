"""
Tests for synthesis generator module.

Tests cover:
- SynthesisGenerator class
- Mandatory synthesis generation
- LLM fallback chain (Opus -> Sonnet -> combined)
- Synthesis prompt building
- Export link generation
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.debate.phases.synthesis_generator import SynthesisGenerator


@dataclass
class MockResult:
    """Mock debate result."""

    final_answer: str = ""
    synthesis: str = ""
    winner: str = ""
    confidence: float = 0.8
    export_links: dict = field(default_factory=dict)


@dataclass
class MockEnv:
    """Mock environment."""

    task: str = "What is the best approach to testing?"


@dataclass
class MockCritique:
    """Mock critique."""

    agent: str = "critic1"
    target: str = "proposer1"
    summary: str = "Good points but misses edge cases"


@dataclass
class MockDebateContext:
    """Mock debate context."""

    result: MockResult = field(default_factory=MockResult)
    env: MockEnv = field(default_factory=MockEnv)
    proposals: dict = field(default_factory=dict)
    critiques: list = field(default_factory=list)
    context_messages: list = field(default_factory=list)
    debate_id: str = "test-debate-456"


class TestSynthesisGenerator:
    """Tests for SynthesisGenerator class."""

    def test_init_defaults(self):
        """Generator initializes with defaults."""
        gen = SynthesisGenerator()

        assert gen.protocol is None
        assert gen.hooks == {}
        assert gen._notify_spectator is None

    def test_init_with_dependencies(self):
        """Generator stores injected dependencies."""
        protocol = MagicMock()
        hooks = {"on_synthesis": MagicMock()}
        notify = MagicMock()

        gen = SynthesisGenerator(
            protocol=protocol,
            hooks=hooks,
            notify_spectator=notify,
        )

        assert gen.protocol is protocol
        assert gen.hooks is hooks
        assert gen._notify_spectator is notify


class TestSynthesisContinuationGuards:
    """Tests for synthesis truncation detection and continuation."""

    def test_is_likely_truncated_detects_common_markers(self):
        gen = SynthesisGenerator()
        assert gen._is_likely_truncated("This ended with ellipsis...")
        assert gen._is_likely_truncated('```json\n{"a": 1}\n')
        assert gen._is_likely_truncated("Section:\n")

    def test_is_likely_truncated_allows_complete_text(self):
        gen = SynthesisGenerator()
        assert gen._is_likely_truncated("Complete sentence.") is False

    @pytest.mark.asyncio
    async def test_ensure_complete_synthesis_appends_continuation(self):
        import aragora.debate.phases.synthesis_generator as synth_mod

        gen = SynthesisGenerator()
        ctx = MockDebateContext()
        synthesizer = AsyncMock()
        synthesizer.generate = AsyncMock(return_value="Final recommendation complete.")

        with patch.object(synth_mod, "_SYNTHESIS_CONTINUATION_ATTEMPTS", 1):
            completed = await gen._ensure_complete_synthesis(
                ctx=ctx,
                synthesizer=synthesizer,
                synthesis="Partial recommendation:",
                source="opus",
            )

        assert "Partial recommendation:" in completed
        assert "Final recommendation complete." in completed
        synthesizer.generate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ensure_complete_synthesis_skips_when_complete(self):
        gen = SynthesisGenerator()
        ctx = MockDebateContext()
        synthesizer = AsyncMock()

        completed = await gen._ensure_complete_synthesis(
            ctx=ctx,
            synthesizer=synthesizer,
            synthesis="Complete output.",
            source="opus",
        )

        assert completed == "Complete output."
        synthesizer.generate.assert_not_called()


class TestBuildSynthesisPrompt:
    """Tests for _build_synthesis_prompt method."""

    def test_prompt_includes_task(self):
        """Prompt includes the debate task."""
        ctx = MockDebateContext()
        ctx.env.task = "Should we use microservices?"

        gen = SynthesisGenerator()
        prompt = gen._build_synthesis_prompt(ctx)

        assert "Should we use microservices?" in prompt

    def test_prompt_includes_proposals(self):
        """Prompt includes agent proposals."""
        ctx = MockDebateContext()
        ctx.proposals = {
            "claude": "Use monolith for simplicity",
            "gpt4": "Microservices for scalability",
        }

        gen = SynthesisGenerator()
        prompt = gen._build_synthesis_prompt(ctx)

        assert "claude" in prompt
        assert "Use monolith for simplicity" in prompt
        assert "gpt4" in prompt
        assert "Microservices for scalability" in prompt

    def test_prompt_includes_critiques(self):
        """Prompt includes critiques when available."""
        ctx = MockDebateContext()
        ctx.proposals = {"agent1": "Proposal"}
        ctx.critiques = [MockCritique()]

        gen = SynthesisGenerator()
        prompt = gen._build_synthesis_prompt(ctx)

        assert "critic1" in prompt
        assert "proposer1" in prompt

    def test_prompt_handles_empty_critiques(self):
        """Prompt handles missing critiques."""
        ctx = MockDebateContext()
        ctx.proposals = {"agent1": "Proposal"}
        ctx.critiques = []

        gen = SynthesisGenerator()
        prompt = gen._build_synthesis_prompt(ctx)

        assert "No critiques recorded" in prompt

    def test_prompt_truncates_long_proposals(self):
        """Long proposals are truncated."""
        ctx = MockDebateContext()
        ctx.proposals = {"agent1": "x" * 5000}

        gen = SynthesisGenerator()
        prompt = gen._build_synthesis_prompt(ctx)

        # Proposal should be truncated to ~1500 chars; total prompt includes
        # repo path hints (~12K) plus base template, so verify the full 5000-
        # char proposal is not present (i.e. it was actually truncated).
        assert "x" * 5000 not in prompt


class TestCombineProposalsAsSynthesis:
    """Tests for _combine_proposals_as_synthesis method."""

    def test_synthesis_with_winner(self):
        """Synthesis prioritizes winner when available."""
        ctx = MockDebateContext()
        ctx.proposals = {
            "winner": "Winning proposal text",
            "loser": "Losing proposal text",
        }
        ctx.result.winner = "winner"

        gen = SynthesisGenerator()
        synthesis = gen._combine_proposals_as_synthesis(ctx)

        assert "Winning Position (winner)" in synthesis
        assert "Winning proposal text" in synthesis
        assert "Other Perspectives" in synthesis

    def test_synthesis_without_winner(self):
        """Synthesis combines all when no winner."""
        ctx = MockDebateContext()
        ctx.proposals = {
            "agent1": "First proposal",
            "agent2": "Second proposal",
        }
        ctx.result.winner = None

        gen = SynthesisGenerator()
        synthesis = gen._combine_proposals_as_synthesis(ctx)

        assert "Combined Perspectives" in synthesis
        assert "First proposal" in synthesis
        assert "Second proposal" in synthesis

    def test_synthesis_includes_task(self):
        """Synthesis includes the debate question."""
        ctx = MockDebateContext()
        ctx.env.task = "What is the meaning of life?"
        ctx.proposals = {"agent1": "42"}

        gen = SynthesisGenerator()
        synthesis = gen._combine_proposals_as_synthesis(ctx)

        assert "What is the meaning of life?" in synthesis

    def test_synthesis_truncates_long_proposals(self):
        """Long proposals are truncated in synthesis."""
        ctx = MockDebateContext()
        ctx.proposals = {"agent1": "x" * 10000}
        ctx.result.winner = "agent1"

        gen = SynthesisGenerator()
        synthesis = gen._combine_proposals_as_synthesis(ctx)

        # Winner truncated to 2000, others to 500
        assert len(synthesis) < 8000


class TestGenerateExportLinks:
    """Tests for _generate_export_links method."""

    def test_links_generated_with_debate_id(self):
        """Export links generated when debate_id available."""
        ctx = MockDebateContext()
        ctx.debate_id = "debate-123"

        gen = SynthesisGenerator()
        gen._generate_export_links(ctx)

        assert "json" in ctx.result.export_links
        assert "markdown" in ctx.result.export_links
        assert "html" in ctx.result.export_links
        assert "txt" in ctx.result.export_links
        assert "csv_summary" in ctx.result.export_links
        assert "csv_messages" in ctx.result.export_links

    def test_links_include_debate_id(self):
        """Links include the debate ID."""
        ctx = MockDebateContext()
        ctx.debate_id = "my-debate-id"

        gen = SynthesisGenerator()
        gen._generate_export_links(ctx)

        assert "my-debate-id" in ctx.result.export_links["json"]

    def test_no_links_without_debate_id(self):
        """No links generated without debate_id."""
        ctx = MockDebateContext()
        ctx.debate_id = None

        gen = SynthesisGenerator()
        gen._generate_export_links(ctx)

        assert ctx.result.export_links == {}

    def test_export_ready_hook_called(self):
        """on_export_ready hook is called."""
        ctx = MockDebateContext()
        ctx.debate_id = "debate-123"
        hook = MagicMock()

        gen = SynthesisGenerator(hooks={"on_export_ready": hook})
        gen._generate_export_links(ctx)

        hook.assert_called_once()
        call_kwargs = hook.call_args[1]
        assert call_kwargs["debate_id"] == "debate-123"


class TestEmitSynthesisEvents:
    """Tests for _emit_synthesis_events method."""

    def test_on_synthesis_hook_called(self):
        """on_synthesis hook is called with content."""
        ctx = MockDebateContext()
        hook = MagicMock()

        gen = SynthesisGenerator(hooks={"on_synthesis": hook})
        gen._emit_synthesis_events(ctx, "Synthesis text", "opus")

        hook.assert_called_once()
        assert hook.call_args[1]["content"] == "Synthesis text"

    def test_on_message_hook_called(self):
        """on_message hook is called for backwards compat."""
        ctx = MockDebateContext()
        hook = MagicMock()
        protocol = MagicMock(rounds=3)

        gen = SynthesisGenerator(hooks={"on_message": hook}, protocol=protocol)
        gen._emit_synthesis_events(ctx, "Synthesis text", "opus")

        hook.assert_called_once()
        call_kwargs = hook.call_args[1]
        assert call_kwargs["agent"] == "synthesis-agent"
        assert call_kwargs["role"] == "synthesis"
        assert call_kwargs["round_num"] == 4  # rounds + 1

    def test_spectator_notified(self):
        """Spectator is notified of synthesis."""
        ctx = MockDebateContext()
        ctx.result.confidence = 0.9
        notify = MagicMock()

        gen = SynthesisGenerator(notify_spectator=notify)
        gen._emit_synthesis_events(ctx, "Synthesis text", "sonnet")

        notify.assert_called_once()
        call_kwargs = notify.call_args[1]
        assert "synthesis" in str(notify.call_args)

    def test_hook_errors_handled(self):
        """Hook errors are handled gracefully."""
        ctx = MockDebateContext()
        bad_hook = MagicMock(side_effect=RuntimeError("Hook error"))

        gen = SynthesisGenerator(hooks={"on_synthesis": bad_hook})

        # Should not raise
        gen._emit_synthesis_events(ctx, "Text", "opus")


class TestContractGuidedDefault:
    """Tests that contract-guided synthesis is the default path."""

    def test_contract_guided_default_without_explicit_contract(self):
        """Synthesis uses contract-guided structure even when no contract is in the task."""
        ctx = MockDebateContext()
        ctx.env.task = "Should we use microservices or monolith?"
        ctx.proposals = {
            "claude": "Use monolith for simplicity",
            "gpt4": "Microservices for scalability",
        }
        ctx.critiques = []

        gen = SynthesisGenerator()
        prompt = gen._build_synthesis_prompt(ctx)

        # Contract-guided prompt markers (from _build_contract_guided_prompt)
        assert "OUTPUT FORMAT REQUIREMENTS (MANDATORY)" in prompt
        assert "Ranked High-Level Tasks" in prompt
        assert "Gate Criteria" in prompt
        assert "JSON Payload" in prompt
        # Should NOT contain the default synthesis prompt markers
        assert "approximately 1200 words" not in prompt
        assert "DEFINITIVE ANSWER" not in prompt

    def test_contract_guided_default_still_uses_explicit_contract(self):
        """When an explicit contract is in the context, it is used instead of the default."""
        ctx = MockDebateContext()
        ctx.env = MagicMock()
        ctx.env.task = "Design a rate limiter"
        ctx.env.context = (
            "Some preamble.\n"
            "### Output Contract (Deterministic Quality Gates)\n"
            "Required sections:\n"
            "1. Custom Section A\n"
            "2. Custom Section B\n"
        )
        ctx.proposals = {"agent1": "Proposal text"}
        ctx.critiques = []

        gen = SynthesisGenerator()
        prompt = gen._build_synthesis_prompt(ctx)

        assert "Custom Section A" in prompt
        assert "Custom Section B" in prompt
        assert "OUTPUT FORMAT REQUIREMENTS (MANDATORY)" in prompt

    def test_default_output_contract_content(self):
        """The default output contract contains the expected required sections."""
        contract = SynthesisGenerator._default_output_contract()

        assert "Output Contract (Deterministic Quality Gates)" in contract
        assert "Ranked High-Level Tasks" in contract
        assert "Suggested Subtasks" in contract
        assert "Owner module / file paths" in contract
        assert "Test Plan" in contract
        assert "Rollback Plan" in contract
        assert "Gate Criteria" in contract
        assert "JSON Payload" in contract


class TestGenerateMandatorySynthesis:
    """Tests for generate_mandatory_synthesis method."""

    @pytest.mark.asyncio
    async def test_no_proposals_generates_fallback_synthesis(self):
        """When no proposals, generates fallback synthesis instead of returning False."""
        ctx = MockDebateContext()
        ctx.proposals = {}

        gen = SynthesisGenerator()
        result = await gen.generate_mandatory_synthesis(ctx)

        # Now returns True with fallback synthesis (avoids silent endings)
        assert result is True
        assert "No proposals were generated" in ctx.result.synthesis
        assert ctx.result.final_answer == ctx.result.synthesis

    @pytest.mark.asyncio
    async def test_synthesis_stored_in_result(self):
        """Synthesis is stored in result."""
        ctx = MockDebateContext()
        ctx.proposals = {"agent1": "Proposal"}

        gen = SynthesisGenerator()

        with (
            patch("aragora.utils.env.is_offline_mode", return_value=False),
            patch("aragora.agents.api_agents.anthropic.AnthropicAPIAgent") as mock_agent_class,
        ):
            mock_agent = AsyncMock()
            mock_agent.generate = AsyncMock(return_value="Generated synthesis")
            mock_agent_class.return_value = mock_agent

            result = await gen.generate_mandatory_synthesis(ctx)

        assert result is True
        assert ctx.result.synthesis == "Generated synthesis"
        assert ctx.result.final_answer == "Generated synthesis"

    @pytest.mark.asyncio
    async def test_opus_timeout_falls_back_to_sonnet(self):
        """Timeout on Opus falls back to Sonnet."""
        ctx = MockDebateContext()
        ctx.proposals = {"agent1": "Proposal"}

        gen = SynthesisGenerator()

        call_count = 0

        async def mock_generate(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise asyncio.TimeoutError()
            return "Sonnet synthesis"

        with (
            patch("aragora.utils.env.is_offline_mode", return_value=False),
            patch("aragora.agents.api_agents.anthropic.AnthropicAPIAgent") as mock_agent_class,
        ):
            mock_agent = MagicMock()
            mock_agent.generate = mock_generate
            mock_agent_class.return_value = mock_agent

            result = await gen.generate_mandatory_synthesis(ctx)

        assert result is True
        assert "Sonnet synthesis" in ctx.result.synthesis

    @pytest.mark.asyncio
    async def test_import_error_falls_back_to_combined(self):
        """Import error falls back to combined proposals."""
        ctx = MockDebateContext()
        ctx.proposals = {"agent1": "Proposal"}
        ctx.env.task = "Test question"

        gen = SynthesisGenerator()

        # Patch the import to raise ImportError
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if "anthropic" in name:
                raise ImportError("No module")
            return original_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=mock_import):
            result = await gen.generate_mandatory_synthesis(ctx)

        assert result is True
        # Should have some synthesis (combined fallback)
        assert ctx.result.synthesis != ""

    @pytest.mark.asyncio
    async def test_all_llm_failures_use_combined(self):
        """All LLM failures fall back to combined proposals."""
        ctx = MockDebateContext()
        ctx.proposals = {"agent1": "Proposal 1", "agent2": "Proposal 2"}
        ctx.env.task = "Test question"

        gen = SynthesisGenerator()

        with patch("aragora.agents.api_agents.anthropic.AnthropicAPIAgent") as mock_agent_class:
            mock_agent_class.side_effect = RuntimeError("All agents failed")

            result = await gen.generate_mandatory_synthesis(ctx)

        assert result is True
        assert (
            "Combined Perspectives" in ctx.result.synthesis
            or "Final Synthesis" in ctx.result.synthesis
        )

    @pytest.mark.asyncio
    async def test_export_links_generated(self):
        """Export links are generated after synthesis."""
        ctx = MockDebateContext()
        ctx.proposals = {"agent1": "Proposal"}
        ctx.debate_id = "debate-789"

        gen = SynthesisGenerator()

        with patch("aragora.agents.api_agents.anthropic.AnthropicAPIAgent") as mock_agent_class:
            mock_agent = AsyncMock()
            mock_agent.generate = AsyncMock(return_value="Synthesis")
            mock_agent_class.return_value = mock_agent

            await gen.generate_mandatory_synthesis(ctx)

        assert "json" in ctx.result.export_links
        assert "debate-789" in ctx.result.export_links["json"]

    @pytest.mark.asyncio
    async def test_synthesis_events_emitted(self):
        """Synthesis events are emitted."""
        ctx = MockDebateContext()
        ctx.proposals = {"agent1": "Proposal"}
        on_synthesis = MagicMock()

        gen = SynthesisGenerator(hooks={"on_synthesis": on_synthesis})

        with patch("aragora.agents.api_agents.anthropic.AnthropicAPIAgent") as mock_agent_class:
            mock_agent = AsyncMock()
            mock_agent.generate = AsyncMock(return_value="Synthesis")
            mock_agent_class.return_value = mock_agent

            await gen.generate_mandatory_synthesis(ctx)

        on_synthesis.assert_called_once()
