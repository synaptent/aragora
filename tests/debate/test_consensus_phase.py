"""
Tests for aragora.debate.phases.consensus_phase module.

Tests ConsensusPhase class and voting/consensus resolution.
"""

import pytest
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional
from unittest.mock import MagicMock, AsyncMock

from aragora.debate.context import DebateContext
from aragora.debate.phases.consensus_phase import ConsensusPhase


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
    stance: str | None = None


@dataclass
class MockVote:
    """Mock vote for testing."""

    agent: str = "test_agent"
    choice: str = "proposal_a"
    confidence: float = 0.8
    reasoning: str = "Good proposal"


@dataclass
class MockDebateResult:
    """Mock debate result for testing."""

    id: str = "debate_001"
    votes: list = field(default_factory=list)
    critiques: list = field(default_factory=list)
    messages: list = field(default_factory=list)
    final_answer: str = ""
    consensus_reached: bool = False
    confidence: float = 0.0
    consensus_strength: str = ""
    consensus_variance: float = 0.0
    dissenting_views: list = field(default_factory=list)
    rounds_used: int = 0
    debate_cruxes: list = field(default_factory=list)
    # Mirrors DebateResult.metadata (aragora/core_types.py); the consensus phase
    # records vote participation there.
    metadata: dict = field(default_factory=dict)
    evidence_suggestions: list = field(default_factory=list)
    winner: str | None = None  # Added for synthesis generation
    synthesis: str | None = None  # Added for synthesis generation


@dataclass
class MockProtocol:
    """Mock protocol for testing."""

    consensus: str = "majority"
    consensus_threshold: float = 0.5
    user_vote_weight: float = 0.5
    rounds: int = 3
    judge_selection: str = "random"


# ============================================================================
# ConsensusPhase Construction Tests
# ============================================================================


class TestConsensusPhaseConstruction:
    """Tests for ConsensusPhase construction."""

    def test_minimal_construction(self):
        """Should create with no arguments."""
        phase = ConsensusPhase()
        assert phase.protocol is None
        assert phase.hooks == {}

    def test_full_construction(self):
        """Should create with all arguments."""
        protocol = MockProtocol()
        hooks = {"on_vote": MagicMock()}

        phase = ConsensusPhase(
            protocol=protocol,
            elo_system=MagicMock(),
            memory=MagicMock(),
            hooks=hooks,
        )

        assert phase.protocol is protocol
        assert "on_vote" in phase.hooks


# ============================================================================
# None Consensus Mode Tests
# ============================================================================


class TestNoneConsensusMode:
    """Tests for 'none' consensus mode."""

    @pytest.mark.asyncio
    async def test_none_mode_combines_proposals(self):
        """Should combine all proposals without voting."""
        protocol = MockProtocol(consensus="none")
        phase = ConsensusPhase(protocol=protocol)

        ctx = DebateContext(env=MockEnvironment())
        ctx.proposals = {"claude": "Proposal A", "gpt4": "Proposal B"}
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        # Synthesis uses markdown format: **agent:** or just agent name
        assert "claude" in ctx.result.final_answer
        assert "gpt4" in ctx.result.final_answer
        assert ctx.result.consensus_reached is False
        assert ctx.result.confidence == 0.5


# ============================================================================
# Majority Consensus Mode Tests
# ============================================================================


class TestMajorityConsensusMode:
    """Tests for 'majority' consensus mode."""

    @pytest.mark.asyncio
    async def test_majority_voting(self):
        """Should collect votes and determine majority winner."""
        protocol = MockProtocol(consensus="majority", consensus_threshold=0.5)

        async def vote_with_agent(agent, proposals, task):
            return MockVote(agent=agent.name, choice="claude", confidence=0.8)

        phase = ConsensusPhase(
            protocol=protocol,
            vote_with_agent=vote_with_agent,
            group_similar_votes=lambda votes: {"claude": ["claude"]},
        )

        agents = [MockAgent(name="claude"), MockAgent(name="gpt4")]
        ctx = DebateContext(env=MockEnvironment(), agents=agents)
        ctx.proposals = {"claude": "Proposal A", "gpt4": "Proposal B"}
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        assert ctx.result.consensus_reached is True
        assert ctx.result.confidence == 1.0  # All votes for same choice

    @pytest.mark.asyncio
    async def test_majority_no_consensus(self):
        """Should detect when consensus threshold not met."""
        protocol = MockProtocol(consensus="majority", consensus_threshold=0.8)

        vote_idx = [0]

        async def vote_with_agent(agent, proposals, task):
            vote_idx[0] += 1
            if vote_idx[0] == 1:
                return MockVote(agent=agent.name, choice="claude", confidence=0.8)
            return MockVote(agent=agent.name, choice="gpt4", confidence=0.7)

        phase = ConsensusPhase(
            protocol=protocol,
            vote_with_agent=vote_with_agent,
            group_similar_votes=lambda votes: {"claude": ["claude"], "gpt4": ["gpt4"]},
        )

        agents = [MockAgent(name="claude"), MockAgent(name="gpt4")]
        ctx = DebateContext(env=MockEnvironment(), agents=agents)
        ctx.proposals = {"claude": "Proposal A", "gpt4": "Proposal B"}
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        assert ctx.result.consensus_reached is False
        assert ctx.result.confidence == 0.5  # 50% for winner

    @pytest.mark.asyncio
    async def test_weighted_voting(self):
        """Should apply vote weights from various sources."""
        protocol = MockProtocol(consensus="majority")

        async def vote_with_agent(agent, proposals, task):
            return MockVote(agent=agent.name, choice="claude", confidence=0.8)

        phase = ConsensusPhase(
            protocol=protocol,
            vote_with_agent=vote_with_agent,
            agent_weights={"claude": 0.5, "gpt4": 1.5},
            group_similar_votes=lambda votes: {"claude": ["claude"]},
        )

        agents = [MockAgent(name="claude"), MockAgent(name="gpt4")]
        ctx = DebateContext(env=MockEnvironment(), agents=agents)
        ctx.proposals = {"claude": "Proposal A"}
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        # Should have applied weights
        assert ctx.result.consensus_reached is True

    @pytest.mark.asyncio
    async def test_emit_vote_hook(self):
        """Should emit on_vote hook for each vote."""
        protocol = MockProtocol(consensus="majority")
        on_vote = MagicMock()

        async def vote_with_agent(agent, proposals, task):
            return MockVote(agent=agent.name, choice="claude", confidence=0.8)

        phase = ConsensusPhase(
            protocol=protocol,
            vote_with_agent=vote_with_agent,
            hooks={"on_vote": on_vote},
            group_similar_votes=lambda votes: {"claude": ["claude"]},
        )

        agents = [MockAgent(name="claude")]
        ctx = DebateContext(env=MockEnvironment(), agents=agents)
        ctx.proposals = {"claude": "Proposal A"}
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        on_vote.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_vote_to_recorder(self):
        """Should record votes to recorder."""
        protocol = MockProtocol(consensus="majority")
        recorder = MagicMock()

        async def vote_with_agent(agent, proposals, task):
            return MockVote(agent=agent.name, choice="claude", confidence=0.8)

        phase = ConsensusPhase(
            protocol=protocol,
            vote_with_agent=vote_with_agent,
            recorder=recorder,
            group_similar_votes=lambda votes: {"claude": ["claude"]},
        )

        agents = [MockAgent(name="claude")]
        ctx = DebateContext(env=MockEnvironment(), agents=agents)
        ctx.proposals = {"claude": "Proposal A"}
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        recorder.record_vote.assert_called_once()


# ============================================================================
# Unanimous Consensus Mode Tests
# ============================================================================


class TestUnanimousConsensusMode:
    """Tests for 'unanimous' consensus mode."""

    @pytest.mark.asyncio
    async def test_unanimous_success(self):
        """Should detect unanimous consensus."""
        protocol = MockProtocol(consensus="unanimous")

        async def vote_with_agent(agent, proposals, task):
            return MockVote(agent=agent.name, choice="claude", confidence=0.9)

        phase = ConsensusPhase(
            protocol=protocol,
            vote_with_agent=vote_with_agent,
            group_similar_votes=lambda votes: {"claude": ["claude"]},
        )

        agents = [MockAgent(name="claude"), MockAgent(name="gpt4")]
        ctx = DebateContext(env=MockEnvironment(), agents=agents)
        ctx.proposals = {"claude": "Proposal A"}
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        assert ctx.result.consensus_reached is True
        assert ctx.result.consensus_strength == "unanimous"

    @pytest.mark.asyncio
    async def test_unanimous_failure(self):
        """Should detect when unanimity not achieved."""
        protocol = MockProtocol(consensus="unanimous")

        vote_idx = [0]

        async def vote_with_agent(agent, proposals, task):
            vote_idx[0] += 1
            if vote_idx[0] == 1:
                return MockVote(agent=agent.name, choice="claude", confidence=0.8)
            return MockVote(agent=agent.name, choice="gpt4", confidence=0.8)

        phase = ConsensusPhase(
            protocol=protocol,
            vote_with_agent=vote_with_agent,
            group_similar_votes=lambda votes: {"claude": ["claude"], "gpt4": ["gpt4"]},
        )

        agents = [MockAgent(name="claude"), MockAgent(name="gpt4")]
        ctx = DebateContext(env=MockEnvironment(), agents=agents)
        ctx.proposals = {"claude": "Proposal A", "gpt4": "Proposal B"}
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        assert ctx.result.consensus_reached is False
        assert ctx.result.consensus_strength == "none"
        assert ctx.result.synthesis == ctx.result.final_answer
        assert "Proposal A" in ctx.result.final_answer
        assert "Proposal B" in ctx.result.final_answer

    @pytest.mark.asyncio
    async def test_unanimous_with_voting_errors(self):
        """Should count voting errors as dissent."""
        protocol = MockProtocol(consensus="unanimous")

        async def vote_with_agent(agent, proposals, task):
            if agent.name == "gpt4":
                raise Exception("Vote error")
            return MockVote(agent=agent.name, choice="claude", confidence=0.9)

        phase = ConsensusPhase(
            protocol=protocol,
            vote_with_agent=vote_with_agent,
            group_similar_votes=lambda votes: {"claude": ["claude"]},
        )

        agents = [MockAgent(name="claude"), MockAgent(name="gpt4")]
        ctx = DebateContext(env=MockEnvironment(), agents=agents)
        ctx.proposals = {"claude": "Proposal A"}
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        # Voting errors count as dissent for unanimous consensus.
        assert ctx.result.consensus_reached is False
        assert ctx.result.consensus_strength == "none"
        assert ctx.result.confidence == pytest.approx(0.5, rel=0.01)
        assert "Proposal A" in ctx.result.final_answer
        assert ctx.result.synthesis == ctx.result.final_answer


# ============================================================================
# Judge Consensus Mode Tests
# ============================================================================


class TestJudgeConsensusMode:
    """Tests for 'judge' consensus mode."""

    @pytest.mark.asyncio
    async def test_judge_synthesis(self):
        """Should use judge to synthesize final answer."""
        protocol = MockProtocol(consensus="judge", judge_selection="random")

        judge = MockAgent(name="judge_claude", role="judge")

        phase = ConsensusPhase(
            protocol=protocol,
            select_judge=AsyncMock(return_value=judge),
            build_judge_prompt=MagicMock(return_value="Synthesize these proposals"),
            generate_with_agent=AsyncMock(return_value="Synthesized answer"),
        )

        agents = [MockAgent(name="claude"), MockAgent(name="gpt4")]
        ctx = DebateContext(env=MockEnvironment(), agents=agents)
        ctx.proposals = {"claude": "Proposal A", "gpt4": "Proposal B"}
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        assert ctx.result.consensus_reached is True
        assert ctx.result.confidence == 0.8
        assert ctx.result.synthesis == ctx.result.final_answer
        assert "Proposal A" in ctx.result.final_answer
        assert "Proposal B" in ctx.result.final_answer

    @pytest.mark.asyncio
    async def test_judge_error_fallback(self):
        """Should fall back to first proposal on judge error."""
        protocol = MockProtocol(consensus="judge")

        judge = MockAgent(name="judge_claude", role="judge")

        phase = ConsensusPhase(
            protocol=protocol,
            select_judge=AsyncMock(return_value=judge),
            build_judge_prompt=MagicMock(return_value="Synthesize"),
            generate_with_agent=AsyncMock(side_effect=Exception("Judge error")),
        )

        agents = [MockAgent(name="claude")]
        ctx = DebateContext(env=MockEnvironment(), agents=agents)
        ctx.proposals = {"claude": "Fallback proposal"}
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        # Output now includes fallback header
        assert "Fallback proposal" in ctx.result.final_answer
        assert ctx.result.consensus_reached is False

    @pytest.mark.asyncio
    async def test_emit_judge_selected_hook(self):
        """Should emit on_judge_selected hook."""
        protocol = MockProtocol(consensus="judge", judge_selection="voted")
        on_judge = MagicMock()

        judge = MockAgent(name="judge_claude", role="judge")

        phase = ConsensusPhase(
            protocol=protocol,
            select_judge=AsyncMock(return_value=judge),
            build_judge_prompt=MagicMock(return_value="Synthesize"),
            generate_with_agent=AsyncMock(return_value="Answer"),
            hooks={"on_judge_selected": on_judge},
        )

        ctx = DebateContext(env=MockEnvironment(), agents=[])
        ctx.proposals = {"claude": "Proposal"}
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        on_judge.assert_called_once_with("judge_claude", "voted")


# ============================================================================
# Vote Grouping Tests
# ============================================================================


class TestVoteGrouping:
    """Tests for vote grouping and choice mapping."""

    @pytest.mark.asyncio
    async def test_group_similar_votes(self):
        """Should group similar vote choices."""
        protocol = MockProtocol(consensus="majority")

        async def vote_with_agent(agent, proposals, task):
            return MockVote(agent=agent.name, choice="Claude's proposal", confidence=0.8)

        def group_similar(votes):
            return {"claude": ["claude", "Claude's proposal"]}

        phase = ConsensusPhase(
            protocol=protocol,
            vote_with_agent=vote_with_agent,
            group_similar_votes=group_similar,
        )

        agents = [MockAgent(name="claude")]
        ctx = DebateContext(env=MockEnvironment(), agents=agents)
        ctx.proposals = {"claude": "Proposal A"}
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        # Vote should be counted under canonical choice
        assert ctx.result.consensus_reached is True


# ============================================================================
# User Vote Tests
# ============================================================================


class TestUserVotes:
    """Tests for user vote handling."""

    @pytest.mark.asyncio
    async def test_include_user_votes(self):
        """Should include user votes in majority count."""
        protocol = MockProtocol(consensus="majority", user_vote_weight=0.5)

        async def vote_with_agent(agent, proposals, task):
            return MockVote(agent=agent.name, choice="gpt4", confidence=0.8)

        user_votes = [{"choice": "claude", "user_id": "user1", "intensity": 5}]

        phase = ConsensusPhase(
            protocol=protocol,
            vote_with_agent=vote_with_agent,
            user_votes=user_votes,
            drain_user_events=MagicMock(),
            group_similar_votes=lambda votes: {"claude": ["claude"], "gpt4": ["gpt4"]},
        )

        agents = [MockAgent(name="gpt4")]
        ctx = DebateContext(env=MockEnvironment(), agents=agents)
        ctx.proposals = {"claude": "Proposal A", "gpt4": "Proposal B"}
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        # User vote should be counted (with weight 0.5)
        assert "claude" in ctx.vote_tally or "gpt4" in ctx.vote_tally


# ============================================================================
# Calibration Tracker Tests
# ============================================================================


class TestCalibrationTracking:
    """Tests for calibration prediction tracking."""

    @pytest.mark.asyncio
    async def test_record_calibration_predictions(self):
        """Should record calibration predictions."""
        protocol = MockProtocol(consensus="majority")
        calibration = MagicMock()

        async def vote_with_agent(agent, proposals, task):
            return MockVote(agent=agent.name, choice="claude", confidence=0.9)

        phase = ConsensusPhase(
            protocol=protocol,
            vote_with_agent=vote_with_agent,
            calibration_tracker=calibration,
            extract_debate_domain=lambda: "test_domain",
            group_similar_votes=lambda votes: {"claude": ["claude"]},
        )

        agents = [MockAgent(name="claude")]
        ctx = DebateContext(env=MockEnvironment(), agents=agents)
        ctx.proposals = {"claude": "Proposal A"}
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        calibration.record_prediction.assert_called_once()


# ============================================================================
# Position Tracker Tests
# ============================================================================


class TestPositionTracking:
    """Tests for position tracker integration."""

    @pytest.mark.asyncio
    async def test_record_vote_position(self):
        """Should record vote position."""
        protocol = MockProtocol(consensus="majority")
        position_tracker = MagicMock()

        async def vote_with_agent(agent, proposals, task):
            return MockVote(agent=agent.name, choice="claude", confidence=0.8)

        phase = ConsensusPhase(
            protocol=protocol,
            vote_with_agent=vote_with_agent,
            position_tracker=position_tracker,
            group_similar_votes=lambda votes: {"claude": ["claude"]},
        )

        agents = [MockAgent(name="claude")]
        ctx = DebateContext(env=MockEnvironment(), agents=agents)
        ctx.proposals = {"claude": "Proposal A"}
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        position_tracker.record_position.assert_called()

    @pytest.mark.asyncio
    async def test_finalize_debate_position(self):
        """Should finalize debate for position tracker."""
        protocol = MockProtocol(consensus="majority")
        position_tracker = MagicMock()

        async def vote_with_agent(agent, proposals, task):
            return MockVote(agent=agent.name, choice="claude", confidence=0.8)

        phase = ConsensusPhase(
            protocol=protocol,
            vote_with_agent=vote_with_agent,
            position_tracker=position_tracker,
            group_similar_votes=lambda votes: {"claude": ["claude"]},
        )

        agents = [MockAgent(name="claude")]
        ctx = DebateContext(env=MockEnvironment(), agents=agents)
        ctx.proposals = {"claude": "Proposal A"}
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        position_tracker.finalize_debate.assert_called_once()


# ============================================================================
# Spectator Notification Tests
# ============================================================================


class TestSpectatorNotifications:
    """Tests for spectator notifications."""

    @pytest.mark.asyncio
    async def test_notify_spectator_on_vote(self):
        """Should notify spectator of votes."""
        protocol = MockProtocol(consensus="majority")
        notify = MagicMock()

        async def vote_with_agent(agent, proposals, task):
            return MockVote(agent=agent.name, choice="claude", confidence=0.8)

        phase = ConsensusPhase(
            protocol=protocol,
            vote_with_agent=vote_with_agent,
            notify_spectator=notify,
            group_similar_votes=lambda votes: {"claude": ["claude"]},
        )

        agents = [MockAgent(name="claude")]
        ctx = DebateContext(env=MockEnvironment(), agents=agents)
        ctx.proposals = {"claude": "Proposal A"}
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        # Should be called for vote and consensus
        assert notify.call_count >= 2

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_notify_spectator_on_consensus(self):
        """Should notify spectator of consensus result."""
        protocol = MockProtocol(consensus="majority")
        notify = MagicMock()

        async def vote_with_agent(agent, proposals, task):
            return MockVote(agent=agent.name, choice="claude", confidence=0.8)

        phase = ConsensusPhase(
            protocol=protocol,
            vote_with_agent=vote_with_agent,
            notify_spectator=notify,
            group_similar_votes=lambda votes: {"claude": ["claude"]},
        )

        agents = [MockAgent(name="claude")]
        ctx = DebateContext(env=MockEnvironment(), agents=agents)
        ctx.proposals = {"claude": "Proposal A"}
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        # Check consensus notification
        consensus_calls = [c for c in notify.call_args_list if c[0][0] == "consensus"]
        assert len(consensus_calls) >= 1


# ============================================================================
# Edge Case Tests
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases."""

    @pytest.mark.asyncio
    async def test_empty_agents(self):
        """Should handle empty agents list."""
        protocol = MockProtocol(consensus="majority")

        phase = ConsensusPhase(
            protocol=protocol,
            vote_with_agent=AsyncMock(),
            group_similar_votes=lambda votes: {},
        )

        ctx = DebateContext(env=MockEnvironment(), agents=[])
        ctx.proposals = {"claude": "Proposal A"}
        ctx.result = MockDebateResult()

        # Should not raise
        await phase.execute(ctx)

    @pytest.mark.asyncio
    async def test_empty_proposals(self):
        """Should handle empty proposals."""
        protocol = MockProtocol(consensus="none")

        phase = ConsensusPhase(protocol=protocol)

        ctx = DebateContext(env=MockEnvironment())
        ctx.proposals = {}
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        # With no proposals, the consensus phase sets a descriptive fallback message
        assert "No proposals" in ctx.result.final_answer

    @pytest.mark.asyncio
    async def test_unknown_consensus_mode(self):
        """Should fall back to none mode for unknown consensus."""
        protocol = MockProtocol(consensus="unknown_mode")

        phase = ConsensusPhase(protocol=protocol)

        ctx = DebateContext(env=MockEnvironment())
        ctx.proposals = {"claude": "Proposal A"}
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        assert ctx.result.consensus_reached is False

    @pytest.mark.asyncio
    async def test_vote_error_handling(self):
        """Should continue on vote errors."""
        protocol = MockProtocol(consensus="majority")

        async def vote_with_agent(agent, proposals, task):
            if agent.name == "error_agent":
                raise Exception("Vote failed")
            return MockVote(agent=agent.name, choice="claude", confidence=0.8)

        phase = ConsensusPhase(
            protocol=protocol,
            vote_with_agent=vote_with_agent,
            group_similar_votes=lambda votes: {"claude": ["claude"]},
        )

        agents = [MockAgent(name="claude"), MockAgent(name="error_agent")]
        ctx = DebateContext(env=MockEnvironment(), agents=agents)
        ctx.proposals = {"claude": "Proposal A"}
        ctx.result = MockDebateResult()

        # Should not raise
        await phase.execute(ctx)

        # Should have one successful vote
        assert len(ctx.result.votes) == 1


# ============================================================================
# Phase 11C: Extended Edge Case Tests
# ============================================================================


class TestPhase11CEdgeCases:
    """Phase 11C: Extended edge case tests for consensus phase hardening."""

    @pytest.mark.asyncio
    async def test_unanimous_dissent(self):
        """All agents vote differently - should not reach consensus."""
        protocol = MockProtocol(consensus="majority", consensus_threshold=0.5)

        vote_choices = ["proposal_a", "proposal_b", "proposal_c", "proposal_d"]
        vote_idx = [0]

        async def vote_with_agent(agent, proposals, task):
            choice = vote_choices[vote_idx[0] % len(vote_choices)]
            vote_idx[0] += 1
            return MockVote(agent=agent.name, choice=choice, confidence=0.8)

        phase = ConsensusPhase(
            protocol=protocol,
            vote_with_agent=vote_with_agent,
            group_similar_votes=lambda votes: {
                "proposal_a": ["proposal_a"],
                "proposal_b": ["proposal_b"],
                "proposal_c": ["proposal_c"],
                "proposal_d": ["proposal_d"],
            },
        )

        agents = [
            MockAgent(name="agent_1"),
            MockAgent(name="agent_2"),
            MockAgent(name="agent_3"),
            MockAgent(name="agent_4"),
        ]
        ctx = DebateContext(env=MockEnvironment(), agents=agents)
        ctx.proposals = {
            "proposal_a": "A",
            "proposal_b": "B",
            "proposal_c": "C",
            "proposal_d": "D",
        }
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        # No majority (each has 25% < 50% threshold)
        assert ctx.result.consensus_reached is False
        assert ctx.result.confidence == 0.25  # 1/4 for each
        # consensus_strength is set based on winner confidence, not consensus_reached
        # With 4 equal votes, winner has 0.25 confidence which maps to "strong" in some modes

    @pytest.mark.asyncio
    async def test_verification_timeout_handling(self):
        """Z3 verification times out - should continue gracefully."""
        protocol = MockProtocol(consensus="majority")

        async def vote_with_agent(agent, proposals, task):
            return MockVote(agent=agent.name, choice="claude", confidence=0.8)

        # Mock verify_claims that times out
        async def verify_claims_timeout(proposal_text, limit=2):
            # Simulates timeout by returning minimal result
            return {"verified": 0, "disproven": 0}

        phase = ConsensusPhase(
            protocol=protocol,
            vote_with_agent=vote_with_agent,
            verify_claims=verify_claims_timeout,
            group_similar_votes=lambda votes: {"claude": ["claude"]},
        )

        agents = [MockAgent(name="claude")]
        ctx = DebateContext(env=MockEnvironment(), agents=agents)
        ctx.proposals = {"claude": "Proposal with claims"}
        ctx.result = MockDebateResult()

        # Should not raise even with "timeout"
        await phase.execute(ctx)

        assert ctx.result.consensus_reached is True
        # No verification bonus applied due to timeout
        assert ctx.result.confidence > 0

    @pytest.mark.asyncio
    async def test_all_agents_fail_voting(self):
        """All agents fail during voting - should handle gracefully."""
        protocol = MockProtocol(consensus="majority")

        async def vote_with_agent(agent, proposals, task):
            raise Exception(f"Agent {agent.name} failed to vote")

        phase = ConsensusPhase(
            protocol=protocol,
            vote_with_agent=vote_with_agent,
            group_similar_votes=lambda votes: {},
        )

        agents = [MockAgent(name="agent_1"), MockAgent(name="agent_2")]
        ctx = DebateContext(env=MockEnvironment(), agents=agents)
        ctx.proposals = {"agent_1": "Proposal A"}
        ctx.result = MockDebateResult()

        # Should not raise
        await phase.execute(ctx)

        # No votes collected
        assert len(ctx.result.votes) == 0
        assert ctx.result.consensus_reached is False

    @pytest.mark.asyncio
    async def test_single_proposal_with_multiple_voters(self):
        """Single proposal should reach consensus if threshold met."""
        protocol = MockProtocol(consensus="majority", consensus_threshold=0.5)

        async def vote_with_agent(agent, proposals, task):
            return MockVote(agent=agent.name, choice="only_proposal", confidence=0.9)

        phase = ConsensusPhase(
            protocol=protocol,
            vote_with_agent=vote_with_agent,
            group_similar_votes=lambda votes: {"only_proposal": ["only_proposal"]},
        )

        agents = [MockAgent(name="a1"), MockAgent(name="a2"), MockAgent(name="a3")]
        ctx = DebateContext(env=MockEnvironment(), agents=agents)
        ctx.proposals = {"only_proposal": "The only proposal"}
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        assert ctx.result.consensus_reached is True
        assert ctx.result.confidence == 1.0
        assert ctx.result.consensus_strength == "unanimous"

    @pytest.mark.asyncio
    async def test_consensus_with_abstentions(self):
        """Some agents abstain (return None) - should count remaining votes."""
        protocol = MockProtocol(consensus="majority", consensus_threshold=0.5)

        vote_idx = [0]

        async def vote_with_agent(agent, proposals, task):
            vote_idx[0] += 1
            if vote_idx[0] == 2:
                # Return None to simulate abstention
                return None
            return MockVote(agent=agent.name, choice="proposal_a", confidence=0.8)

        phase = ConsensusPhase(
            protocol=protocol,
            vote_with_agent=vote_with_agent,
            group_similar_votes=lambda votes: {"proposal_a": ["proposal_a"]},
        )

        agents = [MockAgent(name="a1"), MockAgent(name="a2"), MockAgent(name="a3")]
        ctx = DebateContext(env=MockEnvironment(), agents=agents)
        ctx.proposals = {"proposal_a": "Proposal A"}
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        # 2 votes for proposal_a, 1 abstention
        assert len(ctx.result.votes) == 2
        assert ctx.result.consensus_reached is True

    @pytest.mark.asyncio
    async def test_extremely_high_consensus_threshold(self):
        """Threshold of 0.99 - nearly impossible to reach."""
        protocol = MockProtocol(consensus="majority", consensus_threshold=0.99)
        # Disable RLM early termination so all 10 agents vote
        protocol.enable_rlm_early_termination = False

        vote_idx = [0]

        async def vote_with_agent(agent, proposals, task):
            vote_idx[0] += 1
            if vote_idx[0] <= 9:
                return MockVote(agent=agent.name, choice="proposal_a", confidence=0.9)
            return MockVote(agent=agent.name, choice="proposal_b", confidence=0.9)

        phase = ConsensusPhase(
            protocol=protocol,
            vote_with_agent=vote_with_agent,
            group_similar_votes=lambda votes: {
                "proposal_a": ["proposal_a"],
                "proposal_b": ["proposal_b"],
            },
        )

        agents = [MockAgent(name=f"agent_{i}") for i in range(10)]
        ctx = DebateContext(env=MockEnvironment(), agents=agents)
        ctx.proposals = {"proposal_a": "A", "proposal_b": "B"}
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        # 90% < 99% threshold
        assert ctx.result.consensus_reached is False
        assert ctx.result.confidence == 0.9

    @pytest.mark.asyncio
    async def test_verification_disproven_claims_penalty(self):
        """Disproven claims should reduce agent credibility in voting."""
        protocol = MockProtocol(consensus="majority")
        protocol.verify_claims_during_consensus = True

        async def vote_with_agent(agent, proposals, task):
            return MockVote(agent=agent.name, choice="proposal_a", confidence=0.8)

        # Mock verify_claims that finds disproven claims
        async def verify_claims_disproven(proposal_text, limit=2):
            if "false_claim" in proposal_text:
                return {"verified": 0, "disproven": 2}
            return {"verified": 1, "disproven": 0}

        phase = ConsensusPhase(
            protocol=protocol,
            vote_with_agent=vote_with_agent,
            verify_claims=verify_claims_disproven,
            group_similar_votes=lambda votes: {"proposal_a": ["proposal_a"]},
        )

        agents = [MockAgent(name="claude")]
        ctx = DebateContext(env=MockEnvironment(), agents=agents)
        ctx.proposals = {"proposal_a": "This contains a false_claim"}
        ctx.result = MockDebateResult()
        ctx.result.verification_results = {}

        await phase.execute(ctx)

        # Phase should complete without error
        assert ctx.result.consensus_reached is True

    @pytest.mark.asyncio
    async def test_concurrent_vote_collection(self):
        """Votes should be collected even with varying response times."""
        import asyncio

        protocol = MockProtocol(consensus="majority")
        # Disable RLM early termination so all 5 agents complete voting
        protocol.enable_rlm_early_termination = False

        async def slow_vote(agent, proposals, task):
            await asyncio.sleep(0.01)  # Simulate network delay
            return MockVote(agent=agent.name, choice="proposal_a", confidence=0.8)

        phase = ConsensusPhase(
            protocol=protocol,
            vote_with_agent=slow_vote,
            group_similar_votes=lambda votes: {"proposal_a": ["proposal_a"]},
        )

        agents = [MockAgent(name=f"agent_{i}") for i in range(5)]
        ctx = DebateContext(env=MockEnvironment(), agents=agents)
        ctx.proposals = {"proposal_a": "Proposal"}
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        # All 5 votes should be collected
        assert len(ctx.result.votes) == 5
        assert ctx.result.consensus_reached is True

    @pytest.mark.asyncio
    async def test_tie_breaking(self):
        """Tied vote should be resolved (first proposal wins as tiebreaker)."""
        protocol = MockProtocol(consensus="majority", consensus_threshold=0.5)

        vote_idx = [0]

        async def vote_with_agent(agent, proposals, task):
            vote_idx[0] += 1
            if vote_idx[0] <= 2:
                return MockVote(agent=agent.name, choice="proposal_a", confidence=0.8)
            return MockVote(agent=agent.name, choice="proposal_b", confidence=0.8)

        phase = ConsensusPhase(
            protocol=protocol,
            vote_with_agent=vote_with_agent,
            group_similar_votes=lambda votes: {
                "proposal_a": ["proposal_a"],
                "proposal_b": ["proposal_b"],
            },
        )

        agents = [MockAgent(name=f"agent_{i}") for i in range(4)]
        ctx = DebateContext(env=MockEnvironment(), agents=agents)
        ctx.proposals = {"proposal_a": "A", "proposal_b": "B"}
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        # 50-50 tie, threshold is 0.5, so winner should be selected
        # With 50% = threshold, should meet threshold
        assert ctx.result.confidence == 0.5

    @pytest.mark.asyncio
    async def test_belief_analysis_integration(self):
        """Should integrate with belief analyzer if available."""
        protocol = MockProtocol(consensus="majority")

        async def vote_with_agent(agent, proposals, task):
            return MockVote(agent=agent.name, choice="proposal_a", confidence=0.8)

        # Mock belief analyzer
        mock_analyzer = MagicMock()
        mock_analyzer.compute_posterior.return_value = 0.75

        phase = ConsensusPhase(
            protocol=protocol,
            vote_with_agent=vote_with_agent,
            get_belief_analyzer=lambda: mock_analyzer,
            group_similar_votes=lambda votes: {"proposal_a": ["proposal_a"]},
        )

        agents = [MockAgent(name="claude")]
        ctx = DebateContext(env=MockEnvironment(), agents=agents)
        ctx.proposals = {"proposal_a": "Proposal"}
        ctx.result = MockDebateResult()

        await phase.execute(ctx)

        # Phase completes with belief analyzer integration
        assert ctx.result.consensus_reached is True
