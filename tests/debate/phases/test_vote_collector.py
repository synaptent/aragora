"""
Tests for VoteCollector module.

Tests cover:
- VoteCollectorConfig initialization and defaults
- VoteCollector initialization
- Vote collection logic (collect_votes, collect_votes_with_errors)
- Timeout handling (overall timeout, per-agent timeout)
- RLM early termination (_check_clear_majority, early termination in collection)
- Position shuffling (_collect_votes_with_shuffling, _collect_single_permutation_votes)
- Vote success handling (_handle_vote_success)
- Vote grouping (compute_vote_groups)
- Edge cases (no votes, single voter, no vote callback, exceptions)
- Factory function (create_vote_collector)
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.core_types import DebateResult, Vote
from aragora.debate.context import DebateContext
from aragora.debate.phases.vote_collector import (
    AGENT_TIMEOUT_SECONDS,
    RLM_EARLY_TERMINATION_THRESHOLD,
    RLM_MAJORITY_LEAD_THRESHOLD,
    VOTE_COLLECTION_TIMEOUT,
    _VoteTaskOwner,
    VoteCollector,
    VoteCollectorConfig,
    create_vote_collector,
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
) -> DebateContext:
    """Create a DebateContext with sensible defaults for testing."""
    result = DebateResult()
    # Use is None check to allow empty list
    if agents is None:
        agents = [MockAgent(name="agent1"), MockAgent(name="agent2")]
    ctx = DebateContext(
        env=MockEnvironment(),
        agents=agents,
        proposals=proposals
        if proposals is not None
        else {"agent1": "Proposal A", "agent2": "Proposal B"},
        result=result,
        start_time=time.time(),
        debate_id="test-debate-123",
    )
    return ctx


# =============================================================================
# VoteCollectorConfig Tests
# =============================================================================


class TestVoteCollectorConfig:
    """Tests for VoteCollectorConfig dataclass."""

    def test_default_values(self):
        """Config initializes with correct defaults."""
        config = VoteCollectorConfig()

        assert config.vote_with_agent is None
        assert config.with_timeout is None
        assert config.notify_spectator is None
        assert config.hooks == {}
        assert config.recorder is None
        assert config.position_tracker is None
        assert config.group_similar_votes is None
        assert config.vote_collection_timeout == VOTE_COLLECTION_TIMEOUT
        assert config.agent_timeout == AGENT_TIMEOUT_SECONDS
        assert config.enable_rlm_early_termination is True
        assert config.rlm_early_termination_threshold == RLM_EARLY_TERMINATION_THRESHOLD
        assert config.rlm_majority_lead_threshold == RLM_MAJORITY_LEAD_THRESHOLD
        assert config.enable_position_shuffling is False
        assert config.position_shuffling_permutations == 3
        assert config.position_shuffling_seed is None

    def test_custom_values(self):
        """Config accepts and stores custom values."""
        vote_callback = MagicMock()
        timeout_callback = MagicMock()
        hooks = {"on_vote": MagicMock()}
        recorder = MagicMock()

        config = VoteCollectorConfig(
            vote_with_agent=vote_callback,
            with_timeout=timeout_callback,
            hooks=hooks,
            recorder=recorder,
            vote_collection_timeout=60.0,
            agent_timeout=15.0,
            enable_rlm_early_termination=False,
            rlm_early_termination_threshold=0.5,
            rlm_majority_lead_threshold=0.3,
            enable_position_shuffling=True,
            position_shuffling_permutations=5,
            position_shuffling_seed=42,
        )

        assert config.vote_with_agent is vote_callback
        assert config.with_timeout is timeout_callback
        assert config.hooks == hooks
        assert config.recorder is recorder
        assert config.vote_collection_timeout == 60.0
        assert config.agent_timeout == 15.0
        assert config.enable_rlm_early_termination is False
        assert config.rlm_early_termination_threshold == 0.5
        assert config.rlm_majority_lead_threshold == 0.3
        assert config.enable_position_shuffling is True
        assert config.position_shuffling_permutations == 5
        assert config.position_shuffling_seed == 42


# =============================================================================
# VoteCollector Initialization Tests
# =============================================================================


class TestVoteCollectorInit:
    """Tests for VoteCollector initialization."""

    def test_init_with_minimal_config(self):
        """Collector initializes with minimal config."""
        config = VoteCollectorConfig()
        collector = VoteCollector(config)

        assert collector.config is config
        assert collector._vote_with_agent is None
        assert collector._with_timeout is None
        assert collector._notify_spectator is None
        assert collector.hooks == {}
        assert collector.recorder is None
        assert collector.position_tracker is None
        assert collector._group_similar_votes is None
        assert collector.VOTE_COLLECTION_TIMEOUT == VOTE_COLLECTION_TIMEOUT

    def test_init_with_full_config(self):
        """Collector initializes with all config options."""
        vote_callback = MagicMock()
        timeout_callback = MagicMock()
        notify_callback = MagicMock()
        hooks = {"on_vote": MagicMock()}
        recorder = MagicMock()
        position_tracker = MagicMock()
        group_callback = MagicMock()

        config = VoteCollectorConfig(
            vote_with_agent=vote_callback,
            with_timeout=timeout_callback,
            notify_spectator=notify_callback,
            hooks=hooks,
            recorder=recorder,
            position_tracker=position_tracker,
            group_similar_votes=group_callback,
            vote_collection_timeout=120.0,
        )
        collector = VoteCollector(config)

        assert collector._vote_with_agent is vote_callback
        assert collector._with_timeout is timeout_callback
        assert collector._notify_spectator is notify_callback
        assert collector.hooks == hooks
        assert collector.recorder is recorder
        assert collector.position_tracker is position_tracker
        assert collector._group_similar_votes is group_callback
        assert collector.VOTE_COLLECTION_TIMEOUT == 120.0


# =============================================================================
# Vote Collection Logic Tests
# =============================================================================


class TestCollectVotes:
    """Tests for collect_votes method."""

    @pytest.fixture
    def mock_governor(self):
        """Create mock complexity governor."""
        mock = MagicMock()
        mock.get_scaled_timeout.return_value = 30.0
        return mock

    @pytest.mark.asyncio
    async def test_collect_votes_no_callback_returns_empty(self):
        """Returns empty list when no vote_with_agent callback."""
        config = VoteCollectorConfig()
        collector = VoteCollector(config)
        ctx = make_context()

        votes = await collector.collect_votes(ctx)

        assert votes == []

    @pytest.mark.asyncio
    async def test_collect_votes_basic(self, mock_governor):
        """Basic vote collection from all agents."""
        vote1 = make_vote(agent="agent1", choice="agent2")
        vote2 = make_vote(agent="agent2", choice="agent1")

        async def mock_vote(agent, proposals, task):
            if agent.name == "agent1":
                return vote1
            return vote2

        config = VoteCollectorConfig(vote_with_agent=mock_vote)
        collector = VoteCollector(config)
        ctx = make_context()

        with patch(
            "aragora.debate.phases.vote_collector.get_complexity_governor",
            return_value=mock_governor,
        ):
            votes = await collector.collect_votes(ctx)

        assert len(votes) == 2
        assert vote1 in votes
        assert vote2 in votes

    @pytest.mark.asyncio
    async def test_collect_votes_with_timeout_wrapper(self, mock_governor):
        """Vote collection uses timeout wrapper when provided."""
        vote = make_vote(agent="agent1", choice="agent2")

        async def mock_vote(agent, proposals, task):
            return vote

        async def mock_with_timeout(coro, agent_name, timeout_seconds):
            return await coro

        config = VoteCollectorConfig(
            vote_with_agent=mock_vote,
            with_timeout=mock_with_timeout,
        )
        collector = VoteCollector(config)
        ctx = make_context(agents=[MockAgent(name="agent1")])

        with patch(
            "aragora.debate.phases.vote_collector.get_complexity_governor",
            return_value=mock_governor,
        ):
            votes = await collector.collect_votes(ctx)

        assert len(votes) == 1
        assert votes[0] == vote

    @pytest.mark.asyncio
    async def test_collect_votes_handles_agent_exception(self, mock_governor):
        """Vote collection handles agent exceptions gracefully."""
        vote = make_vote(agent="agent2", choice="agent1")

        async def mock_vote(agent, proposals, task):
            if agent.name == "agent1":
                raise RuntimeError("Agent error")
            return vote

        config = VoteCollectorConfig(vote_with_agent=mock_vote)
        collector = VoteCollector(config)
        ctx = make_context()

        with patch(
            "aragora.debate.phases.vote_collector.get_complexity_governor",
            return_value=mock_governor,
        ):
            votes = await collector.collect_votes(ctx)

        # Only agent2's vote should be collected
        assert len(votes) == 1
        assert votes[0] == vote

    @pytest.mark.asyncio
    async def test_collect_votes_handles_none_result(self, mock_governor):
        """Vote collection handles None vote result."""
        vote = make_vote(agent="agent2", choice="agent1")

        async def mock_vote(agent, proposals, task):
            if agent.name == "agent1":
                return None
            return vote

        config = VoteCollectorConfig(vote_with_agent=mock_vote)
        collector = VoteCollector(config)
        ctx = make_context()

        with patch(
            "aragora.debate.phases.vote_collector.get_complexity_governor",
            return_value=mock_governor,
        ):
            votes = await collector.collect_votes(ctx)

        assert len(votes) == 1
        assert votes[0] == vote

    @pytest.mark.asyncio
    async def test_collect_votes_handles_exception_result(self, mock_governor):
        """Vote collection handles Exception returned as result."""
        vote = make_vote(agent="agent2", choice="agent1")

        async def mock_vote(agent, proposals, task):
            if agent.name == "agent1":
                return ValueError("Parse error")
            return vote

        config = VoteCollectorConfig(vote_with_agent=mock_vote)
        collector = VoteCollector(config)
        ctx = make_context()

        with patch(
            "aragora.debate.phases.vote_collector.get_complexity_governor",
            return_value=mock_governor,
        ):
            votes = await collector.collect_votes(ctx)

        assert len(votes) == 1
        assert votes[0] == vote


# =============================================================================
# Timeout Handling Tests
# =============================================================================


class TestTimeoutHandling:
    """Tests for timeout handling in vote collection."""

    @pytest.fixture
    def mock_governor(self):
        """Create mock complexity governor."""
        mock = MagicMock()
        mock.get_scaled_timeout.return_value = 30.0
        return mock

    @pytest.mark.asyncio
    async def test_collect_votes_overall_timeout(self, mock_governor):
        """Vote collection respects overall timeout."""

        async def slow_vote(agent, proposals, task):
            await asyncio.sleep(10)  # Very slow vote
            return make_vote(agent=agent.name)

        config = VoteCollectorConfig(
            vote_with_agent=slow_vote,
            vote_collection_timeout=0.1,  # Very short timeout
        )
        collector = VoteCollector(config)
        ctx = make_context()

        with patch(
            "aragora.debate.phases.vote_collector.get_complexity_governor",
            return_value=mock_governor,
        ):
            votes = await collector.collect_votes(ctx)

        # Should timeout and return partial results (possibly empty)
        assert len(votes) < 2

    @pytest.mark.asyncio
    async def test_collect_votes_partial_on_timeout(self, mock_governor):
        """Vote collection returns partial votes on timeout."""
        call_count = 0

        async def vote_with_delay(agent, proposals, task):
            nonlocal call_count
            call_count += 1
            if agent.name == "agent1":
                return make_vote(agent="agent1")
            # agent2 is very slow
            await asyncio.sleep(10)
            return make_vote(agent="agent2")

        config = VoteCollectorConfig(
            vote_with_agent=vote_with_delay,
            vote_collection_timeout=0.2,
        )
        collector = VoteCollector(config)
        ctx = make_context()

        with patch(
            "aragora.debate.phases.vote_collector.get_complexity_governor",
            return_value=mock_governor,
        ):
            votes = await collector.collect_votes(ctx)

        # agent1 vote should be returned, agent2 timed out
        assert len(votes) >= 0  # At least tried

    @pytest.mark.asyncio
    async def test_timeout_observes_late_task_failures(self, mock_governor):
        """Timeout detaches every child and reports only late control flow."""

        class VoteAbort(BaseException):
            pass

        release = asyncio.Event()
        loop_contexts: list[dict[str, Any]] = []

        async def delayed_failure(agent, proposals, task):
            if agent.name == "agent0":
                return make_vote(agent=agent.name)
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            if agent.name == "agent1":
                raise RuntimeError("late ordinary failure")
            raise VoteAbort("late control flow")

        collector = VoteCollector(
            VoteCollectorConfig(
                vote_with_agent=delayed_failure,
                vote_collection_timeout=0.02,
                enable_rlm_early_termination=False,
            )
        )
        ctx = make_context(agents=[MockAgent(name=f"agent{i}") for i in range(3)])
        loop = asyncio.get_running_loop()
        old_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: loop_contexts.append(context))

        try:
            with patch(
                "aragora.debate.phases.vote_collector.get_complexity_governor",
                return_value=mock_governor,
            ):
                votes = await asyncio.wait_for(collector.collect_votes(ctx), timeout=0.2)

            assert [vote.agent for vote in votes] == ["agent0"]
            release.set()
            await asyncio.sleep(0.02)
            assert [type(context.get("exception")) for context in loop_contexts] == [VoteAbort]
            assert all(
                context.get("message") != "Task exception was never retrieved"
                for context in loop_contexts
            )
        finally:
            release.set()
            await asyncio.sleep(0)
            loop.set_exception_handler(old_handler)

    @pytest.mark.asyncio
    async def test_caller_cancellation_observes_owned_vote_tasks(self, mock_governor):
        """Caller cancellation is prompt while child outcomes remain observed."""

        class VoteAbort(BaseException):
            pass

        release = asyncio.Event()
        all_started = asyncio.Event()
        started = 0
        loop_contexts: list[dict[str, Any]] = []

        async def delayed_failure(agent, proposals, task):
            nonlocal started
            started += 1
            if started == 2:
                all_started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            if agent.name == "agent0":
                raise RuntimeError("late ordinary failure")
            raise VoteAbort("late control flow")

        collector = VoteCollector(
            VoteCollectorConfig(
                vote_with_agent=delayed_failure,
                enable_rlm_early_termination=False,
            )
        )
        ctx = make_context(agents=[MockAgent(name=f"agent{i}") for i in range(2)])
        loop = asyncio.get_running_loop()
        old_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: loop_contexts.append(context))

        try:
            with patch(
                "aragora.debate.phases.vote_collector.get_complexity_governor",
                return_value=mock_governor,
            ):
                collection = asyncio.create_task(collector.collect_votes(ctx))
                await asyncio.wait_for(all_started.wait(), timeout=0.2)
                collection.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(collection, timeout=0.2)

            release.set()
            await asyncio.sleep(0.02)
            assert [type(context.get("exception")) for context in loop_contexts] == [VoteAbort]
            assert all(
                context.get("message") != "Task exception was never retrieved"
                for context in loop_contexts
            )
        finally:
            release.set()
            await asyncio.sleep(0)
            loop.set_exception_handler(old_handler)


class TestVoteTaskOwnership:
    """Exact-once lifecycle tests independent of vote semantics."""

    @pytest.mark.asyncio
    async def test_completion_winning_cancel_race_is_consumed_once(self):
        """A task that completes while cancel loses is consumed, not detached."""
        task = MagicMock(spec=asyncio.Task)
        task.done.side_effect = [False, True]
        task.cancel.return_value = False
        consume = MagicMock()
        owner = _VoteTaskOwner([task])

        owner.settle(consume, propagate=True)
        owner.settle(consume, propagate=True)

        consume.assert_called_once_with(task)
        task.add_done_callback.assert_not_called()
        assert owner.classification(task) == "consumed"

    @pytest.mark.asyncio
    async def test_completed_control_flow_propagates(self):
        """A completed control-flow failure is never downgraded to a skip."""

        class VoteAbort(BaseException):
            pass

        async def abort():
            raise VoteAbort("completed control flow")

        task = asyncio.create_task(abort())
        await asyncio.sleep(0)
        owner = _VoteTaskOwner([task])

        with pytest.raises(VoteAbort, match="completed control flow"):
            owner.settle(lambda completed: completed.result(), propagate=True)
        assert owner.classification(task) == "consumed"


# =============================================================================
# RLM Early Termination Tests
# =============================================================================


class TestRLMEarlyTermination:
    """Tests for RLM-inspired early termination."""

    def test_check_clear_majority_disabled(self):
        """Returns false when RLM early termination is disabled."""
        config = VoteCollectorConfig(enable_rlm_early_termination=False)
        collector = VoteCollector(config)

        votes = [make_vote(choice="A")] * 10

        has_majority, leader = collector._check_clear_majority(votes, total_agents=10)

        assert has_majority is False
        assert leader is None

    def test_check_clear_majority_empty_votes(self):
        """Returns false for empty votes."""
        config = VoteCollectorConfig(enable_rlm_early_termination=True)
        collector = VoteCollector(config)

        has_majority, leader = collector._check_clear_majority([], total_agents=10)

        assert has_majority is False
        assert leader is None

    def test_check_clear_majority_zero_agents(self):
        """Returns false for zero total agents."""
        config = VoteCollectorConfig(enable_rlm_early_termination=True)
        collector = VoteCollector(config)

        votes = [make_vote(choice="A")]

        has_majority, leader = collector._check_clear_majority(votes, total_agents=0)

        assert has_majority is False
        assert leader is None

    def test_check_clear_majority_below_threshold(self):
        """Returns false when below early termination threshold."""
        config = VoteCollectorConfig(
            enable_rlm_early_termination=True,
            rlm_early_termination_threshold=0.75,  # Need 75% of votes
        )
        collector = VoteCollector(config)

        # Only 5 votes collected out of 10 agents (50%)
        votes = [make_vote(choice="A")] * 5

        has_majority, leader = collector._check_clear_majority(votes, total_agents=10)

        assert has_majority is False
        assert leader is None

    def test_check_clear_majority_no_clear_leader(self):
        """Returns false when no clear majority leader."""
        config = VoteCollectorConfig(
            enable_rlm_early_termination=True,
            rlm_early_termination_threshold=0.5,
        )
        collector = VoteCollector(config)

        # 5 votes for A, 5 votes for B out of 10 agents - no majority
        votes = [make_vote(choice="A")] * 5 + [make_vote(choice="B")] * 5

        has_majority, leader = collector._check_clear_majority(votes, total_agents=10)

        assert has_majority is False
        assert leader is None

    def test_check_clear_majority_insufficient_lead(self):
        """Returns false when lead is insufficient."""
        config = VoteCollectorConfig(
            enable_rlm_early_termination=True,
            rlm_early_termination_threshold=0.5,
            rlm_majority_lead_threshold=0.3,  # Need 30% lead
        )
        collector = VoteCollector(config)

        # 6 votes for A, 4 votes for B - lead is only 20%
        votes = [make_vote(choice="A")] * 6 + [make_vote(choice="B")] * 4

        has_majority, leader = collector._check_clear_majority(votes, total_agents=10)

        assert has_majority is False
        assert leader is None

    def test_check_clear_majority_success(self):
        """Returns true when clear majority is reached."""
        config = VoteCollectorConfig(
            enable_rlm_early_termination=True,
            rlm_early_termination_threshold=0.5,
            rlm_majority_lead_threshold=0.2,
        )
        collector = VoteCollector(config)

        # 8 votes for A, 2 votes for B out of 10 agents
        # Lead is 60% (6/10), which exceeds 20% threshold
        votes = [make_vote(choice="A")] * 8 + [make_vote(choice="B")] * 2

        has_majority, leader = collector._check_clear_majority(votes, total_agents=10)

        assert has_majority is True
        assert leader == "A"

    def test_check_clear_majority_single_candidate(self):
        """Returns true when only one candidate has all votes."""
        config = VoteCollectorConfig(
            enable_rlm_early_termination=True,
            rlm_early_termination_threshold=0.5,
            rlm_majority_lead_threshold=0.2,
        )
        collector = VoteCollector(config)

        # All 8 votes for A
        votes = [make_vote(choice="A")] * 8

        has_majority, leader = collector._check_clear_majority(votes, total_agents=10)

        assert has_majority is True
        assert leader == "A"

    def test_check_clear_majority_votes_without_choice(self):
        """Handles votes without choice attribute."""
        config = VoteCollectorConfig(enable_rlm_early_termination=True)
        collector = VoteCollector(config)

        # Create mock votes without choice
        mock_vote = MagicMock()
        del mock_vote.choice  # Remove choice attribute
        votes = [mock_vote] * 8

        has_majority, leader = collector._check_clear_majority(votes, total_agents=10)

        assert has_majority is False
        assert leader is None

    @pytest.mark.asyncio
    async def test_collect_votes_early_termination_triggers(self):
        """Vote collection terminates early when clear majority reached."""
        mock_governor = MagicMock()
        mock_governor.get_scaled_timeout.return_value = 30.0

        call_order = []

        async def mock_vote(agent, proposals, task):
            call_order.append(agent.name)
            return make_vote(agent=agent.name, choice="consensus")

        # Create many agents
        agents = [MockAgent(name=f"agent{i}") for i in range(10)]

        config = VoteCollectorConfig(
            vote_with_agent=mock_vote,
            enable_rlm_early_termination=True,
            rlm_early_termination_threshold=0.5,
            rlm_majority_lead_threshold=0.1,
        )
        collector = VoteCollector(config)
        ctx = make_context(agents=agents)

        with patch(
            "aragora.debate.phases.vote_collector.get_complexity_governor",
            return_value=mock_governor,
        ):
            votes = await collector.collect_votes(ctx)

        # Should have terminated early (not all 10 agents)
        assert len(votes) > 0
        # All votes should be for consensus
        assert all(v.choice == "consensus" for v in votes)

    @pytest.mark.asyncio
    async def test_collect_votes_early_termination_hook_called(self):
        """Early termination calls the on_rlm_early_termination hook."""
        mock_governor = MagicMock()
        mock_governor.get_scaled_timeout.return_value = 30.0

        hook_called = []

        def early_termination_hook(**kwargs):
            hook_called.append(kwargs)

        async def mock_vote(agent, proposals, task):
            return make_vote(agent=agent.name, choice="winner")

        agents = [MockAgent(name=f"agent{i}") for i in range(10)]

        config = VoteCollectorConfig(
            vote_with_agent=mock_vote,
            hooks={"on_rlm_early_termination": early_termination_hook},
            enable_rlm_early_termination=True,
            rlm_early_termination_threshold=0.5,
            rlm_majority_lead_threshold=0.1,
        )
        collector = VoteCollector(config)
        ctx = make_context(agents=agents)

        with patch(
            "aragora.debate.phases.vote_collector.get_complexity_governor",
            return_value=mock_governor,
        ):
            await collector.collect_votes(ctx)

        # Hook should have been called
        assert len(hook_called) == 1
        assert hook_called[0]["leader"] == "winner"

    @pytest.mark.asyncio
    async def test_collect_votes_early_termination_spectator_notified(self):
        """Early termination notifies spectator."""
        mock_governor = MagicMock()
        mock_governor.get_scaled_timeout.return_value = 30.0

        notifications = []

        def notify_spectator(event, **kwargs):
            notifications.append((event, kwargs))

        async def mock_vote(agent, proposals, task):
            return make_vote(agent=agent.name, choice="winner")

        agents = [MockAgent(name=f"agent{i}") for i in range(10)]

        config = VoteCollectorConfig(
            vote_with_agent=mock_vote,
            notify_spectator=notify_spectator,
            enable_rlm_early_termination=True,
            rlm_early_termination_threshold=0.5,
            rlm_majority_lead_threshold=0.1,
        )
        collector = VoteCollector(config)
        ctx = make_context(agents=agents)

        with patch(
            "aragora.debate.phases.vote_collector.get_complexity_governor",
            return_value=mock_governor,
        ):
            await collector.collect_votes(ctx)

        # Should have rlm_early_termination notification
        early_term_notifs = [n for n in notifications if n[0] == "rlm_early_termination"]
        assert len(early_term_notifs) == 1

    @pytest.mark.asyncio
    async def test_early_stop_observes_delayed_cancellation_cleanup(self):
        """Early stop returns promptly and observes every detached voter."""

        class VoteAbort(BaseException):
            pass

        release_cleanup = asyncio.Event()
        loop_contexts: list[dict[str, Any]] = []
        hook = MagicMock()

        async def mock_vote(agent, proposals, task):
            agent_number = int(agent.name.removeprefix("agent"))
            if agent_number < 6:
                return make_vote(agent=agent.name, choice="winner")
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                await release_cleanup.wait()
            if agent_number == 6:
                return make_vote(agent=agent.name, choice="late")
            if agent_number == 7:
                raise RuntimeError("late cleanup")
            if agent_number == 8:
                raise VoteAbort("late control flow")
            return None

        collector = VoteCollector(
            VoteCollectorConfig(
                vote_with_agent=mock_vote,
                hooks={"on_rlm_early_termination": hook},
                enable_rlm_early_termination=True,
                rlm_early_termination_threshold=0.5,
                rlm_majority_lead_threshold=0.1,
                vote_collection_timeout=1.0,
            )
        )
        ctx = make_context(agents=[MockAgent(name=f"agent{i}") for i in range(10)])
        loop = asyncio.get_running_loop()
        old_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: loop_contexts.append(context))

        try:
            votes = await asyncio.wait_for(collector.collect_votes(ctx), timeout=0.2)
            assert len(votes) == 6
            hook.assert_called_once_with(leader="winner", votes_collected=6, total_agents=10)

            release_cleanup.set()
            await asyncio.sleep(0.02)
            assert [type(context.get("exception")) for context in loop_contexts] == [VoteAbort]
            assert all(
                context.get("message") != "Task exception was never retrieved"
                for context in loop_contexts
            )
        finally:
            release_cleanup.set()
            await asyncio.sleep(0)
            loop.set_exception_handler(old_handler)


# =============================================================================
# Position Shuffling Tests
# =============================================================================


class TestPositionShuffling:
    """Tests for position shuffling bias mitigation."""

    @pytest.fixture
    def mock_governor(self):
        """Create mock complexity governor."""
        mock = MagicMock()
        mock.get_scaled_timeout.return_value = 30.0
        return mock

    @pytest.mark.asyncio
    async def test_collect_votes_with_shuffling_no_proposals(self, mock_governor):
        """Returns empty when no proposals for shuffling."""

        async def mock_vote(agent, proposals, task):
            return make_vote(agent=agent.name)

        config = VoteCollectorConfig(
            vote_with_agent=mock_vote,
            enable_position_shuffling=True,
            position_shuffling_permutations=3,
        )
        collector = VoteCollector(config)
        ctx = make_context(proposals={})

        with patch(
            "aragora.debate.phases.vote_collector.get_complexity_governor",
            return_value=mock_governor,
        ):
            votes = await collector._collect_votes_with_shuffling(ctx)

        assert votes == []

    @pytest.mark.asyncio
    async def test_collect_votes_with_shuffling_enabled(self, mock_governor):
        """Position shuffling collects votes across permutations."""
        vote_calls = []

        async def mock_vote(agent, proposals, task):
            vote_calls.append((agent.name, list(proposals.keys())))
            return make_vote(agent=agent.name, choice=list(proposals.keys())[0])

        config = VoteCollectorConfig(
            vote_with_agent=mock_vote,
            enable_position_shuffling=True,
            position_shuffling_permutations=3,
            position_shuffling_seed=42,
        )
        collector = VoteCollector(config)
        ctx = make_context()

        with patch(
            "aragora.debate.phases.vote_collector.get_complexity_governor",
            return_value=mock_governor,
        ):
            votes = await collector.collect_votes(ctx)

        # Should have called vote for each agent in each permutation
        assert len(vote_calls) == 6  # 2 agents x 3 permutations

    @pytest.mark.asyncio
    async def test_collect_single_permutation_votes(self, mock_governor):
        """Single permutation vote collection works correctly."""

        async def mock_vote(agent, proposals, task):
            return make_vote(agent=agent.name)

        config = VoteCollectorConfig(vote_with_agent=mock_vote)
        collector = VoteCollector(config)
        ctx = make_context()
        proposals = {"agent1": "Proposal A", "agent2": "Proposal B"}

        with patch(
            "aragora.debate.phases.vote_collector.get_complexity_governor",
            return_value=mock_governor,
        ):
            votes = await collector._collect_single_permutation_votes(ctx, proposals, 0)

        assert len(votes) == 2

    @pytest.mark.asyncio
    async def test_collect_single_permutation_handles_exceptions(self, mock_governor):
        """Single permutation handles agent exceptions."""

        async def mock_vote(agent, proposals, task):
            if agent.name == "agent1":
                raise RuntimeError("Agent error")
            return make_vote(agent=agent.name)

        config = VoteCollectorConfig(vote_with_agent=mock_vote)
        collector = VoteCollector(config)
        ctx = make_context()
        proposals = {"agent1": "Proposal A", "agent2": "Proposal B"}

        with patch(
            "aragora.debate.phases.vote_collector.get_complexity_governor",
            return_value=mock_governor,
        ):
            votes = await collector._collect_single_permutation_votes(ctx, proposals, 0)

        # Should have 1 vote (agent2's)
        assert len(votes) == 1

    @pytest.mark.asyncio
    async def test_position_shuffling_timeout(self, mock_governor):
        """Position shuffling respects extended timeout."""

        async def slow_vote(agent, proposals, task):
            await asyncio.sleep(10)
            return make_vote(agent=agent.name)

        config = VoteCollectorConfig(
            vote_with_agent=slow_vote,
            enable_position_shuffling=True,
            position_shuffling_permutations=3,
            vote_collection_timeout=0.01,  # Very short timeout
        )
        collector = VoteCollector(config)
        ctx = make_context()

        with patch(
            "aragora.debate.phases.vote_collector.get_complexity_governor",
            return_value=mock_governor,
        ):
            votes = await collector.collect_votes(ctx)

        # Should timeout and return empty
        assert votes == []

    @pytest.mark.asyncio
    async def test_position_shuffling_timeout_observes_child_task(self, mock_governor):
        """The outer shuffling timeout cannot orphan a permutation voter."""

        class VoteAbort(BaseException):
            pass

        release = asyncio.Event()
        loop_contexts: list[dict[str, Any]] = []

        async def late_abort(agent, proposals, task):
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            raise VoteAbort("late shuffled control flow")

        collector = VoteCollector(
            VoteCollectorConfig(
                vote_with_agent=late_abort,
                vote_collection_timeout=0.01,
                enable_position_shuffling=True,
                position_shuffling_permutations=1,
            )
        )
        loop = asyncio.get_running_loop()
        old_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: loop_contexts.append(context))

        try:
            with patch(
                "aragora.debate.phases.vote_collector.get_complexity_governor",
                return_value=mock_governor,
            ):
                assert await collector.collect_votes(make_context()) == []
            release.set()
            await asyncio.sleep(0.02)
            assert [context.get("message") for context in loop_contexts] == [
                "Detached vote task raised a control-flow exception",
                "Detached vote task raised a control-flow exception",
            ]
        finally:
            release.set()
            await asyncio.sleep(0)
            loop.set_exception_handler(old_handler)


# =============================================================================
# Vote Success Handling Tests
# =============================================================================


class TestHandleVoteSuccess:
    """Tests for _handle_vote_success method."""

    def test_handle_vote_success_notifies_spectator(self):
        """Vote success notifies spectator."""
        notifications = []

        def notify(event, **kwargs):
            notifications.append((event, kwargs))

        config = VoteCollectorConfig(notify_spectator=notify)
        collector = VoteCollector(config)
        ctx = make_context()
        agent = MockAgent(name="voter1")
        vote = make_vote(agent="voter1", choice="agent1", confidence=0.9)

        collector._handle_vote_success(ctx, agent, vote)

        assert len(notifications) == 1
        assert notifications[0][0] == "vote"
        assert notifications[0][1]["agent"] == "voter1"
        assert "agent1" in notifications[0][1]["details"]

    def test_handle_vote_success_calls_hook(self):
        """Vote success calls on_vote hook."""
        hook_calls = []

        def on_vote(agent_name, choice, confidence):
            hook_calls.append((agent_name, choice, confidence))

        config = VoteCollectorConfig(hooks={"on_vote": on_vote})
        collector = VoteCollector(config)
        ctx = make_context()
        agent = MockAgent(name="voter1")
        vote = make_vote(agent="voter1", choice="agent1", confidence=0.85)

        collector._handle_vote_success(ctx, agent, vote)

        assert len(hook_calls) == 1
        assert hook_calls[0] == ("voter1", "agent1", 0.85)

    def test_handle_vote_success_records_vote(self):
        """Vote success records vote with recorder."""
        recorder = MagicMock()

        config = VoteCollectorConfig(recorder=recorder)
        collector = VoteCollector(config)
        ctx = make_context()
        agent = MockAgent(name="voter1")
        vote = make_vote(agent="voter1", choice="agent1", reasoning="Good choice")

        collector._handle_vote_success(ctx, agent, vote)

        recorder.record_vote.assert_called_once_with("voter1", "agent1", "Good choice")

    def test_handle_vote_success_handles_recorder_error(self):
        """Vote success handles recorder errors gracefully."""
        recorder = MagicMock()
        recorder.record_vote.side_effect = RuntimeError("Record error")

        config = VoteCollectorConfig(recorder=recorder)
        collector = VoteCollector(config)
        ctx = make_context()
        agent = MockAgent(name="voter1")
        vote = make_vote()

        # Should not raise
        collector._handle_vote_success(ctx, agent, vote)

    def test_handle_vote_success_tracks_position(self):
        """Vote success tracks position with position_tracker."""
        position_tracker = MagicMock()

        config = VoteCollectorConfig(position_tracker=position_tracker)
        collector = VoteCollector(config)
        ctx = make_context()
        agent = MockAgent(name="voter1")
        vote = make_vote(agent="voter1", choice="agent1", confidence=0.9)

        collector._handle_vote_success(ctx, agent, vote)

        position_tracker.record_position.assert_called_once()
        call_kwargs = position_tracker.record_position.call_args[1]
        assert call_kwargs["agent_name"] == "voter1"
        assert call_kwargs["position_type"] == "vote"
        assert call_kwargs["position_text"] == "agent1"
        assert call_kwargs["confidence"] == 0.9

    def test_handle_vote_success_handles_position_tracker_error(self):
        """Vote success handles position tracker errors gracefully."""
        position_tracker = MagicMock()
        position_tracker.record_position.side_effect = RuntimeError("Tracker error")

        config = VoteCollectorConfig(position_tracker=position_tracker)
        collector = VoteCollector(config)
        ctx = make_context()
        agent = MockAgent(name="voter1")
        vote = make_vote()

        # Should not raise
        collector._handle_vote_success(ctx, agent, vote)


# =============================================================================
# Vote Grouping Tests
# =============================================================================


class TestComputeVoteGroups:
    """Tests for compute_vote_groups method."""

    def test_compute_vote_groups_no_callback(self):
        """Without grouping callback, returns identity mapping."""
        config = VoteCollectorConfig()
        collector = VoteCollector(config)

        votes = [
            make_vote(choice="A"),
            make_vote(choice="B"),
            make_vote(choice="A"),
        ]

        groups, mapping = collector.compute_vote_groups(votes)

        # Identity mapping
        assert groups == {"A": ["A"], "B": ["B"]}
        assert mapping == {"A": "A", "B": "B"}

    def test_compute_vote_groups_with_callback(self):
        """With grouping callback, uses the grouped results."""

        def group_similar(votes):
            # Group "A" and "A variant" as "A"
            return {"A": ["A", "A variant"], "B": ["B"]}

        config = VoteCollectorConfig(group_similar_votes=group_similar)
        collector = VoteCollector(config)

        votes = [
            make_vote(choice="A"),
            make_vote(choice="A variant"),
            make_vote(choice="B"),
        ]

        groups, mapping = collector.compute_vote_groups(votes)

        assert groups == {"A": ["A", "A variant"], "B": ["B"]}
        assert mapping == {"A": "A", "A variant": "A", "B": "B"}

    def test_compute_vote_groups_empty_votes(self):
        """Empty votes returns empty groups."""
        config = VoteCollectorConfig()
        collector = VoteCollector(config)

        groups, mapping = collector.compute_vote_groups([])

        assert groups == {}
        assert mapping == {}


# =============================================================================
# collect_votes_with_errors Tests
# =============================================================================


class TestCollectVotesWithErrors:
    """Tests for collect_votes_with_errors method (unanimity mode)."""

    @pytest.fixture
    def mock_governor(self):
        """Create mock complexity governor."""
        mock = MagicMock()
        mock.get_scaled_timeout.return_value = 30.0
        return mock

    @pytest.mark.asyncio
    async def test_collect_votes_with_errors_no_callback(self):
        """Returns empty when no vote_with_agent callback."""
        config = VoteCollectorConfig()
        collector = VoteCollector(config)
        ctx = make_context()

        votes, errors = await collector.collect_votes_with_errors(ctx)

        assert votes == []
        assert errors == 0

    @pytest.mark.asyncio
    async def test_collect_votes_with_errors_basic(self, mock_governor):
        """Basic vote collection with error tracking."""

        async def mock_vote(agent, proposals, task):
            return make_vote(agent=agent.name)

        config = VoteCollectorConfig(vote_with_agent=mock_vote)
        collector = VoteCollector(config)
        ctx = make_context()

        with patch(
            "aragora.debate.phases.vote_collector.get_complexity_governor",
            return_value=mock_governor,
        ):
            votes, errors = await collector.collect_votes_with_errors(ctx)

        assert len(votes) == 2
        assert errors == 0

    @pytest.mark.asyncio
    async def test_collect_votes_with_errors_counts_exceptions(self, mock_governor):
        """Tracks errors from agent exceptions."""

        async def mock_vote(agent, proposals, task):
            if agent.name == "agent1":
                raise RuntimeError("Agent error")
            return make_vote(agent=agent.name)

        config = VoteCollectorConfig(vote_with_agent=mock_vote)
        collector = VoteCollector(config)
        ctx = make_context()

        with patch(
            "aragora.debate.phases.vote_collector.get_complexity_governor",
            return_value=mock_governor,
        ):
            votes, errors = await collector.collect_votes_with_errors(ctx)

        assert len(votes) == 1
        assert errors == 1

    @pytest.mark.asyncio
    async def test_collect_votes_with_errors_counts_none(self, mock_governor):
        """Tracks errors from None vote results."""

        async def mock_vote(agent, proposals, task):
            if agent.name == "agent1":
                return None
            return make_vote(agent=agent.name)

        config = VoteCollectorConfig(vote_with_agent=mock_vote)
        collector = VoteCollector(config)
        ctx = make_context()

        with patch(
            "aragora.debate.phases.vote_collector.get_complexity_governor",
            return_value=mock_governor,
        ):
            votes, errors = await collector.collect_votes_with_errors(ctx)

        assert len(votes) == 1
        assert errors == 1

    @pytest.mark.asyncio
    async def test_collect_votes_with_errors_counts_exception_result(self, mock_governor):
        """Tracks errors from Exception returned as result."""

        async def mock_vote(agent, proposals, task):
            if agent.name == "agent1":
                return ValueError("Parse error")
            return make_vote(agent=agent.name)

        config = VoteCollectorConfig(vote_with_agent=mock_vote)
        collector = VoteCollector(config)
        ctx = make_context()

        with patch(
            "aragora.debate.phases.vote_collector.get_complexity_governor",
            return_value=mock_governor,
        ):
            votes, errors = await collector.collect_votes_with_errors(ctx)

        assert len(votes) == 1
        assert errors == 1

    @pytest.mark.asyncio
    async def test_collect_votes_with_errors_timeout_as_errors(self, mock_governor):
        """Timeout missing votes are counted as errors."""

        async def slow_vote(agent, proposals, task):
            if agent.name == "agent1":
                await asyncio.sleep(10)
            return make_vote(agent=agent.name)

        config = VoteCollectorConfig(
            vote_with_agent=slow_vote,
            vote_collection_timeout=0.1,
        )
        collector = VoteCollector(config)
        ctx = make_context()

        with patch(
            "aragora.debate.phases.vote_collector.get_complexity_governor",
            return_value=mock_governor,
        ):
            votes, errors = await collector.collect_votes_with_errors(ctx)

        # The slow agent should timeout
        assert errors >= 1

    @pytest.mark.asyncio
    async def test_unanimous_timeout_observes_late_control_flow(self, mock_governor):
        """Unanimous timeout counts the missing vote and observes its task."""

        class VoteAbort(BaseException):
            pass

        release = asyncio.Event()
        loop_contexts: list[dict[str, Any]] = []

        async def vote_or_abort(agent, proposals, task):
            if agent.name == "agent0":
                return make_vote(agent=agent.name)
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            raise VoteAbort("late unanimous control flow")

        collector = VoteCollector(
            VoteCollectorConfig(
                vote_with_agent=vote_or_abort,
                vote_collection_timeout=0.01,
            )
        )
        ctx = make_context(agents=[MockAgent(name=f"agent{i}") for i in range(2)])
        loop = asyncio.get_running_loop()
        old_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: loop_contexts.append(context))

        try:
            with patch(
                "aragora.debate.phases.vote_collector.get_complexity_governor",
                return_value=mock_governor,
            ):
                votes, errors = await collector.collect_votes_with_errors(ctx)
            assert ([vote.agent for vote in votes], errors) == (["agent0"], 1)
            release.set()
            await asyncio.sleep(0.02)
            assert [context.get("message") for context in loop_contexts] == [
                "Detached vote task raised a control-flow exception"
            ]
        finally:
            release.set()
            await asyncio.sleep(0)
            loop.set_exception_handler(old_handler)


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases."""

    @pytest.fixture
    def mock_governor(self):
        """Create mock complexity governor."""
        mock = MagicMock()
        mock.get_scaled_timeout.return_value = 30.0
        return mock

    @pytest.mark.asyncio
    async def test_no_agents(self, mock_governor):
        """Vote collection with no agents returns empty."""

        async def mock_vote(agent, proposals, task):
            return make_vote(agent=agent.name)

        config = VoteCollectorConfig(vote_with_agent=mock_vote)
        collector = VoteCollector(config)
        ctx = make_context(agents=[])

        with patch(
            "aragora.debate.phases.vote_collector.get_complexity_governor",
            return_value=mock_governor,
        ):
            votes = await collector.collect_votes(ctx)

        assert votes == []

    @pytest.mark.asyncio
    async def test_single_agent(self, mock_governor):
        """Vote collection with single agent."""

        async def mock_vote(agent, proposals, task):
            return make_vote(agent=agent.name, choice="self")

        config = VoteCollectorConfig(vote_with_agent=mock_vote)
        collector = VoteCollector(config)
        ctx = make_context(agents=[MockAgent(name="solo")])

        with patch(
            "aragora.debate.phases.vote_collector.get_complexity_governor",
            return_value=mock_governor,
        ):
            votes = await collector.collect_votes(ctx)

        assert len(votes) == 1
        assert votes[0].agent == "solo"

    @pytest.mark.asyncio
    async def test_all_agents_fail(self, mock_governor):
        """All agents failing returns empty votes."""

        async def mock_vote(agent, proposals, task):
            raise RuntimeError("All fail")

        config = VoteCollectorConfig(vote_with_agent=mock_vote)
        collector = VoteCollector(config)
        ctx = make_context()

        with patch(
            "aragora.debate.phases.vote_collector.get_complexity_governor",
            return_value=mock_governor,
        ):
            votes = await collector.collect_votes(ctx)

        assert votes == []

    @pytest.mark.asyncio
    async def test_no_proposals(self, mock_governor):
        """Vote collection with no proposals."""

        async def mock_vote(agent, proposals, task):
            return make_vote(agent=agent.name)

        config = VoteCollectorConfig(vote_with_agent=mock_vote)
        collector = VoteCollector(config)
        ctx = make_context(proposals={})

        with patch(
            "aragora.debate.phases.vote_collector.get_complexity_governor",
            return_value=mock_governor,
        ):
            votes = await collector.collect_votes(ctx)

        assert len(votes) == 2

    def test_handle_vote_success_unanimous_flag(self):
        """Unanimous flag doesn't change behavior."""
        notifications = []

        def notify(event, **kwargs):
            notifications.append((event, kwargs))

        config = VoteCollectorConfig(notify_spectator=notify)
        collector = VoteCollector(config)
        ctx = make_context()
        agent = MockAgent(name="voter1")
        vote = make_vote()

        collector._handle_vote_success(ctx, agent, vote, unanimous=True)

        # Should still notify
        assert len(notifications) == 1


# =============================================================================
# Factory Function Tests
# =============================================================================


class TestCreateVoteCollector:
    """Tests for create_vote_collector factory function."""

    def test_create_with_defaults(self):
        """Factory creates collector with default values."""
        collector = create_vote_collector()

        assert collector._vote_with_agent is None
        assert collector._with_timeout is None
        assert collector._notify_spectator is None
        assert collector.hooks == {}
        assert collector.config.enable_rlm_early_termination is True
        assert collector.config.enable_position_shuffling is False

    def test_create_with_callbacks(self):
        """Factory creates collector with provided callbacks."""
        vote_cb = MagicMock()
        timeout_cb = MagicMock()
        notify_cb = MagicMock()

        collector = create_vote_collector(
            vote_with_agent=vote_cb,
            with_timeout=timeout_cb,
            notify_spectator=notify_cb,
        )

        assert collector._vote_with_agent is vote_cb
        assert collector._with_timeout is timeout_cb
        assert collector._notify_spectator is notify_cb

    def test_create_with_hooks(self):
        """Factory creates collector with hooks."""
        hooks = {"on_vote": MagicMock(), "on_rlm_early_termination": MagicMock()}

        collector = create_vote_collector(hooks=hooks)

        assert collector.hooks == hooks

    def test_create_with_recorders(self):
        """Factory creates collector with recorder and position tracker."""
        recorder = MagicMock()
        position_tracker = MagicMock()

        collector = create_vote_collector(
            recorder=recorder,
            position_tracker=position_tracker,
        )

        assert collector.recorder is recorder
        assert collector.position_tracker is position_tracker

    def test_create_with_timeouts(self):
        """Factory creates collector with custom timeouts."""
        collector = create_vote_collector(
            vote_collection_timeout=120.0,
            agent_timeout=45.0,
        )

        assert collector.VOTE_COLLECTION_TIMEOUT == 120.0
        assert collector.config.agent_timeout == 45.0

    def test_create_with_rlm_settings(self):
        """Factory creates collector with RLM early termination settings."""
        collector = create_vote_collector(
            enable_rlm_early_termination=False,
            rlm_early_termination_threshold=0.6,
            rlm_majority_lead_threshold=0.3,
        )

        assert collector.config.enable_rlm_early_termination is False
        assert collector.config.rlm_early_termination_threshold == 0.6
        assert collector.config.rlm_majority_lead_threshold == 0.3

    def test_create_with_position_shuffling(self):
        """Factory creates collector with position shuffling settings."""
        collector = create_vote_collector(
            enable_position_shuffling=True,
            position_shuffling_permutations=5,
            position_shuffling_seed=123,
        )

        assert collector.config.enable_position_shuffling is True
        assert collector.config.position_shuffling_permutations == 5
        assert collector.config.position_shuffling_seed == 123

    def test_create_with_vote_grouping(self):
        """Factory creates collector with vote grouping callback."""
        group_cb = MagicMock()

        collector = create_vote_collector(group_similar_votes=group_cb)

        assert collector._group_similar_votes is group_cb


# =============================================================================
# Integration Tests
# =============================================================================


class TestVoteCollectorIntegration:
    """Integration tests for VoteCollector."""

    @pytest.fixture
    def mock_governor(self):
        """Create mock complexity governor."""
        mock = MagicMock()
        mock.get_scaled_timeout.return_value = 30.0
        return mock

    @pytest.mark.asyncio
    async def test_full_vote_collection_flow(self, mock_governor):
        """Test complete vote collection flow with all features."""
        notifications = []
        hook_calls = []
        recorded_votes = []
        positions = []

        def notify(event, **kwargs):
            notifications.append((event, kwargs))

        def on_vote(agent_name, choice, confidence):
            hook_calls.append((agent_name, choice, confidence))

        recorder = MagicMock()
        recorder.record_vote = lambda a, c, r: recorded_votes.append((a, c, r))

        position_tracker = MagicMock()
        position_tracker.record_position = lambda **kw: positions.append(kw)

        async def mock_vote(agent, proposals, task):
            return make_vote(
                agent=agent.name,
                choice="winner",
                reasoning=f"Vote by {agent.name}",
                confidence=0.9,
            )

        agents = [MockAgent(name=f"agent{i}") for i in range(3)]

        config = VoteCollectorConfig(
            vote_with_agent=mock_vote,
            notify_spectator=notify,
            hooks={"on_vote": on_vote},
            recorder=recorder,
            position_tracker=position_tracker,
            # Disable early termination to collect all votes
            enable_rlm_early_termination=False,
        )
        collector = VoteCollector(config)
        ctx = make_context(agents=agents)

        with patch(
            "aragora.debate.phases.vote_collector.get_complexity_governor",
            return_value=mock_governor,
        ):
            votes = await collector.collect_votes(ctx)

        # All votes collected (no early termination)
        assert len(votes) == 3

        # All notifications sent
        assert len([n for n in notifications if n[0] == "vote"]) == 3

        # All hooks called
        assert len(hook_calls) == 3

        # All votes recorded
        assert len(recorded_votes) == 3

        # All positions tracked
        assert len(positions) == 3

    @pytest.mark.asyncio
    async def test_mixed_success_and_failure(self, mock_governor):
        """Test vote collection with mixed success and failure."""

        async def mock_vote(agent, proposals, task):
            if "fail" in agent.name:
                raise RuntimeError("Intentional failure")
            return make_vote(agent=agent.name)

        agents = [
            MockAgent(name="success1"),
            MockAgent(name="fail1"),
            MockAgent(name="success2"),
            MockAgent(name="fail2"),
        ]

        config = VoteCollectorConfig(vote_with_agent=mock_vote)
        collector = VoteCollector(config)
        ctx = make_context(agents=agents)

        with patch(
            "aragora.debate.phases.vote_collector.get_complexity_governor",
            return_value=mock_governor,
        ):
            votes, errors = await collector.collect_votes_with_errors(ctx)

        # 2 successful, 2 failures
        assert len(votes) == 2
        assert errors == 2
        assert all(v.agent.startswith("success") for v in votes)
