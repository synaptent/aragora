"""
Tests for vote processor module.

Tests cover:
- VoteProcessor class
- Vote collection with timeout
- Vote grouping and mapping
- Weight computation
- Calibration adjustments
- User vote integration
- Choice normalization
"""

import asyncio
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.debate.phases.vote_processor import (
    DEFAULT_VOTE_COLLECTION_TIMEOUT,
    VoteProcessor,
)


@dataclass
class MockVote:
    """Mock vote."""

    agent: str
    choice: str
    confidence: float = 0.8
    reasoning: str = "Good reasoning"
    continue_debate: bool = False


@dataclass
class MockAgent:
    """Mock agent."""

    name: str
    role: str = "proposer"


@dataclass
class MockResult:
    """Mock debate result."""

    id: str = "result-123"
    rounds_used: int = 2


@dataclass
class MockEnv:
    """Mock environment."""

    task: str = "What is the best approach?"


@dataclass
class MockDebateContext:
    """Mock debate context."""

    agents: list = field(default_factory=list)
    proposals: dict = field(default_factory=dict)
    result: MockResult = field(default_factory=MockResult)
    env: MockEnv = field(default_factory=MockEnv)
    choice_mapping: dict = field(default_factory=dict)


class TestVoteProcessorInit:
    """Tests for VoteProcessor initialization."""

    def test_default_init(self):
        """Default initialization sets correct defaults."""
        processor = VoteProcessor()

        assert processor.memory is None
        assert processor.elo_system is None
        assert processor.agent_weights == {}
        assert processor.hooks == {}
        assert processor.user_votes == []
        assert processor.vote_collection_timeout == DEFAULT_VOTE_COLLECTION_TIMEOUT

    def test_custom_init(self):
        """Custom initialization stores all parameters."""
        memory = MagicMock()
        elo = MagicMock()
        hooks = {"on_vote": MagicMock()}
        user_votes = [{"choice": "claude"}]

        processor = VoteProcessor(
            memory=memory,
            elo_system=elo,
            hooks=hooks,
            user_votes=user_votes,
            vote_collection_timeout=60.0,
        )

        assert processor.memory is memory
        assert processor.elo_system is elo
        assert processor.hooks is hooks
        assert processor.user_votes == user_votes
        assert processor.vote_collection_timeout == 60.0


class TestCollectVotes:
    """Tests for vote collection."""

    @pytest.mark.asyncio
    async def test_collects_votes_from_agents(self):
        """Collects votes from all agents."""
        ctx = MockDebateContext()
        ctx.agents = [MockAgent("agent1"), MockAgent("agent2")]
        ctx.proposals = {"agent1": "Proposal 1", "agent2": "Proposal 2"}

        async def mock_vote(agent, proposals, task):
            return MockVote(agent.name, "agent1")

        processor = VoteProcessor(vote_with_agent=mock_vote)
        votes = await processor.collect_votes(ctx)

        assert len(votes) == 2
        assert all(v.choice == "agent1" for v in votes)

    @pytest.mark.asyncio
    async def test_handles_vote_errors(self):
        """Handles exceptions during voting gracefully."""
        ctx = MockDebateContext()
        ctx.agents = [MockAgent("agent1"), MockAgent("agent2")]

        call_count = 0

        async def mock_vote(agent, proposals, task):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Vote failed")
            return MockVote(agent.name, "choice")

        processor = VoteProcessor(vote_with_agent=mock_vote)
        votes = await processor.collect_votes(ctx)

        # One vote succeeded, one failed
        assert len(votes) == 1

    @pytest.mark.asyncio
    async def test_handles_none_votes(self):
        """Handles None vote results."""
        ctx = MockDebateContext()
        ctx.agents = [MockAgent("agent1"), MockAgent("agent2")]

        async def mock_vote(agent, proposals, task):
            if agent.name == "agent1":
                return None
            return MockVote(agent.name, "choice")

        processor = VoteProcessor(vote_with_agent=mock_vote)
        votes = await processor.collect_votes(ctx)

        assert len(votes) == 1
        assert votes[0].agent == "agent2"

    @pytest.mark.asyncio
    async def test_returns_empty_without_callback(self):
        """Returns empty list when no vote callback."""
        ctx = MockDebateContext()
        ctx.agents = [MockAgent("agent1")]

        processor = VoteProcessor()  # No callback
        votes = await processor.collect_votes(ctx)

        assert votes == []

    @pytest.mark.asyncio
    async def test_timeout_returns_partial_votes(self):
        """Timeout returns partial votes collected."""
        ctx = MockDebateContext()
        ctx.agents = [MockAgent("agent1"), MockAgent("agent2")]

        async def slow_vote(agent, proposals, task):
            if agent.name == "agent2":
                await asyncio.sleep(10)  # Very slow
            return MockVote(agent.name, "choice")

        processor = VoteProcessor(
            vote_with_agent=slow_vote,
            vote_collection_timeout=0.1,  # Very short timeout
        )

        votes = await processor.collect_votes(ctx)

        # Should get at least agent1's vote before timeout
        assert len(votes) >= 1


class TestCollectVotesWithErrors:
    """Tests for vote collection with error tracking."""

    @pytest.mark.asyncio
    async def test_tracks_error_count(self):
        """Tracks count of voting errors."""
        ctx = MockDebateContext()
        ctx.agents = [MockAgent("agent1"), MockAgent("agent2"), MockAgent("agent3")]

        call_count = 0

        async def mock_vote(agent, proposals, task):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Vote failed")
            if call_count == 2:
                return None
            return MockVote(agent.name, "choice")

        processor = VoteProcessor(vote_with_agent=mock_vote)
        votes, errors = await processor.collect_votes_with_errors(ctx)

        assert len(votes) == 1
        assert errors == 2  # One exception, one None


class TestComputeVoteGroups:
    """Tests for vote grouping."""

    def test_identity_grouping_without_callback(self):
        """Without callback, uses identity grouping."""
        votes = [
            MockVote("a1", "Yes"),
            MockVote("a2", "No"),
        ]
        processor = VoteProcessor()

        groups, mapping = processor.compute_vote_groups(votes)

        assert groups == {"Yes": ["Yes"], "No": ["No"]}
        assert mapping == {"Yes": "Yes", "No": "No"}

    def test_uses_grouping_callback(self):
        """Uses grouping callback when provided."""
        votes = [
            MockVote("a1", "Yes"),
            MockVote("a2", "yes"),
            MockVote("a3", "NO"),
        ]

        def group_callback(votes):
            return {"Yes": ["Yes", "yes"], "No": ["NO"]}

        processor = VoteProcessor(group_similar_votes=group_callback)
        groups, mapping = processor.compute_vote_groups(votes)

        assert mapping["Yes"] == "Yes"
        assert mapping["yes"] == "Yes"
        assert mapping["NO"] == "No"


class TestComputeVoteWeights:
    """Tests for vote weight computation."""

    def test_computes_weights_for_agents(self):
        """Computes weights using WeightCalculator."""
        agents = [MockAgent("agent1"), MockAgent("agent2")]

        processor = VoteProcessor()

        with patch("aragora.debate.phases.vote_processor.WeightCalculator") as mock_calc_class:
            mock_calc = MagicMock()
            mock_calc.compute_weights.return_value = {"agent1": 1.2, "agent2": 0.8}
            mock_calc_class.return_value = mock_calc

            weights = processor.compute_vote_weights(agents)

        assert weights == {"agent1": 1.2, "agent2": 0.8}


class TestCountWeightedVotes:
    """Tests for weighted vote counting."""

    def test_counts_weighted_votes(self):
        """Counts votes with weights applied."""
        votes = [
            MockVote("agent1", "Yes"),
            MockVote("agent2", "No"),
        ]
        weights = {"agent1": 2.0, "agent2": 1.0}
        mapping = {"Yes": "Yes", "No": "No"}

        processor = VoteProcessor()
        counts, total = processor.count_weighted_votes(votes, mapping, weights)

        assert counts["Yes"] == 2.0
        assert counts["No"] == 1.0
        assert total == 3.0

    def test_handles_missing_weights(self):
        """Uses default weight 1.0 for unknown agents."""
        votes = [MockVote("unknown", "Yes")]
        weights = {}
        mapping = {"Yes": "Yes"}

        processor = VoteProcessor()
        counts, total = processor.count_weighted_votes(votes, mapping, weights)

        assert counts["Yes"] == 1.0
        assert total == 1.0

    def test_applies_choice_mapping(self):
        """Applies choice mapping to canonical form."""
        votes = [
            MockVote("a1", "yes"),
            MockVote("a2", "YES"),
        ]
        weights = {"a1": 1.0, "a2": 1.0}
        mapping = {"yes": "Yes", "YES": "Yes"}

        processor = VoteProcessor()
        counts, total = processor.count_weighted_votes(votes, mapping, weights)

        assert counts["Yes"] == 2.0

    def test_skips_exceptions(self):
        """Skips exception objects in vote list."""
        votes = [
            MockVote("a1", "Yes"),
            RuntimeError("Failed"),  # Should be skipped
        ]
        weights = {"a1": 1.0}
        mapping = {"Yes": "Yes"}

        processor = VoteProcessor()
        counts, total = processor.count_weighted_votes(votes, mapping, weights)

        assert counts["Yes"] == 1.0
        assert total == 1.0


class TestAddUserVotes:
    """Tests for user vote integration."""

    def test_adds_user_votes(self):
        """Adds user votes to counts."""
        user_votes = [
            {"choice": "Yes", "intensity": 5},
            {"choice": "No", "intensity": 5},
        ]
        counts = Counter({"Yes": 2.0})
        mapping = {"Yes": "Yes", "No": "No"}

        processor = VoteProcessor(user_votes=user_votes)
        new_counts, total = processor.add_user_votes(counts, 2.0, mapping)

        assert new_counts["Yes"] > 2.0  # Added user vote
        assert new_counts["No"] > 0  # New user vote

    def test_applies_intensity_multiplier(self):
        """Applies intensity multiplier callback."""
        user_votes = [{"choice": "Yes", "intensity": 10}]

        def multiplier(intensity, protocol):
            return intensity / 5  # 10 -> 2.0

        processor = VoteProcessor(
            user_votes=user_votes,
            user_vote_multiplier=multiplier,
        )
        counts, total = processor.add_user_votes(Counter(), 0.0, {"Yes": "Yes"})

        # Base weight 0.5 * multiplier 2.0 = 1.0
        assert counts["Yes"] == 1.0

    def test_skips_empty_choices(self):
        """Skips user votes with empty choice."""
        user_votes = [
            {"choice": "", "intensity": 5},
            {"choice": "Yes", "intensity": 5},
        ]
        processor = VoteProcessor(user_votes=user_votes)
        counts, total = processor.add_user_votes(Counter(), 0.0, {"Yes": "Yes"})

        # Only one vote added
        assert "Yes" in counts

    def test_skips_missing_user_vote_entries(self):
        """Partially populated event batches ignore empty user-vote entries."""
        processor = VoteProcessor(user_votes=[None, {"choice": "Yes", "intensity": 5}])

        counts, total = processor.add_user_votes(Counter(), 0.0, {"Yes": "Yes"})

        assert counts["Yes"] == pytest.approx(0.5)
        assert total == pytest.approx(0.5)


class TestNormalizeChoiceToAgent:
    """Tests for choice normalization."""

    def test_direct_match(self):
        """Matches agent name directly."""
        agents = [MockAgent("claude"), MockAgent("gpt4")]
        proposals = {}

        processor = VoteProcessor()
        result = processor.normalize_choice_to_agent("claude", agents, proposals)

        assert result == "claude"

    def test_case_insensitive_match(self):
        """Matches agent name case-insensitively."""
        agents = [MockAgent("Claude"), MockAgent("GPT4")]
        proposals = {}

        processor = VoteProcessor()
        result = processor.normalize_choice_to_agent("claude", agents, proposals)

        assert result == "Claude"

    def test_strips_quotes(self):
        """Strips quotes from choice."""
        agents = [MockAgent("claude")]
        proposals = {}

        processor = VoteProcessor()
        result = processor.normalize_choice_to_agent('"claude"', agents, proposals)

        assert result == "claude"

    def test_proposal_reference(self):
        """Matches 'Proposal from X' format."""
        agents = [MockAgent("claude")]
        proposals = {}

        processor = VoteProcessor()
        result = processor.normalize_choice_to_agent("Proposal from claude", agents, proposals)

        assert result == "claude"

    def test_partial_match(self):
        """Matches partial agent name."""
        agents = [MockAgent("claude-cli")]
        proposals = {}

        processor = VoteProcessor()
        result = processor.normalize_choice_to_agent("claude", agents, proposals)

        assert result == "claude-cli"

    def test_returns_original_if_no_match(self):
        """Returns original choice if no match."""
        agents = [MockAgent("claude")]
        proposals = {}

        processor = VoteProcessor()
        result = processor.normalize_choice_to_agent("unknown", agents, proposals)

        assert result == "unknown"


class TestApplyCalibrationToVotes:
    """Tests for calibration adjustment."""

    def test_adjusts_vote_confidence(self):
        """Adjusts vote confidence based on calibration."""
        votes = [MockVote("agent1", "Yes", 0.9)]
        ctx = MockDebateContext()

        calibration = MagicMock()
        summary = MagicMock()
        summary.bias_direction = "over"
        calibration.get_calibration_summary.return_value = summary

        processor = VoteProcessor(calibration_tracker=calibration)

        # Patch at the source module where adjust_agent_confidence is defined
        with patch("aragora.agents.calibration.adjust_agent_confidence") as mock_adjust:
            mock_adjust.return_value = 0.8  # Adjusted down

            adjusted = processor.apply_calibration_to_votes(votes, ctx)

        assert len(adjusted) == 1
        assert adjusted[0].confidence == 0.8

    def test_skips_without_tracker(self):
        """Skips calibration without tracker."""
        votes = [MockVote("agent1", "Yes", 0.9)]
        ctx = MockDebateContext()

        processor = VoteProcessor()  # No tracker
        adjusted = processor.apply_calibration_to_votes(votes, ctx)

        assert adjusted[0].confidence == 0.9  # Unchanged

    def test_handles_calibration_errors(self):
        """Handles calibration errors gracefully."""
        votes = [MockVote("agent1", "Yes", 0.9)]
        ctx = MockDebateContext()

        calibration = MagicMock()
        calibration.get_calibration_summary.side_effect = RuntimeError("Error")

        processor = VoteProcessor(calibration_tracker=calibration)
        adjusted = processor.apply_calibration_to_votes(votes, ctx)

        assert adjusted[0].confidence == 0.9  # Unchanged


class TestHandleVoteSuccess:
    """Tests for vote success handling."""

    def test_notifies_spectator(self):
        """Notifies spectator of vote."""
        ctx = MockDebateContext()
        agent = MockAgent("claude")
        vote = MockVote("claude", "Yes", 0.85)

        notify = MagicMock()
        processor = VoteProcessor(notify_spectator=notify)

        processor._handle_vote_success(ctx, agent, vote)

        notify.assert_called_once()
        assert notify.call_args[0][0] == "vote"

    def test_calls_on_vote_hook(self):
        """Calls on_vote hook."""
        ctx = MockDebateContext()
        agent = MockAgent("claude")
        vote = MockVote("claude", "Yes", 0.85)

        hook = MagicMock()
        processor = VoteProcessor(hooks={"on_vote": hook})

        processor._handle_vote_success(ctx, agent, vote)

        hook.assert_called_once_with("claude", "Yes", 0.85)

    def test_ignores_disabled_on_vote_hook(self):
        """An explicitly disabled optional hook is not called."""
        ctx = MockDebateContext()
        agent = MockAgent("claude")
        vote = MockVote("claude", "Yes", 0.85)

        processor = VoteProcessor(hooks={"on_vote": None})

        processor._handle_vote_success(ctx, agent, vote)

    def test_records_vote(self):
        """Records vote with recorder."""
        ctx = MockDebateContext()
        agent = MockAgent("claude")
        vote = MockVote("claude", "Yes", reasoning="Good choice")

        recorder = MagicMock()
        processor = VoteProcessor(recorder=recorder)

        processor._handle_vote_success(ctx, agent, vote)

        recorder.record_vote.assert_called_once_with("claude", "Yes", "Good choice")

    def test_tracks_position(self):
        """Tracks position with position tracker."""
        ctx = MockDebateContext()
        agent = MockAgent("claude")
        vote = MockVote("claude", "Yes", 0.85)

        tracker = MagicMock()
        processor = VoteProcessor(position_tracker=tracker)

        processor._handle_vote_success(ctx, agent, vote)

        tracker.record_position.assert_called_once()
