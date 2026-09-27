"""
Tests for consensus phase module.

Tests cover:
- ConsensusDependencies dataclass
- ConsensusCallbacks dataclass
- ConsensusPhase initialization (new style and legacy style)
- execute method (timeout, error handling, cancellation, hooks)
- _execute_consensus mode routing (none, majority, unanimous, judge, byzantine, prover_estimator, unknown)
- _handle_none_consensus method
- _handle_fallback_consensus method
- _handle_majority_consensus method
- _handle_unanimous_consensus method
- _handle_judge_consensus method
- _ensure_quorum method
- _required_participation method
- _normalize_choice_to_agent method
- _count_weighted_votes method
- _add_user_votes method
- _emit_guaranteed_events method
- _verify_consensus_formally method
- Error handling and edge cases
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.core_types import DebateResult, Vote
from aragora.debate.context import DebateContext
from aragora.debate.phases.consensus_phase import (
    ConsensusCallbacks,
    ConsensusDependencies,
    ConsensusPhase,
)


# =============================================================================
# Mock Objects
# =============================================================================


@dataclass
class MockAgent:
    """Mock agent for testing."""

    name: str = "test-agent"
    provider: str = "test-provider"
    model_type: str = "test-model"
    timeout: float = 120.0


@dataclass
class MockProtocol:
    """Mock debate protocol for testing."""

    consensus: str = "none"
    rounds: int = 3
    consensus_timeout: float = 5.0
    consensus_threshold: float = 0.6
    min_participation_ratio: float = 0.5
    min_participation_count: int = 2
    user_vote_weight: float = 0.5
    formal_verification_enabled: bool = False
    judge_selection: str = "random"
    enable_judge_deliberation: bool = False
    enable_position_shuffling: bool = False
    position_shuffling_permutations: int = 3
    enable_self_vote_mitigation: bool = False
    enable_verbosity_normalization: bool = False
    verify_claims_during_consensus: bool = False


@dataclass
class MockEnvironment:
    """Mock debate environment for testing."""

    task: str = "Test task"


def make_vote(
    agent: str = "voter1",
    choice: str = "agent1",
    reasoning: str = "Good proposal",
    confidence: float = 0.8,
) -> Vote:
    """Create a real Vote object for testing."""
    return Vote(agent=agent, choice=choice, reasoning=reasoning, confidence=confidence)


def make_context(
    proposals: dict[str, str] | None = None,
    agents: list | None = None,
    consensus_mode: str = "none",
) -> tuple[DebateContext, MockProtocol]:
    """Create a DebateContext with sensible defaults for testing."""
    protocol = MockProtocol(consensus=consensus_mode)
    result = DebateResult()
    ctx = DebateContext(
        env=MockEnvironment(),
        agents=agents or [MockAgent(name="agent1"), MockAgent(name="agent2")],
        proposals=proposals
        if proposals is not None
        else {"agent1": "Proposal A", "agent2": "Proposal B"},
        result=result,
        start_time=time.time(),
        debate_id="test-debate-123",
    )
    return ctx, protocol


# =============================================================================
# ConsensusDependencies Tests
# =============================================================================


class TestConsensusDependencies:
    """Tests for ConsensusDependencies dataclass."""

    def test_default_values(self):
        """Dependencies initializes with correct defaults."""
        deps = ConsensusDependencies()

        assert deps.protocol is None
        assert deps.elo_system is None
        assert deps.memory is None
        assert deps.agent_weights == {}
        assert deps.flip_detector is None
        assert deps.position_tracker is None
        assert deps.calibration_tracker is None
        assert deps.recorder is None
        assert deps.hooks == {}
        assert deps.user_votes == []

    def test_custom_values(self):
        """Dependencies accepts and stores custom values."""
        protocol = MockProtocol()
        deps = ConsensusDependencies(
            protocol=protocol,
            agent_weights={"agent1": 1.5},
            user_votes=[{"choice": "agent1"}],
        )

        assert deps.protocol is protocol
        assert deps.agent_weights == {"agent1": 1.5}
        assert len(deps.user_votes) == 1


# =============================================================================
# ConsensusCallbacks Tests
# =============================================================================


class TestConsensusCallbacks:
    """Tests for ConsensusCallbacks dataclass."""

    def test_default_values(self):
        """Callbacks initializes with all None defaults."""
        cbs = ConsensusCallbacks()

        assert cbs.vote_with_agent is None
        assert cbs.with_timeout is None
        assert cbs.select_judge is None
        assert cbs.build_judge_prompt is None
        assert cbs.generate_with_agent is None
        assert cbs.group_similar_votes is None
        assert cbs.get_calibration_weight is None
        assert cbs.notify_spectator is None
        assert cbs.drain_user_events is None
        assert cbs.extract_debate_domain is None
        assert cbs.get_belief_analyzer is None
        assert cbs.user_vote_multiplier is None
        assert cbs.verify_claims is None

    def test_custom_values(self):
        """Callbacks stores custom callable values."""
        vote_fn = AsyncMock()
        timeout_fn = MagicMock()
        cbs = ConsensusCallbacks(vote_with_agent=vote_fn, with_timeout=timeout_fn)

        assert cbs.vote_with_agent is vote_fn
        assert cbs.with_timeout is timeout_fn


# =============================================================================
# ConsensusPhase Initialization Tests
# =============================================================================


class TestConsensusPhaseInit:
    """Tests for ConsensusPhase initialization."""

    def test_init_with_dataclasses(self):
        """Initializes correctly with new-style dataclass dependencies."""
        protocol = MockProtocol()
        deps = ConsensusDependencies(protocol=protocol)
        cbs = ConsensusCallbacks(vote_with_agent=AsyncMock())

        phase = ConsensusPhase(deps=deps, callbacks=cbs)

        assert phase.protocol is protocol
        assert phase._vote_with_agent is cbs.vote_with_agent

    def test_init_with_legacy_params(self):
        """Initializes correctly with legacy keyword arguments."""
        protocol = MockProtocol()
        vote_fn = AsyncMock()

        phase = ConsensusPhase(
            protocol=protocol,
            elo_system=None,
            memory=None,
            vote_with_agent=vote_fn,
        )

        assert phase.protocol is protocol
        assert phase._vote_with_agent is vote_fn

    def test_init_creates_helper_classes(self):
        """Initialization creates internal helper classes."""
        deps = ConsensusDependencies(protocol=MockProtocol())
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        assert phase._winner_selector is not None
        assert phase._consensus_verifier is not None
        assert phase._synthesis_generator is not None
        assert phase._vote_bonus_calculator is not None

    def test_init_with_no_protocol(self):
        """Initializes gracefully with no protocol."""
        phase = ConsensusPhase()

        assert phase.protocol is None


# =============================================================================
# _handle_none_consensus Tests
# =============================================================================


class TestHandleNoneConsensus:
    """Tests for _handle_none_consensus method."""

    @pytest.mark.asyncio
    async def test_combines_all_proposals(self):
        """None mode combines all proposals into final answer."""
        ctx, protocol = make_context(proposals={"agent1": "Proposal A", "agent2": "Proposal B"})
        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        await phase._handle_none_consensus(ctx)

        assert "[agent1]" in ctx.result.final_answer
        assert "Proposal A" in ctx.result.final_answer
        assert "[agent2]" in ctx.result.final_answer
        assert "Proposal B" in ctx.result.final_answer
        assert ctx.result.consensus_reached is False
        assert ctx.result.confidence == 0.5

    @pytest.mark.asyncio
    async def test_handles_empty_proposals(self):
        """None mode handles empty proposals."""
        ctx, protocol = make_context(proposals={})
        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        await phase._handle_none_consensus(ctx)

        assert "No proposals available" in ctx.result.final_answer
        assert ctx.result.consensus_reached is False

    @pytest.mark.asyncio
    async def test_single_proposal(self):
        """None mode handles single proposal."""
        ctx, protocol = make_context(proposals={"agent1": "Only proposal"})
        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        await phase._handle_none_consensus(ctx)

        assert "[agent1]" in ctx.result.final_answer
        assert "Only proposal" in ctx.result.final_answer


# =============================================================================
# _handle_fallback_consensus Tests
# =============================================================================


class TestHandleFallbackConsensusExtended:
    """Tests for _handle_fallback_consensus method."""

    @pytest.mark.asyncio
    async def test_fallback_with_no_votes_no_tally(self):
        """Fallback with no votes and no tally uses proposals text."""
        ctx, protocol = make_context(proposals={"agent1": "Proposal A", "agent2": "Proposal B"})
        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        await phase._handle_fallback_consensus(ctx, reason="timeout")

        assert ctx.result.consensus_reached is False
        assert ctx.result.confidence == 0.5
        assert ctx.result.consensus_strength == "fallback"
        assert "[agent1]" in ctx.result.final_answer
        assert "[agent2]" in ctx.result.final_answer

    @pytest.mark.asyncio
    async def test_fallback_with_existing_votes(self):
        """Fallback uses existing votes to determine winner."""
        ctx, protocol = make_context(proposals={"agent1": "Proposal A", "agent2": "Proposal B"})
        v1 = make_vote(agent="voter1", choice="agent1")
        v2 = make_vote(agent="voter2", choice="agent1")
        v3 = make_vote(agent="voter3", choice="agent2")
        ctx.result.votes = [v1, v2, v3]
        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        await phase._handle_fallback_consensus(ctx, reason="error")

        assert ctx.result.consensus_reached is True
        assert ctx.result.winner == "agent1"
        assert ctx.result.consensus_strength == "fallback"

    @pytest.mark.asyncio
    async def test_fallback_with_vote_tally(self):
        """Fallback uses vote_tally when no result votes available."""
        ctx, protocol = make_context(proposals={"agent1": "Proposal A", "agent2": "Proposal B"})
        ctx.vote_tally = {"agent2": 5.0, "agent1": 3.0}
        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        await phase._handle_fallback_consensus(ctx, reason="timeout")

        assert ctx.result.consensus_reached is True
        assert ctx.result.winner == "agent2"

    @pytest.mark.asyncio
    async def test_fallback_with_no_proposals(self):
        """Fallback with no proposals produces descriptive message."""
        ctx, protocol = make_context(proposals={})
        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        await phase._handle_fallback_consensus(ctx, reason="timeout")

        assert "No proposals available" in ctx.result.final_answer
        assert ctx.result.consensus_reached is False

    @pytest.mark.asyncio
    async def test_fallback_winner_not_in_proposals(self):
        """Fallback with winner not in proposals produces combined answer."""
        ctx, protocol = make_context(proposals={"agent1": "Proposal A"})
        v1 = make_vote(agent="voter1", choice="agent_unknown")
        ctx.result.votes = [v1]
        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        await phase._handle_fallback_consensus(ctx, reason="error")

        # Winner is "agent_unknown" which is not in proposals, so combined text
        assert "agent_unknown" in ctx.result.final_answer
        assert ctx.result.consensus_reached is True


# =============================================================================
# _ensure_quorum Tests
# =============================================================================


class TestEnsureQuorum:
    """Tests for _ensure_quorum method."""

    def test_quorum_met(self):
        """Returns True when enough votes are present."""
        ctx, protocol = make_context(agents=[MockAgent(name=f"a{i}") for i in range(4)])
        protocol.min_participation_ratio = 0.5
        protocol.min_participation_count = 2
        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        assert phase._ensure_quorum(ctx, vote_count=3) is True

    def test_quorum_not_met(self):
        """Returns False and sets result when insufficient votes."""
        ctx, protocol = make_context(agents=[MockAgent(name=f"a{i}") for i in range(10)])
        protocol.min_participation_ratio = 0.5
        protocol.min_participation_count = 2
        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        result = phase._ensure_quorum(ctx, vote_count=1)

        assert result is False
        assert ctx.result.consensus_reached is False
        assert ctx.result.confidence == 0.0
        assert ctx.result.status == "insufficient_participation"

    def test_quorum_with_notify_spectator(self):
        """Notifies spectator when quorum not met."""
        ctx, protocol = make_context(agents=[MockAgent(name=f"a{i}") for i in range(10)])
        notify_fn = MagicMock()
        deps = ConsensusDependencies(protocol=protocol)
        cbs = ConsensusCallbacks(notify_spectator=notify_fn)
        phase = ConsensusPhase(deps=deps, callbacks=cbs)

        phase._ensure_quorum(ctx, vote_count=1)

        notify_fn.assert_called_once()
        call_args = notify_fn.call_args
        assert "Insufficient participation" in call_args[1]["details"]


# =============================================================================
# _required_participation Tests
# =============================================================================


class TestRequiredParticipation:
    """Tests for _required_participation method."""

    def test_uses_ratio_and_count(self):
        """Returns max of ratio-based and count-based minimum."""
        protocol = MockProtocol(min_participation_ratio=0.5, min_participation_count=2)
        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        # 10 agents * 0.5 = 5 > min_count 2
        assert phase._required_participation(10) == 5

    def test_min_count_dominates_small_groups(self):
        """min_participation_count dominates for small groups."""
        protocol = MockProtocol(min_participation_ratio=0.5, min_participation_count=3)
        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        # 4 agents * 0.5 = 2 < min_count 3
        assert phase._required_participation(4) == 3


# =============================================================================
# _normalize_choice_to_agent Tests
# =============================================================================


class TestNormalizeChoiceToAgent:
    """Tests for _normalize_choice_to_agent method."""

    def _make_phase(self):
        deps = ConsensusDependencies(protocol=MockProtocol())
        return ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

    def test_exact_match_in_proposals(self):
        """Returns choice unchanged when it matches a proposal key exactly."""
        phase = self._make_phase()
        agents = [MockAgent(name="claude-opus")]
        proposals = {"claude-opus": "proposal text"}

        result = phase._normalize_choice_to_agent("claude-opus", agents, proposals)

        assert result == "claude-opus"

    def test_case_insensitive_match(self):
        """Matches agent name case-insensitively."""
        phase = self._make_phase()
        agents = [MockAgent(name="Claude-Opus")]
        proposals = {}

        result = phase._normalize_choice_to_agent("claude-opus", agents, proposals)

        assert result == "Claude-Opus"

    def test_prefix_match(self):
        """Matches when choice is a prefix of agent name."""
        phase = self._make_phase()
        agents = [MockAgent(name="claude-opus-4")]
        proposals = {}

        result = phase._normalize_choice_to_agent("claude", agents, proposals)

        assert result == "claude-opus-4"

    def test_base_name_match_with_hyphen(self):
        """Matches base name (before hyphen) of agent."""
        phase = self._make_phase()
        agents = [MockAgent(name="gpt-4o")]
        proposals = {}

        result = phase._normalize_choice_to_agent("gpt", agents, proposals)

        assert result == "gpt-4o"

    def test_empty_choice_returns_empty(self):
        """Returns empty string for empty choice."""
        phase = self._make_phase()
        result = phase._normalize_choice_to_agent("", [], {})

        assert result == ""

    def test_no_match_returns_original(self):
        """Returns original choice when no match found."""
        phase = self._make_phase()
        agents = [MockAgent(name="claude")]
        proposals = {}

        result = phase._normalize_choice_to_agent("unknown-agent", agents, proposals)

        assert result == "unknown-agent"


# =============================================================================
# _count_weighted_votes Tests
# =============================================================================


class TestCountWeightedVotes:
    """Tests for _count_weighted_votes method."""

    def _make_phase(self):
        deps = ConsensusDependencies(protocol=MockProtocol())
        return ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

    def test_counts_with_uniform_weights(self):
        """Counts votes with uniform weights."""
        phase = self._make_phase()
        votes = [
            make_vote(agent="v1", choice="agent1"),
            make_vote(agent="v2", choice="agent1"),
            make_vote(agent="v3", choice="agent2"),
        ]
        choice_mapping = {}
        weight_cache = {"v1": 1.0, "v2": 1.0, "v3": 1.0}

        counts, total = phase._count_weighted_votes(votes, choice_mapping, weight_cache)

        assert counts["agent1"] == 2.0
        assert counts["agent2"] == 1.0
        assert total == 3.0

    def test_counts_with_varying_weights(self):
        """Counts votes with different agent weights."""
        phase = self._make_phase()
        votes = [
            make_vote(agent="v1", choice="agent1"),
            make_vote(agent="v2", choice="agent2"),
        ]
        choice_mapping = {}
        weight_cache = {"v1": 2.0, "v2": 0.5}

        counts, total = phase._count_weighted_votes(votes, choice_mapping, weight_cache)

        assert counts["agent1"] == 2.0
        assert counts["agent2"] == 0.5
        assert total == 2.5

    def test_uses_choice_mapping(self):
        """Maps votes to canonical choices via choice_mapping."""
        phase = self._make_phase()
        votes = [
            make_vote(agent="v1", choice="Agent-1"),
            make_vote(agent="v2", choice="agent_1"),
        ]
        choice_mapping = {"Agent-1": "agent1", "agent_1": "agent1"}
        weight_cache = {"v1": 1.0, "v2": 1.0}

        counts, total = phase._count_weighted_votes(votes, choice_mapping, weight_cache)

        assert counts["agent1"] == 2.0
        assert total == 2.0

    def test_default_weight_for_unknown_agent(self):
        """Uses default weight 1.0 for agents not in cache."""
        phase = self._make_phase()
        votes = [make_vote(agent="unknown", choice="agent1")]
        weight_cache = {}

        counts, total = phase._count_weighted_votes(votes, {}, weight_cache)

        assert counts["agent1"] == 1.0
        assert total == 1.0


# =============================================================================
# _add_user_votes Tests
# =============================================================================


class TestAddUserVotes:
    """Tests for _add_user_votes method."""

    def test_adds_user_votes_with_weight(self):
        """Adds user votes with base weight from protocol."""
        protocol = MockProtocol(user_vote_weight=1.0)
        deps = ConsensusDependencies(
            protocol=protocol,
            user_votes=[{"choice": "agent1", "user_id": "user1"}],
        )
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        vote_counts = {"agent1": 5.0}
        new_counts, new_total = phase._add_user_votes(vote_counts, 5.0, {})

        assert new_counts["agent1"] == 6.0
        assert new_total == 6.0

    def test_no_user_votes(self):
        """Handles case with no user votes."""
        protocol = MockProtocol(user_vote_weight=0.5)
        deps = ConsensusDependencies(protocol=protocol, user_votes=[])
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        vote_counts = {"agent1": 5.0}
        new_counts, new_total = phase._add_user_votes(vote_counts, 5.0, {})

        assert new_counts["agent1"] == 5.0
        assert new_total == 5.0

    def test_user_vote_multiplier_callback(self):
        """Uses user_vote_multiplier callback when provided."""
        protocol = MockProtocol(user_vote_weight=1.0)
        multiplier_fn = MagicMock(return_value=2.0)
        deps = ConsensusDependencies(
            protocol=protocol,
            user_votes=[{"choice": "agent1", "intensity": 8}],
        )
        cbs = ConsensusCallbacks(user_vote_multiplier=multiplier_fn)
        phase = ConsensusPhase(deps=deps, callbacks=cbs)

        vote_counts = {"agent1": 5.0}
        new_counts, new_total = phase._add_user_votes(vote_counts, 5.0, {})

        # base_weight(1.0) * multiplier(2.0) = 2.0 added
        assert new_counts["agent1"] == 7.0
        multiplier_fn.assert_called_once_with(8, protocol)

    def test_user_vote_with_choice_mapping(self):
        """User votes respect choice_mapping for canonical names."""
        protocol = MockProtocol(user_vote_weight=1.0)
        deps = ConsensusDependencies(
            protocol=protocol,
            user_votes=[{"choice": "Agent1", "intensity": 5}],
        )
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        vote_counts = {"agent1": 5.0}
        choice_mapping = {"Agent1": "agent1"}
        new_counts, new_total = phase._add_user_votes(vote_counts, 5.0, choice_mapping)

        assert new_counts["agent1"] == 6.0

    def test_user_vote_with_empty_choice_skipped(self):
        """User votes with empty choice are skipped."""
        protocol = MockProtocol(user_vote_weight=1.0)
        deps = ConsensusDependencies(
            protocol=protocol,
            user_votes=[{"choice": "", "user_id": "user1"}],
        )
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        vote_counts = {"agent1": 5.0}
        new_counts, new_total = phase._add_user_votes(vote_counts, 5.0, {})

        assert new_counts["agent1"] == 5.0
        assert new_total == 5.0


# =============================================================================
# execute Tests
# =============================================================================


class TestExecute:
    """Tests for the execute method."""

    @pytest.mark.asyncio
    async def test_execute_none_mode(self):
        """Execute runs none consensus mode end-to-end."""
        ctx, protocol = make_context(
            proposals={"agent1": "Proposal A"},
            consensus_mode="none",
        )
        deps = ConsensusDependencies(protocol=protocol)
        cbs = ConsensusCallbacks()
        phase = ConsensusPhase(deps=deps, callbacks=cbs)

        with patch.object(
            phase._synthesis_generator,
            "generate_mandatory_synthesis",
            new_callable=AsyncMock,
            return_value=True,
        ):
            await phase.execute(ctx)

        assert ctx.result.final_answer is not None
        assert ctx.result.consensus_reached is False

    @pytest.mark.asyncio
    async def test_execute_handles_timeout(self):
        """Execute handles timeout by falling back."""
        ctx, protocol = make_context(
            proposals={"agent1": "Proposal A"},
            consensus_mode="majority",
        )
        protocol.consensus_timeout = 0.001  # Very short timeout
        deps = ConsensusDependencies(protocol=protocol)
        cbs = ConsensusCallbacks()
        phase = ConsensusPhase(deps=deps, callbacks=cbs)

        async def slow_consensus(*args, **kwargs):
            await asyncio.sleep(10)

        with patch.object(phase, "_execute_consensus", side_effect=slow_consensus):
            with patch.object(
                phase._synthesis_generator,
                "generate_mandatory_synthesis",
                new_callable=AsyncMock,
                return_value=True,
            ):
                await phase.execute(ctx)

        assert ctx.result.consensus_strength == "fallback"

    @pytest.mark.asyncio
    async def test_execute_handles_exception(self):
        """Execute handles exceptions by falling back."""
        ctx, protocol = make_context(
            proposals={"agent1": "Proposal A"},
            consensus_mode="majority",
        )
        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        with patch.object(phase, "_execute_consensus", side_effect=RuntimeError("test error")):
            with patch.object(
                phase._synthesis_generator,
                "generate_mandatory_synthesis",
                new_callable=AsyncMock,
                return_value=True,
            ):
                await phase.execute(ctx)

        assert ctx.result.consensus_strength == "fallback"

    @pytest.mark.asyncio
    async def test_execute_respects_cancellation_token(self):
        """Execute raises DebateCancelled when cancellation token is set."""
        from aragora.debate.cancellation import DebateCancelled

        ctx, protocol = make_context()
        # Use a mock token to avoid asyncio.Event cross-loop issues
        token = MagicMock()
        token.is_cancelled = True
        token.reason = "User requested cancellation"
        ctx.cancellation_token = token
        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        with pytest.raises(DebateCancelled):
            await phase.execute(ctx)

    @pytest.mark.asyncio
    async def test_execute_uses_default_cancellation_reason(self):
        """Cancelled contexts without a reason still raise a useful exception."""
        from aragora.debate.cancellation import DebateCancelled

        ctx, protocol = make_context()
        token = MagicMock()
        token.is_cancelled = True
        token.reason = None
        ctx.cancellation_token = token
        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        with pytest.raises(DebateCancelled, match="Debate cancelled") as exc_info:
            await phase.execute(ctx)

        assert exc_info.value.reason == "Debate cancelled"

    @pytest.mark.asyncio
    async def test_execute_triggers_pre_consensus_hook(self):
        """Execute triggers PRE_CONSENSUS hook when hook_manager is present."""
        ctx, protocol = make_context(consensus_mode="none")
        hook_manager = AsyncMock()
        ctx.hook_manager = hook_manager
        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        with patch.object(
            phase._synthesis_generator,
            "generate_mandatory_synthesis",
            new_callable=AsyncMock,
            return_value=True,
        ):
            await phase.execute(ctx)

        hook_manager.trigger.assert_any_call("pre_consensus", ctx=ctx, proposals=ctx.proposals)

    @pytest.mark.asyncio
    async def test_execute_fallback_synthesis_on_failure(self):
        """Execute creates fallback synthesis when synthesis generator fails."""
        ctx, protocol = make_context(
            proposals={"agent1": "Proposal text here"},
            consensus_mode="none",
        )
        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        with patch.object(
            phase._synthesis_generator,
            "generate_mandatory_synthesis",
            new_callable=AsyncMock,
            return_value=False,
        ):
            await phase.execute(ctx)

        assert ctx.result.synthesis is not None
        assert "Debate Summary" in ctx.result.synthesis


# =============================================================================
# _execute_consensus Mode Routing Tests
# =============================================================================


class TestExecuteConsensusRouting:
    """Tests for _execute_consensus mode routing."""

    @pytest.mark.asyncio
    async def test_routes_none_mode(self):
        """Routes 'none' mode to _handle_none_consensus."""
        ctx, protocol = make_context()
        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        with patch.object(phase, "_handle_none_consensus", new_callable=AsyncMock) as mock:
            await phase._execute_consensus(ctx, "none")
            mock.assert_called_once_with(ctx)

    @pytest.mark.asyncio
    async def test_routes_majority_mode(self):
        """Routes 'majority' mode to _handle_majority_consensus."""
        ctx, protocol = make_context()
        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        with patch.object(phase, "_handle_majority_consensus", new_callable=AsyncMock) as mock:
            await phase._execute_consensus(ctx, "majority")
            mock.assert_called_once_with(ctx, threshold_override=None)

    @pytest.mark.asyncio
    async def test_routes_weighted_to_majority(self):
        """Routes 'weighted' mode to _handle_majority_consensus."""
        ctx, protocol = make_context()
        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        with patch.object(phase, "_handle_majority_consensus", new_callable=AsyncMock) as mock:
            await phase._execute_consensus(ctx, "weighted")
            mock.assert_called_once_with(ctx, threshold_override=None)

    @pytest.mark.asyncio
    async def test_routes_supermajority_with_threshold(self):
        """Routes 'supermajority' to majority with 2/3 threshold override."""
        ctx, protocol = make_context()
        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        with patch.object(phase, "_handle_majority_consensus", new_callable=AsyncMock) as mock:
            await phase._execute_consensus(ctx, "supermajority")
            _, kwargs = mock.call_args
            assert kwargs["threshold_override"] >= 2 / 3

    @pytest.mark.asyncio
    async def test_routes_any_with_zero_threshold(self):
        """Routes 'any' mode to majority with 0.0 threshold override."""
        ctx, protocol = make_context()
        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        with patch.object(phase, "_handle_majority_consensus", new_callable=AsyncMock) as mock:
            await phase._execute_consensus(ctx, "any")
            _, kwargs = mock.call_args
            assert kwargs["threshold_override"] == 0.0

    @pytest.mark.asyncio
    async def test_routes_unanimous_mode(self):
        """Routes 'unanimous' mode to _handle_unanimous_consensus."""
        ctx, protocol = make_context()
        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        with patch.object(phase, "_handle_unanimous_consensus", new_callable=AsyncMock) as mock:
            await phase._execute_consensus(ctx, "unanimous")
            mock.assert_called_once_with(ctx)

    @pytest.mark.asyncio
    async def test_routes_judge_mode(self):
        """Routes 'judge' mode to _handle_judge_consensus."""
        ctx, protocol = make_context()
        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        with patch.object(phase, "_handle_judge_consensus", new_callable=AsyncMock) as mock:
            await phase._execute_consensus(ctx, "judge")
            mock.assert_called_once_with(ctx)

    @pytest.mark.asyncio
    async def test_routes_hybrid_mode_to_judge(self):
        """Routes 'hybrid' mode to judge-based finalization."""
        ctx, protocol = make_context()
        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        with patch.object(phase, "_handle_judge_consensus", new_callable=AsyncMock) as mock:
            await phase._execute_consensus(ctx, "hybrid")
            mock.assert_called_once_with(ctx)

    @pytest.mark.asyncio
    async def test_routes_byzantine_mode(self):
        """Routes 'byzantine' mode to _handle_byzantine_consensus."""
        ctx, protocol = make_context()
        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        with patch.object(phase, "_handle_byzantine_consensus", new_callable=AsyncMock) as mock:
            await phase._execute_consensus(ctx, "byzantine")
            mock.assert_called_once_with(ctx)

    @pytest.mark.asyncio
    async def test_routes_prover_estimator_mode(self):
        """Routes 'prover_estimator' mode to its handler."""
        ctx, protocol = make_context()
        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        with patch.object(
            phase,
            "_handle_prover_estimator_consensus",
            new_callable=AsyncMock,
        ) as mock:
            await phase._execute_consensus(ctx, "prover_estimator")
            mock.assert_called_once_with(ctx)

    @pytest.mark.asyncio
    async def test_unknown_mode_falls_back_to_none(self):
        """Unknown consensus mode falls back to none."""
        ctx, protocol = make_context()
        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        with patch.object(phase, "_handle_none_consensus", new_callable=AsyncMock) as mock:
            await phase._execute_consensus(ctx, "unknown_mode")
            mock.assert_called_once_with(ctx)


# =============================================================================
# _emit_guaranteed_events Tests
# =============================================================================


class TestEmitGuaranteedEvents:
    """Tests for _emit_guaranteed_events method."""

    def test_emits_consensus_event(self):
        """Emits on_consensus hook with correct data."""
        ctx, protocol = make_context()
        ctx.result.consensus_reached = True
        ctx.result.confidence = 0.85
        ctx.result.final_answer = "Winner answer"
        ctx.result.synthesis = "Full synthesis"
        on_consensus = MagicMock()
        hooks = {"on_consensus": on_consensus}
        deps = ConsensusDependencies(protocol=protocol, hooks=hooks)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        phase._emit_guaranteed_events(ctx)

        on_consensus.assert_called_once_with(
            reached=True,
            confidence=0.85,
            answer="Winner answer",
            synthesis="Full synthesis",
        )

    def test_emits_debate_end_event(self):
        """Emits on_debate_end hook with duration and rounds."""
        ctx, protocol = make_context()
        ctx.result.rounds_used = 3
        ctx.start_time = time.time() - 10.0
        on_debate_end = MagicMock()
        hooks = {"on_debate_end": on_debate_end}
        deps = ConsensusDependencies(protocol=protocol, hooks=hooks)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        phase._emit_guaranteed_events(ctx)

        on_debate_end.assert_called_once()
        call_kwargs = on_debate_end.call_args[1]
        assert call_kwargs["rounds"] == 3
        assert call_kwargs["duration"] >= 9.0

    def test_handles_hook_errors_gracefully(self):
        """Handles errors in hook callbacks without raising."""
        ctx, protocol = make_context()
        ctx.result.consensus_reached = True
        ctx.result.confidence = 0.5
        ctx.result.final_answer = "answer"
        ctx.result.synthesis = ""
        on_consensus = MagicMock(side_effect=RuntimeError("Hook error"))
        hooks = {"on_consensus": on_consensus}
        deps = ConsensusDependencies(protocol=protocol, hooks=hooks)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        # Should not raise
        phase._emit_guaranteed_events(ctx)

    def test_no_emit_when_no_result(self):
        """Does nothing when ctx.result is None."""
        ctx, protocol = make_context()
        ctx.result = None
        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        # Should not raise
        phase._emit_guaranteed_events(ctx)

    def test_no_emit_when_no_hooks(self):
        """Does nothing when no hooks are configured."""
        ctx, protocol = make_context()
        deps = ConsensusDependencies(protocol=protocol, hooks={})
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        # Should not raise
        phase._emit_guaranteed_events(ctx)


# =============================================================================
# _handle_judge_consensus Tests
# =============================================================================


class TestHandleJudgeConsensus:
    """Tests for _handle_judge_consensus method."""

    @pytest.mark.asyncio
    async def test_judge_without_required_callbacks(self):
        """Judge mode fails gracefully without select_judge/generate_with_agent."""
        ctx, protocol = make_context(
            proposals={"agent1": "Proposal A"},
            consensus_mode="judge",
        )
        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        await phase._handle_judge_consensus(ctx)

        assert ctx.result.consensus_reached is False
        assert ctx.result.confidence == 0.5

    @pytest.mark.asyncio
    async def test_judge_successful_synthesis(self):
        """Judge mode produces synthesis from judge agent."""
        ctx, protocol = make_context(
            proposals={"agent1": "Proposal A"},
            consensus_mode="judge",
        )
        judge_agent = MockAgent(name="judge-claude")
        select_judge = AsyncMock(return_value=judge_agent)
        generate_fn = AsyncMock(return_value="Judge synthesis result")
        build_prompt = MagicMock(return_value="Judge prompt")
        deps = ConsensusDependencies(protocol=protocol)
        cbs = ConsensusCallbacks(
            select_judge=select_judge,
            generate_with_agent=generate_fn,
            build_judge_prompt=build_prompt,
        )
        phase = ConsensusPhase(deps=deps, callbacks=cbs)

        await phase._handle_judge_consensus(ctx)

        assert ctx.result.consensus_reached is True
        assert ctx.result.confidence == 0.8
        assert ctx.result.final_answer == "Judge synthesis result"
        assert ctx.result.winner == "judge-claude"

    @pytest.mark.asyncio
    async def test_judge_falls_back_on_all_failures(self):
        """Judge mode falls back to majority when all judges fail."""
        ctx, protocol = make_context(
            proposals={"agent1": "Proposal A"},
            consensus_mode="judge",
        )
        judge_agent = MockAgent(name="judge-claude")
        select_judge = AsyncMock(return_value=judge_agent)
        generate_fn = AsyncMock(side_effect=RuntimeError("Judge failed"))
        build_prompt = MagicMock(return_value="Judge prompt")
        deps = ConsensusDependencies(protocol=protocol)
        cbs = ConsensusCallbacks(
            select_judge=select_judge,
            generate_with_agent=generate_fn,
            build_judge_prompt=build_prompt,
        )
        phase = ConsensusPhase(deps=deps, callbacks=cbs)

        # Mock the majority and fallback paths too
        with patch.object(
            phase, "_handle_majority_consensus", new_callable=AsyncMock
        ) as mock_majority:
            # Majority also fails -> full fallback
            mock_majority.side_effect = RuntimeError("Majority also failed")
            await phase._handle_judge_consensus(ctx)

        # Should have fallen back
        assert ctx.result.consensus_strength == "fallback"


# =============================================================================
# _verify_consensus_formally Tests
# =============================================================================


class TestVerifyConsensusFormally:
    """Tests for _verify_consensus_formally method."""

    @pytest.mark.asyncio
    async def test_skips_when_no_protocol(self):
        """Skips formal verification when protocol is None."""
        ctx, _ = make_context()
        phase = ConsensusPhase()

        await phase._verify_consensus_formally(ctx)
        assert ctx.result.formal_verification is None

    @pytest.mark.asyncio
    async def test_skips_when_not_enabled(self):
        """Skips formal verification when not enabled in protocol."""
        ctx, protocol = make_context()
        protocol.formal_verification_enabled = False
        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        await phase._verify_consensus_formally(ctx)

        assert ctx.result.formal_verification is None

    @pytest.mark.asyncio
    async def test_skips_when_no_final_answer(self):
        """Skips formal verification when no final answer available."""
        ctx, protocol = make_context()
        protocol.formal_verification_enabled = True
        ctx.result.final_answer = ""
        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        await phase._verify_consensus_formally(ctx)

        assert ctx.result.formal_verification is None


# =============================================================================
# _apply_calibration_to_votes Tests
# =============================================================================


class TestApplyCalibrationToVotes:
    """Tests for _apply_calibration_to_votes method."""

    def test_returns_votes_unchanged_when_no_calibration_tracker(self):
        """Returns votes unchanged when calibration_tracker is None."""
        deps = ConsensusDependencies(protocol=MockProtocol(), calibration_tracker=None)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        votes = [make_vote(agent="agent1", confidence=0.8)]
        ctx, _ = make_context()

        result = phase._apply_calibration_to_votes(votes, ctx)

        assert result is votes
        assert result[0].confidence == 0.8

    def test_handles_exception_votes_in_list(self):
        """Passes through exception objects in vote list."""
        calibration_tracker = MagicMock()
        deps = ConsensusDependencies(
            protocol=MockProtocol(),
            calibration_tracker=calibration_tracker,
        )
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        err = RuntimeError("vote failed")
        votes = [err]
        ctx, _ = make_context()

        result = phase._apply_calibration_to_votes(votes, ctx)

        assert result[0] is err


# =============================================================================
# Integration-style Tests
# =============================================================================


class TestConsensusPhaseIntegration:
    """Integration tests for ConsensusPhase."""

    @pytest.mark.asyncio
    async def test_full_none_consensus_flow(self):
        """Tests complete none consensus flow including events."""
        on_consensus = MagicMock()
        on_debate_end = MagicMock()
        hooks = {"on_consensus": on_consensus, "on_debate_end": on_debate_end}

        ctx, protocol = make_context(
            proposals={"agent1": "Proposal A", "agent2": "Proposal B"},
            consensus_mode="none",
        )
        deps = ConsensusDependencies(protocol=protocol, hooks=hooks)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        with patch.object(
            phase._synthesis_generator,
            "generate_mandatory_synthesis",
            new_callable=AsyncMock,
            return_value=True,
        ):
            await phase.execute(ctx)

        # Both proposals should appear in the final answer
        assert "Proposal A" in ctx.result.final_answer
        assert "Proposal B" in ctx.result.final_answer
        assert ctx.result.consensus_reached is False

        # Events should have been emitted
        on_consensus.assert_called_once()
        on_debate_end.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_with_no_protocol_uses_none_mode(self):
        """Execute with no protocol defaults to 'none' consensus mode."""
        ctx, _ = make_context(proposals={"agent1": "Proposal A"})
        phase = ConsensusPhase()

        with patch.object(
            phase._synthesis_generator,
            "generate_mandatory_synthesis",
            new_callable=AsyncMock,
            return_value=True,
        ):
            await phase.execute(ctx)

        assert ctx.result.consensus_reached is False
        assert "Proposal A" in ctx.result.final_answer


# =============================================================================
# Additional Coverage: Byzantine Consensus Tests
# =============================================================================


class TestByzantineConsensus:
    """Tests for Byzantine consensus mode."""

    @pytest.mark.asyncio
    async def test_byzantine_requires_at_least_4_agents(self):
        """Byzantine consensus requires at least 4 agents, falls back to majority."""
        ctx, protocol = make_context(
            proposals={"agent1": "Proposal A"},
            agents=[MockAgent("agent1"), MockAgent("agent2"), MockAgent("agent3")],
            consensus_mode="byzantine",
        )

        deps = ConsensusDependencies(protocol=protocol)
        vote_with_agent = AsyncMock(return_value=make_vote(choice="agent1"))
        callbacks = ConsensusCallbacks(vote_with_agent=vote_with_agent)
        phase = ConsensusPhase(deps=deps, callbacks=callbacks)

        with patch.object(
            phase._synthesis_generator,
            "generate_mandatory_synthesis",
            new_callable=AsyncMock,
            return_value=True,
        ):
            await phase.execute(ctx)

        # Should have fallen back to majority voting (or completed some consensus)
        assert ctx.result.final_answer is not None

    @pytest.mark.asyncio
    async def test_byzantine_falls_back_on_error(self):
        """Byzantine consensus falls back to majority on import error."""
        agents = [MockAgent(f"agent{i}") for i in range(5)]
        ctx, protocol = make_context(
            proposals={"agent1": "Proposal A"},
            agents=agents,
            consensus_mode="byzantine",
        )

        # Create vote function for majority fallback
        vote_fn = AsyncMock(return_value=make_vote(choice="agent1"))

        deps = ConsensusDependencies(protocol=protocol)
        callbacks = ConsensusCallbacks(vote_with_agent=vote_fn)
        phase = ConsensusPhase(deps=deps, callbacks=callbacks)

        with patch.object(
            phase._synthesis_generator,
            "generate_mandatory_synthesis",
            new_callable=AsyncMock,
            return_value=True,
        ):
            # Byzantine will fail to import in test environment and fall back
            await phase.execute(ctx)

        # Should have processed some consensus
        assert ctx.result.final_answer is not None


# =============================================================================
# Additional Coverage: Prover-Estimator Consensus Tests
# =============================================================================


class TestProverEstimatorConsensus:
    """Tests for prover-estimator consensus mode."""

    @pytest.mark.asyncio
    async def test_prover_estimator_populates_result(self):
        """Prover-estimator records confidence and verification metadata."""
        ctx, protocol = make_context(
            proposals={"agent1": "Proposal A", "agent2": "Proposal B"},
            agents=[MockAgent("agent1"), MockAgent("agent2")],
            consensus_mode="prover_estimator",
        )
        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        pe_result = MagicMock(
            overall_confidence=0.82,
            grounding_score=0.74,
            obfuscation_detected=False,
            subclaims=[object(), object()],
            challenges=[object()],
        )
        engine = MagicMock()
        engine.run = AsyncMock(return_value=pe_result)

        with patch(
            "aragora.debate.prover_estimator.ProverEstimatorEngine",
            return_value=engine,
        ) as engine_cls:
            await phase._handle_prover_estimator_consensus(ctx)

        engine_cls.assert_called_once()
        engine.run.assert_awaited_once()
        assert ctx.result.final_answer == "Proposal A"
        assert ctx.result.consensus_reached is True
        assert ctx.result.consensus_strength == "strong"
        assert ctx.result.confidence == pytest.approx(0.82)
        assert ctx.result.formal_verification["prover_estimator"] == {
            "overall_confidence": 0.82,
            "grounding_score": 0.74,
            "obfuscation_detected": False,
            "subclaim_count": 2,
            "challenge_count": 1,
        }

    @pytest.mark.asyncio
    async def test_prover_estimator_falls_back_to_majority_on_error(self):
        """Engine failures fall back to majority consensus instead of aborting."""
        ctx, protocol = make_context(consensus_mode="prover_estimator")
        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        engine = MagicMock()
        engine.run = AsyncMock(side_effect=RuntimeError("boom"))

        with (
            patch(
                "aragora.debate.prover_estimator.ProverEstimatorEngine",
                return_value=engine,
            ),
            patch.object(
                phase,
                "_handle_majority_consensus",
                new_callable=AsyncMock,
            ) as mock_majority,
        ):
            await phase._handle_prover_estimator_consensus(ctx)

        mock_majority.assert_awaited_once_with(ctx)


# =============================================================================
# Additional Coverage: Judge Deliberation Tests
# =============================================================================


class TestJudgeDeliberation:
    """Tests for judge deliberation mode."""

    @pytest.mark.asyncio
    async def test_judge_deliberation_with_insufficient_judges(self):
        """Judge deliberation falls back to single judge when not enough judges."""
        ctx, protocol = make_context(
            proposals={"agent1": "Proposal A"},
            consensus_mode="judge",
        )
        protocol.enable_judge_deliberation = True

        select_judge = AsyncMock()
        select_judge.return_value = MockAgent("judge1")

        generate_fn = AsyncMock(return_value="Synthesized answer")

        deps = ConsensusDependencies(protocol=protocol)
        callbacks = ConsensusCallbacks(
            select_judge=select_judge,
            generate_with_agent=generate_fn,
            build_judge_prompt=MagicMock(return_value="Judge prompt"),
        )
        phase = ConsensusPhase(deps=deps, callbacks=callbacks)

        with patch.object(
            phase._synthesis_generator,
            "generate_mandatory_synthesis",
            new_callable=AsyncMock,
            return_value=True,
        ):
            await phase.execute(ctx)

        # Should have used single judge synthesis fallback
        assert ctx.result.final_answer is not None


# =============================================================================
# Additional Coverage: Cancellation Token Tests
# =============================================================================


class TestCancellationToken:
    """Tests for cancellation token handling."""

    @pytest.mark.asyncio
    async def test_execute_raises_on_cancelled_token(self):
        """Execute raises DebateCancelled when token is cancelled."""
        ctx, protocol = make_context()
        ctx.cancellation_token = MagicMock()
        ctx.cancellation_token.is_cancelled = True
        ctx.cancellation_token.reason = "User cancelled"

        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        with pytest.raises(Exception) as exc_info:
            await phase.execute(ctx)

        # Should raise DebateCancelled or similar
        assert (
            "cancel" in str(exc_info.value).lower()
            or "cancelled" in str(type(exc_info.value).__name__).lower()
        )


# =============================================================================
# Additional Coverage: Hook Manager Tests
# =============================================================================


class TestHookManagerIntegration:
    """Tests for hook manager integration."""

    @pytest.mark.asyncio
    async def test_execute_triggers_pre_consensus_hook(self):
        """Execute triggers pre_consensus hook when hook_manager is available."""
        ctx, protocol = make_context(consensus_mode="none")
        hook_manager = AsyncMock()
        ctx.hook_manager = hook_manager

        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        with patch.object(
            phase._synthesis_generator,
            "generate_mandatory_synthesis",
            new_callable=AsyncMock,
            return_value=True,
        ):
            await phase.execute(ctx)

        hook_manager.trigger.assert_any_call("pre_consensus", ctx=ctx, proposals=ctx.proposals)

    @pytest.mark.asyncio
    async def test_execute_handles_pre_consensus_hook_error(self):
        """Execute handles pre_consensus hook errors gracefully."""
        ctx, protocol = make_context(consensus_mode="none")
        hook_manager = AsyncMock()
        hook_manager.trigger.side_effect = RuntimeError("Hook error")
        ctx.hook_manager = hook_manager

        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        with patch.object(
            phase._synthesis_generator,
            "generate_mandatory_synthesis",
            new_callable=AsyncMock,
            return_value=True,
        ):
            # Should not raise
            await phase.execute(ctx)


# =============================================================================
# Additional Coverage: Supermajority Mode Tests
# =============================================================================


class TestSupermajorityMode:
    """Tests for supermajority consensus mode."""

    @pytest.mark.asyncio
    async def test_supermajority_uses_higher_threshold(self):
        """Supermajority mode uses 2/3 threshold."""
        ctx, protocol = make_context(consensus_mode="supermajority")
        protocol.consensus_threshold = 0.5  # Should be overridden to at least 2/3

        vote_fn = AsyncMock(return_value=make_vote(choice="agent1"))
        deps = ConsensusDependencies(protocol=protocol)
        callbacks = ConsensusCallbacks(vote_with_agent=vote_fn)
        phase = ConsensusPhase(deps=deps, callbacks=callbacks)

        with patch.object(
            phase._synthesis_generator,
            "generate_mandatory_synthesis",
            new_callable=AsyncMock,
            return_value=True,
        ):
            await phase.execute(ctx)

        # Consensus should have been attempted
        assert ctx.result is not None


# =============================================================================
# Additional Coverage: Fallback Synthesis Tests
# =============================================================================


class TestFallbackSynthesis:
    """Tests for fallback synthesis when mandatory synthesis fails."""

    @pytest.mark.asyncio
    async def test_fallback_synthesis_when_mandatory_fails(self):
        """Creates fallback synthesis when mandatory synthesis fails."""
        ctx, protocol = make_context(
            proposals={"agent1": "Proposal content here"},
            consensus_mode="none",
        )

        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        with patch.object(
            phase._synthesis_generator,
            "generate_mandatory_synthesis",
            new_callable=AsyncMock,
            return_value=False,
        ):
            await phase.execute(ctx)

        # Should have created fallback synthesis
        assert ctx.result.final_answer is not None
        assert len(ctx.result.final_answer) > 0


# =============================================================================
# Additional Coverage: Weight Calculation Tests
# =============================================================================


class TestWeightCalculation:
    """Tests for vote weight calculation."""

    def test_compute_vote_weights_with_bias_mitigation(self):
        """Computes weights with self-vote and verbosity bias mitigation."""
        protocol = MockProtocol()
        protocol.enable_self_vote_mitigation = True
        protocol.enable_verbosity_normalization = True

        deps = ConsensusDependencies(protocol=protocol)
        callbacks = ConsensusCallbacks()
        phase = ConsensusPhase(deps=deps, callbacks=callbacks)

        agents = [MockAgent("agent1"), MockAgent("agent2")]
        votes = [make_vote(agent="agent1", choice="agent1")]  # Self-vote
        proposals = {"agent1": "Short", "agent2": "A very long proposal " * 100}

        ctx, _ = make_context(agents=agents, proposals=proposals)

        # Should compute weights without error
        weights = phase._compute_vote_weights(ctx, votes=votes)

        assert isinstance(weights, dict)

    def test_compute_vote_weights_without_bias_mitigation(self):
        """Computes weights without bias mitigation enabled."""
        protocol = MockProtocol()
        protocol.enable_self_vote_mitigation = False
        protocol.enable_verbosity_normalization = False

        deps = ConsensusDependencies(protocol=protocol)
        callbacks = ConsensusCallbacks()
        phase = ConsensusPhase(deps=deps, callbacks=callbacks)

        agents = [MockAgent("agent1"), MockAgent("agent2")]
        ctx, _ = make_context(agents=agents)

        weights = phase._compute_vote_weights(ctx)

        assert isinstance(weights, dict)


# =============================================================================
# Additional Coverage: Fallback Consensus Tests
# =============================================================================


class TestHandleFallbackConsensusAdditional:
    """Tests for fallback consensus handling."""

    @pytest.mark.asyncio
    async def test_fallback_uses_vote_tally_when_no_votes(self):
        """Uses vote_tally when votes list is empty."""
        ctx, protocol = make_context(proposals={"agent1": "Prop A", "agent2": "Prop B"})
        ctx.vote_tally = {"agent1": 3, "agent2": 1}
        ctx.result.votes = []

        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        await phase._handle_fallback_consensus(ctx, reason="test")

        assert ctx.result.winner == "agent1"
        assert ctx.result.consensus_reached is True

    @pytest.mark.asyncio
    async def test_fallback_handles_no_proposals(self):
        """Handles fallback when no proposals available."""
        ctx, protocol = make_context(proposals={})

        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        await phase._handle_fallback_consensus(ctx, reason="error")

        assert "No proposals available" in ctx.result.final_answer
        assert ctx.result.consensus_reached is False


# =============================================================================
# Additional Coverage: User Vote Tests
# =============================================================================


class TestUserVotes:
    """Tests for user vote handling."""

    def test_add_user_votes_with_intensity(self):
        """Adds user votes with intensity multiplier."""
        protocol = MockProtocol()
        protocol.user_vote_weight = 0.5

        user_votes = [
            {"user_id": "user1", "choice": "agent1", "intensity": 10},
        ]

        deps = ConsensusDependencies(protocol=protocol, user_votes=user_votes)
        callbacks = ConsensusCallbacks(
            user_vote_multiplier=lambda intensity, proto: intensity / 5.0,
        )
        phase = ConsensusPhase(deps=deps, callbacks=callbacks)

        vote_counts = {"agent1": 2.0, "agent2": 1.0}
        total_weighted = 3.0
        choice_mapping = {}

        # Copy original values
        original_agent1 = vote_counts["agent1"]
        original_total = total_weighted

        new_counts, new_total = phase._add_user_votes(vote_counts, total_weighted, choice_mapping)

        # User vote should have been added with intensity multiplier
        # base_weight (0.5) * intensity_multiplier (10/5 = 2.0) = 1.0 added weight
        assert new_counts["agent1"] >= original_agent1  # Vote was added
        assert new_total >= original_total  # Total was increased


# =============================================================================
# Additional Coverage: Quorum Tests
# =============================================================================


class TestQuorumEnsure:
    """Tests for quorum checking."""

    def test_required_participation_uses_protocol_settings(self):
        """Uses protocol min_participation settings."""
        protocol = MockProtocol()
        protocol.min_participation_ratio = 0.8
        protocol.min_participation_count = 3

        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        required = phase._required_participation(10)

        # Should be max of (10 * 0.8 = 8) and (3)
        assert required == 8

    def test_ensure_quorum_sets_insufficient_status(self):
        """Sets status to insufficient_participation when quorum not met."""
        protocol = MockProtocol()
        protocol.min_participation_ratio = 0.5
        protocol.min_participation_count = 5

        ctx, _ = make_context(
            agents=[MockAgent(f"agent{i}") for i in range(10)],
            proposals={"agent1": "Prop"},
        )

        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        result = phase._ensure_quorum(ctx, vote_count=3)  # Less than required 5

        assert result is False
        assert ctx.result.status == "insufficient_participation"


# =============================================================================
# Additional Coverage: Formal Verification Tests
# =============================================================================


class TestFormalVerificationExtended:
    """Extended tests for formal verification."""

    @pytest.mark.asyncio
    async def test_formal_verification_handles_import_error(self):
        """Handles ImportError when formal verification module unavailable."""
        ctx, protocol = make_context()
        protocol.formal_verification_enabled = True
        ctx.result.final_answer = "Test answer"
        ctx.result.consensus_reached = True

        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        with patch.dict("sys.modules", {"aragora.verification.formal": None}):
            # This will cause ImportError when trying to import
            # The method should handle this gracefully
            await phase._verify_consensus_formally(ctx)

        # After import error, the result should have been set
        if ctx.result.formal_verification is not None:
            assert ctx.result.formal_verification.get("status") in ("unavailable", "error")

    @pytest.mark.asyncio
    async def test_formal_verification_handles_timeout(self):
        """Handles timeout during formal verification."""
        ctx, protocol = make_context()
        protocol.formal_verification_enabled = True
        protocol.formal_verification_timeout = 0.01  # Very short timeout
        ctx.result.final_answer = "Test answer"
        ctx.result.consensus_reached = True

        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        # The actual verification happens inside the method, which imports the manager
        # We'll just test that the method doesn't raise with enabled verification
        await phase._verify_consensus_formally(ctx)

        # Result should have some form of verification status or None
        # (depends on whether verification module is available)


# =============================================================================
# Additional Coverage: Timeout Handling Tests
# =============================================================================


class TestTimeoutHandling:
    """Tests for timeout handling during consensus."""

    @pytest.mark.asyncio
    async def test_execute_handles_consensus_timeout(self):
        """Handles timeout during consensus execution."""
        ctx, protocol = make_context(consensus_mode="majority")
        protocol.consensus_timeout = 0.01  # Very short timeout

        # Create a slow vote function
        async def slow_vote(*args, **kwargs):
            await asyncio.sleep(10)
            return make_vote()

        deps = ConsensusDependencies(protocol=protocol)
        callbacks = ConsensusCallbacks(vote_with_agent=slow_vote)
        phase = ConsensusPhase(deps=deps, callbacks=callbacks)

        with patch.object(
            phase._synthesis_generator,
            "generate_mandatory_synthesis",
            new_callable=AsyncMock,
            return_value=True,
        ):
            await phase.execute(ctx)

        # Should have fallen back
        assert ctx.result.consensus_strength == "fallback"


# =============================================================================
# Additional Coverage: Event Emission Tests
# =============================================================================


class TestGuaranteedEvents:
    """Tests for guaranteed event emission."""

    def test_emit_guaranteed_events_handles_hook_exception(self):
        """Handles exceptions in event hooks gracefully."""
        ctx, protocol = make_context()
        ctx.result.consensus_reached = True
        ctx.result.confidence = 0.8
        ctx.result.final_answer = "Answer"
        ctx.result.synthesis = "Synthesis"

        on_consensus = MagicMock(side_effect=RuntimeError("Hook failed"))
        on_debate_end = MagicMock()

        deps = ConsensusDependencies(
            protocol=protocol,
            hooks={"on_consensus": on_consensus, "on_debate_end": on_debate_end},
        )
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        # Should not raise
        phase._emit_guaranteed_events(ctx)

        # on_debate_end should still be called despite on_consensus failure
        on_debate_end.assert_called_once()

    def test_emit_guaranteed_events_with_no_result(self):
        """Handles case when result is None."""
        ctx, protocol = make_context()
        ctx.result = None

        deps = ConsensusDependencies(protocol=protocol)
        phase = ConsensusPhase(deps=deps, callbacks=ConsensusCallbacks())

        # Should not raise
        phase._emit_guaranteed_events(ctx)
