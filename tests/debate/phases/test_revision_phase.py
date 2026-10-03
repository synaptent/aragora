"""
Tests for the RevisionPhase module.

Tests cover:
- RevisionGenerator initialization
- Revision generation with mocked agents
- Concurrency limiting via semaphore
- Timeout handling (phase and per-agent)
- Error recovery and circuit breaker integration
- Edge cases (no critiques, single agent, all timeouts)
- Molecule tracking (Gastown pattern)
- Rhetorical observation
- Heartbeat emission
- Prompt building and message creation
- Context mutation and result accumulation
"""

import asyncio
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.debate.phases.revision_phase import (
    REVISION_PHASE_BASE_TIMEOUT,
    RevisionGenerator,
    calculate_phase_timeout,
)


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


@dataclass
class MockAgent:
    """Mock agent for testing."""

    name: str
    role: str = "proposer"
    model: str = "mock-model"
    timeout: int = 60


@dataclass
class MockCritique:
    """Mock critique for testing."""

    agent: str
    target_agent: str
    target_content: str = "test content"
    issues: list = field(default_factory=lambda: ["issue1"])
    suggestions: list = field(default_factory=lambda: ["suggestion1"])
    severity: float = 5.0
    reasoning: str = "test reasoning"


@dataclass
class MockEnvironment:
    """Mock environment for testing."""

    task: str = "Test debate task"


@dataclass
class MockDebateResult:
    """Mock debate result for testing."""

    id: str = "test-debate-123"
    messages: list = field(default_factory=list)


class MockDebateContext:
    """Mock debate context for testing."""

    def __init__(
        self,
        agents=None,
        proposers=None,
        proposals=None,
        task="Test task",
        debate_id="test-debate-123",
    ):
        self.agents = agents or []
        self.proposers = proposers or agents or []
        self.proposals = proposals or {}
        self.env = MockEnvironment(task=task)
        self.result = MockDebateResult(id=debate_id)
        self.context_messages = []
        self.partial_messages = []
        self.loop_id = "loop-1"
        self.debate_id = debate_id

    def add_message(self, msg):
        """Mirror :meth:`DebateContext.add_message` — all three destinations.

        The real method appends to ``context_messages``, ``partial_messages``
        AND ``result.messages`` (``debate_state.py``). This mock previously
        appended only to ``context_messages``, so phases that *also* appended to
        ``result.messages`` themselves looked correct here while double-counting
        every message in production — which is exactly how #9661 survived: the
        assertion below expects one message and got one, because the mock did
        not reproduce the duplication the real context caused.
        """
        self.context_messages.append(msg)
        self.partial_messages.append(msg)
        if self.result is not None:
            self.result.messages.append(msg)


# ---------------------------------------------------------------------------
# calculate_phase_timeout
# ---------------------------------------------------------------------------


class TestCalculatePhaseTimeout:
    """Tests for calculate_phase_timeout function."""

    def test_returns_base_timeout_for_single_agent(self):
        """Single agent should use at least base timeout."""
        timeout = calculate_phase_timeout(1, 60.0)

        # (1 / 5) * 60 + 60 = 72, which is less than 120 base
        assert timeout == REVISION_PHASE_BASE_TIMEOUT

    def test_scales_with_agent_count(self):
        """Timeout should scale with number of agents."""
        from aragora.config import MAX_CONCURRENT_REVISIONS

        # Need enough agents to exceed one batch to see scaling
        timeout_small = calculate_phase_timeout(MAX_CONCURRENT_REVISIONS, 60.0)
        timeout_large = calculate_phase_timeout(MAX_CONCURRENT_REVISIONS * 2, 60.0)

        # More agents should mean longer timeout
        assert timeout_large > timeout_small

    def test_includes_buffer_time(self):
        """Timeout should include 60s buffer."""
        # With 5 agents and 60s timeout: (5/5) * 60 + 60 = 120
        timeout = calculate_phase_timeout(5, 60.0)

        assert timeout >= REVISION_PHASE_BASE_TIMEOUT

    def test_never_below_base_timeout(self):
        """Timeout should never be below base timeout."""
        timeout = calculate_phase_timeout(1, 10.0)

        assert timeout >= REVISION_PHASE_BASE_TIMEOUT

    def test_large_agent_count(self):
        """Should handle large agent counts correctly."""
        from aragora.config import MAX_CONCURRENT_REVISIONS

        timeout = calculate_phase_timeout(20, 120.0)

        expected = (20 / MAX_CONCURRENT_REVISIONS) * 120 + 60
        assert timeout == expected

    def test_zero_agents(self):
        """Zero agents returns base timeout (degenerate case)."""
        timeout = calculate_phase_timeout(0, 60.0)

        # (0/5)*60 + 60 = 60, base timeout is 120
        assert timeout == REVISION_PHASE_BASE_TIMEOUT

    def test_zero_agent_timeout(self):
        """Zero agent timeout still returns at least base timeout."""
        timeout = calculate_phase_timeout(10, 0.0)

        # (10/5)*0 + 60 = 60 < 120 base
        assert timeout == REVISION_PHASE_BASE_TIMEOUT

    def test_very_large_agent_timeout(self):
        """Very large per-agent timeout produces larger phase timeout."""
        from aragora.config import MAX_CONCURRENT_REVISIONS

        timeout = calculate_phase_timeout(10, 600.0)

        expected = (10 / MAX_CONCURRENT_REVISIONS) * 600 + 60
        assert timeout == expected
        assert timeout > REVISION_PHASE_BASE_TIMEOUT

    def test_fractional_agents_per_batch(self):
        """Non-integer ratio of agents to max_concurrent is handled."""
        # 3 agents, 5 max_concurrent -> 3/5 = 0.6 batches
        timeout = calculate_phase_timeout(3, 100.0)

        expected = (3 / 5) * 100 + 60
        assert timeout == max(expected, REVISION_PHASE_BASE_TIMEOUT)


# ---------------------------------------------------------------------------
# RevisionGenerator.__init__
# ---------------------------------------------------------------------------


class TestRevisionGeneratorInit:
    """Tests for RevisionGenerator initialization."""

    def test_init_minimal(self):
        """RevisionGenerator can be initialized with no arguments."""
        generator = RevisionGenerator()

        assert generator.circuit_breaker is None
        assert generator.hooks == {}
        assert generator.recorder is None

    def test_init_with_callbacks(self):
        """RevisionGenerator stores callback functions."""
        mock_generate = AsyncMock()
        mock_build_prompt = MagicMock()
        mock_timeout = AsyncMock()

        generator = RevisionGenerator(
            generate_with_agent=mock_generate,
            build_revision_prompt=mock_build_prompt,
            with_timeout=mock_timeout,
        )

        assert generator._generate_with_agent is mock_generate
        assert generator._build_revision_prompt is mock_build_prompt
        assert generator._with_timeout is mock_timeout

    def test_init_with_circuit_breaker(self):
        """RevisionGenerator stores circuit breaker."""
        mock_cb = MagicMock()
        generator = RevisionGenerator(circuit_breaker=mock_cb)

        assert generator.circuit_breaker is mock_cb

    def test_init_with_hooks(self):
        """RevisionGenerator stores hooks."""
        hooks = {"on_message": MagicMock()}
        generator = RevisionGenerator(hooks=hooks)

        assert generator.hooks == hooks

    def test_init_hooks_default_to_empty_dict(self):
        """Hooks default to empty dict when None."""
        generator = RevisionGenerator(hooks=None)

        assert generator.hooks == {}

    def test_init_with_custom_concurrency(self):
        """RevisionGenerator accepts custom max_concurrent."""
        generator = RevisionGenerator(max_concurrent=3)

        assert generator._max_concurrent == 3

    def test_init_with_molecule_tracker(self):
        """RevisionGenerator stores molecule tracker."""
        mock_tracker = MagicMock()
        generator = RevisionGenerator(molecule_tracker=mock_tracker)

        assert generator._molecule_tracker is mock_tracker

    def test_init_active_molecules_empty(self):
        """Active molecules dict starts empty."""
        generator = RevisionGenerator()

        assert generator._active_molecules == {}

    def test_init_all_optional_callbacks(self):
        """All optional callbacks stored correctly."""
        mock_spectator = MagicMock()
        mock_heartbeat = MagicMock()
        mock_grounded = MagicMock()
        mock_rhetorical = MagicMock()

        generator = RevisionGenerator(
            notify_spectator=mock_spectator,
            heartbeat_callback=mock_heartbeat,
            record_grounded_position=mock_grounded,
            rhetorical_observer=mock_rhetorical,
        )

        assert generator._notify_spectator is mock_spectator
        assert generator._emit_heartbeat is mock_heartbeat
        assert generator._record_grounded_position is mock_grounded
        assert generator._rhetorical_observer is mock_rhetorical


# ---------------------------------------------------------------------------
# execute_revision_phase - basic execution
# ---------------------------------------------------------------------------


class TestRevisionGeneratorExecute:
    """Tests for execute_revision_phase method."""

    @pytest.fixture
    def basic_generator(self):
        """Create a basic generator with mocked callbacks."""
        mock_generate = AsyncMock(return_value="Revised proposal")
        mock_build_prompt = MagicMock(return_value="Revision prompt")

        async def passthrough_timeout(coro, *args, **kwargs):
            """Passthrough timeout that just awaits the coroutine."""
            return await coro

        return RevisionGenerator(
            generate_with_agent=mock_generate,
            build_revision_prompt=mock_build_prompt,
            with_timeout=passthrough_timeout,
        )

    @pytest.mark.asyncio
    async def test_execute_returns_empty_without_callbacks(self):
        """Returns empty dict when callbacks are missing."""
        generator = RevisionGenerator()
        ctx = MockDebateContext(
            proposers=[MockAgent("agent1")],
            proposals={"agent1": "Initial proposal"},
        )
        critiques = [MockCritique("critic1", "agent1")]

        result = await generator.execute_revision_phase(ctx, 1, critiques, [])

        assert result == {}

    @pytest.mark.asyncio
    async def test_execute_returns_empty_without_generate_callback(self):
        """Returns empty when only build_revision_prompt is set."""
        generator = RevisionGenerator(
            build_revision_prompt=MagicMock(return_value="prompt"),
        )
        ctx = MockDebateContext(
            proposers=[MockAgent("agent1")],
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        result = await generator.execute_revision_phase(ctx, 1, critiques, [])

        assert result == {}

    @pytest.mark.asyncio
    async def test_execute_returns_empty_without_build_prompt_callback(self):
        """Returns empty when only generate_with_agent is set."""
        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
        )
        ctx = MockDebateContext(
            proposers=[MockAgent("agent1")],
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        result = await generator.execute_revision_phase(ctx, 1, critiques, [])

        assert result == {}

    @pytest.mark.asyncio
    async def test_execute_returns_empty_without_critiques(self, basic_generator):
        """Returns empty dict when no critiques."""
        ctx = MockDebateContext(
            proposers=[MockAgent("agent1")],
            proposals={"agent1": "Initial proposal"},
        )

        result = await basic_generator.execute_revision_phase(ctx, 1, [], [])

        assert result == {}

    @pytest.mark.asyncio
    async def test_execute_basic_revision(self, basic_generator):
        """Basic revision generation works."""
        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Initial proposal"},
        )
        critiques = [MockCritique("critic1", "agent1")]
        partial_messages = []

        result = await basic_generator.execute_revision_phase(ctx, 1, critiques, partial_messages)

        assert "agent1" in result
        assert result["agent1"] == "Revised proposal"
        assert ctx.proposals["agent1"] == "Revised proposal"
        assert len(partial_messages) == 1

    @pytest.mark.asyncio
    async def test_execute_multiple_agents(self, basic_generator):
        """Handles multiple agents with separate revisions."""
        agents = [MockAgent("agent1"), MockAgent("agent2")]
        ctx = MockDebateContext(
            proposers=agents,
            proposals={"agent1": "Proposal 1", "agent2": "Proposal 2"},
        )
        critiques = [
            MockCritique("critic", "agent1"),
            MockCritique("critic", "agent2"),
        ]
        partial_messages = []

        result = await basic_generator.execute_revision_phase(ctx, 1, critiques, partial_messages)

        assert len(result) == 2
        assert "agent1" in result
        assert "agent2" in result

    @pytest.mark.asyncio
    async def test_execute_skips_agents_without_critiques(self, basic_generator):
        """Agents without critiques don't generate revisions."""
        agents = [MockAgent("agent1"), MockAgent("agent2")]
        ctx = MockDebateContext(
            proposers=agents,
            proposals={"agent1": "Proposal 1", "agent2": "Proposal 2"},
        )
        # Only agent1 has critiques
        critiques = [MockCritique("critic", "agent1")]
        partial_messages = []

        result = await basic_generator.execute_revision_phase(ctx, 1, critiques, partial_messages)

        assert len(result) == 1
        assert "agent1" in result
        assert "agent2" not in result

    @pytest.mark.asyncio
    async def test_execute_updates_proposals_dict(self, basic_generator):
        """The ctx.proposals dict is mutated with revised content."""
        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Old proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        await basic_generator.execute_revision_phase(ctx, 1, critiques, [])

        assert ctx.proposals["agent1"] == "Revised proposal"

    @pytest.mark.asyncio
    async def test_execute_appends_to_result_messages(self, basic_generator):
        """Messages are appended to ctx.result.messages."""
        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        await basic_generator.execute_revision_phase(ctx, 1, critiques, [])

        assert len(ctx.result.messages) == 1
        msg = ctx.result.messages[0]
        assert msg.role == "proposer"
        assert msg.agent == "agent1"
        assert msg.content == "Revised proposal"
        assert msg.round == 1

    @pytest.mark.asyncio
    async def test_execute_adds_message_to_context(self, basic_generator):
        """Messages are added to ctx via add_message."""
        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        await basic_generator.execute_revision_phase(ctx, 1, critiques, [])

        assert len(ctx.context_messages) == 1

    @pytest.mark.asyncio
    async def test_execute_partial_messages_appended(self, basic_generator):
        """Partial messages list gets new messages appended."""
        agents = [MockAgent("agent1"), MockAgent("agent2")]
        ctx = MockDebateContext(
            proposers=agents,
            proposals={"agent1": "P1", "agent2": "P2"},
        )
        critiques = [
            MockCritique("critic", "agent1"),
            MockCritique("critic", "agent2"),
        ]
        partial_messages = []

        await basic_generator.execute_revision_phase(ctx, 1, critiques, partial_messages)

        assert len(partial_messages) == 2

    @pytest.mark.asyncio
    async def test_execute_round_number_passed_correctly(self):
        """The round number is used in message creation."""
        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
            build_revision_prompt=MagicMock(return_value="prompt"),
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        await generator.execute_revision_phase(ctx, 5, critiques, [])

        assert ctx.result.messages[0].round == 5

    @pytest.mark.asyncio
    async def test_execute_different_revisions_per_agent(self):
        """Different agents can get different revision results."""
        call_index = 0

        async def per_agent_generate(agent, *args, **kwargs):
            nonlocal call_index
            call_index += 1
            return f"Revision for {agent.name}"

        generator = RevisionGenerator(
            generate_with_agent=per_agent_generate,
            build_revision_prompt=MagicMock(return_value="prompt"),
        )

        agents = [MockAgent("alice"), MockAgent("bob")]
        ctx = MockDebateContext(
            proposers=agents,
            proposals={"alice": "P1", "bob": "P2"},
        )
        critiques = [
            MockCritique("critic", "alice"),
            MockCritique("critic", "bob"),
        ]

        result = await generator.execute_revision_phase(ctx, 1, critiques, [])

        assert result["alice"] == "Revision for alice"
        assert result["bob"] == "Revision for bob"


# ---------------------------------------------------------------------------
# Concurrency limiting
# ---------------------------------------------------------------------------


class TestRevisionGeneratorConcurrency:
    """Tests for concurrency limiting."""

    @pytest.mark.asyncio
    async def test_respects_max_concurrent_limit(self):
        """Semaphore limits concurrent revisions."""
        concurrent_count = 0
        max_concurrent_observed = 0

        async def slow_generate(*args, **kwargs):
            nonlocal concurrent_count, max_concurrent_observed
            concurrent_count += 1
            max_concurrent_observed = max(max_concurrent_observed, concurrent_count)
            await asyncio.sleep(0.05)
            concurrent_count -= 1
            return "Revised"

        async def passthrough_timeout(coro, *args, **kwargs):
            return await coro

        generator = RevisionGenerator(
            generate_with_agent=slow_generate,
            build_revision_prompt=MagicMock(return_value="prompt"),
            with_timeout=passthrough_timeout,
            max_concurrent=2,
        )

        agents = [MockAgent(f"agent{i}") for i in range(5)]
        ctx = MockDebateContext(
            proposers=agents,
            proposals={a.name: f"Proposal {a.name}" for a in agents},
        )
        critiques = [MockCritique("critic", a.name) for a in agents]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        # Should never exceed max_concurrent
        assert max_concurrent_observed <= 2

    @pytest.mark.asyncio
    async def test_max_concurrent_one_runs_sequentially(self):
        """max_concurrent=1 forces sequential execution."""
        concurrent_count = 0
        max_concurrent_observed = 0

        async def slow_generate(*args, **kwargs):
            nonlocal concurrent_count, max_concurrent_observed
            concurrent_count += 1
            max_concurrent_observed = max(max_concurrent_observed, concurrent_count)
            await asyncio.sleep(0.02)
            concurrent_count -= 1
            return "Revised"

        async def passthrough_timeout(coro, *args, **kwargs):
            return await coro

        generator = RevisionGenerator(
            generate_with_agent=slow_generate,
            build_revision_prompt=MagicMock(return_value="prompt"),
            with_timeout=passthrough_timeout,
            max_concurrent=1,
        )

        agents = [MockAgent(f"agent{i}") for i in range(3)]
        ctx = MockDebateContext(
            proposers=agents,
            proposals={a.name: f"P{a.name}" for a in agents},
        )
        critiques = [MockCritique("critic", a.name) for a in agents]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        # With max_concurrent=1, only 1 at a time
        assert max_concurrent_observed == 1

    @pytest.mark.asyncio
    async def test_all_agents_eventually_complete(self):
        """All agents get to run despite bounded concurrency."""
        completed = set()

        async def track_generate(agent, *args, **kwargs):
            await asyncio.sleep(0.01)
            completed.add(agent.name)
            return "Revised"

        async def passthrough_timeout(coro, *args, **kwargs):
            return await coro

        generator = RevisionGenerator(
            generate_with_agent=track_generate,
            build_revision_prompt=MagicMock(return_value="prompt"),
            with_timeout=passthrough_timeout,
            max_concurrent=2,
        )

        agents = [MockAgent(f"agent{i}") for i in range(6)]
        ctx = MockDebateContext(
            proposers=agents,
            proposals={a.name: f"P{a.name}" for a in agents},
        )
        critiques = [MockCritique("critic", a.name) for a in agents]

        result = await generator.execute_revision_phase(ctx, 1, critiques, [])

        assert len(result) == 6
        assert completed == {f"agent{i}" for i in range(6)}

    @pytest.mark.asyncio
    async def test_large_max_concurrent_allows_parallelism(self):
        """Large max_concurrent allows many agents at once."""
        concurrent_count = 0
        max_concurrent_observed = 0

        async def fast_generate(*args, **kwargs):
            nonlocal concurrent_count, max_concurrent_observed
            concurrent_count += 1
            max_concurrent_observed = max(max_concurrent_observed, concurrent_count)
            await asyncio.sleep(0.02)
            concurrent_count -= 1
            return "Revised"

        async def passthrough_timeout(coro, *args, **kwargs):
            return await coro

        generator = RevisionGenerator(
            generate_with_agent=fast_generate,
            build_revision_prompt=MagicMock(return_value="prompt"),
            with_timeout=passthrough_timeout,
            max_concurrent=100,
        )

        agents = [MockAgent(f"agent{i}") for i in range(5)]
        ctx = MockDebateContext(
            proposers=agents,
            proposals={a.name: f"P{a.name}" for a in agents},
        )
        critiques = [MockCritique("critic", a.name) for a in agents]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        # With 100 max_concurrent, all 5 can run simultaneously
        assert max_concurrent_observed >= 2  # At least some parallelism


# ---------------------------------------------------------------------------
# Timeout handling
# ---------------------------------------------------------------------------


class TestRevisionGeneratorTimeout:
    """Tests for timeout handling."""

    @pytest.mark.asyncio
    async def test_per_agent_timeout_applied(self):
        """Individual agent timeout is passed to with_timeout."""
        timeout_called_with = []

        async def capture_timeout(coro, name, timeout_seconds=None):
            timeout_called_with.append(timeout_seconds)
            return await coro

        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
            build_revision_prompt=MagicMock(return_value="prompt"),
            with_timeout=capture_timeout,
        )

        agent = MockAgent("agent1", timeout=120)
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        with patch("aragora.debate.phases.revision_phase.get_complexity_governor") as mock_gov:
            mock_gov.return_value.get_scaled_timeout.return_value = 120.0
            await generator.execute_revision_phase(ctx, 1, critiques, [])

        assert len(timeout_called_with) == 1
        assert timeout_called_with[0] == 120.0

    @pytest.mark.asyncio
    async def test_agent_timeout_attribute_used(self):
        """Agent's own timeout attribute is read for scaling."""
        captured_base_timeout = []

        with patch("aragora.debate.phases.revision_phase.get_complexity_governor") as mock_gov:

            def capture_scaled(val):
                captured_base_timeout.append(val)
                return val

            mock_gov.return_value.get_scaled_timeout.side_effect = capture_scaled

            async def passthrough_timeout(coro, name, timeout_seconds=None):
                return await coro

            generator = RevisionGenerator(
                generate_with_agent=AsyncMock(return_value="Revised"),
                build_revision_prompt=MagicMock(return_value="prompt"),
                with_timeout=passthrough_timeout,
            )

            agent = MockAgent("agent1", timeout=200)
            ctx = MockDebateContext(
                proposers=[agent],
                proposals={"agent1": "Proposal"},
            )
            critiques = [MockCritique("critic", "agent1")]

            await generator.execute_revision_phase(ctx, 1, critiques, [])

        assert captured_base_timeout[0] == 200.0

    @pytest.mark.asyncio
    async def test_phase_timeout_catches_stalled_agents(self):
        """Phase timeout triggers when all agents stall."""

        async def never_complete(*args, **kwargs):
            await asyncio.sleep(1000)  # Very long
            return "Never reached"

        generator = RevisionGenerator(
            generate_with_agent=never_complete,
            build_revision_prompt=MagicMock(return_value="prompt"),
            max_concurrent=5,
        )

        agents = [MockAgent("agent1")]
        ctx = MockDebateContext(
            proposers=agents,
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        # Patch the phase timeout calculation to return a very short timeout
        with patch(
            "aragora.debate.phases.revision_phase.calculate_phase_timeout",
            return_value=0.1,
        ):
            result = await generator.execute_revision_phase(ctx, 1, critiques, [])

        # Should return empty because all timed out
        assert result == {}

    @pytest.mark.asyncio
    async def test_phase_timeout_fills_results_with_timeout_errors(self):
        """Phase timeout generates TimeoutError entries for each agent."""
        mock_cb = MagicMock()

        async def never_complete(*args, **kwargs):
            await asyncio.sleep(1000)
            return "Never reached"

        generator = RevisionGenerator(
            generate_with_agent=never_complete,
            build_revision_prompt=MagicMock(return_value="prompt"),
            circuit_breaker=mock_cb,
            max_concurrent=5,
        )

        agents = [MockAgent("agent1"), MockAgent("agent2")]
        ctx = MockDebateContext(
            proposers=agents,
            proposals={"agent1": "P1", "agent2": "P2"},
        )
        critiques = [
            MockCritique("critic", "agent1"),
            MockCritique("critic", "agent2"),
        ]

        with patch(
            "aragora.debate.phases.revision_phase.calculate_phase_timeout",
            return_value=0.1,
        ):
            result = await generator.execute_revision_phase(ctx, 1, critiques, [])

        # Both agents should fail
        assert result == {}
        # Circuit breaker should record failures for both
        assert mock_cb.record_failure.call_count == 2

    @pytest.mark.asyncio
    async def test_handles_individual_timeout_exception(self):
        """Handles TimeoutError from individual agents gracefully."""

        async def timeout_error(*args, **kwargs):
            raise asyncio.TimeoutError("Agent timed out")

        generator = RevisionGenerator(
            generate_with_agent=timeout_error,
            build_revision_prompt=MagicMock(return_value="prompt"),
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        # Should not raise, just log and continue
        result = await generator.execute_revision_phase(ctx, 1, critiques, [])

        assert result == {}

    @pytest.mark.asyncio
    async def test_agent_without_timeout_attribute_uses_default(self):
        """Agent without timeout attr falls back to AGENT_TIMEOUT_SECONDS."""
        captured_base = []

        with patch("aragora.debate.phases.revision_phase.get_complexity_governor") as mock_gov:

            def capture(val):
                captured_base.append(val)
                return val

            mock_gov.return_value.get_scaled_timeout.side_effect = capture

            generator = RevisionGenerator(
                generate_with_agent=AsyncMock(return_value="Revised"),
                build_revision_prompt=MagicMock(return_value="prompt"),
            )

            # Agent without timeout attribute
            agent = MagicMock()
            agent.name = "agent_no_timeout"
            del agent.timeout  # ensure getattr falls back

            ctx = MockDebateContext(
                proposers=[agent],
                proposals={"agent_no_timeout": "Proposal"},
            )
            critiques = [MockCritique("critic", "agent_no_timeout")]

            await generator.execute_revision_phase(ctx, 1, critiques, [])

        from aragora.config import AGENT_TIMEOUT_SECONDS

        assert captured_base[0] == float(AGENT_TIMEOUT_SECONDS)


# ---------------------------------------------------------------------------
# Error recovery and circuit breaker
# ---------------------------------------------------------------------------


class TestRevisionGeneratorErrorRecovery:
    """Tests for error recovery and circuit breaker integration."""

    @pytest.mark.asyncio
    async def test_records_failure_on_exception(self):
        """Circuit breaker records failure when agent throws."""
        mock_cb = MagicMock()

        async def failing_generate(*args, **kwargs):
            raise RuntimeError("API error")

        generator = RevisionGenerator(
            generate_with_agent=failing_generate,
            build_revision_prompt=MagicMock(return_value="prompt"),
            circuit_breaker=mock_cb,
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        mock_cb.record_failure.assert_called_once_with("agent1")

    @pytest.mark.asyncio
    async def test_records_success_on_completion(self):
        """Circuit breaker records success on successful revision."""
        mock_cb = MagicMock()

        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
            build_revision_prompt=MagicMock(return_value="prompt"),
            circuit_breaker=mock_cb,
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        mock_cb.record_success.assert_called_once_with("agent1")

    @pytest.mark.asyncio
    async def test_partial_results_on_mixed_success(self):
        """Returns partial results when some agents fail."""
        call_count = 0

        async def mixed_generate(agent, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if agent.name == "agent1":
                return "Revised 1"
            raise RuntimeError("Agent 2 failed")

        generator = RevisionGenerator(
            generate_with_agent=mixed_generate,
            build_revision_prompt=MagicMock(return_value="prompt"),
        )

        agents = [MockAgent("agent1"), MockAgent("agent2")]
        ctx = MockDebateContext(
            proposers=agents,
            proposals={"agent1": "Proposal 1", "agent2": "Proposal 2"},
        )
        critiques = [
            MockCritique("critic", "agent1"),
            MockCritique("critic", "agent2"),
        ]

        result = await generator.execute_revision_phase(ctx, 1, critiques, [])

        assert len(result) == 1
        assert "agent1" in result

    @pytest.mark.asyncio
    async def test_circuit_breaker_mixed_success_failure(self):
        """Circuit breaker records both success and failure for mixed results."""
        mock_cb = MagicMock()

        async def mixed_generate(agent, *args, **kwargs):
            if agent.name == "agent1":
                return "Revised 1"
            raise RuntimeError("Failure")

        generator = RevisionGenerator(
            generate_with_agent=mixed_generate,
            build_revision_prompt=MagicMock(return_value="prompt"),
            circuit_breaker=mock_cb,
        )

        agents = [MockAgent("agent1"), MockAgent("agent2")]
        ctx = MockDebateContext(
            proposers=agents,
            proposals={"agent1": "P1", "agent2": "P2"},
        )
        critiques = [
            MockCritique("critic", "agent1"),
            MockCritique("critic", "agent2"),
        ]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        mock_cb.record_success.assert_called_once_with("agent1")
        mock_cb.record_failure.assert_called_once_with("agent2")

    @pytest.mark.asyncio
    async def test_no_circuit_breaker_still_works(self):
        """Revisions work without a circuit breaker configured."""

        async def failing_generate(*args, **kwargs):
            raise RuntimeError("No CB test")

        generator = RevisionGenerator(
            generate_with_agent=failing_generate,
            build_revision_prompt=MagicMock(return_value="prompt"),
            circuit_breaker=None,
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        # Should not raise even without circuit breaker
        result = await generator.execute_revision_phase(ctx, 1, critiques, [])

        assert result == {}

    @pytest.mark.asyncio
    async def test_keyboard_interrupt_propagates(self):
        """KeyboardInterrupt-like exceptions still propagate as BaseException results."""

        # asyncio.gather with return_exceptions=True captures BaseException too
        async def cancel_generate(*args, **kwargs):
            raise asyncio.CancelledError()

        generator = RevisionGenerator(
            generate_with_agent=cancel_generate,
            build_revision_prompt=MagicMock(return_value="prompt"),
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        # CancelledError is a BaseException, gather(return_exceptions=True) captures it
        result = await generator.execute_revision_phase(ctx, 1, critiques, [])

        assert result == {}


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestRevisionGeneratorEdgeCases:
    """Edge case tests for RevisionGenerator."""

    @pytest.mark.asyncio
    async def test_single_agent_works(self):
        """Single agent revision works correctly."""
        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Single revision"),
            build_revision_prompt=MagicMock(return_value="prompt"),
        )

        agent = MockAgent("solo")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"solo": "Initial"},
        )
        critiques = [MockCritique("critic", "solo")]

        result = await generator.execute_revision_phase(ctx, 1, critiques, [])

        assert result == {"solo": "Single revision"}

    @pytest.mark.asyncio
    async def test_all_agents_timeout(self):
        """Handles case where all agents time out."""

        async def always_timeout(*args, **kwargs):
            raise asyncio.TimeoutError("Timed out")

        generator = RevisionGenerator(
            generate_with_agent=always_timeout,
            build_revision_prompt=MagicMock(return_value="prompt"),
        )

        agents = [MockAgent("agent1"), MockAgent("agent2")]
        ctx = MockDebateContext(
            proposers=agents,
            proposals={"agent1": "P1", "agent2": "P2"},
        )
        critiques = [
            MockCritique("critic", "agent1"),
            MockCritique("critic", "agent2"),
        ]

        result = await generator.execute_revision_phase(ctx, 1, critiques, [])

        assert result == {}

    @pytest.mark.asyncio
    async def test_empty_proposers_list(self):
        """Empty proposers list returns empty result."""
        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
            build_revision_prompt=MagicMock(return_value="prompt"),
        )

        ctx = MockDebateContext(proposers=[])
        critiques = [MockCritique("critic", "nonexistent")]

        result = await generator.execute_revision_phase(ctx, 1, critiques, [])

        assert result == {}

    @pytest.mark.asyncio
    async def test_critiques_for_nonexistent_agent(self):
        """Critiques for agents not in proposers are ignored."""
        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
            build_revision_prompt=MagicMock(return_value="prompt"),
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        # Critique targets a different agent
        critiques = [MockCritique("critic", "agent2")]

        result = await generator.execute_revision_phase(ctx, 1, critiques, [])

        # agent1 has no critiques targeting it, so no revision
        assert result == {}

    @pytest.mark.asyncio
    async def test_empty_revision_string(self):
        """Empty string revision is still stored."""
        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value=""),
            build_revision_prompt=MagicMock(return_value="prompt"),
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Original"},
        )
        critiques = [MockCritique("critic", "agent1")]

        result = await generator.execute_revision_phase(ctx, 1, critiques, [])

        assert "agent1" in result
        assert result["agent1"] == ""

    @pytest.mark.asyncio
    async def test_very_long_revision_content(self):
        """Long revision content is handled correctly."""
        long_content = "x" * 100_000
        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value=long_content),
            build_revision_prompt=MagicMock(return_value="prompt"),
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Short"},
        )
        critiques = [MockCritique("critic", "agent1")]

        result = await generator.execute_revision_phase(ctx, 1, critiques, [])

        assert len(result["agent1"]) == 100_000

    @pytest.mark.asyncio
    async def test_multiple_critiques_same_agent(self):
        """Multiple critiques targeting the same agent are all passed."""
        mock_build = MagicMock(return_value="prompt")
        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
            build_revision_prompt=mock_build,
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        critiques = [
            MockCritique("critic1", "agent1"),
            MockCritique("critic2", "agent1"),
            MockCritique("critic3", "agent1"),
        ]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        # build_revision_prompt should receive all 3 critiques
        call_args = mock_build.call_args[0]
        assert len(call_args[2]) == 3

    @pytest.mark.asyncio
    async def test_agent_with_missing_proposal(self):
        """Agent without a proposal in ctx.proposals gets empty string."""
        mock_build = MagicMock(return_value="prompt")
        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
            build_revision_prompt=mock_build,
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={},  # No proposal for agent1
        )
        critiques = [MockCritique("critic", "agent1")]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        # proposals.get returns "" for missing agent
        call_args = mock_build.call_args[0]
        assert call_args[1] == ""

    @pytest.mark.asyncio
    async def test_context_without_loop_id(self):
        """Context without loop_id attribute uses empty string."""
        mock_observer = MagicMock()
        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
            build_revision_prompt=MagicMock(return_value="prompt"),
            rhetorical_observer=mock_observer,
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        delattr(ctx, "loop_id")
        critiques = [MockCritique("critic", "agent1")]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        mock_observer.observe.assert_called_once()
        call_kwargs = mock_observer.observe.call_args[1]
        assert call_kwargs["loop_id"] == ""

    @pytest.mark.asyncio
    async def test_result_without_id_for_grounded_position(self):
        """Result without id attribute falls back to env.task for debate_id."""
        mock_record = MagicMock()
        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
            build_revision_prompt=MagicMock(return_value="prompt"),
            record_grounded_position=mock_record,
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
            task="My debate about AI safety",
        )
        # Replace result with object that has no 'id' attribute
        ctx.result = MagicMock(spec=[])
        ctx.result.messages = []
        critiques = [MockCritique("critic", "agent1")]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        # Should fall back to ctx.env.task[:50]
        call_args = mock_record.call_args[0]
        assert call_args[2] == "My debate about AI safety"


# ---------------------------------------------------------------------------
# Hooks and callbacks
# ---------------------------------------------------------------------------


class TestRevisionGeneratorHooks:
    """Tests for hooks and callbacks."""

    @pytest.mark.asyncio
    async def test_on_message_hook_called(self):
        """on_message hook is called for each revision."""
        mock_hook = MagicMock()
        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
            build_revision_prompt=MagicMock(return_value="prompt"),
            hooks={"on_message": mock_hook},
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        mock_hook.assert_called_once_with(
            agent="agent1",
            content="Revised",
            role="proposer",
            round_num=1,
        )

    @pytest.mark.asyncio
    async def test_on_message_hook_called_per_agent(self):
        """on_message hook is called once per successful revision."""
        mock_hook = MagicMock()
        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
            build_revision_prompt=MagicMock(return_value="prompt"),
            hooks={"on_message": mock_hook},
        )

        agents = [MockAgent("agent1"), MockAgent("agent2")]
        ctx = MockDebateContext(
            proposers=agents,
            proposals={"agent1": "P1", "agent2": "P2"},
        )
        critiques = [
            MockCritique("critic", "agent1"),
            MockCritique("critic", "agent2"),
        ]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        assert mock_hook.call_count == 2

    @pytest.mark.asyncio
    async def test_on_message_hook_not_called_on_failure(self):
        """on_message hook is not called when agent fails."""
        mock_hook = MagicMock()

        async def fail_generate(*args, **kwargs):
            raise RuntimeError("Failed")

        generator = RevisionGenerator(
            generate_with_agent=fail_generate,
            build_revision_prompt=MagicMock(return_value="prompt"),
            hooks={"on_message": mock_hook},
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        mock_hook.assert_not_called()

    @pytest.mark.asyncio
    async def test_notify_spectator_called(self):
        """Spectator notification is sent for revisions."""
        mock_notify = MagicMock()
        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised content"),
            build_revision_prompt=MagicMock(return_value="prompt"),
            notify_spectator=mock_notify,
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        mock_notify.assert_called_with(
            "propose",
            agent="agent1",
            details="Revised proposal (15 chars)",
            metric=15,
        )

    @pytest.mark.asyncio
    async def test_notify_spectator_not_called_on_failure(self):
        """Spectator is not notified when revision fails."""
        mock_notify = MagicMock()

        async def fail_generate(*args, **kwargs):
            raise RuntimeError("Failed")

        generator = RevisionGenerator(
            generate_with_agent=fail_generate,
            build_revision_prompt=MagicMock(return_value="prompt"),
            notify_spectator=mock_notify,
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_recorder_records_revision(self):
        """Recorder records revision turn."""
        mock_recorder = MagicMock()
        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
            build_revision_prompt=MagicMock(return_value="prompt"),
            recorder=mock_recorder,
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        mock_recorder.record_turn.assert_called_once_with("agent1", "Revised", 1)

    @pytest.mark.asyncio
    async def test_recorder_error_handled(self):
        """Recorder errors are caught and logged."""
        mock_recorder = MagicMock()
        mock_recorder.record_turn.side_effect = RuntimeError("Recorder failed")

        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
            build_revision_prompt=MagicMock(return_value="prompt"),
            recorder=mock_recorder,
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        # Should not raise
        result = await generator.execute_revision_phase(ctx, 1, critiques, [])

        assert "agent1" in result

    @pytest.mark.asyncio
    async def test_record_grounded_position_called(self):
        """Grounded position recording is called."""
        mock_record = MagicMock()
        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
            build_revision_prompt=MagicMock(return_value="prompt"),
            record_grounded_position=mock_record,
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
            debate_id="debate-123",
        )
        ctx.result.id = "debate-123"
        critiques = [MockCritique("critic", "agent1")]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        mock_record.assert_called_once_with("agent1", "Revised", "debate-123", 1, 0.75)

    @pytest.mark.asyncio
    async def test_record_grounded_position_not_called_on_failure(self):
        """Grounded position not recorded on failure."""
        mock_record = MagicMock()

        async def fail_generate(*args, **kwargs):
            raise RuntimeError("Failed")

        generator = RevisionGenerator(
            generate_with_agent=fail_generate,
            build_revision_prompt=MagicMock(return_value="prompt"),
            record_grounded_position=mock_record,
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        mock_record.assert_not_called()


# ---------------------------------------------------------------------------
# Heartbeat emission
# ---------------------------------------------------------------------------


class TestRevisionGeneratorHeartbeat:
    """Tests for heartbeat emission during revisions."""

    @pytest.mark.asyncio
    async def test_heartbeat_emitted_at_start(self):
        """Heartbeat is emitted at revision phase start."""
        mock_heartbeat = MagicMock()
        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
            build_revision_prompt=MagicMock(return_value="prompt"),
            heartbeat_callback=mock_heartbeat,
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        # Should be called at least twice: start and processed
        assert mock_heartbeat.call_count >= 2

        # First call should be starting
        first_call = mock_heartbeat.call_args_list[0]
        assert first_call[0][0] == "revision_round_1"
        assert "starting" in first_call[0][1]

    @pytest.mark.asyncio
    async def test_heartbeat_emitted_for_each_result(self):
        """Heartbeat is emitted for each processed result."""
        mock_heartbeat = MagicMock()
        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
            build_revision_prompt=MagicMock(return_value="prompt"),
            heartbeat_callback=mock_heartbeat,
        )

        agents = [MockAgent("agent1"), MockAgent("agent2")]
        ctx = MockDebateContext(
            proposers=agents,
            proposals={"agent1": "P1", "agent2": "P2"},
        )
        critiques = [
            MockCritique("critic", "agent1"),
            MockCritique("critic", "agent2"),
        ]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        # Check that processed heartbeats were emitted
        processed_calls = [c for c in mock_heartbeat.call_args_list if "processed" in str(c)]
        assert len(processed_calls) == 2

    @pytest.mark.asyncio
    async def test_heartbeat_starting_includes_agent_count(self):
        """Starting heartbeat includes number of agents."""
        mock_heartbeat = MagicMock()
        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
            build_revision_prompt=MagicMock(return_value="prompt"),
            heartbeat_callback=mock_heartbeat,
        )

        agents = [MockAgent("a1"), MockAgent("a2"), MockAgent("a3")]
        ctx = MockDebateContext(
            proposers=agents,
            proposals={a.name: "P" for a in agents},
        )
        critiques = [MockCritique("critic", a.name) for a in agents]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        first_call = mock_heartbeat.call_args_list[0]
        assert "starting_3_agents" in first_call[0][1]

    @pytest.mark.asyncio
    async def test_heartbeat_processed_shows_count(self):
        """Processed heartbeat shows count of completed."""
        mock_heartbeat = MagicMock()
        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
            build_revision_prompt=MagicMock(return_value="prompt"),
            heartbeat_callback=mock_heartbeat,
        )

        agents = [MockAgent("a1"), MockAgent("a2")]
        ctx = MockDebateContext(
            proposers=agents,
            proposals={"a1": "P1", "a2": "P2"},
        )
        critiques = [MockCritique("critic", "a1"), MockCritique("critic", "a2")]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        # Look for processed_1_of_2 and processed_2_of_2
        processed_calls = [c for c in mock_heartbeat.call_args_list if "processed" in str(c)]
        assert any("processed_1_of_2" in str(c) for c in processed_calls)
        assert any("processed_2_of_2" in str(c) for c in processed_calls)

    @pytest.mark.asyncio
    async def test_heartbeat_not_emitted_without_callback(self):
        """No error when heartbeat callback is None."""
        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
            build_revision_prompt=MagicMock(return_value="prompt"),
            heartbeat_callback=None,
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        # Should not raise
        result = await generator.execute_revision_phase(ctx, 1, critiques, [])

        assert "agent1" in result

    @pytest.mark.asyncio
    async def test_heartbeat_task_cancelled_on_completion(self):
        """Heartbeat background task is cancelled after revisions complete."""
        heartbeat_calls = []

        def track_heartbeat(*args):
            heartbeat_calls.append(args)

        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
            build_revision_prompt=MagicMock(return_value="prompt"),
            heartbeat_callback=track_heartbeat,
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        # Wait a bit to ensure heartbeat task is truly cancelled
        await asyncio.sleep(0.1)
        count_after = len(heartbeat_calls)
        await asyncio.sleep(0.1)

        # No more heartbeats should appear
        assert len(heartbeat_calls) == count_after

    @pytest.mark.asyncio
    async def test_heartbeat_emitted_even_on_all_failures(self):
        """Heartbeat processed calls are emitted even when agents fail."""
        mock_heartbeat = MagicMock()

        async def fail_generate(*args, **kwargs):
            raise RuntimeError("Failed")

        generator = RevisionGenerator(
            generate_with_agent=fail_generate,
            build_revision_prompt=MagicMock(return_value="prompt"),
            heartbeat_callback=mock_heartbeat,
        )

        agents = [MockAgent("agent1"), MockAgent("agent2")]
        ctx = MockDebateContext(
            proposers=agents,
            proposals={"agent1": "P1", "agent2": "P2"},
        )
        critiques = [
            MockCritique("critic", "agent1"),
            MockCritique("critic", "agent2"),
        ]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        # Processed heartbeats still emitted for failures
        processed_calls = [c for c in mock_heartbeat.call_args_list if "processed" in str(c)]
        assert len(processed_calls) == 2


# ---------------------------------------------------------------------------
# Rhetorical observer
# ---------------------------------------------------------------------------


class TestRevisionGeneratorRhetoricalObserver:
    """Tests for rhetorical pattern observation."""

    @pytest.mark.asyncio
    async def test_rhetorical_observer_called(self):
        """Rhetorical observer is called for revisions."""
        mock_observer = MagicMock()
        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised proposal"),
            build_revision_prompt=MagicMock(return_value="prompt"),
            rhetorical_observer=mock_observer,
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        ctx.loop_id = "loop-123"
        critiques = [MockCritique("critic", "agent1")]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        mock_observer.observe.assert_called_once_with(
            agent="agent1",
            content="Revised proposal",
            round=1,
            loop_id="loop-123",
        )

    @pytest.mark.asyncio
    async def test_rhetorical_observer_error_handled(self):
        """Rhetorical observer errors are caught."""
        mock_observer = MagicMock()
        mock_observer.observe.side_effect = RuntimeError("Observer failed")

        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
            build_revision_prompt=MagicMock(return_value="prompt"),
            rhetorical_observer=mock_observer,
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        # Should not raise
        result = await generator.execute_revision_phase(ctx, 1, critiques, [])

        assert "agent1" in result

    @pytest.mark.asyncio
    async def test_rhetorical_observer_not_called_without_observer(self):
        """No error when rhetorical observer is None."""
        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
            build_revision_prompt=MagicMock(return_value="prompt"),
            rhetorical_observer=None,
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        result = await generator.execute_revision_phase(ctx, 1, critiques, [])

        assert "agent1" in result

    @pytest.mark.asyncio
    async def test_rhetorical_observer_not_called_on_failure(self):
        """Rhetorical observer not called when revision fails."""
        mock_observer = MagicMock()

        async def fail(*args, **kwargs):
            raise RuntimeError("Fail")

        generator = RevisionGenerator(
            generate_with_agent=fail,
            build_revision_prompt=MagicMock(return_value="prompt"),
            rhetorical_observer=mock_observer,
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        mock_observer.observe.assert_not_called()


# ---------------------------------------------------------------------------
# Molecule tracking (Gastown pattern)
# ---------------------------------------------------------------------------


class TestRevisionGeneratorMoleculeTracking:
    """Tests for molecule tracking (Gastown pattern)."""

    @pytest.mark.asyncio
    async def test_molecules_created_for_agents(self):
        """Molecules are created for each agent."""
        mock_tracker = MagicMock()
        mock_molecule = MagicMock()
        mock_molecule.molecule_id = "mol-123"
        mock_tracker.create_molecule.return_value = mock_molecule

        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
            build_revision_prompt=MagicMock(return_value="prompt"),
            molecule_tracker=mock_tracker,
        )

        agents = [MockAgent("agent1"), MockAgent("agent2")]
        ctx = MockDebateContext(
            proposers=agents,
            proposals={"agent1": "P1", "agent2": "P2"},
            debate_id="debate-123",
        )
        critiques = [
            MockCritique("critic", "agent1"),
            MockCritique("critic", "agent2"),
        ]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        # Should create molecule for each agent
        assert mock_tracker.create_molecule.call_count == 2

    @pytest.mark.asyncio
    async def test_molecule_started_on_generation(self):
        """Molecule is marked as started when generation begins."""
        mock_tracker = MagicMock()
        mock_molecule = MagicMock()
        mock_molecule.molecule_id = "mol-123"
        mock_tracker.create_molecule.return_value = mock_molecule

        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
            build_revision_prompt=MagicMock(return_value="prompt"),
            molecule_tracker=mock_tracker,
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        mock_tracker.start_molecule.assert_called_once_with("mol-123")

    @pytest.mark.asyncio
    async def test_molecule_completed_on_success(self):
        """Molecule is marked complete on successful revision."""
        mock_tracker = MagicMock()
        mock_molecule = MagicMock()
        mock_molecule.molecule_id = "mol-123"
        mock_tracker.create_molecule.return_value = mock_molecule

        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised proposal"),
            build_revision_prompt=MagicMock(return_value="prompt"),
            molecule_tracker=mock_tracker,
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        mock_tracker.complete_molecule.assert_called_once()
        call_args = mock_tracker.complete_molecule.call_args
        assert call_args[0][0] == "mol-123"
        assert call_args[0][1]["chars"] == 16  # len("Revised proposal")
        assert call_args[0][1]["round"] == 1

    @pytest.mark.asyncio
    async def test_molecule_failed_on_error(self):
        """Molecule is marked failed on revision error."""
        mock_tracker = MagicMock()
        mock_molecule = MagicMock()
        mock_molecule.molecule_id = "mol-123"
        mock_tracker.create_molecule.return_value = mock_molecule

        async def failing_generate(*args, **kwargs):
            raise RuntimeError("API error")

        generator = RevisionGenerator(
            generate_with_agent=failing_generate,
            build_revision_prompt=MagicMock(return_value="prompt"),
            molecule_tracker=mock_tracker,
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        mock_tracker.fail_molecule.assert_called_once()
        call_args = mock_tracker.fail_molecule.call_args
        assert call_args[0][0] == "mol-123"
        assert "API error" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_molecule_tracker_import_error_handled(self):
        """Import errors in molecule tracking are handled gracefully."""
        mock_tracker = MagicMock()
        mock_tracker.create_molecule.side_effect = ImportError("No molecules")

        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
            build_revision_prompt=MagicMock(return_value="prompt"),
            molecule_tracker=mock_tracker,
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        # Should not raise
        result = await generator.execute_revision_phase(ctx, 1, critiques, [])

        assert "agent1" in result

    @pytest.mark.asyncio
    async def test_molecule_tracker_generic_error_handled(self):
        """Generic errors in molecule tracking are handled gracefully."""
        mock_tracker = MagicMock()
        mock_tracker.create_molecule.side_effect = RuntimeError("Tracker broken")

        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
            build_revision_prompt=MagicMock(return_value="prompt"),
            molecule_tracker=mock_tracker,
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        result = await generator.execute_revision_phase(ctx, 1, critiques, [])

        assert "agent1" in result

    @pytest.mark.asyncio
    async def test_start_molecule_without_active_molecule(self):
        """_start_molecule handles missing molecule_id gracefully."""
        mock_tracker = MagicMock()
        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
            build_revision_prompt=MagicMock(return_value="prompt"),
            molecule_tracker=mock_tracker,
        )

        # Directly call _start_molecule with no active molecules
        generator._start_molecule("nonexistent_agent")

        # start_molecule should not be called because there's no molecule_id
        mock_tracker.start_molecule.assert_not_called()

    @pytest.mark.asyncio
    async def test_complete_molecule_without_active_molecule(self):
        """_complete_molecule handles missing molecule_id gracefully."""
        mock_tracker = MagicMock()
        generator = RevisionGenerator(
            molecule_tracker=mock_tracker,
        )

        generator._complete_molecule("nonexistent", {"chars": 10})

        mock_tracker.complete_molecule.assert_not_called()

    @pytest.mark.asyncio
    async def test_fail_molecule_without_active_molecule(self):
        """_fail_molecule handles missing molecule_id gracefully."""
        mock_tracker = MagicMock()
        generator = RevisionGenerator(
            molecule_tracker=mock_tracker,
        )

        generator._fail_molecule("nonexistent", "some error")

        mock_tracker.fail_molecule.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_molecule_error_handled(self):
        """Errors in start_molecule are caught gracefully."""
        mock_tracker = MagicMock()
        mock_tracker.start_molecule.side_effect = RuntimeError("Start error")

        generator = RevisionGenerator(molecule_tracker=mock_tracker)
        generator._active_molecules["agent1"] = "mol-1"

        # Should not raise
        generator._start_molecule("agent1")

    @pytest.mark.asyncio
    async def test_complete_molecule_error_handled(self):
        """Errors in complete_molecule are caught gracefully."""
        mock_tracker = MagicMock()
        mock_tracker.complete_molecule.side_effect = RuntimeError("Complete error")

        generator = RevisionGenerator(molecule_tracker=mock_tracker)
        generator._active_molecules["agent1"] = "mol-1"

        # Should not raise
        generator._complete_molecule("agent1", {"chars": 10})

    @pytest.mark.asyncio
    async def test_fail_molecule_error_handled(self):
        """Errors in fail_molecule are caught gracefully."""
        mock_tracker = MagicMock()
        mock_tracker.fail_molecule.side_effect = RuntimeError("Fail error")

        generator = RevisionGenerator(molecule_tracker=mock_tracker)
        generator._active_molecules["agent1"] = "mol-1"

        # Should not raise
        generator._fail_molecule("agent1", "some error")

    @pytest.mark.asyncio
    async def test_no_molecule_tracking_without_tracker(self):
        """All molecule methods are no-ops without a tracker."""
        generator = RevisionGenerator(molecule_tracker=None)

        # None of these should raise
        generator._start_molecule("agent1")
        generator._complete_molecule("agent1", {"chars": 10})
        generator._fail_molecule("agent1", "error")
        generator._create_revision_molecules("debate-1", 1, [MockAgent("a1")])

    @pytest.mark.asyncio
    async def test_molecule_debate_id_fallback(self):
        """Molecule creation uses env.task fallback when debate_id is None."""
        mock_tracker = MagicMock()
        mock_molecule = MagicMock()
        mock_molecule.molecule_id = "mol-1"
        mock_tracker.create_molecule.return_value = mock_molecule

        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
            build_revision_prompt=MagicMock(return_value="prompt"),
            molecule_tracker=mock_tracker,
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
            task="My long debate task about something",
        )
        ctx.debate_id = None  # Force fallback
        critiques = [MockCritique("critic", "agent1")]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        # Should use env.task[:50] as debate_id
        call_args = mock_tracker.create_molecule.call_args
        assert call_args[1]["debate_id"] == "My long debate task about something"


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


class TestRevisionGeneratorPromptBuilding:
    """Tests for revision prompt building."""

    @pytest.mark.asyncio
    async def test_prompt_built_with_agent_critiques(self):
        """Prompt is built with agent-specific critiques."""
        mock_build = MagicMock(return_value="Built prompt")
        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
            build_revision_prompt=mock_build,
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Original proposal"},
        )
        critiques = [
            MockCritique("critic1", "agent1"),
            MockCritique("critic2", "agent1"),
            MockCritique("critic3", "other_agent"),  # Should not be included
        ]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        # Check that build was called with only agent1's critiques
        mock_build.assert_called_once()
        call_args = mock_build.call_args[0]
        agent_critiques = call_args[2]
        assert len(agent_critiques) == 2
        assert all(c.target_agent == "agent1" for c in agent_critiques)

    @pytest.mark.asyncio
    async def test_prompt_includes_original_proposal(self):
        """Prompt building receives original proposal."""
        mock_build = MagicMock(return_value="Built prompt")
        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
            build_revision_prompt=mock_build,
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "My original proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        call_args = mock_build.call_args[0]
        assert call_args[1] == "My original proposal"

    @pytest.mark.asyncio
    async def test_prompt_includes_round_number(self):
        """Prompt building receives round number."""
        mock_build = MagicMock(return_value="Built prompt")
        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
            build_revision_prompt=mock_build,
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        await generator.execute_revision_phase(ctx, 2, critiques, [])

        call_args = mock_build.call_args[0]
        assert call_args[3] == 2  # round_num

    @pytest.mark.asyncio
    async def test_prompt_includes_agent_object(self):
        """Prompt building receives the agent object."""
        mock_build = MagicMock(return_value="Built prompt")
        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
            build_revision_prompt=mock_build,
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        call_args = mock_build.call_args[0]
        assert call_args[0] is agent

    @pytest.mark.asyncio
    async def test_generate_receives_prompt_and_context(self):
        """generate_with_agent receives the built prompt and context messages."""
        captured_args = []

        async def capture_generate(agent, prompt, context_messages):
            # Snapshot the context_messages at call time (list may be mutated later)
            captured_args.append((agent, prompt, list(context_messages)))
            return "Revised"

        generator = RevisionGenerator(
            generate_with_agent=capture_generate,
            build_revision_prompt=MagicMock(return_value="Built prompt for revision"),
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        ctx.context_messages = ["msg1", "msg2"]
        critiques = [MockCritique("critic", "agent1")]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        assert len(captured_args) == 1
        assert captured_args[0][0] is agent
        assert captured_args[0][1] == "Built prompt for revision"
        # Context messages should contain the initial messages at call time
        assert "msg1" in captured_args[0][2]
        assert "msg2" in captured_args[0][2]


# ---------------------------------------------------------------------------
# Without timeout wrapper
# ---------------------------------------------------------------------------


class TestRevisionGeneratorWithoutTimeout:
    """Tests for revision generation without timeout wrapper."""

    @pytest.mark.asyncio
    async def test_works_without_timeout_wrapper(self):
        """Generator works when with_timeout is not provided."""
        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
            build_revision_prompt=MagicMock(return_value="prompt"),
            with_timeout=None,  # No timeout wrapper
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        result = await generator.execute_revision_phase(ctx, 1, critiques, [])

        assert "agent1" in result
        assert result["agent1"] == "Revised"

    @pytest.mark.asyncio
    async def test_without_timeout_calls_generate_directly(self):
        """Without timeout wrapper, generate is called directly."""
        call_count = 0

        async def counting_generate(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return "Revised"

        generator = RevisionGenerator(
            generate_with_agent=counting_generate,
            build_revision_prompt=MagicMock(return_value="prompt"),
            with_timeout=None,
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        assert call_count == 1

    @pytest.mark.asyncio
    async def test_with_timeout_wrapper_wraps_generation(self):
        """With timeout wrapper, it wraps the generation call."""
        timeout_called = False

        async def mock_timeout(coro, name, timeout_seconds=None):
            nonlocal timeout_called
            timeout_called = True
            return await coro

        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised"),
            build_revision_prompt=MagicMock(return_value="prompt"),
            with_timeout=mock_timeout,
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Proposal"},
        )
        critiques = [MockCritique("critic", "agent1")]

        with patch("aragora.debate.phases.revision_phase.get_complexity_governor") as mock_gov:
            mock_gov.return_value.get_scaled_timeout.return_value = 60.0
            await generator.execute_revision_phase(ctx, 1, critiques, [])

        assert timeout_called


# ---------------------------------------------------------------------------
# _observe_rhetorical_patterns direct tests
# ---------------------------------------------------------------------------


class TestObserveRhetoricalPatterns:
    """Direct unit tests for _observe_rhetorical_patterns method."""

    def test_no_observer_no_error(self):
        """No error when observer is None."""
        generator = RevisionGenerator(rhetorical_observer=None)

        # Should not raise
        generator._observe_rhetorical_patterns("agent1", "content", 1, "loop-1")

    def test_observer_called_with_correct_args(self):
        """Observer is called with correct arguments."""
        mock_obs = MagicMock()
        generator = RevisionGenerator(rhetorical_observer=mock_obs)

        generator._observe_rhetorical_patterns("agent1", "some content", 3, "loop-42")

        mock_obs.observe.assert_called_once_with(
            agent="agent1",
            content="some content",
            round=3,
            loop_id="loop-42",
        )

    def test_observer_exception_caught(self):
        """Exceptions from observer are caught."""
        mock_obs = MagicMock()
        mock_obs.observe.side_effect = ValueError("Bad observation")
        generator = RevisionGenerator(rhetorical_observer=mock_obs)

        # Should not raise
        generator._observe_rhetorical_patterns("agent1", "content", 1, "loop-1")


# ---------------------------------------------------------------------------
# _create_revision_molecules direct tests
# ---------------------------------------------------------------------------


class TestCreateRevisionMolecules:
    """Direct unit tests for _create_revision_molecules method."""

    def test_no_tracker_no_error(self):
        """No error when tracker is None."""
        generator = RevisionGenerator(molecule_tracker=None)

        generator._create_revision_molecules("debate-1", 1, [MockAgent("a1")])

    def test_creates_molecule_per_agent(self):
        """Creates one molecule per agent."""
        mock_tracker = MagicMock()
        mock_molecule = MagicMock()
        mock_molecule.molecule_id = "mol-1"
        mock_tracker.create_molecule.return_value = mock_molecule

        generator = RevisionGenerator(molecule_tracker=mock_tracker)

        agents = [MockAgent("a1"), MockAgent("a2"), MockAgent("a3")]
        generator._create_revision_molecules("debate-1", 2, agents)

        assert mock_tracker.create_molecule.call_count == 3
        assert generator._active_molecules["a1"] == "mol-1"
        assert generator._active_molecules["a2"] == "mol-1"
        assert generator._active_molecules["a3"] == "mol-1"

    def test_stores_molecule_id_per_agent(self):
        """Each agent gets its own molecule_id stored."""
        mock_tracker = MagicMock()
        ids = iter(["mol-a", "mol-b"])

        def create_molecule(**kwargs):
            m = MagicMock()
            m.molecule_id = next(ids)
            return m

        mock_tracker.create_molecule.side_effect = create_molecule

        generator = RevisionGenerator(molecule_tracker=mock_tracker)
        agents = [MockAgent("a1"), MockAgent("a2")]
        generator._create_revision_molecules("debate-1", 1, agents)

        assert generator._active_molecules["a1"] == "mol-a"
        assert generator._active_molecules["a2"] == "mol-b"

    def test_import_error_handled(self):
        """ImportError during molecule creation is caught."""
        mock_tracker = MagicMock()
        mock_tracker.create_molecule.side_effect = ImportError("No molecules module")

        generator = RevisionGenerator(molecule_tracker=mock_tracker)

        # Should not raise
        generator._create_revision_molecules("debate-1", 1, [MockAgent("a1")])

    def test_generic_error_handled(self):
        """Generic error during molecule creation is caught."""
        mock_tracker = MagicMock()
        mock_tracker.create_molecule.side_effect = RuntimeError("DB down")

        generator = RevisionGenerator(molecule_tracker=mock_tracker)

        # Should not raise
        generator._create_revision_molecules("debate-1", 1, [MockAgent("a1")])


# ---------------------------------------------------------------------------
# Integration-style tests
# ---------------------------------------------------------------------------


class TestRevisionGeneratorIntegration:
    """Integration-style tests combining multiple features."""

    @pytest.mark.asyncio
    async def test_full_flow_with_all_callbacks(self):
        """Full revision flow with all callbacks configured."""
        mock_cb = MagicMock()
        mock_recorder = MagicMock()
        mock_spectator = MagicMock()
        mock_heartbeat = MagicMock()
        mock_grounded = MagicMock()
        mock_observer = MagicMock()
        mock_hook = MagicMock()
        mock_tracker = MagicMock()
        mock_molecule = MagicMock()
        mock_molecule.molecule_id = "mol-int"
        mock_tracker.create_molecule.return_value = mock_molecule

        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Full revision"),
            build_revision_prompt=MagicMock(return_value="prompt"),
            circuit_breaker=mock_cb,
            recorder=mock_recorder,
            notify_spectator=mock_spectator,
            heartbeat_callback=mock_heartbeat,
            record_grounded_position=mock_grounded,
            rhetorical_observer=mock_observer,
            hooks={"on_message": mock_hook},
            molecule_tracker=mock_tracker,
        )

        agent = MockAgent("agent1")
        ctx = MockDebateContext(
            proposers=[agent],
            proposals={"agent1": "Original"},
            debate_id="debate-int",
        )
        ctx.result.id = "debate-int"
        critiques = [MockCritique("critic", "agent1")]
        partial_messages = []

        result = await generator.execute_revision_phase(ctx, 1, critiques, partial_messages)

        # Verify all callbacks were invoked
        assert result == {"agent1": "Full revision"}
        mock_cb.record_success.assert_called_once_with("agent1")
        mock_recorder.record_turn.assert_called_once()
        mock_spectator.assert_called_once()
        mock_heartbeat.assert_called()
        mock_grounded.assert_called_once()
        mock_observer.observe.assert_called_once()
        mock_hook.assert_called_once()
        mock_tracker.create_molecule.assert_called_once()
        mock_tracker.start_molecule.assert_called_once()
        mock_tracker.complete_molecule.assert_called_once()
        assert len(partial_messages) == 1
        assert len(ctx.result.messages) == 1

    @pytest.mark.asyncio
    async def test_multi_agent_with_mixed_results_and_tracking(self):
        """Multiple agents with mixed success/failure and full tracking."""
        mock_cb = MagicMock()
        mock_tracker = MagicMock()
        mol_ids = iter(["mol-a", "mol-b", "mol-c"])

        def make_mol(**kwargs):
            m = MagicMock()
            m.molecule_id = next(mol_ids)
            return m

        mock_tracker.create_molecule.side_effect = make_mol

        async def mixed_generate(agent, *args, **kwargs):
            if agent.name == "agent2":
                raise RuntimeError("Agent2 failed")
            return f"Revised by {agent.name}"

        generator = RevisionGenerator(
            generate_with_agent=mixed_generate,
            build_revision_prompt=MagicMock(return_value="prompt"),
            circuit_breaker=mock_cb,
            molecule_tracker=mock_tracker,
        )

        agents = [MockAgent("agent1"), MockAgent("agent2"), MockAgent("agent3")]
        ctx = MockDebateContext(
            proposers=agents,
            proposals={a.name: f"P-{a.name}" for a in agents},
        )
        critiques = [MockCritique("critic", a.name) for a in agents]
        partial_messages = []

        result = await generator.execute_revision_phase(ctx, 2, critiques, partial_messages)

        # agent1 and agent3 succeed, agent2 fails
        assert len(result) == 2
        assert "agent1" in result
        assert "agent2" not in result
        assert "agent3" in result

        # Circuit breaker calls
        assert mock_cb.record_success.call_count == 2
        assert mock_cb.record_failure.call_count == 1
        mock_cb.record_failure.assert_called_once_with("agent2")

        # Molecule tracking
        assert mock_tracker.create_molecule.call_count == 3
        assert mock_tracker.start_molecule.call_count == 3
        assert mock_tracker.complete_molecule.call_count == 2
        assert mock_tracker.fail_molecule.call_count == 1

        # Partial messages only for successful agents
        assert len(partial_messages) == 2

    @pytest.mark.asyncio
    async def test_revision_preserves_existing_proposals(self):
        """Existing proposals for other agents are not modified."""
        generator = RevisionGenerator(
            generate_with_agent=AsyncMock(return_value="Revised A1"),
            build_revision_prompt=MagicMock(return_value="prompt"),
        )

        agents = [MockAgent("agent1")]
        ctx = MockDebateContext(
            proposers=agents,
            proposals={"agent1": "Old A1", "agent2": "Untouched A2"},
        )
        critiques = [MockCritique("critic", "agent1")]

        await generator.execute_revision_phase(ctx, 1, critiques, [])

        assert ctx.proposals["agent1"] == "Revised A1"
        assert ctx.proposals["agent2"] == "Untouched A2"

    @pytest.mark.asyncio
    async def test_uses_callbacks_bound_at_phase_entry(self):
        """A later attribute mutation must not yield a silent None revision."""
        generate = AsyncMock(return_value="Revised A1")
        generator = RevisionGenerator(generate_with_agent=generate)

        def build_prompt(*_args):
            generator._generate_with_agent = None
            return "prompt"

        generator._build_revision_prompt = build_prompt
        ctx = MockDebateContext(
            proposers=[MockAgent("agent1")],
            proposals={"agent1": "Old A1"},
        )

        result = await generator.execute_revision_phase(
            ctx,
            1,
            [MockCritique("critic", "agent1")],
            [],
        )

        assert result == {"agent1": "Revised A1"}
        generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_revision_message_is_recorded_exactly_once():
    """#9661: every mid-debate message was recorded twice.

    `DebateContext.add_message` already appends to `result.messages`, and the
    phases appended again themselves, so each message landed twice — inflating
    `agent_contributions` and putting byte-identical duplicate claims into the
    crux top-k, which distorted card ranking in published receipts.

    Asserting "exactly once" rather than "at least one" is the point: the old
    assertion passed against a mock that did not reproduce the duplication.
    """
    generator = RevisionGenerator(
        generate_with_agent=AsyncMock(return_value="Revised proposal"),
        build_revision_prompt=MagicMock(return_value="Revision prompt"),
    )
    ctx = MockDebateContext(proposers=[MockAgent("agent1")], proposals={"agent1": "Proposal"})

    await generator.execute_revision_phase(ctx, 1, [MockCritique("critic", "agent1")], [])

    assert len(ctx.result.messages) == 1
    assert len(ctx.context_messages) == 1
    assert len(ctx.partial_messages) == 1
