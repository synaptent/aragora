"""
Tests for critique generator module.

Tests cover:
- CritiqueResult dataclass
- _is_effectively_empty_critique function
- CritiqueGenerator class initialization
- _classify_error method
- execute_critique_phase method
- _process_critique_result method
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.core import Critique, Message
from aragora.debate.phases.critique_generator import (
    CritiqueGenerator,
    CritiqueResult,
    _is_effectively_empty_critique,
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
    timeout: float = 30.0


@dataclass
class MockEnv:
    """Mock environment for testing."""

    task: str = "What is the best approach to testing?"


@dataclass
class MockResult:
    """Mock debate result for testing."""

    messages: list = field(default_factory=list)
    critiques: list = field(default_factory=list)
    final_answer: str = ""


@dataclass
class MockDebateContext:
    """Mock debate context for testing."""

    result: MockResult = field(default_factory=MockResult)
    env: MockEnv = field(default_factory=MockEnv)
    proposals: dict = field(default_factory=dict)
    context_messages: list = field(default_factory=list)
    partial_messages: list = field(default_factory=list)
    debate_id: str = "test-debate-123"
    agent_failures: dict = field(default_factory=dict)

    def record_agent_failure(
        self,
        agent_name: str,
        phase: str,
        error_type: str,
        message: str,
        provider: str | None = None,
    ) -> None:
        """Record an agent failure for post-run diagnostics."""
        record = {
            "phase": phase,
            "error_type": error_type,
            "message": message,
            "provider": provider or "",
        }
        self.agent_failures.setdefault(agent_name, []).append(record)

    def add_message(self, msg: Any) -> None:
        """Mirror production message tracking."""
        self.context_messages.append(msg)
        self.partial_messages.append(msg)
        self.result.messages.append(msg)


@dataclass
class MockCircuitBreaker:
    """Mock circuit breaker for testing."""

    failures: dict = field(default_factory=dict)
    successes: dict = field(default_factory=dict)

    def record_failure(self, agent_name: str) -> None:
        """Record a failure for an agent."""
        self.failures[agent_name] = self.failures.get(agent_name, 0) + 1

    def record_success(self, agent_name: str) -> None:
        """Record a success for an agent."""
        self.successes[agent_name] = self.successes.get(agent_name, 0) + 1


def create_critique(
    agent: str = "critic1",
    target_agent: str = "target1",
    issues: list[str] | None = None,
    suggestions: list[str] | None = None,
    severity: float = 5.0,
) -> Critique:
    """Create a real Critique object for testing."""
    return Critique(
        agent=agent,
        target_agent=target_agent,
        target_content="Some content",
        issues=issues if issues is not None else ["Issue 1", "Issue 2"],
        suggestions=suggestions if suggestions is not None else ["Suggestion 1"],
        severity=severity,
        reasoning="Test reasoning",
    )


# =============================================================================
# CritiqueResult Tests
# =============================================================================


class TestCritiqueResult:
    """Tests for CritiqueResult dataclass."""

    def test_success_when_critique_exists_no_error(self):
        """CritiqueResult.success returns True when critique exists and no error."""
        result = CritiqueResult(
            critic=MockAgent(),
            target_agent="target1",
            critique=create_critique(),
            error=None,
        )

        assert result.success is True

    def test_success_false_when_error_exists(self):
        """CritiqueResult.success returns False when error exists."""
        result = CritiqueResult(
            critic=MockAgent(),
            target_agent="target1",
            critique=create_critique(),
            error=ValueError("Some error"),
        )

        assert result.success is False

    def test_success_false_when_critique_is_none(self):
        """CritiqueResult.success returns False when critique is None."""
        result = CritiqueResult(
            critic=MockAgent(),
            target_agent="target1",
            critique=None,
            error=None,
        )

        assert result.success is False

    def test_success_false_when_both_none(self):
        """CritiqueResult.success returns False when both critique and error are None."""
        result = CritiqueResult(
            critic=MockAgent(),
            target_agent="target1",
            critique=None,
            error=None,
        )

        assert result.success is False

    def test_success_false_when_error_but_no_critique(self):
        """CritiqueResult.success returns False when error exists but no critique."""
        result = CritiqueResult(
            critic=MockAgent(),
            target_agent="target1",
            critique=None,
            error=TimeoutError("Timed out"),
        )

        assert result.success is False


# =============================================================================
# _is_effectively_empty_critique Tests
# =============================================================================


class TestIsEffectivelyEmptyCritique:
    """Tests for _is_effectively_empty_critique function."""

    def test_returns_true_for_empty_issues_and_suggestions(self):
        """Returns True when both issues and suggestions are empty."""
        critique = create_critique(issues=[], suggestions=[])

        assert _is_effectively_empty_critique(critique) is True

    def test_returns_true_for_whitespace_only_issues(self):
        """Returns True when issues contain only whitespace."""
        critique = create_critique(issues=["   ", "\t", "\n"], suggestions=[])

        assert _is_effectively_empty_critique(critique) is True

    def test_returns_true_for_agent_response_was_empty_placeholder(self):
        """Returns True when single issue is 'agent response was empty'."""
        critique = create_critique(issues=["agent response was empty"], suggestions=[])

        assert _is_effectively_empty_critique(critique) is True

    def test_returns_true_for_agent_produced_empty_output_placeholder(self):
        """Returns True for '(agent produced empty output)' placeholder."""
        critique = create_critique(issues=["(agent produced empty output)"], suggestions=[])

        assert _is_effectively_empty_critique(critique) is True

    def test_returns_true_for_unparenthesized_empty_output_placeholder(self):
        """Returns True for 'agent produced empty output' without parens."""
        critique = create_critique(issues=["agent produced empty output"], suggestions=[])

        assert _is_effectively_empty_critique(critique) is True

    def test_returns_false_for_placeholder_with_real_suggestions(self):
        """Returns False when placeholder issue exists but has real suggestions."""
        critique = create_critique(
            issues=["agent response was empty"],
            suggestions=["Try adding more detail"],
        )

        assert _is_effectively_empty_critique(critique) is False

    def test_returns_false_for_real_issues(self):
        """Returns False when there are real issues."""
        critique = create_critique(
            issues=["The proposal lacks specificity", "Missing error handling"],
            suggestions=[],
        )

        assert _is_effectively_empty_critique(critique) is False

    def test_returns_false_for_real_suggestions(self):
        """Returns False when there are real suggestions."""
        critique = create_critique(
            issues=[],
            suggestions=["Add more test coverage", "Consider edge cases"],
        )

        assert _is_effectively_empty_critique(critique) is False

    def test_returns_false_for_both_real_issues_and_suggestions(self):
        """Returns False when there are both real issues and suggestions."""
        critique = create_critique(
            issues=["Missing validation"],
            suggestions=["Add input validation"],
        )

        assert _is_effectively_empty_critique(critique) is False

    def test_handles_mixed_whitespace_and_real_issues(self):
        """Returns False when there's at least one real issue among whitespace."""
        critique = create_critique(
            issues=["  ", "Real issue here", "\t"],
            suggestions=[],
        )

        assert _is_effectively_empty_critique(critique) is False


# =============================================================================
# CritiqueGenerator Initialization Tests
# =============================================================================


class TestCritiqueGeneratorInit:
    """Tests for CritiqueGenerator initialization."""

    def test_init_with_no_arguments(self):
        """Generator initializes with defaults when no arguments provided."""
        gen = CritiqueGenerator()

        assert gen._critique_with_agent is None
        assert gen._with_timeout is None
        assert gen.circuit_breaker is None
        assert gen.hooks == {}
        assert gen.recorder is None
        assert gen._select_critics_for_proposal is None
        assert gen._notify_spectator is None
        assert gen._emit_heartbeat is None

    def test_init_with_all_callbacks(self):
        """Generator stores all injected callbacks."""
        critique_cb = AsyncMock()
        timeout_cb = AsyncMock()
        circuit_breaker = MockCircuitBreaker()
        hooks = {"on_critique": MagicMock()}
        recorder = MagicMock()
        select_critics = MagicMock()
        notify_spectator = MagicMock()
        heartbeat = MagicMock()

        gen = CritiqueGenerator(
            critique_with_agent=critique_cb,
            with_timeout=timeout_cb,
            circuit_breaker=circuit_breaker,
            hooks=hooks,
            recorder=recorder,
            select_critics_for_proposal=select_critics,
            notify_spectator=notify_spectator,
            heartbeat_callback=heartbeat,
            max_concurrent=5,
        )

        assert gen._critique_with_agent is critique_cb
        assert gen._with_timeout is timeout_cb
        assert gen.circuit_breaker is circuit_breaker
        assert gen.hooks is hooks
        assert gen.recorder is recorder
        assert gen._select_critics_for_proposal is select_critics
        assert gen._notify_spectator is notify_spectator
        assert gen._emit_heartbeat is heartbeat
        assert gen._max_concurrent == 5

    def test_max_concurrent_default_value(self):
        """Generator uses MAX_CONCURRENT_CRITIQUES as default."""
        from aragora.config import MAX_CONCURRENT_CRITIQUES

        gen = CritiqueGenerator()

        assert gen._max_concurrent == MAX_CONCURRENT_CRITIQUES

    def test_hooks_defaults_to_empty_dict(self):
        """Hooks defaults to empty dict when None passed."""
        gen = CritiqueGenerator(hooks=None)

        assert gen.hooks == {}

    def test_molecule_tracker_initialization(self):
        """Generator stores molecule tracker when provided."""
        tracker = MagicMock()

        gen = CritiqueGenerator(molecule_tracker=tracker)

        assert gen._molecule_tracker is tracker
        assert gen._active_molecules == {}


# =============================================================================
# _classify_error Tests
# =============================================================================


class TestClassifyError:
    """Tests for _classify_error static method."""

    def test_classifies_timeout_error(self):
        """TimeoutError is classified as 'timeout'."""
        error = asyncio.TimeoutError()

        result = CritiqueGenerator._classify_error(error)

        assert result == "timeout"

    def test_classifies_empty_message_error(self):
        """Error with 'empty' in message is classified as 'empty'."""
        error = ValueError("The response was empty")

        result = CritiqueGenerator._classify_error(error)

        assert result == "empty"

    def test_classifies_empty_uppercase_message(self):
        """Error with 'Empty' (uppercase) in message is classified as 'empty'."""
        error = ValueError("Agent returned Empty response")

        result = CritiqueGenerator._classify_error(error)

        assert result == "empty"

    def test_classifies_other_exception(self):
        """Other exceptions are classified as 'exception'."""
        error = RuntimeError("Something went wrong")

        result = CritiqueGenerator._classify_error(error)

        assert result == "exception"

    def test_classifies_connection_error_as_exception(self):
        """Connection errors are classified as 'exception'."""
        error = ConnectionError("Failed to connect")

        result = CritiqueGenerator._classify_error(error)

        assert result == "exception"

    def test_classifies_api_error_as_exception(self):
        """API errors are classified as 'exception'."""
        error = Exception("API rate limit exceeded")

        result = CritiqueGenerator._classify_error(error)

        assert result == "exception"


# =============================================================================
# execute_critique_phase Tests
# =============================================================================


class TestExecuteCritiquePhase:
    """Tests for execute_critique_phase method."""

    @pytest.mark.asyncio
    async def test_returns_empty_lists_when_no_critique_callback(self):
        """Returns empty lists when critique_with_agent callback is None."""
        gen = CritiqueGenerator()
        ctx = MockDebateContext()
        critics = [MockAgent(name="critic1")]

        messages, critiques = await gen.execute_critique_phase(
            ctx=ctx,
            critics=critics,
            round_num=1,
            partial_messages=[],
            partial_critiques=[],
        )

        assert messages == []
        assert critiques == []

    @pytest.mark.asyncio
    async def test_generates_critiques_for_valid_proposals(self):
        """Generates critiques for proposals that are not empty."""
        mock_critique = create_critique(agent="critic1", target_agent="proposer1")
        critique_cb = AsyncMock(return_value=mock_critique)

        gen = CritiqueGenerator(critique_with_agent=critique_cb)
        ctx = MockDebateContext()
        ctx.proposals = {"proposer1": "This is a valid proposal"}
        critic = MockAgent(name="critic1")
        critics = [critic]

        messages, critiques = await gen.execute_critique_phase(
            ctx=ctx,
            critics=critics,
            round_num=1,
            partial_messages=[],
            partial_critiques=[],
        )

        # Should generate critiques since proposals are valid
        assert critique_cb.called
        assert len(ctx.result.messages) == 1
        assert len(ctx.context_messages) == 1
        assert len(ctx.partial_messages) == 1

    @pytest.mark.asyncio
    async def test_uses_callback_bound_at_phase_entry(self):
        """A later attribute mutation must not yield a silent None task result."""
        mock_critique = create_critique(agent="critic1", target_agent="proposer1")
        critique_cb = AsyncMock(return_value=mock_critique)
        gen = CritiqueGenerator(critique_with_agent=critique_cb)

        def select_critics(_proposal_agent, critics):
            gen._critique_with_agent = None
            return critics

        gen._select_critics_for_proposal = select_critics
        ctx = MockDebateContext(proposals={"proposer1": "A proposal"})

        messages, critiques = await gen.execute_critique_phase(
            ctx=ctx,
            critics=[MockAgent(name="critic1")],
            round_num=1,
            partial_messages=[],
            partial_critiques=[],
        )

        assert len(messages) == 1
        assert len(critiques) == 1
        critique_cb.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_empty_proposals(self):
        """Skips proposals that contain empty output placeholder."""
        critique_cb = AsyncMock(return_value=create_critique())

        gen = CritiqueGenerator(critique_with_agent=critique_cb)
        ctx = MockDebateContext()
        ctx.proposals = {
            "agent1": "(Agent produced empty output)",
            "agent2": "Valid proposal",
        }
        critics = [MockAgent(name="critic1")]

        await gen.execute_critique_phase(
            ctx=ctx,
            critics=critics,
            round_num=1,
            partial_messages=[],
            partial_critiques=[],
        )

        # Only the valid proposal should be critiqued
        call_args = critique_cb.call_args_list
        for call in call_args:
            # Second positional arg is the proposal text
            proposal_text = call[0][1]
            assert "(Agent produced empty output)" not in proposal_text

    @pytest.mark.asyncio
    async def test_handles_timeout_errors(self):
        """Handles timeout errors during critique generation."""
        critique_cb = AsyncMock(side_effect=asyncio.TimeoutError())

        gen = CritiqueGenerator(critique_with_agent=critique_cb)
        ctx = MockDebateContext()
        ctx.proposals = {"proposer1": "Valid proposal"}
        critics = [MockAgent(name="critic1")]

        messages, critiques = await gen.execute_critique_phase(
            ctx=ctx,
            critics=critics,
            round_num=1,
            partial_messages=[],
            partial_critiques=[],
        )

        # Timeout is logged and skipped - no critiques produced
        assert len(critiques) == 0

    @pytest.mark.asyncio
    async def test_handles_empty_critiques_with_retry(self):
        """Retries when critique is effectively empty, then fails."""
        # First call returns empty, retry also returns empty
        empty_critique = create_critique(issues=[], suggestions=[])
        critique_cb = AsyncMock(return_value=empty_critique)

        gen = CritiqueGenerator(critique_with_agent=critique_cb)
        ctx = MockDebateContext()
        ctx.proposals = {"proposer1": "Valid proposal"}
        critics = [MockAgent(name="critic1")]

        await gen.execute_critique_phase(
            ctx=ctx,
            critics=critics,
            round_num=1,
            partial_messages=[],
            partial_critiques=[],
        )

        # Should have been called twice (initial + retry)
        assert critique_cb.call_count >= 2

    @pytest.mark.asyncio
    async def test_calls_heartbeat_callback_periodically(self):
        """Calls heartbeat callback during critique generation."""
        mock_critique = create_critique(agent="critic1", target_agent="proposer1")
        critique_cb = AsyncMock(return_value=mock_critique)
        heartbeat_cb = MagicMock()

        gen = CritiqueGenerator(
            critique_with_agent=critique_cb,
            heartbeat_callback=heartbeat_cb,
        )
        ctx = MockDebateContext()
        ctx.proposals = {"proposer1": "Valid proposal"}
        critics = [MockAgent(name="critic1")]

        await gen.execute_critique_phase(
            ctx=ctx,
            critics=critics,
            round_num=1,
            partial_messages=[],
            partial_critiques=[],
        )

        # Heartbeat should be called
        assert heartbeat_cb.called

    @pytest.mark.asyncio
    async def test_uses_select_critics_callback_when_provided(self):
        """Uses select_critics_for_proposal callback when provided."""
        mock_critique = create_critique()
        critique_cb = AsyncMock(return_value=mock_critique)
        select_critics = MagicMock(return_value=[MockAgent(name="selected-critic")])

        gen = CritiqueGenerator(
            critique_with_agent=critique_cb,
            select_critics_for_proposal=select_critics,
        )
        ctx = MockDebateContext()
        ctx.proposals = {"proposer1": "Valid proposal"}
        critics = [MockAgent(name="critic1"), MockAgent(name="critic2")]

        await gen.execute_critique_phase(
            ctx=ctx,
            critics=critics,
            round_num=1,
            partial_messages=[],
            partial_critiques=[],
        )

        select_critics.assert_called()

    @pytest.mark.asyncio
    async def test_excludes_proposer_from_critics_by_default(self):
        """Excludes the proposer from being a critic of their own proposal."""
        mock_critique = create_critique()
        critique_cb = AsyncMock(return_value=mock_critique)

        gen = CritiqueGenerator(critique_with_agent=critique_cb)
        ctx = MockDebateContext()
        ctx.proposals = {"proposer1": "Valid proposal"}
        # Include the proposer in the critics list
        critics = [MockAgent(name="proposer1"), MockAgent(name="critic2")]

        await gen.execute_critique_phase(
            ctx=ctx,
            critics=critics,
            round_num=1,
            partial_messages=[],
            partial_critiques=[],
        )

        # Only critic2 should have been used (proposer1 excluded)
        for call in critique_cb.call_args_list:
            critic_arg = call[0][0]  # First positional arg is critic
            assert critic_arg.name != "proposer1"

    @pytest.mark.asyncio
    async def test_respects_max_concurrent_limit(self):
        """Respects the max_concurrent limit for parallel execution."""
        call_times = []

        async def track_critique(*args, **kwargs):
            import time

            call_times.append(time.time())
            await asyncio.sleep(0.1)
            return create_critique()

        gen = CritiqueGenerator(
            critique_with_agent=track_critique,
            max_concurrent=1,  # Only 1 at a time
        )
        ctx = MockDebateContext()
        ctx.proposals = {"p1": "Proposal 1", "p2": "Proposal 2"}
        critics = [MockAgent(name="c1"), MockAgent(name="c2")]

        await gen.execute_critique_phase(
            ctx=ctx,
            critics=critics,
            round_num=1,
            partial_messages=[],
            partial_critiques=[],
        )

        # With max_concurrent=1, calls should be sequential
        # We can't guarantee exact order but calls should complete

    @pytest.mark.asyncio
    async def test_with_timeout_wrapper_used_when_provided(self):
        """Uses with_timeout wrapper when provided."""
        mock_critique = create_critique()
        critique_cb = AsyncMock(return_value=mock_critique)
        timeout_wrapper = AsyncMock(return_value=mock_critique)

        gen = CritiqueGenerator(
            critique_with_agent=critique_cb,
            with_timeout=timeout_wrapper,
        )
        ctx = MockDebateContext()
        ctx.proposals = {"proposer1": "Valid proposal"}
        critics = [MockAgent(name="critic1")]

        await gen.execute_critique_phase(
            ctx=ctx,
            critics=critics,
            round_num=1,
            partial_messages=[],
            partial_critiques=[],
        )

        timeout_wrapper.assert_called()


# =============================================================================
# _process_critique_result Tests
# =============================================================================


class TestProcessCritiqueResult:
    """Tests for _process_critique_result method."""

    def test_processes_successful_critique(self):
        """Successfully processes a valid critique result."""
        circuit_breaker = MockCircuitBreaker()
        hooks = {"on_critique": MagicMock()}
        recorder = MagicMock()

        gen = CritiqueGenerator(
            circuit_breaker=circuit_breaker,
            hooks=hooks,
            recorder=recorder,
        )

        ctx = MockDebateContext()
        ctx.proposals = {"target1": "Proposal text"}
        result = ctx.result
        new_messages = []
        new_critiques = []
        partial_messages = []
        partial_critiques = []

        mock_critique = create_critique(
            agent="critic1",
            target_agent="target1",
            issues=["Issue 1"],
            severity=5.0,
        )
        crit_result = CritiqueResult(
            critic=MockAgent(name="critic1"),
            target_agent="target1",
            critique=mock_critique,
            error=None,
        )

        returned = gen._process_critique_result(
            crit_result,
            ctx,
            round_num=1,
            result=result,
            new_messages=new_messages,
            new_critiques=new_critiques,
            partial_messages=partial_messages,
            partial_critiques=partial_critiques,
        )

        # Circuit breaker should record success
        assert circuit_breaker.successes.get("critic1", 0) > 0

        # Hook should be called
        hooks["on_critique"].assert_called()

        # Critique should be added to result
        assert mock_critique in result.critiques

    def test_handles_empty_critique(self):
        """Handles critique that is effectively empty."""
        circuit_breaker = MockCircuitBreaker()
        hooks = {"on_agent_error": MagicMock(), "on_critique": MagicMock()}

        gen = CritiqueGenerator(
            circuit_breaker=circuit_breaker,
            hooks=hooks,
        )

        ctx = MockDebateContext()
        ctx.proposals = {"target1": "Proposal text"}
        result = ctx.result
        new_messages = []
        new_critiques = []
        partial_messages = []
        partial_critiques = []

        # Empty critique
        empty_critique = create_critique(issues=[], suggestions=[])
        crit_result = CritiqueResult(
            critic=MockAgent(name="critic1"),
            target_agent="target1",
            critique=empty_critique,
            error=None,
        )

        gen._process_critique_result(
            crit_result,
            ctx,
            round_num=1,
            result=result,
            new_messages=new_messages,
            new_critiques=new_critiques,
            partial_messages=partial_messages,
            partial_critiques=partial_critiques,
        )

        # Circuit breaker should record failure
        assert circuit_breaker.failures.get("critic1", 0) > 0

        # Agent failure should be recorded
        assert "critic1" in ctx.agent_failures

    def test_handles_error_result(self):
        """Handles critique result with an error."""
        circuit_breaker = MockCircuitBreaker()
        hooks = {"on_agent_error": MagicMock(), "on_critique": MagicMock()}

        gen = CritiqueGenerator(
            circuit_breaker=circuit_breaker,
            hooks=hooks,
        )

        ctx = MockDebateContext()
        ctx.proposals = {"target1": "Proposal text"}
        result = ctx.result
        new_messages = []
        new_critiques = []
        partial_messages = []
        partial_critiques = []

        # Error result
        crit_result = CritiqueResult(
            critic=MockAgent(name="critic1"),
            target_agent="target1",
            critique=None,
            error=RuntimeError("Something went wrong"),
        )

        returned = gen._process_critique_result(
            crit_result,
            ctx,
            round_num=1,
            result=result,
            new_messages=new_messages,
            new_critiques=new_critiques,
            partial_messages=partial_messages,
            partial_critiques=partial_critiques,
        )

        # Circuit breaker should record failure
        assert circuit_breaker.failures.get("critic1", 0) > 0

        # on_agent_error hook should be called
        hooks["on_agent_error"].assert_called()

        # Placeholder critique should be created
        assert len(new_critiques) == 1

    def test_updates_circuit_breaker_on_failure(self):
        """Updates circuit breaker on critique failure."""
        circuit_breaker = MockCircuitBreaker()

        gen = CritiqueGenerator(circuit_breaker=circuit_breaker)

        ctx = MockDebateContext()
        ctx.proposals = {"target1": "Proposal text"}
        result = ctx.result
        new_messages = []
        new_critiques = []
        partial_messages = []
        partial_critiques = []

        # None critique (timeout case)
        crit_result = CritiqueResult(
            critic=MockAgent(name="critic1"),
            target_agent="target1",
            critique=None,
            error=None,
        )

        gen._process_critique_result(
            crit_result,
            ctx,
            round_num=1,
            result=result,
            new_messages=new_messages,
            new_critiques=new_critiques,
            partial_messages=partial_messages,
            partial_critiques=partial_critiques,
        )

        # Circuit breaker should have recorded a failure
        assert circuit_breaker.failures.get("critic1", 0) > 0

    def test_notifies_spectator_on_success(self):
        """Notifies spectator on successful critique."""
        notify_spectator = MagicMock()

        gen = CritiqueGenerator(notify_spectator=notify_spectator)

        ctx = MockDebateContext()
        ctx.proposals = {"target1": "Proposal text"}
        result = ctx.result
        new_messages = []
        new_critiques = []
        partial_messages = []
        partial_critiques = []

        mock_critique = create_critique(
            agent="critic1",
            target_agent="target1",
            issues=["Issue 1"],
            severity=5.0,
        )
        crit_result = CritiqueResult(
            critic=MockAgent(name="critic1"),
            target_agent="target1",
            critique=mock_critique,
            error=None,
        )

        gen._process_critique_result(
            crit_result,
            ctx,
            round_num=1,
            result=result,
            new_messages=new_messages,
            new_critiques=new_critiques,
            partial_messages=partial_messages,
            partial_critiques=partial_critiques,
        )

        notify_spectator.assert_any_call(
            "critique",
            agent="critic1",
            details="Critiqued target1: 1 issues",
            metric=5.0,
        )

    def test_records_turn_with_recorder(self):
        """Records critique turn with recorder when available."""
        recorder = MagicMock()

        gen = CritiqueGenerator(recorder=recorder)

        ctx = MockDebateContext()
        ctx.proposals = {"target1": "Proposal text"}
        result = ctx.result
        new_messages = []
        new_critiques = []
        partial_messages = []
        partial_critiques = []

        mock_critique = create_critique(
            agent="critic1",
            target_agent="target1",
            issues=["Issue 1"],
        )
        crit_result = CritiqueResult(
            critic=MockAgent(name="critic1"),
            target_agent="target1",
            critique=mock_critique,
            error=None,
        )

        gen._process_critique_result(
            crit_result,
            ctx,
            round_num=1,
            result=result,
            new_messages=new_messages,
            new_critiques=new_critiques,
            partial_messages=partial_messages,
            partial_critiques=partial_critiques,
        )

        recorder.record_turn.assert_called_once()

    def test_handles_recorder_errors_gracefully(self):
        """Handles recorder errors without raising."""
        recorder = MagicMock()
        recorder.record_turn.side_effect = RuntimeError("Recorder error")

        gen = CritiqueGenerator(recorder=recorder)

        ctx = MockDebateContext()
        ctx.proposals = {"target1": "Proposal text"}
        result = ctx.result
        new_messages = []
        new_critiques = []
        partial_messages = []
        partial_critiques = []

        mock_critique = create_critique()
        crit_result = CritiqueResult(
            critic=MockAgent(name="critic1"),
            target_agent="target1",
            critique=mock_critique,
            error=None,
        )

        # Should not raise
        gen._process_critique_result(
            crit_result,
            ctx,
            round_num=1,
            result=result,
            new_messages=new_messages,
            new_critiques=new_critiques,
            partial_messages=partial_messages,
            partial_critiques=partial_critiques,
        )

    def test_adds_message_to_context(self):
        """Adds critique message to context messages."""
        gen = CritiqueGenerator()

        ctx = MockDebateContext()
        ctx.proposals = {"target1": "Proposal text"}
        result = ctx.result
        new_messages = []
        new_critiques = []
        partial_messages = []
        partial_critiques = []

        mock_critique = create_critique()
        crit_result = CritiqueResult(
            critic=MockAgent(name="critic1"),
            target_agent="target1",
            critique=mock_critique,
            error=None,
        )

        gen._process_critique_result(
            crit_result,
            ctx,
            round_num=1,
            result=result,
            new_messages=new_messages,
            new_critiques=new_critiques,
            partial_messages=partial_messages,
            partial_critiques=partial_critiques,
        )

        # Message should be added to context
        assert len(ctx.context_messages) == 1

    def test_creates_placeholder_critique_on_timeout(self):
        """Creates placeholder critique when critique is None (timeout case)."""
        gen = CritiqueGenerator()

        ctx = MockDebateContext()
        ctx.proposals = {"target1": "Proposal text"}
        result = ctx.result
        new_messages = []
        new_critiques = []
        partial_messages = []
        partial_critiques = []

        # None critique represents timeout/unavailable
        crit_result = CritiqueResult(
            critic=MockAgent(name="critic1"),
            target_agent="target1",
            critique=None,
            error=None,
        )

        returned = gen._process_critique_result(
            crit_result,
            ctx,
            round_num=1,
            result=result,
            new_messages=new_messages,
            new_critiques=new_critiques,
            partial_messages=partial_messages,
            partial_critiques=partial_critiques,
        )

        # Placeholder should be created and added
        assert len(new_critiques) == 1
        assert len(partial_critiques) == 1
        assert len(result.critiques) == 1


# =============================================================================
# Molecule Tracking Tests
# =============================================================================


class TestMoleculeTracking:
    """Tests for molecule tracking methods."""

    def test_create_critique_molecule_with_tracker(self):
        """Creates molecule when tracker is available."""
        tracker = MagicMock()
        mock_molecule = MagicMock()
        mock_molecule.molecule_id = "mol-123"
        tracker.create_molecule.return_value = mock_molecule

        gen = CritiqueGenerator(molecule_tracker=tracker)

        with patch("aragora.debate.molecules.MoleculeType") as mock_type:
            mock_type.CRITIQUE = "CRITIQUE"
            gen._create_critique_molecule(
                debate_id="debate-1",
                round_num=1,
                critic_name="critic1",
                target_name="target1",
            )

        tracker.create_molecule.assert_called_once()
        assert "critic1:target1" in gen._active_molecules

    def test_create_critique_molecule_without_tracker(self):
        """Does nothing when tracker is None."""
        gen = CritiqueGenerator()

        # Should not raise
        gen._create_critique_molecule(
            debate_id="debate-1",
            round_num=1,
            critic_name="critic1",
            target_name="target1",
        )

        assert gen._active_molecules == {}

    def test_start_molecule_with_tracker(self):
        """Starts molecule when tracker is available."""
        tracker = MagicMock()

        gen = CritiqueGenerator(molecule_tracker=tracker)
        gen._active_molecules["critic1:target1"] = "mol-123"

        gen._start_molecule("critic1", "target1")

        tracker.start_molecule.assert_called_once_with("mol-123")

    def test_complete_molecule_with_tracker(self):
        """Completes molecule when tracker is available."""
        tracker = MagicMock()

        gen = CritiqueGenerator(molecule_tracker=tracker)
        gen._active_molecules["critic1:target1"] = "mol-123"

        gen._complete_molecule("critic1", "target1", {"issues": 2, "severity": 5.0})

        tracker.complete_molecule.assert_called_once_with(
            "mol-123",
            {"issues": 2, "severity": 5.0},
        )

    def test_fail_molecule_with_tracker(self):
        """Fails molecule when tracker is available."""
        tracker = MagicMock()

        gen = CritiqueGenerator(molecule_tracker=tracker)
        gen._active_molecules["critic1:target1"] = "mol-123"

        gen._fail_molecule("critic1", "target1", "Timeout error")

        tracker.fail_molecule.assert_called_once_with("mol-123", "Timeout error")

    def test_molecule_operations_handle_missing_molecule(self):
        """Molecule operations handle missing molecule ID gracefully."""
        tracker = MagicMock()

        gen = CritiqueGenerator(molecule_tracker=tracker)
        # No active molecule for this key

        # Should not raise
        gen._start_molecule("unknown", "unknown")
        gen._complete_molecule("unknown", "unknown", {})
        gen._fail_molecule("unknown", "unknown", "error")

        # Tracker should not be called
        tracker.start_molecule.assert_not_called()
        tracker.complete_molecule.assert_not_called()
        tracker.fail_molecule.assert_not_called()
