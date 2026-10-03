"""
Tests for aragora.debate.context module.

Tests DebateContext dataclass and helper methods.
"""

import pytest
import time
from dataclasses import dataclass, field
from typing import Optional

from aragora.debate.context import DebateContext


# ============================================================================
# Mock Classes
# ============================================================================


@dataclass
class MockEnvironment:
    """Mock environment for testing."""

    task: str = "Test task"
    context: str = ""
    domain: str = "general"


@dataclass
class MockAgent:
    """Mock agent for testing."""

    name: str = "test_agent"
    role: str = "proposer"
    stance: str | None = None


@dataclass
class MockMessage:
    """Mock message for testing."""

    role: str = "proposer"
    agent: str = "test_agent"
    content: str = "Test content"
    round: int = 0


@dataclass
class MockCritique:
    """Mock critique for testing."""

    agent: str = "critic"
    target_agent: str = "proposer"
    issues: list = field(default_factory=list)
    severity: float = 0.5


@dataclass
class MockDebateResult:
    """Mock debate result for testing."""

    id: str = "test_id"
    debate_id: str = "test_id"
    task: str = "Test task"
    messages: list = field(default_factory=list)
    critiques: list = field(default_factory=list)
    votes: list = field(default_factory=list)
    dissenting_views: list = field(default_factory=list)
    rounds_used: int = 0
    rounds_completed: int = 0
    duration_seconds: float = 0.0
    winner: str | None = None
    consensus_reached: bool = False
    avg_novelty: float = 1.0
    proposals: dict = field(default_factory=dict)
    participants: list = field(default_factory=list)
    status: str = "pending"


# ============================================================================
# DebateContext Initialization Tests
# ============================================================================


class TestDebateContextInit:
    """Tests for DebateContext initialization."""

    def test_minimal_creation(self):
        """Should create with just environment."""
        env = MockEnvironment()
        ctx = DebateContext(env=env)

        assert ctx.env == env
        assert ctx.agents == []
        assert ctx.start_time == 0.0
        assert ctx.debate_id == ""
        assert ctx.domain == "general"

    def test_full_creation(self):
        """Should create with all fields."""
        env = MockEnvironment(task="Full test")
        agents = [MockAgent(name="claude"), MockAgent(name="gpt4")]

        ctx = DebateContext(
            env=env,
            agents=agents,
            start_time=time.time(),
            debate_id="debate_001",
            domain="security",
        )

        assert ctx.env.task == "Full test"
        assert len(ctx.agents) == 2
        assert ctx.debate_id == "debate_001"
        assert ctx.domain == "security"

    def test_default_collections(self):
        """Should have empty default collections."""
        ctx = DebateContext(env=MockEnvironment())

        assert ctx.proposals == {}
        assert ctx.context_messages == []
        assert ctx.partial_messages == []
        assert ctx.partial_critiques == []
        assert ctx.vote_tally == {}
        assert ctx.choice_mapping == {}
        assert ctx.vote_weight_cache == {}


# ============================================================================
# Agent Lookup Tests
# ============================================================================


class TestAgentLookup:
    """Tests for agent lookup methods."""

    def test_get_agent_by_name_found(self):
        """Should find agent by name."""
        agents = [
            MockAgent(name="claude"),
            MockAgent(name="gpt4"),
            MockAgent(name="gemini"),
        ]
        ctx = DebateContext(env=MockEnvironment(), agents=agents)

        result = ctx.get_agent_by_name("gpt4")

        assert result is not None
        assert result.name == "gpt4"

    def test_get_agent_by_name_not_found(self):
        """Should return None when agent not found."""
        agents = [MockAgent(name="claude")]
        ctx = DebateContext(env=MockEnvironment(), agents=agents)

        result = ctx.get_agent_by_name("unknown")

        assert result is None

    def test_get_agent_by_name_empty_list(self):
        """Should return None when no agents."""
        ctx = DebateContext(env=MockEnvironment())

        result = ctx.get_agent_by_name("any")

        assert result is None


# ============================================================================
# Proposal Tests
# ============================================================================


class TestProposals:
    """Tests for proposal handling."""

    def test_get_proposal_exists(self):
        """Should return proposal when exists."""
        ctx = DebateContext(env=MockEnvironment())
        ctx.proposals = {"claude": "My proposal", "gpt4": "Other proposal"}

        assert ctx.get_proposal("claude") == "My proposal"

    def test_get_proposal_not_found(self):
        """Should return empty string when not found."""
        ctx = DebateContext(env=MockEnvironment())
        ctx.proposals = {"claude": "My proposal"}

        assert ctx.get_proposal("unknown") == ""


# ============================================================================
# Message Tracking Tests
# ============================================================================


class TestMessageTracking:
    """Tests for message addition and tracking."""

    def test_add_message_to_context(self):
        """Should add message to context_messages."""
        ctx = DebateContext(env=MockEnvironment())
        msg = MockMessage(content="Test message")

        ctx.add_message(msg)

        assert len(ctx.context_messages) == 1
        assert ctx.context_messages[0] == msg

    def test_add_message_to_partial(self):
        """Should add message to partial_messages for recovery."""
        ctx = DebateContext(env=MockEnvironment())
        msg = MockMessage(content="Test message")

        ctx.add_message(msg)

        assert len(ctx.partial_messages) == 1
        assert ctx.partial_messages[0] == msg

    def test_add_message_to_result(self):
        """One call should record exactly once in every production destination."""
        ctx = DebateContext(env=MockEnvironment())
        ctx.result = MockDebateResult()
        msg = MockMessage(content="Test message")

        ctx.add_message(msg)

        assert ctx.context_messages == [msg]
        assert ctx.partial_messages == [msg]
        assert ctx.result.messages == [msg]

    def test_add_message_no_result(self):
        """Should not crash when result is None."""
        ctx = DebateContext(env=MockEnvironment())
        msg = MockMessage(content="Test message")

        # Should not raise
        ctx.add_message(msg)

        assert len(ctx.context_messages) == 1


# ============================================================================
# Critique Tracking Tests
# ============================================================================


class TestCritiqueTracking:
    """Tests for critique addition and tracking."""

    def test_add_critique_to_round(self):
        """Should add critique to round_critiques."""
        ctx = DebateContext(env=MockEnvironment())
        critique = MockCritique(agent="claude", issues=["Issue 1"])

        ctx.add_critique(critique)

        assert len(ctx.round_critiques) == 1
        assert ctx.round_critiques[0] == critique

    def test_add_critique_to_partial(self):
        """Should add critique to partial_critiques for recovery."""
        ctx = DebateContext(env=MockEnvironment())
        critique = MockCritique(agent="claude")

        ctx.add_critique(critique)

        assert len(ctx.partial_critiques) == 1

    def test_add_critique_to_result(self):
        """Should add critique to result when result exists."""
        ctx = DebateContext(env=MockEnvironment())
        ctx.result = MockDebateResult()
        critique = MockCritique(agent="claude")

        ctx.add_critique(critique)

        assert len(ctx.result.critiques) == 1


# ============================================================================
# Result Finalization Tests
# ============================================================================


class TestResultFinalization:
    """Tests for result finalization."""

    def test_finalize_sets_duration(self):
        """Should set duration_seconds from start_time."""
        ctx = DebateContext(env=MockEnvironment())
        ctx.start_time = time.time() - 5.0  # 5 seconds ago
        ctx.result = MockDebateResult()

        result = ctx.finalize_result()

        assert result.duration_seconds >= 5.0
        assert result.duration_seconds < 10.0  # Reasonable upper bound

    def test_finalize_sets_rounds_used(self):
        """Should set rounds_used from current_round."""
        ctx = DebateContext(env=MockEnvironment())
        ctx.start_time = time.time()
        ctx.current_round = 3
        ctx.result = MockDebateResult()

        result = ctx.finalize_result()

        assert result.rounds_used == 3

    def test_finalize_sets_winner(self):
        """Should set winner from winner_agent."""
        ctx = DebateContext(env=MockEnvironment())
        ctx.start_time = time.time()
        ctx.winner_agent = "claude"
        ctx.result = MockDebateResult()

        result = ctx.finalize_result()

        assert result.winner == "claude"

    def test_finalize_no_result(self):
        """Should return None when result is None."""
        ctx = DebateContext(env=MockEnvironment())

        result = ctx.finalize_result()

        assert result is None


# ============================================================================
# Summary Dict Tests
# ============================================================================


class TestSummaryDict:
    """Tests for summary dict generation."""

    def test_to_summary_dict_basic(self):
        """Should return summary with basic fields."""
        ctx = DebateContext(
            env=MockEnvironment(),
            debate_id="test_001",
            domain="security",
        )

        summary = ctx.to_summary_dict()

        assert summary["debate_id"] == "test_001"
        assert summary["domain"] == "security"
        assert summary["agents"] == []
        assert summary["proposers"] == []
        assert summary["current_round"] == 0

    def test_to_summary_dict_with_agents(self):
        """Should include agent names in summary."""
        agents = [MockAgent(name="claude"), MockAgent(name="gpt4")]
        proposers = [MockAgent(name="claude")]
        ctx = DebateContext(
            env=MockEnvironment(),
            agents=agents,
            proposers=proposers,
        )

        summary = ctx.to_summary_dict()

        assert summary["agents"] == ["claude", "gpt4"]
        assert summary["proposers"] == ["claude"]

    def test_to_summary_dict_with_state(self):
        """Should include state fields in summary."""
        ctx = DebateContext(env=MockEnvironment())
        ctx.current_round = 2
        ctx.proposals = {"a": "x", "b": "y"}
        ctx.context_messages = [MockMessage()] * 5
        ctx.winner_agent = "a"
        ctx.convergence_status = "converged"

        summary = ctx.to_summary_dict()

        assert summary["current_round"] == 2
        assert summary["num_proposals"] == 2
        assert summary["num_messages"] == 5
        assert summary["winner"] == "a"
        assert summary["convergence_status"] == "converged"


# ============================================================================
# Convergence State Tests
# ============================================================================


class TestConvergenceState:
    """Tests for convergence state tracking."""

    def test_default_convergence_state(self):
        """Should have empty default convergence state."""
        ctx = DebateContext(env=MockEnvironment())

        assert ctx.convergence_status == ""
        assert ctx.convergence_similarity == 0.0
        assert ctx.per_agent_similarity == {}
        assert ctx.early_termination is False

    def test_update_convergence_state(self):
        """Should allow updating convergence state."""
        ctx = DebateContext(env=MockEnvironment())

        ctx.convergence_status = "converged"
        ctx.convergence_similarity = 0.95
        ctx.per_agent_similarity = {"claude": 0.96, "gpt4": 0.94}
        ctx.early_termination = True

        assert ctx.convergence_status == "converged"
        assert ctx.convergence_similarity == 0.95
        assert ctx.per_agent_similarity["claude"] == 0.96
        assert ctx.early_termination is True


# ============================================================================
# Cache Tests
# ============================================================================


class TestCaches:
    """Tests for cache fields."""

    def test_default_caches(self):
        """Should have empty default caches."""
        ctx = DebateContext(env=MockEnvironment())

        assert ctx.historical_context_cache == ""
        assert ctx.continuum_context_cache == ""
        assert ctx.research_context is None
        assert ctx.ratings_cache == {}

    def test_update_caches(self):
        """Should allow updating caches."""
        ctx = DebateContext(env=MockEnvironment())

        ctx.historical_context_cache = "Prior debate found..."
        ctx.continuum_context_cache = "Memory retrieved..."
        ctx.research_context = "Research findings..."
        ctx.ratings_cache = {"claude": {"elo": 1600}}

        assert "Prior debate" in ctx.historical_context_cache
        assert "Memory" in ctx.continuum_context_cache
        assert "Research" in ctx.research_context
        assert "claude" in ctx.ratings_cache


# ============================================================================
# Round State Tests
# ============================================================================


class TestRoundState:
    """Tests for round state management."""

    def test_default_round_state(self):
        """Should have default round state."""
        ctx = DebateContext(env=MockEnvironment())

        assert ctx.current_round == 0
        assert ctx.previous_round_responses == {}
        assert ctx.round_critiques == []

    def test_advance_round(self):
        """Should allow advancing round state."""
        ctx = DebateContext(env=MockEnvironment())

        # Simulate round progression
        ctx.current_round = 1
        ctx.previous_round_responses = {"claude": "Round 1 response"}
        ctx.round_critiques = [MockCritique()]

        assert ctx.current_round == 1
        assert "claude" in ctx.previous_round_responses
        assert len(ctx.round_critiques) == 1

    def test_clear_round_critiques(self):
        """Should allow clearing round critiques between rounds."""
        ctx = DebateContext(env=MockEnvironment())
        ctx.round_critiques = [MockCritique(), MockCritique()]

        # Clear for new round
        ctx.round_critiques = []

        assert ctx.round_critiques == []
