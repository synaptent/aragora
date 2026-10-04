"""
Tests for aragora.debate.phases.proposal_phase module.

Tests ProposalPhase class and parallel proposal generation.
"""

import pytest
from dataclasses import dataclass, field
from typing import Optional
from unittest.mock import MagicMock, AsyncMock

from aragora.debate.context import DebateContext
from aragora.debate.phases.proposal_phase import ProposalPhase


# ============================================================================
# Mock Classes
# ============================================================================


@dataclass
class MockEnvironment:
    """Mock environment for testing."""

    task: str = "Test task"
    context: str = ""


@dataclass
class MockAgent:
    """Mock agent for testing."""

    name: str = "test_agent"
    role: str = "proposer"


@dataclass
class MockDebateResult:
    """Mock debate result for testing."""

    id: str = "debate_001"
    messages: list = field(default_factory=list)


# ============================================================================
# ProposalPhase Construction Tests
# ============================================================================


class TestProposalPhaseConstruction:
    """Tests for ProposalPhase construction."""

    def test_minimal_construction(self):
        """Should create with no arguments."""
        phase = ProposalPhase()
        assert phase.circuit_breaker is None
        assert phase.hooks == {}

    def test_full_construction(self):
        """Should create with all arguments."""
        cb = MagicMock()
        hooks = {"on_message": MagicMock()}

        phase = ProposalPhase(
            circuit_breaker=cb,
            hooks=hooks,
            recorder=MagicMock(),
        )

        assert phase.circuit_breaker is cb
        assert "on_message" in phase.hooks


# ============================================================================
# Circuit Breaker Tests
# ============================================================================


class TestCircuitBreakerFiltering:
    """Tests for circuit breaker filtering."""

    @pytest.mark.asyncio
    async def test_filter_proposers(self):
        """Should filter proposers through circuit breaker."""
        cb = MagicMock()
        available = [MockAgent(name="claude")]
        cb.filter_available_agents.return_value = available

        phase = ProposalPhase(
            circuit_breaker=cb,
            build_proposal_prompt=MagicMock(return_value="prompt"),
            generate_with_agent=AsyncMock(return_value="proposal"),
        )

        proposers = [MockAgent(name="claude"), MockAgent(name="gpt4")]
        ctx = DebateContext(env=MockEnvironment(), proposers=proposers)
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        cb.filter_available_agents.assert_called_once()

    @pytest.mark.asyncio
    async def test_circuit_breaker_error_fallback(self):
        """Should fall back to all proposers on error."""
        cb = MagicMock()
        cb.filter_available_agents.side_effect = RuntimeError("CB error")

        phase = ProposalPhase(
            circuit_breaker=cb,
            build_proposal_prompt=MagicMock(return_value="prompt"),
            generate_with_agent=AsyncMock(return_value="proposal"),
        )

        proposers = [MockAgent(name="claude")]
        ctx = DebateContext(env=MockEnvironment(), proposers=proposers)
        ctx.result = MockDebateResult()

        # Should not raise
        await phase.execute(ctx)

    @pytest.mark.asyncio
    async def test_record_success_on_proposal(self):
        """Should record success on successful proposal."""
        cb = MagicMock()
        cb.filter_available_agents.return_value = [MockAgent(name="claude")]

        phase = ProposalPhase(
            circuit_breaker=cb,
            build_proposal_prompt=MagicMock(return_value="prompt"),
            generate_with_agent=AsyncMock(return_value="proposal"),
        )

        ctx = DebateContext(
            env=MockEnvironment(),
            proposers=[MockAgent(name="claude")],
        )
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        cb.record_success.assert_called_with("claude")

    @pytest.mark.asyncio
    async def test_record_failure_on_error(self):
        """Should record failure on proposal error."""
        cb = MagicMock()
        cb.filter_available_agents.return_value = [MockAgent(name="claude")]

        phase = ProposalPhase(
            circuit_breaker=cb,
            build_proposal_prompt=MagicMock(return_value="prompt"),
            generate_with_agent=AsyncMock(side_effect=Exception("Error")),
        )

        ctx = DebateContext(
            env=MockEnvironment(),
            proposers=[MockAgent(name="claude")],
        )
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        cb.record_failure.assert_called_with("claude")


# ============================================================================
# Parallel Generation Tests
# ============================================================================


class TestParallelGeneration:
    """Tests for parallel proposal generation."""

    @pytest.mark.asyncio
    async def test_generate_multiple_proposals(self):
        """Should generate proposals from multiple agents."""
        generate = AsyncMock(side_effect=["Proposal A", "Proposal B"])

        phase = ProposalPhase(
            build_proposal_prompt=MagicMock(return_value="prompt"),
            generate_with_agent=generate,
        )

        proposers = [MockAgent(name="claude"), MockAgent(name="gpt4")]
        ctx = DebateContext(env=MockEnvironment(), proposers=proposers)
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        assert len(ctx.proposals) == 2
        assert "claude" in ctx.proposals or "gpt4" in ctx.proposals

    @pytest.mark.asyncio
    async def test_handle_partial_failures(self):
        """Should continue on partial failures."""

        async def generate_side_effect(agent, prompt, context):
            if agent.name == "claude":
                return "Proposal"
            raise Exception("Agent error")

        phase = ProposalPhase(
            build_proposal_prompt=MagicMock(return_value="prompt"),
            generate_with_agent=generate_side_effect,
        )

        proposers = [MockAgent(name="claude"), MockAgent(name="gpt4")]
        ctx = DebateContext(env=MockEnvironment(), proposers=proposers)
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        # Both should have entries (one success, one error)
        assert len(ctx.proposals) == 2
        assert "[Error" in ctx.proposals.get("gpt4", "")

    @pytest.mark.asyncio
    async def test_timeout_wrapper(self):
        """Should use timeout wrapper when provided."""
        with_timeout = AsyncMock(return_value="proposal")

        phase = ProposalPhase(
            build_proposal_prompt=MagicMock(return_value="prompt"),
            generate_with_agent=AsyncMock(),
            with_timeout=with_timeout,
        )

        proposers = [MockAgent(name="claude")]
        ctx = DebateContext(env=MockEnvironment(), proposers=proposers)
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        with_timeout.assert_called()

    @pytest.mark.asyncio
    async def test_explicit_proposal_timeout_overrides_agent_only_in_this_phase(self):
        seen_timeouts = []

        async def with_timeout(awaitable, _agent_name, *, timeout_seconds):
            seen_timeouts.append(timeout_seconds)
            return await awaitable

        agent = MockAgent(name="claude")
        agent.timeout = 999.0
        phase = ProposalPhase(
            build_proposal_prompt=MagicMock(return_value="prompt"),
            generate_with_agent=AsyncMock(return_value="proposal"),
            with_timeout=with_timeout,
            proposal_timeout_seconds=37.0,
        )
        ctx = DebateContext(env=MockEnvironment(), proposers=[agent])
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        assert seen_timeouts == [37.0]
        assert agent.timeout == 999.0


# ============================================================================
# Message and Event Tests
# ============================================================================


class TestMessageEvents:
    """Tests for message and event emission."""

    @pytest.mark.asyncio
    async def test_add_messages_to_context(self):
        """Should add messages to context."""
        phase = ProposalPhase(
            build_proposal_prompt=MagicMock(return_value="prompt"),
            generate_with_agent=AsyncMock(return_value="proposal"),
        )

        proposers = [MockAgent(name="claude")]
        ctx = DebateContext(env=MockEnvironment(), proposers=proposers)
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        assert len(ctx.context_messages) == 1
        assert ctx.context_messages[0].agent == "claude"
        assert ctx.context_messages[0].role == "proposer"

    @pytest.mark.asyncio
    async def test_emit_on_message_hook(self):
        """Should emit on_message hook."""
        on_message = MagicMock()

        phase = ProposalPhase(
            build_proposal_prompt=MagicMock(return_value="prompt"),
            generate_with_agent=AsyncMock(return_value="proposal"),
            hooks={"on_message": on_message},
        )

        proposers = [MockAgent(name="claude")]
        ctx = DebateContext(env=MockEnvironment(), proposers=proposers)
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        on_message.assert_called()
        call_kwargs = on_message.call_args[1]
        assert call_kwargs["agent"] == "claude"
        assert call_kwargs["role"] == "proposer"

    @pytest.mark.asyncio
    async def test_emit_debate_start_hook(self):
        """Should emit on_debate_start hook."""
        on_start = MagicMock()

        phase = ProposalPhase(
            build_proposal_prompt=MagicMock(return_value="prompt"),
            generate_with_agent=AsyncMock(return_value="proposal"),
            hooks={"on_debate_start": on_start},
        )

        agents = [MockAgent(name="claude")]
        ctx = DebateContext(env=MockEnvironment(), agents=agents, proposers=agents)
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        on_start.assert_called_once()

    @pytest.mark.asyncio
    async def test_notify_spectator(self):
        """Should notify spectator of proposals."""
        notify = MagicMock()

        phase = ProposalPhase(
            build_proposal_prompt=MagicMock(return_value="prompt"),
            generate_with_agent=AsyncMock(return_value="proposal text"),
            notify_spectator=notify,
        )

        proposers = [MockAgent(name="claude")]
        ctx = DebateContext(env=MockEnvironment(), proposers=proposers)
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        # Should be called for debate_start and propose
        assert notify.call_count >= 2


# ============================================================================
# Position Tracking Tests
# ============================================================================


class TestPositionTracking:
    """Tests for position tracking."""

    @pytest.mark.asyncio
    async def test_record_position(self):
        """Should record position for personas."""
        position_tracker = MagicMock()

        phase = ProposalPhase(
            position_tracker=position_tracker,
            build_proposal_prompt=MagicMock(return_value="prompt"),
            generate_with_agent=AsyncMock(return_value="proposal"),
        )

        proposers = [MockAgent(name="claude")]
        ctx = DebateContext(
            env=MockEnvironment(),
            proposers=proposers,
            debate_id="debate_001",
        )
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        position_tracker.record_position.assert_called_once()
        call_kwargs = position_tracker.record_position.call_args[1]
        assert call_kwargs["agent_name"] == "claude"
        assert call_kwargs["position_type"] == "proposal"

    @pytest.mark.asyncio
    async def test_record_grounded_position(self):
        """Should call grounded position callback."""
        record_grounded = MagicMock()

        phase = ProposalPhase(
            build_proposal_prompt=MagicMock(return_value="prompt"),
            generate_with_agent=AsyncMock(return_value="proposal"),
            record_grounded_position=record_grounded,
        )

        proposers = [MockAgent(name="claude")]
        ctx = DebateContext(
            env=MockEnvironment(),
            proposers=proposers,
            debate_id="debate_001",
        )
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        record_grounded.assert_called_once()


# ============================================================================
# Recorder Tests
# ============================================================================


class TestRecorder:
    """Tests for replay recorder."""

    @pytest.mark.asyncio
    async def test_record_proposal(self):
        """Should record proposal to recorder."""
        recorder = MagicMock()

        phase = ProposalPhase(
            recorder=recorder,
            build_proposal_prompt=MagicMock(return_value="prompt"),
            generate_with_agent=AsyncMock(return_value="proposal"),
        )

        proposers = [MockAgent(name="claude")]
        ctx = DebateContext(env=MockEnvironment(), proposers=proposers)
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        recorder.record_turn.assert_called_once()

    @pytest.mark.asyncio
    async def test_skip_record_on_error(self):
        """Should not record failed proposals."""
        recorder = MagicMock()

        phase = ProposalPhase(
            recorder=recorder,
            build_proposal_prompt=MagicMock(return_value="prompt"),
            generate_with_agent=AsyncMock(side_effect=Exception("Error")),
        )

        proposers = [MockAgent(name="claude")]
        ctx = DebateContext(env=MockEnvironment(), proposers=proposers)
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        recorder.record_turn.assert_not_called()


# ============================================================================
# Citation Extraction Tests
# ============================================================================


class TestCitationExtraction:
    """Tests for citation need extraction."""

    @pytest.mark.asyncio
    async def test_extract_citations(self):
        """Should extract citation needs from proposals."""
        extract_citations = MagicMock()

        phase = ProposalPhase(
            build_proposal_prompt=MagicMock(return_value="prompt"),
            generate_with_agent=AsyncMock(return_value="proposal"),
            extract_citation_needs=extract_citations,
        )

        proposers = [MockAgent(name="claude")]
        ctx = DebateContext(env=MockEnvironment(), proposers=proposers)
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        extract_citations.assert_called_once()


# ============================================================================
# Integration Tests
# ============================================================================


class TestProposalPhaseIntegration:
    """Integration tests for full proposal execution."""

    @pytest.mark.asyncio
    async def test_full_proposal_execution(self):
        """Should execute full proposal phase."""
        cb = MagicMock()
        cb.filter_available_agents.return_value = [
            MockAgent(name="claude"),
            MockAgent(name="gpt4"),
        ]
        recorder = MagicMock()
        on_message = MagicMock()
        notify = MagicMock()

        async def generate(agent, prompt, context):
            return f"Proposal from {agent.name}"

        phase = ProposalPhase(
            circuit_breaker=cb,
            recorder=recorder,
            hooks={"on_message": on_message},
            build_proposal_prompt=MagicMock(return_value="prompt"),
            generate_with_agent=generate,
            notify_spectator=notify,
        )

        proposers = [MockAgent(name="claude"), MockAgent(name="gpt4")]
        ctx = DebateContext(env=MockEnvironment(), proposers=proposers)
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        # Verify proposals generated
        assert len(ctx.proposals) == 2
        assert "claude" in ctx.proposals
        assert "gpt4" in ctx.proposals

        # Verify messages added
        assert len(ctx.context_messages) == 2

        # Verify hooks called
        assert on_message.call_count == 2

        # Verify recorder called
        assert recorder.record_turn.call_count == 2

    @pytest.mark.asyncio
    async def test_empty_proposers(self):
        """Should handle empty proposers list."""
        phase = ProposalPhase(
            build_proposal_prompt=MagicMock(return_value="prompt"),
            generate_with_agent=AsyncMock(return_value="proposal"),
        )

        ctx = DebateContext(env=MockEnvironment(), proposers=[])
        ctx.result = MockDebateResult()

        # Should not raise
        await phase.execute(ctx)

        assert ctx.proposals == {}
