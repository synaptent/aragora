"""Tests for orchestrator_runner.py - Debate execution helper methods.

Tests cover:
- _DebateExecutionState dataclass creation and field validation
- initialize_debate_context: debate ID generation, convergence detector, KM init, BeliefNetwork
- setup_debate_infrastructure: logging, tracker notification, budget validation, GUPP hooks
- execute_debate_phases: PhaseExecutor integration, timeout handling, EarlyStopError handling
- record_debate_metrics: duration calculation, span attributes, outcome tracking
- handle_debate_completion: tracker notification, extensions, budget usage, KM ingestion
- cleanup_debate_resources: checkpoint cleanup, channel teardown
- Error handling and recovery scenarios
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch, PropertyMock

import pytest

from aragora.core import DebateResult, Environment, TaskComplexity
from aragora.debate.context import DebateContext
from aragora.debate.post_debate_coordinator import PostDebateConfig
from aragora.debate.orchestrator_runner import (
    _DebateExecutionState,
    _record_debate_telemetry,
    _run_cross_verification,
    initialize_debate_context,
    setup_debate_infrastructure,
    execute_debate_phases,
    record_debate_metrics,
    handle_debate_completion,
    cleanup_debate_resources,
)
from aragora.pipeline.execution_mode import ExecutionMode


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_agent():
    """Create a mock agent."""
    agent = MagicMock()
    agent.name = "test-agent"
    agent.model = "test-model"
    return agent


@pytest.fixture
def mock_agents():
    """Create a list of mock agents."""
    agents = []
    for i in range(3):
        agent = MagicMock()
        agent.name = f"agent-{i}"
        agent.model = f"model-{i}"
        agents.append(agent)
    return agents


@pytest.fixture
def mock_env():
    """Create a mock environment."""
    env = MagicMock(spec=Environment)
    env.task = "Test debate task for testing purposes"
    env.context = {}
    return env


@pytest.fixture
def mock_protocol():
    """Create a mock protocol."""
    protocol = MagicMock()
    protocol.enable_km_belief_sync = False
    protocol.enable_hook_tracking = False
    protocol.checkpoint_cleanup_on_success = True
    protocol.checkpoint_keep_on_success = 0
    protocol.enable_translation = False
    return protocol


@pytest.fixture
def mock_budget_coordinator():
    """Create a mock budget coordinator."""
    coordinator = MagicMock()
    coordinator.check_budget_before_debate = MagicMock()
    coordinator.check_budget_mid_debate = MagicMock()
    coordinator.record_debate_cost = MagicMock()
    return coordinator


@pytest.fixture
def mock_trackers():
    """Create a mock subsystem trackers."""
    trackers = MagicMock()
    trackers.on_debate_start = MagicMock()
    trackers.on_debate_complete = MagicMock()
    return trackers


@pytest.fixture
def mock_extensions():
    """Create a mock extensions."""
    extensions = MagicMock()
    extensions.on_debate_complete = MagicMock()
    return extensions


@pytest.fixture
def mock_phase_executor():
    """Create a mock phase executor."""
    executor = MagicMock()
    executor.execute = AsyncMock()
    return executor


@pytest.fixture
def mock_hook_manager():
    """Create a mock hook manager."""
    return MagicMock()


@pytest.fixture
def mock_span():
    """Create a mock OpenTelemetry span."""
    span = MagicMock()
    span.set_attribute = MagicMock()
    span.record_exception = MagicMock()
    return span


@pytest.fixture
def mock_arena(
    mock_env,
    mock_agents,
    mock_protocol,
    mock_budget_coordinator,
    mock_trackers,
    mock_extensions,
    mock_phase_executor,
    mock_hook_manager,
):
    """Create a mock Arena with all required attributes."""
    arena = MagicMock()
    arena.env = mock_env
    arena.agents = mock_agents
    arena.protocol = mock_protocol
    arena.org_id = "test-org"
    arena.hook_manager = mock_hook_manager
    arena.molecule_orchestrator = None
    arena.checkpoint_bridge = None
    arena.prompt_builder = None
    arena.knowledge_mound = MagicMock()
    arena.enable_knowledge_retrieval = True
    arena.enable_knowledge_ingestion = True
    arena.enable_supermemory = False
    arena.use_performance_selection = False
    arena.enable_auto_execution = False
    arena.enable_result_routing = False
    arena.enable_cross_verification = False
    arena.phase_executor = mock_phase_executor
    arena.extensions = mock_extensions

    # Internal attributes
    arena._budget_coordinator = mock_budget_coordinator
    arena._trackers = mock_trackers
    arena._bead_store = None
    arena._hook_registry = None

    # Methods
    arena._reinit_convergence_for_debate = MagicMock()
    arena._extract_debate_domain = MagicMock(return_value="general")
    # Real _init_km_context returns the pending culture-retrieval task (or
    # None); default to None so initialize_debate_context's post-fix
    # asyncio.shield(pending_culture_task) await has nothing to wait on.
    arena._init_km_context = AsyncMock(return_value=None)
    arena._get_culture_hints = MagicMock(return_value=None)
    arena._apply_culture_hints = MagicMock()
    arena._setup_belief_network = MagicMock()
    arena._select_debate_team = MagicMock(side_effect=lambda agents: agents)
    arena._assign_hierarchy_roles = MagicMock()
    arena._setup_agent_channels = AsyncMock()
    arena._emit_agent_preview = MagicMock()
    arena._create_pending_debate_bead = AsyncMock(return_value=None)
    arena._init_hook_tracking = AsyncMock(return_value={})
    arena._log_phase_failures = MagicMock()
    arena._track_circuit_breaker_metrics = MagicMock()
    arena._ingest_debate_outcome = AsyncMock()
    arena._update_debate_bead = AsyncMock()
    arena._complete_hook_tracking = AsyncMock()
    arena._create_debate_bead = AsyncMock(return_value=None)
    arena._queue_for_supabase_sync = MagicMock()
    arena.cleanup_checkpoints = AsyncMock(return_value=0)
    arena._cleanup_convergence_cache = MagicMock()
    arena._teardown_agent_channels = AsyncMock()
    arena._translate_conclusions = AsyncMock()

    return arena


@pytest.fixture
def mock_debate_result():
    """Create a mock DebateResult."""
    result = MagicMock(spec=DebateResult)
    result.task = "Test task"
    result.consensus_reached = True
    result.confidence = 0.85
    result.messages = [MagicMock(), MagicMock()]
    result.critiques = []
    result.votes = []
    result.rounds_used = 3
    result.final_answer = "Test answer"
    result.bead_id = None
    result.metadata = {}
    return result


@pytest.fixture
def mock_debate_context(mock_env, mock_agents, mock_debate_result):
    """Create a mock DebateContext."""
    ctx = MagicMock(spec=DebateContext)
    ctx.env = mock_env
    ctx.agents = mock_agents
    ctx.debate_id = "test-debate-123"
    ctx.correlation_id = "corr-test"
    ctx.domain = "general"
    ctx.result = mock_debate_result
    ctx.partial_messages = []
    ctx.partial_critiques = []
    ctx.partial_rounds = 0
    ctx.finalize_result = MagicMock(return_value=mock_debate_result)
    return ctx


@pytest.fixture
def execution_state(mock_debate_context):
    """Create a _DebateExecutionState for testing."""
    return _DebateExecutionState(
        debate_id="test-debate-123",
        correlation_id="corr-test",
        domain="general",
        task_complexity=TaskComplexity.MODERATE,
        ctx=mock_debate_context,
        debate_status="completed",
        debate_start_time=time.perf_counter() - 5.0,  # 5 seconds ago
    )


# =============================================================================
# Tests for _DebateExecutionState
# =============================================================================


class TestDebateExecutionState:
    """Tests for _DebateExecutionState dataclass."""

    def test_creation_with_required_fields(self, mock_debate_context):
        """Test creating state with required fields only."""
        state = _DebateExecutionState(
            debate_id="debate-1",
            correlation_id="corr-1",
            domain="tech",
            task_complexity=TaskComplexity.SIMPLE,
            ctx=mock_debate_context,
        )
        assert state.debate_id == "debate-1"
        assert state.correlation_id == "corr-1"
        assert state.domain == "tech"
        assert state.task_complexity == TaskComplexity.SIMPLE
        assert state.ctx is mock_debate_context

    def test_default_values(self, mock_debate_context):
        """Test default values for optional fields."""
        state = _DebateExecutionState(
            debate_id="debate-1",
            correlation_id="corr-1",
            domain="general",
            task_complexity=TaskComplexity.MODERATE,
            ctx=mock_debate_context,
        )
        assert state.gupp_bead_id is None
        assert state.gupp_hook_entries == {}
        assert state.debate_status == "pending"
        assert state.debate_start_time == 0.0

    def test_gupp_fields(self, mock_debate_context):
        """Test GUPP tracking fields."""
        state = _DebateExecutionState(
            debate_id="debate-1",
            correlation_id="corr-1",
            domain="general",
            task_complexity=TaskComplexity.MODERATE,
            ctx=mock_debate_context,
            gupp_bead_id="bead-123",
            gupp_hook_entries={"agent-1": "entry-1"},
        )
        assert state.gupp_bead_id == "bead-123"
        assert state.gupp_hook_entries == {"agent-1": "entry-1"}

    def test_status_modification(self, mock_debate_context):
        """Test that status can be modified."""
        state = _DebateExecutionState(
            debate_id="debate-1",
            correlation_id="corr-1",
            domain="general",
            task_complexity=TaskComplexity.MODERATE,
            ctx=mock_debate_context,
        )
        state.debate_status = "timeout"
        assert state.debate_status == "timeout"

    def test_start_time_modification(self, mock_debate_context):
        """Test that start time can be set."""
        state = _DebateExecutionState(
            debate_id="debate-1",
            correlation_id="corr-1",
            domain="general",
            task_complexity=TaskComplexity.MODERATE,
            ctx=mock_debate_context,
        )
        state.debate_start_time = 12345.67
        assert state.debate_start_time == 12345.67


# =============================================================================
# Tests for initialize_debate_context
# =============================================================================


class TestInitializeDebateContext:
    """Tests for initialize_debate_context function."""

    @pytest.mark.asyncio
    async def test_generates_debate_id(self, mock_arena):
        """Test that a unique debate ID is generated."""
        state = await initialize_debate_context(mock_arena, "corr-123")

        assert state.debate_id is not None
        assert len(state.debate_id) == 36  # UUID format
        assert "-" in state.debate_id

    @pytest.mark.asyncio
    async def test_uses_provided_correlation_id(self, mock_arena):
        """Test that provided correlation ID is used."""
        state = await initialize_debate_context(mock_arena, "my-correlation-id")

        assert state.correlation_id == "my-correlation-id"

    @pytest.mark.asyncio
    async def test_generates_correlation_id_if_empty(self, mock_arena):
        """Test that correlation ID is generated if not provided."""
        state = await initialize_debate_context(mock_arena, "")

        assert state.correlation_id.startswith("corr-")
        assert state.debate_id[:8] in state.correlation_id

    @pytest.mark.asyncio
    async def test_reinitializes_convergence_detector(self, mock_arena):
        """Test that convergence detector is reinitialized for debate."""
        state = await initialize_debate_context(mock_arena, "corr-123")

        mock_arena._reinit_convergence_for_debate.assert_called_once_with(state.debate_id)

    @pytest.mark.asyncio
    async def test_extracts_domain(self, mock_arena):
        """Test that debate domain is extracted."""
        mock_arena._extract_debate_domain.return_value = "finance"

        state = await initialize_debate_context(mock_arena, "corr-123")

        assert state.domain == "finance"
        mock_arena._extract_debate_domain.assert_called_once()

    @pytest.mark.asyncio
    async def test_initializes_km_context(self, mock_arena):
        """Test that Knowledge Mound context is initialized."""
        state = await initialize_debate_context(mock_arena, "corr-123")

        mock_arena._init_km_context.assert_called_once_with(state.debate_id, state.domain)

    @pytest.mark.asyncio
    async def test_applies_culture_hints_when_available(self, mock_arena):
        """Test that culture hints are applied when present."""
        mock_arena._get_culture_hints.return_value = {"formality": "high"}

        await initialize_debate_context(mock_arena, "corr-123")

        mock_arena._apply_culture_hints.assert_called_once_with({"formality": "high"})

    @pytest.mark.asyncio
    async def test_skips_culture_hints_when_none(self, mock_arena):
        """Test that culture hints application is skipped when None."""
        mock_arena._get_culture_hints.return_value = None

        await initialize_debate_context(mock_arena, "corr-123")

        mock_arena._apply_culture_hints.assert_not_called()

    @pytest.mark.asyncio
    async def test_awaits_pending_culture_task_before_reading_hints(self, mock_arena):
        """Regression test for P4a E8 Problem #2 (culture-hints race).

        Before the fix, KM-context init and culture-hint retrieval ran
        concurrently via asyncio.gather with no ordering guarantee: the
        FIFO-scheduled hint read always got a turn before the fire-and-forget
        culture-retrieval task, so hints populated by KM after the read had
        already run were silently lost. _init_km_context now returns the
        in-flight retrieval task, and initialize_debate_context must await it
        (bounded) before consulting _get_culture_hints.
        """
        retrieved = {"done": False}

        async def _slow_retrieval() -> None:
            for _ in range(5):
                await asyncio.sleep(0)
            retrieved["done"] = True

        pending_task = asyncio.ensure_future(_slow_retrieval())
        mock_arena._init_km_context = AsyncMock(return_value=pending_task)
        mock_arena._get_culture_hints = MagicMock(
            side_effect=lambda debate_id: ({"formality": "high"} if retrieved["done"] else None)
        )

        await initialize_debate_context(mock_arena, "corr-123")

        assert retrieved["done"] is True, "culture task must be awaited before hint read"
        mock_arena._apply_culture_hints.assert_called_once_with({"formality": "high"})

    @pytest.mark.asyncio
    async def test_culture_task_wait_is_bounded_by_timeout(self, mock_arena):
        """A pending culture task slower than the wait budget must not hang
        debate start indefinitely; it should time out and proceed without hints."""
        never_done: "asyncio.Future" = asyncio.get_running_loop().create_future()
        mock_arena._init_km_context = AsyncMock(return_value=never_done)
        mock_arena._get_culture_hints = MagicMock(return_value=None)

        try:
            with patch("aragora.debate.orchestrator_runner._CULTURE_HINTS_WAIT_TIMEOUT_S", 0.01):
                state = await initialize_debate_context(mock_arena, "corr-123")
        finally:
            never_done.cancel()

        assert state is not None
        mock_arena._apply_culture_hints.assert_not_called()

    @pytest.mark.asyncio
    async def test_culture_task_failure_outside_narrow_tuple_does_not_fail_debate_start(
        self, mock_arena
    ):
        """A culture-task exception outside the old narrow _NON_BLOCKING_KM_INIT_ERRORS
        tuple must still not propagate out of initialize_debate_context.

        Reviewer-flagged on P4a E8 PR #9002 (claude [P3], grok [P2]): awaiting the
        pending culture task newly exposed debate start to its exceptions, but the
        except clause only covered _NON_BLOCKING_KM_INIT_ERRORS - narrower than the
        module's own "culture hints must never block or fail debate start" invariant.
        A custom exception (deliberately outside that tuple) exercises the gap.
        """

        class CultureBackendError(Exception):
            pass

        async def _raises_custom_error() -> None:
            await asyncio.sleep(0)
            raise CultureBackendError("simulated KM backend failure outside the narrow tuple")

        pending_task = asyncio.ensure_future(_raises_custom_error())
        mock_arena._init_km_context = AsyncMock(return_value=pending_task)
        mock_arena._get_culture_hints = MagicMock(return_value=None)

        state = await initialize_debate_context(mock_arena, "corr-123")

        assert state is not None
        mock_arena._apply_culture_hints.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_debate_context(self, mock_arena):
        """Test that DebateContext is created with correct fields."""
        state = await initialize_debate_context(mock_arena, "corr-123")

        ctx = state.ctx
        assert ctx.env is mock_arena.env
        assert ctx.agents is mock_arena.agents
        assert ctx.debate_id == state.debate_id
        assert ctx.correlation_id == "corr-123"
        assert ctx.domain == state.domain
        assert ctx.hook_manager is mock_arena.hook_manager
        assert ctx.org_id == mock_arena.org_id

    @pytest.mark.asyncio
    async def test_sets_molecule_orchestrator_on_context(self, mock_arena):
        """Test that molecule_orchestrator is set on context."""
        mock_arena.molecule_orchestrator = MagicMock()

        state = await initialize_debate_context(mock_arena, "corr-123")

        assert state.ctx.molecule_orchestrator is mock_arena.molecule_orchestrator

    @pytest.mark.asyncio
    async def test_sets_checkpoint_bridge_on_context(self, mock_arena):
        """Test that checkpoint_bridge is set on context."""
        mock_arena.checkpoint_bridge = MagicMock()

        state = await initialize_debate_context(mock_arena, "corr-123")

        assert state.ctx.checkpoint_bridge is mock_arena.checkpoint_bridge

    @pytest.mark.asyncio
    async def test_sets_up_belief_network_when_enabled(self, mock_arena):
        """Test that BeliefNetwork is set up when km_belief_sync is enabled."""
        mock_arena.protocol.enable_km_belief_sync = True
        mock_belief_network = MagicMock()
        mock_arena._setup_belief_network.return_value = mock_belief_network

        state = await initialize_debate_context(mock_arena, "corr-123")

        mock_arena._setup_belief_network.assert_called_once()
        call_kwargs = mock_arena._setup_belief_network.call_args[1]
        assert call_kwargs["debate_id"] == state.debate_id
        assert call_kwargs["topic"] == mock_arena.env.task
        assert call_kwargs["seed_from_km"] is True
        assert state.ctx.belief_network is mock_belief_network

    @pytest.mark.asyncio
    async def test_skips_belief_network_when_disabled(self, mock_arena):
        """Test that BeliefNetwork is not set up when disabled."""
        mock_arena.protocol.enable_km_belief_sync = False

        await initialize_debate_context(mock_arena, "corr-123")

        mock_arena._setup_belief_network.assert_not_called()

    @pytest.mark.asyncio
    async def test_classifies_task_complexity(self, mock_arena):
        """Test that task complexity is classified."""
        mock_arena.env.task = "Please prove this theorem formally"

        state = await initialize_debate_context(mock_arena, "corr-123")

        # Complex keywords should result in complex classification
        assert state.task_complexity is not None

    @pytest.mark.asyncio
    async def test_classifies_question_with_prompt_builder(self, mock_arena):
        """Test that question classification is called when prompt_builder exists.

        The runner does a two-phase classification: fast heuristic first
        (use_llm=False), then a background LLM pass (use_llm=True).
        """
        mock_arena.prompt_builder = MagicMock()
        mock_arena.prompt_builder.classify_question_async = AsyncMock()

        with patch("aragora.utils.env.is_offline_mode", return_value=False):
            await initialize_debate_context(mock_arena, "corr-123")

        # First call is the fast heuristic, second is the background LLM task
        calls = mock_arena.prompt_builder.classify_question_async.call_args_list
        assert len(calls) >= 1
        assert calls[0] == call(use_llm=False)

    @pytest.mark.asyncio
    async def test_handles_question_classification_timeout(self, mock_arena):
        """Test that question classification timeout is handled gracefully."""
        mock_arena.prompt_builder = MagicMock()
        mock_arena.prompt_builder.classify_question_async = AsyncMock(
            side_effect=asyncio.TimeoutError()
        )

        # Should not raise
        state = await initialize_debate_context(mock_arena, "corr-123")
        assert state.debate_id is not None

    @pytest.mark.asyncio
    async def test_handles_question_classification_value_error(self, mock_arena):
        """Test that question classification ValueError is handled gracefully."""
        mock_arena.prompt_builder = MagicMock()
        mock_arena.prompt_builder.classify_question_async = AsyncMock(
            side_effect=ValueError("Invalid input")
        )

        # Should not raise
        state = await initialize_debate_context(mock_arena, "corr-123")
        assert state.debate_id is not None

    @pytest.mark.asyncio
    async def test_applies_performance_based_selection_when_enabled(self, mock_arena):
        """Test that performance-based agent selection is applied when enabled."""
        mock_arena.use_performance_selection = True

        state = await initialize_debate_context(mock_arena, "corr-123")

        mock_arena._select_debate_team.assert_called_once()
        # Agents should be updated on both arena and context
        assert state.ctx.agents is mock_arena.agents

    @pytest.mark.asyncio
    async def test_skips_performance_selection_when_disabled(self, mock_arena):
        """Test that performance-based selection is skipped when disabled."""
        mock_arena.use_performance_selection = False

        await initialize_debate_context(mock_arena, "corr-123")

        mock_arena._select_debate_team.assert_not_called()

    @pytest.mark.asyncio
    async def test_assigns_hierarchy_roles(self, mock_arena):
        """Test that hierarchy roles are assigned to agents."""
        state = await initialize_debate_context(mock_arena, "corr-123")

        mock_arena._assign_hierarchy_roles.assert_called_once()
        call_args = mock_arena._assign_hierarchy_roles.call_args
        assert call_args[0][0] is state.ctx
        assert call_args[1]["task_type"] == state.domain

    @pytest.mark.asyncio
    async def test_sets_up_agent_channels(self, mock_arena):
        """Test that agent-to-agent channels are set up."""
        state = await initialize_debate_context(mock_arena, "corr-123")

        mock_arena._setup_agent_channels.assert_called_once_with(state.ctx, state.debate_id)


# =============================================================================
# Tests for setup_debate_infrastructure
# =============================================================================


class TestSetupDebateInfrastructure:
    """Tests for setup_debate_infrastructure function."""

    @pytest.mark.asyncio
    async def test_notifies_trackers_of_debate_start(self, mock_arena, execution_state):
        """Test that trackers are notified of debate start."""
        await setup_debate_infrastructure(mock_arena, execution_state)

        mock_arena._trackers.on_debate_start.assert_called_once_with(execution_state.ctx)

    @pytest.mark.asyncio
    async def test_emits_agent_preview(self, mock_arena, execution_state):
        """Test that agent preview is emitted."""
        await setup_debate_infrastructure(mock_arena, execution_state)

        mock_arena._emit_agent_preview.assert_called_once()

    @pytest.mark.asyncio
    async def test_checks_budget_before_debate(self, mock_arena, execution_state):
        """Test that budget is checked before debate starts."""
        await setup_debate_infrastructure(mock_arena, execution_state)

        mock_arena._budget_coordinator.check_budget_before_debate.assert_called_once()
        call_args = mock_arena._budget_coordinator.check_budget_before_debate.call_args
        assert call_args[0][0] == execution_state.debate_id

    @pytest.mark.asyncio
    async def test_budget_exceeded_raises(self, mock_arena, execution_state):
        """Test that budget exceeded error propagates."""
        from aragora.exceptions import AragoraError

        mock_arena._budget_coordinator.check_budget_before_debate.side_effect = AragoraError(
            "Budget exceeded"
        )

        with pytest.raises(AragoraError, match="Budget exceeded"):
            await setup_debate_infrastructure(mock_arena, execution_state)

    @pytest.mark.asyncio
    async def test_initializes_gupp_tracking_when_enabled(self, mock_arena, execution_state):
        """Test that GUPP hook tracking is initialized when enabled."""
        mock_arena.protocol.enable_hook_tracking = True
        mock_arena._create_pending_debate_bead.return_value = "bead-456"
        mock_arena._init_hook_tracking.return_value = {"agent-1": "entry-1"}

        await setup_debate_infrastructure(mock_arena, execution_state)

        mock_arena._create_pending_debate_bead.assert_called_once_with(
            execution_state.debate_id, mock_arena.env.task
        )
        assert execution_state.gupp_bead_id == "bead-456"

    @pytest.mark.asyncio
    async def test_initializes_hook_entries_when_bead_created(self, mock_arena, execution_state):
        """Test that hook entries are initialized when bead is created."""
        mock_arena.protocol.enable_hook_tracking = True
        mock_arena._create_pending_debate_bead.return_value = "bead-789"
        mock_arena._init_hook_tracking.return_value = {"agent-0": "entry-0"}

        await setup_debate_infrastructure(mock_arena, execution_state)

        mock_arena._init_hook_tracking.assert_called_once_with(
            execution_state.debate_id, "bead-789"
        )
        assert execution_state.gupp_hook_entries == {"agent-0": "entry-0"}

    @pytest.mark.asyncio
    async def test_skips_gupp_when_disabled(self, mock_arena, execution_state):
        """Test that GUPP tracking is skipped when disabled."""
        mock_arena.protocol.enable_hook_tracking = False

        await setup_debate_infrastructure(mock_arena, execution_state)

        mock_arena._create_pending_debate_bead.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_gupp_initialization_error(self, mock_arena, execution_state):
        """Test that GUPP initialization errors are handled gracefully."""
        mock_arena.protocol.enable_hook_tracking = True
        mock_arena._create_pending_debate_bead.side_effect = RuntimeError("GUPP error")

        # Should not raise
        await setup_debate_infrastructure(mock_arena, execution_state)

        assert execution_state.gupp_bead_id is None

    @pytest.mark.asyncio
    async def test_creates_initial_result(self, mock_arena, execution_state):
        """Test that initial DebateResult is created on context."""
        await setup_debate_infrastructure(mock_arena, execution_state)

        result = execution_state.ctx.result
        assert result.task == mock_arena.env.task
        assert result.consensus_reached is False
        assert result.confidence == 0.0
        assert result.messages == []
        assert result.critiques == []
        assert result.votes == []
        assert result.rounds_used == 0
        assert result.final_answer == ""

    @pytest.mark.asyncio
    async def test_records_start_time(self, mock_arena, execution_state):
        """Test that debate start time is recorded."""
        execution_state.debate_start_time = 0.0

        await setup_debate_infrastructure(mock_arena, execution_state)

        assert execution_state.debate_start_time > 0


# =============================================================================
# Tests for execute_debate_phases
# =============================================================================


class TestExecuteDebatePhases:
    """Tests for execute_debate_phases function."""

    @pytest.mark.asyncio
    async def test_executes_phase_executor(self, mock_arena, execution_state, mock_span):
        """Test that PhaseExecutor.execute is called."""
        await execute_debate_phases(mock_arena, execution_state, mock_span)

        mock_arena.phase_executor.execute.assert_called_once_with(
            execution_state.ctx,
            debate_id=execution_state.debate_id,
        )

    @pytest.mark.asyncio
    async def test_logs_phase_failures(self, mock_arena, execution_state, mock_span):
        """Test that phase failures are logged."""
        mock_result = MagicMock()
        mock_arena.phase_executor.execute.return_value = mock_result

        await execute_debate_phases(mock_arena, execution_state, mock_span)

        mock_arena._log_phase_failures.assert_called_once_with(mock_result)

    @pytest.mark.asyncio
    async def test_handles_timeout_with_partial_results(
        self, mock_arena, execution_state, mock_span
    ):
        """Test that timeout uses partial results."""
        execution_state.ctx.partial_messages = [MagicMock()]
        execution_state.ctx.partial_critiques = [MagicMock()]
        execution_state.ctx.partial_rounds = 2
        mock_arena.phase_executor.execute.side_effect = asyncio.TimeoutError()

        await execute_debate_phases(mock_arena, execution_state, mock_span)

        assert execution_state.ctx.result.messages == execution_state.ctx.partial_messages
        assert execution_state.ctx.result.critiques == execution_state.ctx.partial_critiques
        assert execution_state.ctx.result.rounds_used == 2
        assert execution_state.debate_status == "blocked"
        mock_span.set_attribute.assert_called_with("debate.status", "timeout")

    @pytest.mark.asyncio
    async def test_handles_early_stop_error(self, mock_arena, execution_state, mock_span):
        """Test that EarlyStopError is handled and re-raised."""
        from aragora.exceptions import EarlyStopError

        mock_arena.phase_executor.execute.side_effect = EarlyStopError(
            "User requested stop", round_stopped=1
        )

        with pytest.raises(EarlyStopError):
            await execute_debate_phases(mock_arena, execution_state, mock_span)

        assert execution_state.debate_status == "blocked"
        mock_span.set_attribute.assert_called_with("debate.status", "aborted")

    @pytest.mark.asyncio
    async def test_handles_general_exception(self, mock_arena, execution_state, mock_span):
        """Test that general exceptions set error status and re-raise."""
        mock_arena.phase_executor.execute.side_effect = ValueError("Something wrong")

        with pytest.raises(ValueError):
            await execute_debate_phases(mock_arena, execution_state, mock_span)

        assert execution_state.debate_status == "failed"
        mock_span.set_attribute.assert_called_with("debate.status", "error")
        mock_span.record_exception.assert_called_once()


# =============================================================================
# Tests for record_debate_metrics
# =============================================================================


class TestRecordDebateMetrics:
    """Tests for record_debate_metrics function."""

    def test_decrements_active_debates(self, mock_arena, execution_state, mock_span):
        """Test that ACTIVE_DEBATES counter is decremented."""
        with patch("aragora.server.metrics.ACTIVE_DEBATES") as mock_counter:
            record_debate_metrics(mock_arena, execution_state, mock_span)

            mock_counter.dec.assert_called_once()

    def test_calculates_duration(self, mock_arena, execution_state, mock_span):
        """Test that duration is calculated correctly."""
        execution_state.debate_start_time = time.perf_counter() - 10.0

        with (
            patch("aragora.server.metrics.ACTIVE_DEBATES"),
            patch("aragora.debate.orchestrator_runner.add_span_attributes") as mock_add_attrs,
            patch("aragora.server.metrics.track_debate_outcome"),
        ):
            record_debate_metrics(mock_arena, execution_state, mock_span)

            call_args = mock_add_attrs.call_args[0]
            attrs = call_args[1]
            assert attrs["debate.duration_seconds"] >= 10.0

    def test_adds_span_attributes(self, mock_arena, execution_state, mock_span):
        """Test that span attributes are added."""
        execution_state.ctx.result.consensus_reached = True
        execution_state.ctx.result.confidence = 0.9
        execution_state.ctx.result.messages = [MagicMock(), MagicMock(), MagicMock()]

        with (
            patch("aragora.server.metrics.ACTIVE_DEBATES"),
            patch("aragora.debate.orchestrator_runner.add_span_attributes") as mock_add_attrs,
            patch("aragora.server.metrics.track_debate_outcome"),
        ):
            record_debate_metrics(mock_arena, execution_state, mock_span)

            mock_add_attrs.assert_called_once()
            call_args = mock_add_attrs.call_args[0]
            assert call_args[0] is mock_span
            attrs = call_args[1]
            assert attrs["debate.status"] == "completed"
            assert attrs["debate.consensus_reached"] is True
            assert attrs["debate.confidence"] == 0.9
            assert attrs["debate.message_count"] == 3

    def test_tracks_debate_outcome(self, mock_arena, execution_state, mock_span):
        """Test that debate outcome is tracked."""
        execution_state.debate_status = "completed"
        execution_state.domain = "finance"
        execution_state.ctx.result.consensus_reached = True
        execution_state.ctx.result.confidence = 0.8

        with (
            patch("aragora.server.metrics.ACTIVE_DEBATES"),
            patch("aragora.debate.orchestrator_runner.add_span_attributes"),
            patch("aragora.server.metrics.track_debate_outcome") as mock_track,
        ):
            record_debate_metrics(mock_arena, execution_state, mock_span)

            mock_track.assert_called_once()
            call_kwargs = mock_track.call_args[1]
            assert call_kwargs["status"] == "completed"
            assert call_kwargs["domain"] == "finance"
            assert call_kwargs["consensus_reached"] is True
            assert call_kwargs["confidence"] == 0.8

    def test_tracks_circuit_breaker_metrics(self, mock_arena, execution_state, mock_span):
        """Test that circuit breaker metrics are tracked."""
        with (
            patch("aragora.server.metrics.ACTIVE_DEBATES"),
            patch("aragora.debate.orchestrator_runner.add_span_attributes"),
            patch("aragora.server.metrics.track_debate_outcome"),
        ):
            record_debate_metrics(mock_arena, execution_state, mock_span)

            mock_arena._track_circuit_breaker_metrics.assert_called_once()

    def test_handles_none_result(self, mock_arena, execution_state, mock_span):
        """Test that None result is handled gracefully."""
        execution_state.ctx.result = None

        with (
            patch("aragora.server.metrics.ACTIVE_DEBATES"),
            patch("aragora.debate.orchestrator_runner.add_span_attributes") as mock_add_attrs,
            patch("aragora.server.metrics.track_debate_outcome"),
        ):
            # Should not raise
            record_debate_metrics(mock_arena, execution_state, mock_span)

            call_args = mock_add_attrs.call_args[0]
            attrs = call_args[1]
            assert attrs["debate.consensus_reached"] is False
            assert attrs["debate.confidence"] == 0.0
            assert attrs["debate.message_count"] == 0


# =============================================================================
# Tests for handle_debate_completion
# =============================================================================


class TestHandleDebateCompletion:
    """Tests for handle_debate_completion function."""

    @pytest.mark.asyncio
    async def test_record_debate_telemetry_records_usage_and_analytics(
        self, mock_arena, execution_state
    ):
        """Telemetry records debate usage and per-agent analytics."""
        result = execution_state.ctx.result
        result.duration_seconds = 12.4
        result.rounds_used = 4
        result.messages = [MagicMock(), MagicMock(), MagicMock()]
        result.votes = [MagicMock()]
        result.metadata = {"provider_routing": {"primary": "anthropic"}}
        result.total_cost_usd = 1.25
        result.per_agent_cost = {"agent-0": 0.4}
        mock_arena.user_id = "user-42"
        mock_arena.protocol.consensus = "majority"
        mock_arena.agents = mock_arena.agents[:2]

        mock_arena.agents[0].provider = "anthropic"
        mock_arena.agents[0].model = "claude-3-7-sonnet"
        mock_arena.agents[0].metrics = SimpleNamespace(
            total_input_tokens=120,
            total_output_tokens=30,
        )

        mock_arena.agents[1].metrics = None
        mock_arena.agents[1].provider = None
        mock_arena.agents[1].agent_type = "openai"
        mock_arena.agents[1].model = "gpt-4o-mini"
        mock_arena.agents[1].total_tokens_in = 90
        mock_arena.agents[1].total_tokens_out = 45

        governor = MagicMock()
        governor.agent_metrics = {"agent-0": SimpleNamespace(avg_latency_ms=321.5)}
        usage_summary = {"total_tokens": 285, "agents_recorded": 2}
        usage_meter = SimpleNamespace(flush_all=AsyncMock())
        analytics = SimpleNamespace(
            record_debate=AsyncMock(),
            record_agent_activity=AsyncMock(),
        )

        with (
            patch(
                "aragora.billing.usage_metering_integration.record_debate_tokens",
                new_callable=AsyncMock,
            ) as mock_record_tokens,
            patch(
                "aragora.services.usage_metering.get_usage_meter",
                return_value=usage_meter,
            ),
            patch(
                "aragora.analytics.debate_analytics.get_debate_analytics",
                return_value=analytics,
            ),
            patch(
                "aragora.billing.usage.calculate_token_cost",
                return_value=Decimal("0.33"),
            ) as mock_calculate_cost,
            patch(
                "aragora.debate.orchestrator_runner.get_complexity_governor",
                return_value=governor,
            ),
        ):
            mock_record_tokens.return_value = usage_summary

            await _record_debate_telemetry(mock_arena, execution_state)

        mock_record_tokens.assert_awaited_once()
        metering_kwargs = mock_record_tokens.await_args.kwargs
        assert metering_kwargs["org_id"] == "test-org"
        assert metering_kwargs["debate_id"] == execution_state.debate_id
        assert metering_kwargs["user_id"] == "user-42"
        assert metering_kwargs["rounds"] == 4
        assert metering_kwargs["duration_seconds"] == 12
        assert metering_kwargs["metadata"] == {
            "status": "completed",
            "confidence": 0.85,
            "consensus_reached": True,
            "message_count": 3,
            "vote_count": 1,
            "provider_routing": {"primary": "anthropic"},
        }
        usage_meter.flush_all.assert_awaited_once()
        assert result.metadata["usage_metering"] == usage_summary

        analytics.record_debate.assert_awaited_once()
        debate_kwargs = analytics.record_debate.await_args.kwargs
        assert debate_kwargs["debate_id"] == execution_state.debate_id
        assert debate_kwargs["rounds"] == 4
        assert debate_kwargs["duration_seconds"] == 12.4
        assert debate_kwargs["agents"] == ["agent-0", "agent-1"]
        assert debate_kwargs["org_id"] == "test-org"
        assert debate_kwargs["user_id"] == "user-42"
        assert debate_kwargs["protocol"] == "majority"
        assert debate_kwargs["total_messages"] == 3
        assert debate_kwargs["total_votes"] == 1
        assert debate_kwargs["total_cost"] == Decimal("1.25")

        assert analytics.record_agent_activity.await_count == 2
        activity_calls = {
            call.kwargs["agent_id"]: call.kwargs
            for call in analytics.record_agent_activity.await_args_list
        }
        assert activity_calls["agent-0"]["tokens_in"] == 120
        assert activity_calls["agent-0"]["tokens_out"] == 30
        assert activity_calls["agent-0"]["response_time_ms"] == 321.5
        assert activity_calls["agent-0"]["cost"] == Decimal("0.4")
        assert activity_calls["agent-0"]["provider"] == "anthropic"
        assert activity_calls["agent-1"]["tokens_in"] == 90
        assert activity_calls["agent-1"]["tokens_out"] == 45
        assert activity_calls["agent-1"]["cost"] == Decimal("0.33")
        assert activity_calls["agent-1"]["provider"] == "openai"
        mock_calculate_cost.assert_called_once_with("openai", "gpt-4o-mini", 90, 45)

    @pytest.mark.asyncio
    async def test_record_debate_telemetry_swallows_noncritical_failures(
        self, mock_arena, execution_state
    ):
        """Telemetry failures should not break debate completion."""
        execution_state.ctx.result.metadata = {}

        with (
            patch(
                "aragora.billing.usage_metering_integration.record_debate_tokens",
                new_callable=AsyncMock,
                side_effect=RuntimeError("metering unavailable"),
            ),
            patch(
                "aragora.analytics.debate_analytics.get_debate_analytics",
                side_effect=RuntimeError("analytics unavailable"),
            ),
        ):
            await _record_debate_telemetry(mock_arena, execution_state)

        assert execution_state.ctx.result.metadata == {}

    @pytest.mark.asyncio
    async def test_run_cross_verification_attaches_metadata(self, mock_agents):
        """Cross-verification attaches grounding metadata to the result."""
        result = DebateResult(task="Test task", final_answer="Test answer")
        verification = MagicMock(
            grounding_delta=0.42,
            hallucination_risk=0.11,
            adversarial_resistance=0.87,
            is_grounded=True,
        )
        engine = MagicMock()
        engine.verify = AsyncMock(return_value=verification)

        with patch(
            "aragora.debate.cross_verification.CrossVerificationEngine",
            return_value=engine,
        ):
            await _run_cross_verification(result, mock_agents)

        engine.verify.assert_awaited_once_with("Test answer", context="Test task")
        assert result.metadata["cross_verification"] == {
            "grounding_delta": 0.42,
            "hallucination_risk": 0.11,
            "adversarial_resistance": 0.87,
            "is_grounded": True,
        }

    @pytest.mark.asyncio
    async def test_notifies_trackers_of_completion(self, mock_arena, execution_state):
        """Test that trackers are notified of debate completion."""
        await handle_debate_completion(mock_arena, execution_state)

        mock_arena._trackers.on_debate_complete.assert_called_once_with(
            execution_state.ctx, execution_state.ctx.result
        )

    @pytest.mark.asyncio
    async def test_records_completion_telemetry(self, mock_arena, execution_state):
        """Completion wiring includes the telemetry hook."""
        with (
            patch(
                "aragora.debate.orchestrator_runner._populate_result_cost",
                new_callable=AsyncMock,
            ),
            patch(
                "aragora.debate.orchestrator_runner._populate_result_tokens_from_agents",
                new_callable=AsyncMock,
            ),
            patch(
                "aragora.debate.orchestrator_runner._record_debate_telemetry",
                new_callable=AsyncMock,
            ) as mock_record_telemetry,
        ):
            await handle_debate_completion(mock_arena, execution_state)

        mock_record_telemetry.assert_awaited_once_with(mock_arena, execution_state)

    @pytest.mark.asyncio
    async def test_skips_tracker_notification_if_no_result(self, mock_arena, execution_state):
        """Test that tracker notification is skipped if result is None."""
        execution_state.ctx.result = None

        await handle_debate_completion(mock_arena, execution_state)

        mock_arena._trackers.on_debate_complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_triggers_extensions(self, mock_arena, execution_state):
        """Test that extensions are triggered."""
        await handle_debate_completion(mock_arena, execution_state)

        mock_arena.extensions.on_debate_complete.assert_called_once_with(
            execution_state.ctx, execution_state.ctx.result, mock_arena.agents
        )

    @pytest.mark.asyncio
    async def test_records_debate_cost(self, mock_arena, execution_state):
        """Test that debate cost is recorded."""
        await handle_debate_completion(mock_arena, execution_state)

        mock_arena._budget_coordinator.record_debate_cost.assert_called_once_with(
            execution_state.debate_id,
            execution_state.ctx.result,
            extensions=mock_arena.extensions,
        )

    @pytest.mark.asyncio
    async def test_skips_cost_recording_if_no_result(self, mock_arena, execution_state):
        """Test that cost recording is skipped if result is None."""
        execution_state.ctx.result = None

        await handle_debate_completion(mock_arena, execution_state)

        mock_arena._budget_coordinator.record_debate_cost.assert_not_called()

    @pytest.mark.asyncio
    async def test_ingests_debate_outcome_to_km(self, mock_arena, execution_state):
        """Test that debate outcome is ingested to Knowledge Mound (background task)."""
        await handle_debate_completion(mock_arena, execution_state)

        mock_arena._ingest_debate_outcome.assert_called_once_with(execution_state.ctx.result)
        assert getattr(execution_state.ctx, "_km_ingest_task", None) is None

    @pytest.mark.asyncio
    async def test_handles_km_ingestion_error(self, mock_arena, execution_state):
        """Test that KM ingestion errors are handled gracefully."""
        mock_arena._ingest_debate_outcome.side_effect = ConnectionError("KM down")

        # Should not raise — ingestion runs in background with retry
        await handle_debate_completion(mock_arena, execution_state)
        assert getattr(execution_state.ctx, "_km_ingest_task", None) is None

    @pytest.mark.asyncio
    async def test_reports_truthful_km_metadata_on_result(self, mock_arena, execution_state):
        """Observed KM retrieval/writeback is attached to result metadata."""
        prompt_builder = MagicMock()
        prompt_builder.get_knowledge_mound_context.return_value = "Institutional context"
        mock_arena.prompt_builder = prompt_builder
        execution_state.ctx._prompt_builder = prompt_builder
        execution_state.ctx._km_item_ids_used = ["km-1", "km-2"]

        await handle_debate_completion(mock_arena, execution_state)
        result = await cleanup_debate_resources(mock_arena, execution_state)

        km_metadata = result.metadata["knowledge_management"]
        assert km_metadata["retrieval"]["status"] == "succeeded"
        assert km_metadata["retrieval"]["observed_context_chars"] == len("Institutional context")
        assert km_metadata["retrieval"]["observed_item_count"] == 2
        assert km_metadata["writeback"]["status"] == "succeeded"

    @pytest.mark.asyncio
    async def test_reports_km_as_not_configured_without_fake_enrichment(
        self, mock_arena, execution_state
    ):
        """Absent KM is reported explicitly instead of inventing enrichment."""
        mock_arena.knowledge_mound = None

        await handle_debate_completion(mock_arena, execution_state)
        result = await cleanup_debate_resources(mock_arena, execution_state)

        km_metadata = result.metadata["knowledge_management"]
        assert km_metadata["context_handoff"]["status"] == "not_configured"
        assert km_metadata["retrieval"]["status"] == "not_configured"
        assert km_metadata["writeback"]["status"] == "not_configured"
        mock_arena._ingest_debate_outcome.assert_not_called()

    @pytest.mark.asyncio
    async def test_preserves_failed_retrieval_state_in_result_metadata(
        self, mock_arena, mock_debate_result
    ):
        """Failed KM handoff remains failed in final metadata."""
        mock_arena._init_km_context.side_effect = ConnectionError("KM unavailable")

        state = await initialize_debate_context(mock_arena, "corr-123")
        state.ctx.result = mock_debate_result
        state.ctx.finalize_result = MagicMock(return_value=mock_debate_result)

        await handle_debate_completion(mock_arena, state)
        result = await cleanup_debate_resources(mock_arena, state)

        km_metadata = result.metadata["knowledge_management"]
        assert km_metadata["context_handoff"]["status"] == "failed"
        assert km_metadata["retrieval"]["status"] == "failed"
        assert km_metadata["retrieval"]["error_type"] == "ConnectionError"
        assert km_metadata["retrieval"]["error"] == "KM unavailable"

    @pytest.mark.asyncio
    async def test_failed_handoff_ignores_stale_prompt_builder_km_context(
        self, mock_arena, mock_debate_result
    ):
        """Stale prompt-builder KM state does not fake current-debate enrichment."""
        prompt_state = {"context": "stale knowledge", "item_ids": ["old-item"]}
        prompt_builder = MagicMock()
        prompt_builder.get_knowledge_mound_context.side_effect = lambda: prompt_state["context"]

        def _set_knowledge_context(context: str, item_ids: list[str] | None = None) -> None:
            prompt_state["context"] = context
            prompt_state["item_ids"] = list(item_ids or [])

        prompt_builder.set_knowledge_context.side_effect = _set_knowledge_context
        mock_arena.prompt_builder = prompt_builder
        mock_arena._init_km_context.side_effect = ConnectionError("KM unavailable")

        state = await initialize_debate_context(mock_arena, "corr-123")
        state.ctx.result = mock_debate_result
        state.ctx.finalize_result = MagicMock(return_value=mock_debate_result)

        await handle_debate_completion(mock_arena, state)
        result = await cleanup_debate_resources(mock_arena, state)

        km_metadata = result.metadata["knowledge_management"]
        assert km_metadata["context_handoff"]["status"] == "failed"
        assert km_metadata["retrieval"]["status"] == "failed"
        assert km_metadata["retrieval"]["observed_context_chars"] == 0
        assert km_metadata["retrieval"]["observed_item_count"] == 0
        assert prompt_builder.set_knowledge_context.call_args_list[0] == call("", [])

    @pytest.mark.asyncio
    async def test_completes_gupp_tracking_on_success(self, mock_arena, execution_state):
        """Test that GUPP tracking is completed on success."""
        execution_state.gupp_bead_id = "bead-123"
        execution_state.gupp_hook_entries = {"agent-1": "entry-1"}
        execution_state.debate_status = "completed"

        await handle_debate_completion(mock_arena, execution_state)

        mock_arena._update_debate_bead.assert_called_once_with(
            "bead-123", execution_state.ctx.result, True
        )
        mock_arena._complete_hook_tracking.assert_called_once_with(
            "bead-123",
            {"agent-1": "entry-1"},
            True,
            error_msg="",
        )
        assert execution_state.ctx.result.bead_id == "bead-123"

    @pytest.mark.asyncio
    async def test_completes_gupp_tracking_on_failure(self, mock_arena, execution_state):
        """Test that GUPP tracking is completed with failure status."""
        execution_state.gupp_bead_id = "bead-456"
        execution_state.gupp_hook_entries = {"agent-0": "entry-0"}
        execution_state.debate_status = "error"

        await handle_debate_completion(mock_arena, execution_state)

        mock_arena._update_debate_bead.assert_called_once_with(
            "bead-456", execution_state.ctx.result, False
        )
        mock_arena._complete_hook_tracking.assert_called_once_with(
            "bead-456",
            {"agent-0": "entry-0"},
            False,
            error_msg="Debate error",
        )

    @pytest.mark.asyncio
    async def test_handles_gupp_completion_error(self, mock_arena, execution_state):
        """Test that GUPP completion errors are handled gracefully."""
        execution_state.gupp_bead_id = "bead-789"
        execution_state.gupp_hook_entries = {"agent-1": "entry-1"}
        mock_arena._update_debate_bead.side_effect = ConnectionError("Failed")

        # Should not raise
        await handle_debate_completion(mock_arena, execution_state)

    @pytest.mark.asyncio
    async def test_creates_bead_if_gupp_not_used(self, mock_arena, execution_state):
        """Test that bead is created if GUPP tracking was not used."""
        execution_state.gupp_bead_id = None
        mock_arena._create_debate_bead.return_value = "new-bead-id"

        await handle_debate_completion(mock_arena, execution_state)

        mock_arena._create_debate_bead.assert_called_once_with(execution_state.ctx.result)
        assert execution_state.ctx.result.bead_id == "new-bead-id"

    @pytest.mark.asyncio
    async def test_handles_bead_creation_error(self, mock_arena, execution_state):
        """Test that bead creation errors are handled gracefully."""
        execution_state.gupp_bead_id = None
        mock_arena._create_debate_bead.side_effect = OSError("Disk full")

        # Should not raise
        await handle_debate_completion(mock_arena, execution_state)

    @pytest.mark.asyncio
    async def test_runs_cross_verification_when_enabled(self, mock_arena, execution_state):
        """Debate completion runs cross-verification only when enabled."""
        mock_arena.enable_cross_verification = True

        with patch(
            "aragora.debate.orchestrator_runner._run_cross_verification",
            new_callable=AsyncMock,
        ) as mock_cross_verification:
            await handle_debate_completion(mock_arena, execution_state)

        mock_cross_verification.assert_awaited_once_with(
            execution_state.ctx.result, mock_arena.agents
        )

    @pytest.mark.asyncio
    async def test_queues_for_supabase_sync(self, mock_arena, execution_state):
        """Test that result is queued for Supabase sync."""
        await handle_debate_completion(mock_arena, execution_state)

        mock_arena._queue_for_supabase_sync.assert_called_once_with(
            execution_state.ctx, execution_state.ctx.result
        )

    @pytest.mark.asyncio
    async def test_records_usage_metering_and_flushes_buffers(self, mock_arena, execution_state):
        """Debate completion persists usage metering and flushes buffered rows."""
        mock_arena.user_id = "test-user"
        execution_state.ctx.result.rounds_used = 4
        execution_state.ctx.result.duration_seconds = 12.4
        execution_state.ctx.result.metadata = {}

        for idx, agent in enumerate(mock_arena.agents[:2]):
            agent.provider = "anthropic"
            agent.model = "claude-sonnet-4"
            agent.total_tokens_in = (idx + 1) * 100
            agent.total_tokens_out = (idx + 1) * 25

        meter = MagicMock()
        meter.flush_all = AsyncMock()

        with (
            patch(
                "aragora.billing.usage_metering_integration.record_debate_tokens",
                new=AsyncMock(
                    return_value={
                        "total_tokens": 375,
                        "agents_recorded": 2,
                        "debate_recorded": True,
                    }
                ),
            ) as mock_record,
            patch("aragora.services.usage_metering.get_usage_meter", return_value=meter),
            patch(
                "aragora.analytics.debate_analytics.get_debate_analytics",
                side_effect=ImportError,
            ),
        ):
            await handle_debate_completion(mock_arena, execution_state)

        mock_record.assert_awaited_once()
        record_kwargs = mock_record.await_args.kwargs
        assert record_kwargs["org_id"] == "test-org"
        assert record_kwargs["user_id"] == "test-user"
        assert record_kwargs["debate_id"] == execution_state.debate_id
        assert record_kwargs["rounds"] == 4
        assert record_kwargs["duration_seconds"] == 12
        assert record_kwargs["metadata"]["status"] == "completed"
        meter.flush_all.assert_awaited_once()
        assert execution_state.ctx.result.metadata["usage_metering"]["debate_recorded"] is True

    @pytest.mark.asyncio
    async def test_auto_execution_preserves_post_debate_execution_mode(
        self, mock_arena, execution_state, monkeypatch
    ):
        """Auto-execution should not reset an explicit post-debate execution mode."""
        mock_arena.enable_auto_execution = True
        mock_arena.disable_post_debate_pipeline = False
        mock_arena.auto_approval_mode = "risk_based"
        mock_arena.post_debate_config = PostDebateConfig(
            execution_mode=ExecutionMode.INTERACTIVE,
            auto_explain=False,
            auto_create_plan=False,
            auto_notify=False,
            auto_execute_plan=False,
            auto_create_pr=False,
            auto_build_integrity_package=False,
            auto_persist_receipt=False,
            auto_gauntlet_validate=False,
            auto_queue_improvement=False,
            auto_execution_bridge=False,
        )
        monkeypatch.setenv("ARAGORA_SYNC_POST_DEBATE", "1")
        captured: dict[str, PostDebateConfig] = {}
        coordinator = MagicMock()
        coordinator.run = MagicMock(return_value=None)

        def _build_coordinator(*, config, settlement_tracker=None, knowledge_mound=None):
            captured["config"] = config
            return coordinator

        with patch(
            "aragora.debate.post_debate_coordinator.PostDebateCoordinator",
            side_effect=_build_coordinator,
        ):
            await handle_debate_completion(mock_arena, execution_state)

        assert captured["config"].execution_mode == ExecutionMode.INTERACTIVE
        assert captured["config"].auto_execute_plan is True

    @pytest.mark.asyncio
    async def test_records_debate_analytics_agent_activity(self, mock_arena, execution_state):
        """Debate completion persists debate and per-agent telemetry into analytics."""
        execution_state.ctx.result.rounds_used = 3
        execution_state.ctx.result.duration_seconds = 9.5
        execution_state.ctx.result.total_cost_usd = 0.12
        execution_state.ctx.result.consensus_reached = True
        execution_state.ctx.result.per_agent_cost = {"agent-0": 0.07, "agent-1": 0.05}
        execution_state.ctx.result.messages = [MagicMock(), MagicMock(), MagicMock()]
        execution_state.ctx.result.votes = [MagicMock()]

        for idx, agent in enumerate(mock_arena.agents):
            agent.name = f"agent-{idx}"
            agent.provider = "anthropic"
            agent.model = "claude-sonnet-4"
            agent.total_tokens_in = 0
            agent.total_tokens_out = 0

        mock_arena.agents[0].total_tokens_in = 180
        mock_arena.agents[0].total_tokens_out = 40
        mock_arena.agents[1].total_tokens_in = 120
        mock_arena.agents[1].total_tokens_out = 20

        analytics = MagicMock()
        analytics.record_debate = AsyncMock()
        analytics.record_agent_activity = AsyncMock()
        meter = MagicMock()
        meter.flush_all = AsyncMock()
        governor = SimpleNamespace(
            agent_metrics={
                "agent-0": SimpleNamespace(avg_latency_ms=111.0),
                "agent-1": SimpleNamespace(avg_latency_ms=222.0),
            }
        )

        with (
            patch(
                "aragora.billing.usage_metering_integration.record_debate_tokens",
                new=AsyncMock(return_value={}),
            ),
            patch("aragora.services.usage_metering.get_usage_meter", return_value=meter),
            patch(
                "aragora.analytics.debate_analytics.get_debate_analytics", return_value=analytics
            ),
            patch(
                "aragora.debate.orchestrator_runner.get_complexity_governor", return_value=governor
            ),
        ):
            await handle_debate_completion(mock_arena, execution_state)

        analytics.record_debate.assert_awaited_once()
        debate_kwargs = analytics.record_debate.await_args.kwargs
        assert debate_kwargs["debate_id"] == execution_state.debate_id
        assert debate_kwargs["rounds"] == 3
        assert debate_kwargs["duration_seconds"] == 9.5
        assert debate_kwargs["total_messages"] == 3
        assert debate_kwargs["total_votes"] == 1

        agent_calls = analytics.record_agent_activity.await_args_list
        assert len(agent_calls) == 2
        first_call = agent_calls[0].kwargs
        second_call = agent_calls[1].kwargs
        assert first_call["agent_name"] == "agent-0"
        assert first_call["response_time_ms"] == 111.0
        assert first_call["tokens_in"] == 180
        assert first_call["tokens_out"] == 40
        assert str(first_call["cost"]) == "0.07"
        assert second_call["agent_name"] == "agent-1"
        assert second_call["response_time_ms"] == 222.0
        assert str(second_call["cost"]) == "0.05"


# =============================================================================
# Tests for cleanup_debate_resources
# =============================================================================


class TestCleanupDebateResources:
    """Tests for cleanup_debate_resources function."""

    @pytest.mark.asyncio
    async def test_cleans_up_checkpoints_on_success(self, mock_arena, execution_state):
        """Test that checkpoints are cleaned up on successful completion."""
        execution_state.debate_status = "completed"
        mock_arena.protocol.checkpoint_cleanup_on_success = True
        mock_arena.protocol.checkpoint_keep_on_success = 2
        mock_arena.cleanup_checkpoints.return_value = 5

        await cleanup_debate_resources(mock_arena, execution_state)

        mock_arena.cleanup_checkpoints.assert_called_once_with(
            execution_state.debate_id, keep_latest=2
        )

    @pytest.mark.asyncio
    async def test_skips_checkpoint_cleanup_on_failure(self, mock_arena, execution_state):
        """Test that checkpoint cleanup is skipped on failure."""
        execution_state.debate_status = "error"

        await cleanup_debate_resources(mock_arena, execution_state)

        mock_arena.cleanup_checkpoints.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_checkpoint_cleanup_when_disabled(self, mock_arena, execution_state):
        """Test that checkpoint cleanup is skipped when disabled."""
        execution_state.debate_status = "completed"
        mock_arena.protocol.checkpoint_cleanup_on_success = False

        await cleanup_debate_resources(mock_arena, execution_state)

        mock_arena.cleanup_checkpoints.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_checkpoint_cleanup_error(self, mock_arena, execution_state):
        """Test that checkpoint cleanup errors are handled gracefully."""
        execution_state.debate_status = "completed"
        mock_arena.cleanup_checkpoints.side_effect = RuntimeError("Cleanup failed")

        # Should not raise
        result = await cleanup_debate_resources(mock_arena, execution_state)

        assert result is not None

    @pytest.mark.asyncio
    async def test_cleans_up_convergence_cache(self, mock_arena, execution_state):
        """Test that convergence cache is cleaned up."""
        await cleanup_debate_resources(mock_arena, execution_state)

        mock_arena._cleanup_convergence_cache.assert_called_once()

    @pytest.mark.asyncio
    async def test_tears_down_agent_channels(self, mock_arena, execution_state):
        """Test that agent channels are torn down."""
        await cleanup_debate_resources(mock_arena, execution_state)

        mock_arena._teardown_agent_channels.assert_called_once()

    @pytest.mark.asyncio
    async def test_finalizes_result(self, mock_arena, execution_state):
        """Test that result is finalized."""
        await cleanup_debate_resources(mock_arena, execution_state)

        execution_state.ctx.finalize_result.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_finalized_result(self, mock_arena, execution_state, mock_debate_result):
        """Test that finalized result is returned."""
        execution_state.ctx.finalize_result.return_value = mock_debate_result

        result = await cleanup_debate_resources(mock_arena, execution_state)

        assert result is mock_debate_result

    @pytest.mark.asyncio
    async def test_translates_conclusions_when_enabled(
        self, mock_arena, execution_state, mock_debate_result
    ):
        """Test that conclusions are translated when translation is enabled."""
        mock_arena.protocol.enable_translation = True
        execution_state.ctx.finalize_result.return_value = mock_debate_result

        await cleanup_debate_resources(mock_arena, execution_state)

        mock_arena._translate_conclusions.assert_called_once_with(mock_debate_result)

    @pytest.mark.asyncio
    async def test_skips_translation_when_disabled(
        self, mock_arena, execution_state, mock_debate_result
    ):
        """Test that translation is skipped when disabled."""
        mock_arena.protocol.enable_translation = False
        execution_state.ctx.finalize_result.return_value = mock_debate_result

        await cleanup_debate_resources(mock_arena, execution_state)

        mock_arena._translate_conclusions.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_translation_when_result_is_none(self, mock_arena, execution_state):
        """Test that translation is skipped when result is None."""
        mock_arena.protocol.enable_translation = True
        execution_state.ctx.finalize_result.return_value = None

        await cleanup_debate_resources(mock_arena, execution_state)

        mock_arena._translate_conclusions.assert_not_called()


# =============================================================================
# Tests for Error Handling and Recovery
# =============================================================================


class TestErrorHandlingAndRecovery:
    """Tests for error handling and recovery scenarios."""

    @pytest.mark.asyncio
    async def test_initialize_handles_km_init_error(self, mock_arena):
        """Test that KM initialization errors do not block the debate."""
        mock_arena._init_km_context.side_effect = ConnectionError("KM unavailable")

        state = await initialize_debate_context(mock_arena, "corr-123")

        km_metadata = state.ctx._knowledge_management_metadata
        assert km_metadata["context_handoff"]["status"] == "failed"
        assert km_metadata["context_handoff"]["error_type"] == "ConnectionError"
        assert km_metadata["context_handoff"]["error"] == "KM unavailable"

    @pytest.mark.asyncio
    async def test_initialize_handles_channel_setup_error(self, mock_arena):
        """Test that channel setup errors are handled."""
        mock_arena._setup_agent_channels.side_effect = RuntimeError("Channel error")

        # The function should propagate this error since it's critical
        with pytest.raises(RuntimeError):
            await initialize_debate_context(mock_arena, "corr-123")

    @pytest.mark.asyncio
    async def test_completion_continues_after_extension_error(self, mock_arena, execution_state):
        """Test that completion continues after extension error."""
        mock_arena.extensions.on_debate_complete.side_effect = ValueError("Ext error")

        # Extension errors should propagate
        with pytest.raises(ValueError):
            await handle_debate_completion(mock_arena, execution_state)

    @pytest.mark.asyncio
    async def test_cleanup_continues_after_individual_errors(self, mock_arena, execution_state):
        """Test that cleanup continues even if individual operations fail."""
        execution_state.debate_status = "completed"
        mock_arena.cleanup_checkpoints.side_effect = OSError("Disk error")

        # Should not raise and should still finalize result
        result = await cleanup_debate_resources(mock_arena, execution_state)

        assert result is not None
        mock_arena._cleanup_convergence_cache.assert_called_once()
        mock_arena._teardown_agent_channels.assert_called_once()

    @pytest.mark.asyncio
    async def test_metrics_recording_with_timeout_status(
        self, mock_arena, execution_state, mock_span
    ):
        """Test metrics recording with timeout status."""
        execution_state.debate_status = "timeout"
        execution_state.ctx.result.consensus_reached = False
        execution_state.ctx.result.confidence = 0.3

        with (
            patch("aragora.server.metrics.ACTIVE_DEBATES"),
            patch("aragora.debate.orchestrator_runner.add_span_attributes"),
            patch("aragora.server.metrics.track_debate_outcome") as mock_track,
        ):
            record_debate_metrics(mock_arena, execution_state, mock_span)

            mock_track.assert_called_once()
            call_kwargs = mock_track.call_args[1]
            assert call_kwargs["status"] == "timeout"

    @pytest.mark.asyncio
    async def test_full_workflow_with_errors(self, mock_arena):
        """Test a realistic workflow with recoverable errors."""
        # Set up for partial success scenario
        mock_arena.protocol.enable_hook_tracking = True
        mock_arena._create_pending_debate_bead.return_value = "bead-test"
        mock_arena._init_hook_tracking.return_value = {"agent-0": "entry-0"}

        # Initialize
        state = await initialize_debate_context(mock_arena, "test-corr")
        assert state.debate_id is not None

        # Setup infrastructure
        await setup_debate_infrastructure(mock_arena, state)
        assert state.gupp_bead_id == "bead-test"
        assert state.debate_start_time > 0

        # Simulate phase execution with timeout
        mock_span = MagicMock()
        state.ctx.partial_messages = [MagicMock()]
        state.ctx.partial_rounds = 1
        mock_arena.phase_executor.execute.side_effect = asyncio.TimeoutError()

        await execute_debate_phases(mock_arena, state, mock_span)
        assert state.debate_status == "blocked"

        # Handle completion with KM error (should be handled)
        mock_arena._ingest_debate_outcome.side_effect = ConnectionError("KM down")
        await handle_debate_completion(mock_arena, state)

        # Cleanup
        result = await cleanup_debate_resources(mock_arena, state)
        assert result is not None


class TestServedModelsReachTheResultMetadata:
    """``handle_debate_completion`` must attach served_models end to end.

    ``collect_served_models`` was unit-tested, but nothing exercised the
    attach block that puts its output on ``ctx.result.metadata`` -- the only
    path by which a receipt learns that a server-side fallback answered with
    a model other than the one the debate pinned (2026-09-05 merge-gate
    addendum on #9989).
    """

    @staticmethod
    def _agent(name: str, requested: str, served: str | None):
        """A fake agent shaped like the Anthropic one: the property the
        collector reads AND the get_metadata() surface callers see."""
        agent = MagicMock()
        agent.name = name
        agent.model = requested
        agent.last_served_model = served
        agent.get_metadata = MagicMock(return_value={"served_model": served})
        return agent

    @pytest.mark.asyncio
    async def test_attaches_served_models_for_a_swapped_agent(self, mock_arena, execution_state):
        swapped = self._agent("claude-1", "claude-fable-5-1", "claude-opus-4-8")
        as_asked = self._agent("claude-2", "claude-fable-5-1", None)
        mock_arena.agents = [swapped, as_asked]
        execution_state.ctx.result.metadata = {}

        await handle_debate_completion(mock_arena, execution_state)

        assert execution_state.ctx.result.metadata["served_models"] == {
            "claude-1": {"requested": "claude-fable-5-1", "served": ["claude-opus-4-8"]}
        }
        # The agent's own metadata surface agrees with what was attached.
        assert swapped.get_metadata()["served_model"] == "claude-opus-4-8"

    @pytest.mark.asyncio
    async def test_no_key_when_every_agent_answered_as_asked(self, mock_arena, execution_state):
        """An empty dict must not be written: absence means 'as asked'."""
        mock_arena.agents = [self._agent("claude-1", "claude-fable-5-1", None)]
        execution_state.ctx.result.metadata = {}

        await handle_debate_completion(mock_arena, execution_state)

        assert "served_models" not in execution_state.ctx.result.metadata

    @pytest.mark.asyncio
    async def test_creates_metadata_when_the_result_has_none(self, mock_arena, execution_state):
        mock_arena.agents = [self._agent("claude-1", "claude-fable-5-1", "claude-opus-4-8")]
        execution_state.ctx.result.metadata = None

        await handle_debate_completion(mock_arena, execution_state)

        assert execution_state.ctx.result.metadata["served_models"] == {
            "claude-1": {"requested": "claude-fable-5-1", "served": ["claude-opus-4-8"]}
        }

    @pytest.mark.asyncio
    async def test_existing_metadata_is_preserved(self, mock_arena, execution_state):
        mock_arena.agents = [self._agent("claude-1", "claude-fable-5-1", "claude-opus-4-8")]
        execution_state.ctx.result.metadata = {"pre_existing": "keep me"}

        await handle_debate_completion(mock_arena, execution_state)

        assert execution_state.ctx.result.metadata["pre_existing"] == "keep me"
        assert "served_models" in execution_state.ctx.result.metadata


class TestUnpinnedCLIAgentsAreNotAttributedAModel:
    """A CLI that never received ``self.model`` must not have its output
    attributed to it (wave-6 ruling, agents, on #9989).

    ``qwen-cli``, ``deepseek-cli`` and the opt-in ``kimi-cli`` each carry a
    native model code the CLI is never told about -- a retired spelling with
    no native successor for qwen, an unverifiable flag for the two CLIs that
    are not installed here (see
    ``aragora.agents.cli_agents.CLIAgent.SENDS_MODEL_ON_WIRE``). They keep
    the requested pin
    (pricing, fallback and the registry all need it) but declare
    ``metadata["model_pinned_on_wire"] = False``, and the collector then
    reports the served model as unknown.
    """

    @staticmethod
    def _cli_agent(registry_name: str, attr: str, model: str):
        import os
        from unittest.mock import patch as _patch

        with _patch.dict(os.environ, {"ARAGORA_ENABLE_KIMI_CLI": "1"}):
            import aragora.agents.cli_agents as cli_agents

            return getattr(cli_agents, attr)(name=registry_name, model=model)

    @pytest.mark.parametrize(
        ("registry_name", "attr", "model"),
        [
            ("qwen-cli", "QwenCLIAgent", "qwen3-coder"),
            ("deepseek-cli", "DeepseekCLIAgent", "deepseek-v4-pro"),
            ("kimi-cli", "KimiCLIAgent", "kimi-k2"),
        ],
    )
    def test_agent_records_that_the_pin_never_reached_the_wire(
        self, registry_name: str, attr: str, model: str
    ) -> None:
        from aragora.debate.orchestrator_runner import (
            UNKNOWN_CLI_DEFAULT_MODEL,
            collect_served_models,
        )

        agent = self._cli_agent(registry_name, attr, model)
        # The requested pin is still carried -- only the CLAIM about the wire
        # changes.
        assert agent.model == model
        assert agent.metadata["model_pinned_on_wire"] is False
        assert collect_served_models([agent]) == {
            registry_name: {"requested": model, "served": [UNKNOWN_CLI_DEFAULT_MODEL]}
        }
        assert UNKNOWN_CLI_DEFAULT_MODEL != model

    def test_a_cli_that_does_pin_its_model_is_untouched(self) -> None:
        """The four CLIs wave 5 pinned still report nothing: their model DID
        reach the command line, so there is no discrepancy to record."""
        from aragora.debate.orchestrator_runner import collect_served_models

        agent = self._cli_agent("codex", "CodexAgent", "gpt-6-astra")
        assert agent.metadata["model_pinned_on_wire"] is True
        assert collect_served_models([agent]) == {}

    @pytest.mark.asyncio
    async def test_the_unknown_marker_reaches_the_result_metadata(
        self, mock_arena, execution_state
    ) -> None:
        from aragora.debate.orchestrator_runner import UNKNOWN_CLI_DEFAULT_MODEL

        mock_arena.agents = [self._cli_agent("qwen-cli", "QwenCLIAgent", "qwen3-coder")]
        execution_state.ctx.result.metadata = {}

        await handle_debate_completion(mock_arena, execution_state)

        assert execution_state.ctx.result.metadata["served_models"] == {
            "qwen-cli": {"requested": "qwen3-coder", "served": [UNKNOWN_CLI_DEFAULT_MODEL]}
        }
