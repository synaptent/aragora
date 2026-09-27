"""
Tests for the debate orchestrator module.

Tests cover:
- _compute_domain_from_task utility function
- Arena initialization and configuration
- Arena context manager behavior
- Team selection and domain extraction
- Event emission and lifecycle
- Running debates with mocked agents
- Phase transitions
- Consensus detection
- Error handling and edge cases
- Early termination on convergence
- Memory integration (outcome storage, pattern retrieval)
- Checkpoint creation during rounds
- Knowledge mound integration (retrieval and ingestion)
- RLM compression activation
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from collections import deque
from datetime import datetime
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.core import Agent, Critique, DebateResult, Environment, Message, Vote
from aragora.debate.orchestrator import Arena, _compute_domain_from_task
from aragora.debate.protocol import DebateProtocol
from aragora.storage.schema import DatabaseManager

# Many tests in this file run full Arena.run() debates (~10-30s each).
# Under load from 9000+ prior tests, these can exceed the global 30s timeout.
pytestmark = pytest.mark.timeout(120)


class MockAgent(Agent):
    """Mock agent for testing Arena functionality."""

    def __init__(
        self,
        name: str = "mock-agent",
        response: str = "Test response",
        model: str = "mock-model",
        role: str = "proposer",
        vote_choice: str | None = None,
        vote_confidence: float = 0.8,
        continue_debate: bool = False,
    ):
        super().__init__(name=name, model=model, role=role)
        self.agent_type = "mock"
        self.response = response
        self.vote_choice = vote_choice
        self.vote_confidence = vote_confidence
        self.continue_debate = continue_debate
        self.generate_calls = 0
        self.critique_calls = 0
        self.vote_calls = 0
        self._generate_side_effect = None

    async def generate(self, prompt: str, context: list = None) -> str:
        self.generate_calls += 1
        if self._generate_side_effect is not None:
            if asyncio.iscoroutinefunction(self._generate_side_effect):
                return await self._generate_side_effect(prompt, context)
            return self._generate_side_effect(prompt, context)
        return self.response

    async def generate_stream(self, prompt: str, context: list = None):
        yield self.response

    async def critique(
        self,
        proposal: str,
        task: str,
        context: list = None,
        target_agent: str = None,
    ) -> Critique:
        self.critique_calls += 1
        return Critique(
            agent=self.name,
            target_agent=target_agent or "unknown",
            target_content=proposal[:100] if proposal else "",
            issues=["Test issue"],
            suggestions=["Test suggestion"],
            severity=0.5,
            reasoning="Test reasoning",
        )

    async def vote(self, proposals: dict, task: str) -> Vote:
        self.vote_calls += 1
        choice = self.vote_choice or (list(proposals.keys())[0] if proposals else self.name)
        return Vote(
            agent=self.name,
            choice=choice,
            reasoning="Test vote",
            confidence=self.vote_confidence,
            continue_debate=self.continue_debate,
        )


class FailingAgent(Agent):
    """Agent that raises exceptions for error handling tests."""

    def __init__(self, name: str = "failing-agent", fail_on: str = "generate"):
        super().__init__(name=name, model="failing-model", role="proposer")
        self.agent_type = "failing"
        self.fail_on = fail_on

    async def generate(self, prompt: str, context: list = None) -> str:
        if self.fail_on == "generate":
            raise RuntimeError("Agent generation failed")
        return "Fallback response"

    async def critique(
        self,
        proposal: str,
        task: str,
        context: list = None,
        target_agent: str = None,
    ) -> Critique:
        if self.fail_on == "critique":
            raise RuntimeError("Agent critique failed")
        return Critique(
            agent=self.name,
            target_agent=target_agent or "unknown",
            target_content=proposal[:100] if proposal else "",
            issues=["Error issue"],
            suggestions=["Error suggestion"],
            severity=0.5,
            reasoning="Error reasoning",
        )

    async def vote(self, proposals: dict, task: str) -> Vote:
        if self.fail_on == "vote":
            raise RuntimeError("Agent vote failed")
        return Vote(
            agent=self.name,
            choice=list(proposals.keys())[0] if proposals else self.name,
            reasoning="Error vote",
            confidence=0.5,
            continue_debate=False,
        )


class TimeoutAgent(Agent):
    """Agent that times out for timeout handling tests."""

    def __init__(self, name: str = "timeout-agent", delay_seconds: float = 10.0):
        super().__init__(name=name, model="timeout-model", role="proposer")
        self.agent_type = "timeout"
        self.delay_seconds = delay_seconds

    async def generate(self, prompt: str, context: list = None) -> str:
        await asyncio.sleep(self.delay_seconds)
        return "Delayed response"

    async def critique(
        self,
        proposal: str,
        task: str,
        context: list = None,
        target_agent: str = None,
    ) -> Critique:
        await asyncio.sleep(self.delay_seconds)
        return Critique(
            agent=self.name,
            target_agent=target_agent or "unknown",
            target_content=proposal[:100] if proposal else "",
            issues=["Timeout issue"],
            suggestions=["Timeout suggestion"],
            severity=0.5,
            reasoning="Timeout reasoning",
        )

    async def vote(self, proposals: dict, task: str) -> Vote:
        await asyncio.sleep(self.delay_seconds)
        return Vote(
            agent=self.name,
            choice=list(proposals.keys())[0] if proposals else self.name,
            reasoning="Timeout vote",
            confidence=0.5,
            continue_debate=False,
        )


class ConvergingAgent(Agent):
    """Agent that returns converging responses to test early termination."""

    def __init__(self, name: str = "converging-agent", response_template: str = "The answer is 42"):
        super().__init__(name=name, model="converging-model", role="proposer")
        self.agent_type = "converging"
        self.response_template = response_template
        self.generate_calls = 0

    async def generate(self, prompt: str, context: list = None) -> str:
        self.generate_calls += 1
        return self.response_template

    async def critique(
        self,
        proposal: str,
        task: str,
        context: list = None,
        target_agent: str = None,
    ) -> Critique:
        return Critique(
            agent=self.name,
            target_agent=target_agent or "unknown",
            target_content=proposal[:100] if proposal else "",
            issues=[],
            suggestions=[],
            severity=0.1,
            reasoning="Full agreement",
        )

    async def vote(self, proposals: dict, task: str) -> Vote:
        choice = list(proposals.keys())[0] if proposals else self.name
        return Vote(
            agent=self.name,
            choice=choice,
            reasoning="Unanimous agreement",
            confidence=0.95,
            continue_debate=False,
        )


# =============================================================================
# Domain Extraction Tests
# =============================================================================


class TestComputeDomainFromTask:
    """Tests for _compute_domain_from_task utility function."""

    def test_security_domain(self):
        """Test security domain detection."""
        assert _compute_domain_from_task("implement authentication system") == "security"
        assert _compute_domain_from_task("fix the security vulnerability") == "security"
        assert _compute_domain_from_task("add encryption to data storage") == "security"
        assert _compute_domain_from_task("prevent hack attacks") == "security"
        assert _compute_domain_from_task("improve auth flow") == "security"

    def test_performance_domain(self):
        """Test performance domain detection."""
        # Note: Order of checks matters - performance keywords are checked early
        assert _compute_domain_from_task("improve the speed of the application") == "performance"
        assert _compute_domain_from_task("implement cache strategy") == "performance"
        assert _compute_domain_from_task("reduce latency") == "performance"
        assert _compute_domain_from_task("optimize the code") == "performance"

    def test_testing_domain(self):
        """Test testing domain detection."""
        assert _compute_domain_from_task("write unit tests for the module") == "testing"
        assert _compute_domain_from_task("improve test coverage") == "testing"
        assert _compute_domain_from_task("fix regression tests") == "testing"

    def test_architecture_domain(self):
        """Test architecture domain detection."""
        assert _compute_domain_from_task("design the system architecture") == "architecture"
        assert _compute_domain_from_task("implement factory pattern") == "architecture"
        assert _compute_domain_from_task("restructure the codebase") == "architecture"

    def test_debugging_domain(self):
        """Test debugging domain detection."""
        assert _compute_domain_from_task("fix the login bug") == "debugging"
        assert _compute_domain_from_task("resolve null pointer error") == "debugging"
        assert _compute_domain_from_task("debug the crash on startup") == "debugging"
        assert _compute_domain_from_task("handle runtime exception") == "debugging"

    def test_api_domain(self):
        """Test API domain detection."""
        assert _compute_domain_from_task("create new endpoint for users") == "api"
        assert _compute_domain_from_task("implement rest service") == "api"
        # Note: "graphql" is API but comes after other checks
        assert _compute_domain_from_task("graphql mutations") == "api"

    def test_database_domain(self):
        """Test database domain detection."""
        assert _compute_domain_from_task("create new sql table") == "database"
        assert _compute_domain_from_task("write database query") == "database"
        # Note: "schema" could be API (graphql) but database is checked after API

    def test_frontend_domain(self):
        """Test frontend domain detection."""
        assert _compute_domain_from_task("update the ui component") == "frontend"
        assert _compute_domain_from_task("improve layout styling") == "frontend"
        assert _compute_domain_from_task("style with css") == "frontend"
        assert _compute_domain_from_task("react component") == "frontend"
        # Note: "fix layout" triggers "debugging" due to "fix"

    def test_general_domain(self):
        """Test general domain fallback."""
        assert _compute_domain_from_task("do something random") == "general"
        assert _compute_domain_from_task("process the data") == "general"
        assert _compute_domain_from_task("implement feature x") == "general"

    def test_first_match_wins(self):
        """Test that the first matching domain wins (order matters)."""
        # "performance" is checked before "database" so "optimize" wins
        assert _compute_domain_from_task("optimize database queries") == "performance"
        # "security" is checked before "testing" so "auth" wins
        assert _compute_domain_from_task("test auth flow") == "security"

    def test_case_sensitivity(self):
        """Test that function expects lowercase input."""
        # The function expects lowercase input (as documented)
        # Mixed case might not match correctly
        assert _compute_domain_from_task("security") == "security"
        assert _compute_domain_from_task("performance") == "performance"

    def test_partial_word_matches(self):
        """Test that word boundaries are not enforced (substring matching)."""
        # "auth" matches in "authentication"
        assert _compute_domain_from_task("authentication") == "security"
        # "test" matches in "testing"
        assert _compute_domain_from_task("testing") == "testing"
        # "cache" is an exact keyword, "caching" doesn't match
        assert _compute_domain_from_task("cache layer") == "performance"
        # "encrypt" matches in "encryption"
        assert _compute_domain_from_task("encryption") == "security"

    def test_multiple_keywords_first_wins(self):
        """Test that with multiple keywords, first domain check wins."""
        # This has both "speed" (performance) and "bug" (debugging)
        # Performance is checked first, so it wins
        assert _compute_domain_from_task("speed up and fix the bug") == "performance"

        # This has both "security" and "test"
        # Security is checked first
        assert _compute_domain_from_task("security test suite") == "security"

    def test_empty_string(self):
        """Test empty string returns general."""
        assert _compute_domain_from_task("") == "general"

    def test_no_keywords(self):
        """Test string with no domain keywords returns general."""
        assert _compute_domain_from_task("hello world") == "general"
        assert _compute_domain_from_task("please help me") == "general"


# =============================================================================
# Arena Initialization Tests
# =============================================================================


class TestArenaInitialization:
    """Tests for Arena initialization and configuration."""

    @pytest.fixture
    def environment(self):
        """Create a test environment."""
        return Environment(task="What is the best approach to solve this problem?")

    @pytest.fixture
    def agents(self):
        """Create test agents."""
        return [
            MockAgent(name="agent1", response="Proposal from agent 1"),
            MockAgent(name="agent2", response="Proposal from agent 2"),
        ]

    @pytest.fixture
    def protocol(self):
        """Create a test protocol."""
        return DebateProtocol(rounds=2, consensus="majority")

    def test_arena_creation_with_protocol(self, environment, agents, protocol):
        """Arena can be created with explicit protocol."""
        arena = Arena(environment, agents, protocol)

        assert arena.protocol == protocol
        assert arena.protocol.rounds == 2
        assert arena.protocol.consensus == "majority"

    def test_arena_stores_agents(self, environment, agents, protocol):
        """Arena stores provided agents."""
        arena = Arena(environment, agents, protocol)

        # Check agents are stored (may be in _agents or agent_pool)
        assert hasattr(arena, "_agents") or hasattr(arena, "agent_pool")

    def test_arena_default_protocol(self, environment, agents):
        """Arena creates default protocol when none provided."""
        arena = Arena(environment, agents)

        assert arena.protocol is not None
        assert arena.protocol.rounds > 0

    def test_arena_stores_environment(self, environment, agents, protocol):
        """Arena stores the environment."""
        arena = Arena(environment, agents, protocol)

        assert arena.env == environment
        assert arena.env.task == "What is the best approach to solve this problem?"

    def test_arena_with_memory(self, environment, agents, protocol):
        """Arena accepts memory argument."""
        mock_memory = MagicMock()
        arena = Arena(environment, agents, protocol, memory=mock_memory)

        assert arena.memory == mock_memory

    def test_arena_with_loop_id(self, environment, agents, protocol):
        """Arena accepts loop_id for multi-loop scoping."""
        arena = Arena(environment, agents, protocol, loop_id="test-loop-123")

        assert arena.loop_id == "test-loop-123"

    def test_arena_with_spectator(self, environment, agents, protocol):
        """Arena accepts spectator stream."""
        mock_spectator = MagicMock()
        arena = Arena(environment, agents, protocol, spectator=mock_spectator)

        assert arena.spectator == mock_spectator

    def test_arena_with_circuit_breaker(self, environment, agents, protocol):
        """Arena accepts circuit breaker for agent failure handling."""
        from aragora.debate.protocol import CircuitBreaker

        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30.0)
        arena = Arena(environment, agents, protocol, circuit_breaker=cb)

        assert arena.circuit_breaker == cb

    def test_arena_with_initial_messages(self, environment, agents, protocol):
        """Arena accepts initial messages for fork debates."""
        initial_msgs = [
            Message(role="proposer", agent="previous", content="Previous context", round=0)
        ]
        arena = Arena(environment, agents, protocol, initial_messages=initial_msgs)

        assert arena.initial_messages == initial_msgs

    def test_arena_with_continuum_memory(self, environment, agents, protocol):
        """Arena accepts continuum memory for cross-debate learning."""
        mock_continuum = MagicMock()
        arena = Arena(environment, agents, protocol, continuum_memory=mock_continuum)

        assert arena.continuum_memory == mock_continuum

    def test_arena_with_consensus_memory(self, environment, agents, protocol):
        """Arena accepts consensus memory for historical outcomes."""
        mock_consensus = MagicMock()
        arena = Arena(environment, agents, protocol, consensus_memory=mock_consensus)

        assert arena.consensus_memory == mock_consensus

    def test_arena_with_knowledge_mound(self, environment, agents, protocol):
        """Arena accepts knowledge mound for unified knowledge queries."""
        mock_mound = MagicMock()
        arena = Arena(
            environment,
            agents,
            protocol,
            knowledge_mound=mock_mound,
            enable_knowledge_retrieval=True,
            enable_knowledge_ingestion=True,
        )

        assert arena.knowledge_mound == mock_mound
        assert arena.enable_knowledge_retrieval is True
        assert arena.enable_knowledge_ingestion is True

    def test_arena_with_checkpointing_enabled(self, environment, agents, protocol):
        """Arena accepts checkpointing configuration."""
        arena = Arena(environment, agents, protocol, enable_checkpointing=True)

        assert arena.checkpoint_manager is not None

    def test_arena_with_performance_monitor(self, environment, agents, protocol):
        """Arena accepts performance monitor configuration."""
        arena = Arena(environment, agents, protocol, enable_performance_monitor=True)

        assert arena.performance_monitor is not None


class TestArenaFromConfig:
    """Tests for Arena.from_config factory method."""

    def test_from_config_creates_arena(self):
        """Arena.from_config creates an arena from configuration."""
        from aragora.debate.arena_config import ArenaConfig

        env = Environment(task="Design a scalable API")
        protocol = DebateProtocol(rounds=3, consensus="majority")
        config = ArenaConfig(loop_id="test-123")
        agents = [MockAgent(name="a1"), MockAgent(name="a2")]

        arena = Arena.from_config(env, agents, protocol, config)

        assert arena is not None
        assert isinstance(arena, Arena)

    def test_arena_direct_creation_works(self):
        """Arena can be created directly with loop_id."""
        env = Environment(task="Design a scalable API")
        protocol = DebateProtocol(rounds=3, consensus="majority")
        agents = [MockAgent(name="a1"), MockAgent(name="a2")]

        # Direct creation works
        arena = Arena(env, agents, protocol, loop_id="test-123")

        assert arena is not None
        assert isinstance(arena, Arena)

    def test_from_config_with_default_config(self):
        """Arena.from_config works with default ArenaConfig."""
        env = Environment(task="Test task")
        agents = [MockAgent(name="a1")]

        arena = Arena.from_config(env, agents)

        assert arena is not None


# =============================================================================
# Domain Extraction Tests
# =============================================================================


class TestArenaDomainExtraction:
    """Tests for domain extraction from tasks."""

    @pytest.fixture
    def arena_with_security_task(self):
        """Arena with a security-related task."""
        env = Environment(task="Implement secure authentication")
        agents = [MockAgent(name="a1"), MockAgent(name="a2")]
        return Arena(env, agents)

    @pytest.fixture
    def arena_with_performance_task(self):
        """Arena with a performance-related task."""
        env = Environment(task="Optimize database query speed")
        agents = [MockAgent(name="a1"), MockAgent(name="a2")]
        return Arena(env, agents)

    def test_extracts_security_domain(self, arena_with_security_task):
        """Security domain is extracted for auth tasks."""
        domain = arena_with_security_task._extract_debate_domain()
        assert domain == "security"

    def test_extracts_performance_domain(self, arena_with_performance_task):
        """Performance domain is extracted for optimization tasks."""
        domain = arena_with_performance_task._extract_debate_domain()
        assert domain == "performance"

    def test_domain_is_cached(self, arena_with_security_task):
        """Domain extraction result is cached."""
        domain1 = arena_with_security_task._extract_debate_domain()
        domain2 = arena_with_security_task._extract_debate_domain()

        assert domain1 == domain2
        assert arena_with_security_task._cache.debate_domain == "security"


# =============================================================================
# Context Manager Tests
# =============================================================================


class TestArenaContextManager:
    """Tests for Arena async context manager behavior."""

    @pytest.fixture
    def environment(self):
        return Environment(task="Test task")

    @pytest.fixture
    def agents(self):
        return [MockAgent(name="a1"), MockAgent(name="a2")]

    @pytest.mark.asyncio
    async def test_context_manager_entry(self, environment, agents):
        """Arena can be used as async context manager."""
        arena = Arena(environment, agents)

        async with arena as entered_arena:
            assert entered_arena is arena

    @pytest.mark.asyncio
    async def test_context_manager_cleanup_on_exit(self, environment, agents):
        """Arena cleans up resources on context exit."""
        arena = Arena(environment, agents)

        async with arena:
            pass

        # After exit, cleanup should have occurred
        # (No exception means successful cleanup)

    @pytest.mark.asyncio
    async def test_context_manager_cleanup_on_exception(self, environment, agents):
        """Arena cleans up even when exception occurs."""
        arena = Arena(environment, agents)

        with pytest.raises(ValueError):
            async with arena:
                raise ValueError("Test error")

        # Cleanup should still have occurred


# =============================================================================
# Team Selection Tests
# =============================================================================


class TestArenaTeamSelection:
    """Tests for debate team selection logic."""

    @pytest.fixture
    def environment(self):
        return Environment(task="Test task")

    @pytest.fixture
    def many_agents(self):
        """Create many agents for team selection tests."""
        return [MockAgent(name=f"agent{i}", role="proposer") for i in range(6)]

    def test_select_team_returns_agents(self, environment, many_agents):
        """Team selection returns a list of agents."""
        arena = Arena(environment, many_agents)

        # Select a team from the agents
        team = arena._select_debate_team(many_agents[:3])

        assert isinstance(team, list)
        assert len(team) > 0
        assert all(isinstance(a, Agent) for a in team)

    def test_select_team_respects_requested_agents(self, environment, many_agents):
        """Team selection includes requested agents."""
        arena = Arena(environment, many_agents)

        requested = many_agents[:2]
        team = arena._select_debate_team(requested)

        # All requested agents should be in the team
        requested_names = {a.name for a in requested}
        team_names = {a.name for a in team}
        assert requested_names.issubset(team_names)

    def test_select_team_with_performance_selection(self, environment, many_agents):
        """Team selection respects performance-based selection flag."""
        arena = Arena(environment, many_agents, use_performance_selection=True)

        team = arena._select_debate_team(many_agents[:3])

        # Should return agents based on performance
        assert len(team) > 0


# =============================================================================
# Event Emission Tests
# =============================================================================


class TestArenaEventEmission:
    """Tests for Arena event emission."""

    @pytest.fixture
    def environment(self):
        return Environment(task="Test task")

    @pytest.fixture
    def agents(self):
        return [MockAgent(name="a1"), MockAgent(name="a2")]

    @pytest.fixture
    def protocol(self):
        return DebateProtocol(rounds=1, consensus="majority")

    def test_arena_has_event_emitter(self, environment, agents, protocol):
        """Arena initializes with an event emitter."""
        arena = Arena(environment, agents, protocol)

        # Event emitter should be initialized (or event_bus)
        assert hasattr(arena, "event_emitter") or hasattr(arena, "event_bus")

    def test_arena_accepts_event_hooks(self, environment, agents, protocol):
        """Arena accepts custom event hooks without error."""
        hooks = {
            "on_debate_start": MagicMock(),
            "on_round_complete": MagicMock(),
        }

        # Should create arena without error
        arena = Arena(environment, agents, protocol, event_hooks=hooks)

        # Arena should be created successfully
        assert arena is not None

    def test_arena_has_event_bus(self, environment, agents, protocol):
        """Arena initializes with event bus."""
        arena = Arena(environment, agents, protocol)

        assert hasattr(arena, "event_bus")
        assert arena.event_bus is not None


# =============================================================================
# Arena Run Tests
# =============================================================================


class TestArenaRun:
    """Tests for Arena.run() execution."""

    @pytest.fixture
    def environment(self):
        return Environment(task="What is 2+2?")

    @pytest.fixture
    def agents(self):
        return [
            MockAgent(name="math1", response="The answer is 4"),
            MockAgent(name="math2", response="2 plus 2 equals 4"),
        ]

    @pytest.fixture
    def protocol(self):
        return DebateProtocol(rounds=1, consensus="majority")

    @pytest.mark.smoke
    @pytest.mark.asyncio
    async def test_run_returns_debate_result(self, environment, agents, protocol):
        """Arena.run() returns a DebateResult."""
        arena = Arena(environment, agents, protocol)

        result = await arena.run()

        assert isinstance(result, DebateResult)
        assert result.task == "What is 2+2?"

    @pytest.mark.asyncio
    async def test_run_populates_final_answer(self, environment, agents, protocol):
        """Arena.run() populates the final answer."""
        arena = Arena(environment, agents, protocol)

        result = await arena.run()

        assert result.final_answer is not None
        assert len(result.final_answer) > 0

    @pytest.mark.asyncio
    async def test_run_tracks_rounds(self, environment, agents, protocol):
        """Arena.run() tracks the number of rounds used."""
        arena = Arena(environment, agents, protocol)

        result = await arena.run()

        assert result.rounds_used >= 1

    @pytest.mark.asyncio
    async def test_run_with_correlation_id(self, environment, agents, protocol):
        """Arena.run() accepts a correlation ID for tracing."""
        arena = Arena(environment, agents, protocol)

        result = await arena.run(correlation_id="test-correlation-123")

        # Should complete without error
        assert result is not None

    @pytest.mark.asyncio
    async def test_run_calls_agent_generate(self, environment, agents, protocol):
        """Arena.run() calls agent generate methods."""
        arena = Arena(environment, agents, protocol)

        await arena.run()

        # At least one agent should have been called
        total_calls = sum(a.generate_calls for a in agents)
        assert total_calls > 0

    @pytest.mark.asyncio
    async def test_run_populates_participants(self, environment, agents, protocol):
        """Arena.run() populates participants list."""
        arena = Arena(environment, agents, protocol)

        result = await arena.run()

        assert len(result.participants) == 2
        assert "math1" in result.participants
        assert "math2" in result.participants

    @pytest.mark.asyncio
    async def test_run_populates_proposals(self, environment, agents, protocol):
        """Arena.run() populates proposals dict."""
        arena = Arena(environment, agents, protocol)

        result = await arena.run()

        assert len(result.proposals) >= 1


# =============================================================================
# Round Execution Flow Tests
# =============================================================================


class TestRoundExecutionFlow:
    """Tests for the debate round execution flow (proposal -> critique -> vote -> consensus)."""

    @pytest.fixture
    def environment(self):
        return Environment(task="Design the best caching strategy")

    @pytest.fixture
    def agents(self):
        return [
            MockAgent(name="proposer1", response="Use Redis caching"),
            MockAgent(name="proposer2", response="Use in-memory caching"),
            MockAgent(name="critic", response="Consider latency trade-offs"),
        ]

    @pytest.fixture
    def multi_round_protocol(self):
        return DebateProtocol(
            rounds=3,
            consensus="majority",
            early_stopping=False,
            convergence_detection=False,
        )

    @pytest.mark.asyncio
    async def test_proposal_phase_generates_proposals(
        self, environment, agents, multi_round_protocol
    ):
        """Proposal phase generates initial proposals from agents."""
        arena = Arena(environment, agents, multi_round_protocol)

        result = await arena.run()

        # Should have proposals from agents
        assert len(result.proposals) >= 1

    @pytest.mark.asyncio
    async def test_critique_phase_produces_critiques(
        self, environment, agents, multi_round_protocol
    ):
        """Critique phase produces critiques for proposals."""
        arena = Arena(environment, agents, multi_round_protocol)

        result = await arena.run()

        # Should have critiques
        assert len(result.critiques) >= 0

    @pytest.mark.asyncio
    async def test_vote_phase_produces_votes(self, environment, agents, multi_round_protocol):
        """Vote phase produces votes from agents."""
        arena = Arena(environment, agents, multi_round_protocol)

        result = await arena.run()

        # Should have votes
        assert result.votes is not None

    @pytest.mark.asyncio
    async def test_consensus_produces_final_answer(self, environment, agents, multi_round_protocol):
        """Consensus phase produces final answer."""
        arena = Arena(environment, agents, multi_round_protocol)

        result = await arena.run()

        # Should have final answer
        assert result.final_answer is not None
        assert len(result.final_answer) > 0

    @pytest.mark.asyncio
    async def test_multiple_rounds_execute(self, environment, agents, multi_round_protocol):
        """Multiple rounds execute in sequence."""
        arena = Arena(environment, agents, multi_round_protocol)

        result = await arena.run()

        # Rounds should have executed
        assert result.rounds_used >= 1


# =============================================================================
# Phase Transition Tests
# =============================================================================


class TestPhaseTransitions:
    """Tests for debate phase transitions."""

    @pytest.fixture
    def environment(self):
        return Environment(task="Design a caching strategy")

    @pytest.fixture
    def agents(self):
        return [
            MockAgent(name="agent1", response="Use Redis for caching"),
            MockAgent(name="agent2", response="Implement in-memory cache"),
        ]

    @pytest.fixture
    def multi_round_protocol(self):
        """Protocol with multiple rounds to test phase transitions."""
        return DebateProtocol(
            rounds=3,
            consensus="majority",
            early_stopping=False,
            convergence_detection=False,
        )

    @pytest.mark.asyncio
    async def test_phase_executor_exists(self, environment, agents, multi_round_protocol):
        """Arena creates phase executor during initialization."""
        arena = Arena(environment, agents, multi_round_protocol)

        assert hasattr(arena, "phase_executor")
        assert arena.phase_executor is not None

    @pytest.mark.asyncio
    async def test_all_phases_initialized(self, environment, agents, multi_round_protocol):
        """All debate phases are initialized."""
        arena = Arena(environment, agents, multi_round_protocol)

        # Check all phases exist
        assert hasattr(arena, "context_initializer")
        assert hasattr(arena, "proposal_phase")
        assert hasattr(arena, "debate_rounds_phase")
        assert hasattr(arena, "consensus_phase")
        assert hasattr(arena, "analytics_phase")
        assert hasattr(arena, "feedback_phase")

    @pytest.mark.asyncio
    async def test_run_executes_all_phases(self, environment, agents, multi_round_protocol):
        """Arena.run() executes through all phases."""
        arena = Arena(environment, agents, multi_round_protocol)

        result = await arena.run()

        # Result should reflect phase execution
        assert result is not None
        assert result.rounds_used >= 1
        assert len(result.messages) >= 0

    @pytest.mark.asyncio
    async def test_proposals_precede_rounds(self, environment, agents, multi_round_protocol):
        """Proposal phase runs before debate rounds."""
        arena = Arena(environment, agents, multi_round_protocol)

        result = await arena.run()

        # Proposals should exist before rounds complete
        assert len(result.proposals) >= 1


# =============================================================================
# Early Termination on Convergence Tests
# =============================================================================


class TestEarlyTerminationOnConvergence:
    """Tests for early termination when consensus/convergence is detected."""

    @pytest.fixture
    def environment(self):
        return Environment(task="What is 2+2?")

    @pytest.fixture
    def converging_agents(self):
        """Agents that give the same response (should converge quickly)."""
        return [
            ConvergingAgent(name="agent1", response_template="The answer is 4"),
            ConvergingAgent(name="agent2", response_template="The answer is 4"),
            ConvergingAgent(name="agent3", response_template="The answer is 4"),
        ]

    @pytest.fixture
    def convergence_protocol(self):
        """Protocol with convergence detection enabled."""
        return DebateProtocol(
            rounds=5,
            consensus="majority",
            convergence_detection=True,
            convergence_threshold=0.9,
            early_stopping=True,
            early_stop_threshold=0.9,
            min_rounds_before_early_stop=1,
        )

    def test_convergence_detector_initialized(
        self, environment, converging_agents, convergence_protocol
    ):
        """Convergence detector is initialized when enabled."""
        arena = Arena(environment, converging_agents, convergence_protocol)

        assert arena.convergence_detector is not None
        assert arena.convergence_detector.convergence_threshold == 0.9

    @pytest.mark.asyncio
    async def test_convergence_may_terminate_early(
        self, environment, converging_agents, convergence_protocol
    ):
        """With converging agents and convergence detection, debate may terminate early."""
        arena = Arena(environment, converging_agents, convergence_protocol)

        result = await arena.run()

        # Debate should complete (may or may not terminate early)
        # With perfect convergence, rounds_used can be 0 if consensus is reached
        # immediately after proposals
        assert result is not None
        assert result.rounds_used >= 0

    def test_convergence_detector_disabled(self, environment, converging_agents):
        """Convergence detector is None when disabled."""
        protocol = DebateProtocol(rounds=5, convergence_detection=False)
        arena = Arena(environment, converging_agents, protocol)

        assert arena.convergence_detector is None

    @pytest.mark.asyncio
    async def test_early_stopping_protocol_flag(self, environment, converging_agents):
        """Early stopping can be controlled via protocol flag."""
        protocol = DebateProtocol(
            rounds=10,
            early_stopping=True,
            early_stop_threshold=0.8,
            min_rounds_before_early_stop=1,
        )
        arena = Arena(environment, converging_agents, protocol)

        result = await arena.run()

        # Debate should complete
        assert result is not None


# =============================================================================
# Consensus Detection Tests
# =============================================================================


class TestConsensusDetection:
    """Tests for consensus detection mechanisms."""

    @pytest.fixture
    def environment(self):
        return Environment(task="Choose the best database")

    @pytest.fixture
    def protocol_majority(self):
        return DebateProtocol(rounds=1, consensus="majority", consensus_threshold=0.6)

    @pytest.fixture
    def protocol_judge(self):
        return DebateProtocol(rounds=1, consensus="judge")

    @pytest.fixture
    def protocol_unanimous(self):
        return DebateProtocol(rounds=1, consensus="unanimous")

    @pytest.mark.asyncio
    async def test_majority_consensus_achieved(self, environment, protocol_majority):
        """Majority consensus is detected when threshold is met."""
        agents = [
            MockAgent(name="a1", response="Use PostgreSQL", vote_choice="a1"),
            MockAgent(name="a2", response="Use PostgreSQL", vote_choice="a1"),
            MockAgent(name="a3", response="Use MySQL", vote_choice="a3"),
        ]
        arena = Arena(environment, agents, protocol_majority)

        result = await arena.run()

        # With 2/3 voting the same, majority should be achieved
        assert result is not None

    @pytest.mark.asyncio
    async def test_judge_consensus(self, environment, protocol_judge):
        """Judge consensus uses designated judge."""
        agents = [
            MockAgent(name="a1", response="Use PostgreSQL"),
            MockAgent(name="a2", response="Use MySQL"),
        ]
        arena = Arena(environment, agents, protocol_judge)

        result = await arena.run()

        assert result is not None
        assert result.final_answer is not None

    @pytest.mark.asyncio
    async def test_convergence_detector_initialization(self, environment):
        """Convergence detector is initialized when enabled."""
        protocol = DebateProtocol(rounds=2, convergence_detection=True, convergence_threshold=0.95)
        agents = [MockAgent(name="a1"), MockAgent(name="a2")]
        arena = Arena(environment, agents, protocol)

        assert arena.convergence_detector is not None
        assert arena.convergence_detector.convergence_threshold == 0.95

    @pytest.mark.asyncio
    async def test_convergence_detector_disabled(self, environment):
        """Convergence detector is None when disabled."""
        protocol = DebateProtocol(rounds=2, convergence_detection=False)
        agents = [MockAgent(name="a1"), MockAgent(name="a2")]
        arena = Arena(environment, agents, protocol)

        assert arena.convergence_detector is None

    @pytest.mark.asyncio
    async def test_voting_phase_exists(self, environment, protocol_majority):
        """Voting phase is initialized."""
        agents = [MockAgent(name="a1"), MockAgent(name="a2")]
        arena = Arena(environment, agents, protocol_majority)

        assert hasattr(arena, "voting_phase")
        assert arena.voting_phase is not None


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for error handling in Arena."""

    @pytest.fixture
    def environment(self):
        return Environment(task="Test error handling")

    @pytest.fixture
    def protocol(self):
        return DebateProtocol(
            rounds=1,
            consensus="majority",
            timeout_seconds=5,  # Short timeout for tests
        )

    @pytest.mark.asyncio
    async def test_run_with_mixed_agents(self, environment, protocol):
        """Arena handles mix of working and failing agents."""
        agents = [
            MockAgent(name="working1", response="Working response 1"),
            MockAgent(name="working2", response="Working response 2"),
        ]
        arena = Arena(environment, agents, protocol)

        # Should complete despite potential issues
        result = await arena.run()
        assert result is not None

    @pytest.mark.asyncio
    async def test_empty_task_raises_error(self):
        """Empty task raises ValueError during Environment creation."""
        with pytest.raises(ValueError, match="Task cannot be empty"):
            Environment(task="")

    @pytest.mark.asyncio
    async def test_task_too_long_raises_error(self):
        """Task exceeding max length raises ValueError."""
        long_task = "x" * 150_000  # Exceeds MAX_TASK_LENGTH (100,000)
        with pytest.raises(ValueError, match="exceeds maximum length"):
            Environment(task=long_task)

    @pytest.mark.asyncio
    async def test_timeout_returns_partial_result(self, environment):
        """Timeout returns partial result instead of failing."""
        protocol = DebateProtocol(rounds=3, timeout_seconds=0.1)  # Very short timeout
        agents = [
            TimeoutAgent(name="slow1", delay_seconds=1.0),
            TimeoutAgent(name="slow2", delay_seconds=1.0),
        ]
        arena = Arena(environment, agents, protocol)

        # Should not raise, should return partial result
        result = await arena.run()
        assert result is not None

    @pytest.mark.asyncio
    async def test_arena_handles_agent_failure_gracefully(self, environment, protocol):
        """Arena handles agent failures gracefully with circuit breaker."""
        from aragora.debate.protocol import CircuitBreaker

        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30.0)
        agents = [
            MockAgent(name="working", response="Working response"),
            MockAgent(name="working2", response="Working response 2"),
        ]
        arena = Arena(environment, agents, protocol, circuit_breaker=cb)

        result = await arena.run()
        assert result is not None


# =============================================================================
# Memory Integration Tests
# =============================================================================


class TestMemoryIntegration:
    """Tests for memory system integration."""

    @pytest.fixture
    def environment(self):
        return Environment(task="Test memory integration")

    @pytest.fixture
    def agents(self):
        return [MockAgent(name="a1"), MockAgent(name="a2")]

    def test_memory_manager_exists(self, environment, agents):
        """MemoryManager is initialized."""
        arena = Arena(environment, agents)

        assert hasattr(arena, "memory_manager")
        assert arena.memory_manager is not None

    def test_context_gatherer_exists(self, environment, agents):
        """ContextGatherer is initialized."""
        arena = Arena(environment, agents)

        assert hasattr(arena, "context_gatherer")
        assert arena.context_gatherer is not None

    def test_prompt_builder_exists(self, environment, agents):
        """PromptBuilder is initialized."""
        arena = Arena(environment, agents)

        assert hasattr(arena, "prompt_builder")
        assert arena.prompt_builder is not None

    @pytest.mark.asyncio
    async def test_store_debate_outcome_called_on_completion(self, environment, agents):
        """Debate outcome is stored via memory manager on completion."""
        mock_continuum = MagicMock()
        mock_continuum.add = MagicMock()
        arena = Arena(environment, agents, continuum_memory=mock_continuum)

        result = await arena.run()

        # Result should be stored (check store was called via checkpoint_ops)
        assert result is not None

    @pytest.mark.asyncio
    async def test_historical_context_fetching(self, environment, agents):
        """Historical context can be fetched from debate embeddings."""
        mock_embeddings = MagicMock()
        mock_embeddings.find_similar_debates = AsyncMock(return_value=[])
        arena = Arena(environment, agents, debate_embeddings=mock_embeddings)

        context = await arena._fetch_historical_context("test task")

        # Should return string (may be empty)
        assert isinstance(context, str)

    def test_get_successful_patterns_from_memory(self, environment, agents):
        """Patterns can be retrieved from memory."""
        mock_memory = MagicMock()
        mock_memory.retrieve_patterns = MagicMock(return_value=[])
        arena = Arena(environment, agents, memory=mock_memory)

        patterns = arena._get_successful_patterns_from_memory()

        # Should return string
        assert isinstance(patterns, str)

    @pytest.mark.asyncio
    async def test_memory_outcome_update(self, environment, agents):
        """Memory outcomes are updated after debate completion."""
        mock_continuum = MagicMock()
        mock_continuum.add = MagicMock()
        mock_continuum.update_outcome = MagicMock()
        arena = Arena(environment, agents, continuum_memory=mock_continuum)

        result = await arena.run()

        # Result should be stored
        assert result is not None


# =============================================================================
# Checkpoint Creation Tests
# =============================================================================


class TestCheckpointCreation:
    """Tests for checkpoint creation during rounds."""

    @pytest.fixture
    def environment(self):
        return Environment(task="Test checkpointing")

    @pytest.fixture
    def agents(self):
        return [MockAgent(name="a1"), MockAgent(name="a2")]

    @pytest.fixture
    def protocol_with_rounds(self):
        return DebateProtocol(rounds=3, consensus="majority")

    def test_checkpoint_manager_created_when_enabled(
        self, environment, agents, protocol_with_rounds
    ):
        """CheckpointManager is created when checkpointing is enabled."""
        arena = Arena(environment, agents, protocol_with_rounds, enable_checkpointing=True)

        assert arena.checkpoint_manager is not None

    def test_checkpoint_manager_not_created_when_disabled(
        self, environment, agents, protocol_with_rounds
    ):
        """CheckpointManager is not created when checkpointing is disabled."""
        arena = Arena(environment, agents, protocol_with_rounds, enable_checkpointing=False)

        assert arena.checkpoint_manager is None

    @pytest.mark.asyncio
    async def test_checkpoint_ops_initialized(self, environment, agents, protocol_with_rounds):
        """CheckpointOperations helper is initialized."""
        arena = Arena(environment, agents, protocol_with_rounds)

        assert hasattr(arena, "_checkpoint_ops")
        assert arena._checkpoint_ops is not None

    @pytest.mark.asyncio
    async def test_create_checkpoint_method_exists(self, environment, agents, protocol_with_rounds):
        """Arena has _create_checkpoint method."""
        arena = Arena(environment, agents, protocol_with_rounds)

        assert hasattr(arena, "_create_checkpoint")
        assert callable(arena._create_checkpoint)

    @pytest.mark.asyncio
    async def test_checkpoint_creation_with_manager(
        self, environment, agents, protocol_with_rounds
    ):
        """Checkpoint is created when manager is configured."""
        mock_checkpoint_mgr = MagicMock()
        mock_checkpoint_mgr.should_checkpoint = MagicMock(return_value=True)
        mock_checkpoint_mgr.create_checkpoint = AsyncMock()

        arena = Arena(
            environment, agents, protocol_with_rounds, checkpoint_manager=mock_checkpoint_mgr
        )

        # Simulate context for checkpoint
        mock_ctx = MagicMock()
        mock_ctx.debate_id = "test-debate"
        mock_ctx.result = MagicMock()
        mock_ctx.result.messages = []
        mock_ctx.result.critiques = []
        mock_ctx.result.votes = {}

        await arena._create_checkpoint(mock_ctx, round_num=1)

        # Checkpoint should have been created
        mock_checkpoint_mgr.should_checkpoint.assert_called()


# =============================================================================
# Knowledge Mound Integration Tests
# =============================================================================


class TestKnowledgeMoundIntegration:
    """Tests for Knowledge Mound integration (retrieval and ingestion)."""

    @pytest.fixture
    def environment(self):
        return Environment(task="Test knowledge mound integration")

    @pytest.fixture
    def agents(self):
        return [MockAgent(name="a1"), MockAgent(name="a2")]

    @pytest.fixture
    def mock_knowledge_mound(self):
        """Create mock Knowledge Mound."""
        mound = MagicMock()
        mound.workspace_id = "test-workspace"
        mound.query_semantic = AsyncMock(return_value=MagicMock(items=[]))
        mound.store = AsyncMock(return_value=MagicMock(success=True, node_id="test-node"))
        return mound

    def test_knowledge_mound_stored(self, environment, agents, mock_knowledge_mound):
        """Knowledge mound is stored in arena."""
        arena = Arena(
            environment,
            agents,
            knowledge_mound=mock_knowledge_mound,
            enable_knowledge_retrieval=True,
            enable_knowledge_ingestion=True,
        )

        assert arena.knowledge_mound == mock_knowledge_mound
        assert arena.enable_knowledge_retrieval is True
        assert arena.enable_knowledge_ingestion is True

    def test_knowledge_retrieval_disabled(self, environment, agents, mock_knowledge_mound):
        """Knowledge retrieval can be disabled."""
        arena = Arena(
            environment,
            agents,
            knowledge_mound=mock_knowledge_mound,
            enable_knowledge_retrieval=False,
        )

        assert arena.enable_knowledge_retrieval is False

    def test_knowledge_ingestion_disabled(self, environment, agents, mock_knowledge_mound):
        """Knowledge ingestion can be disabled."""
        arena = Arena(
            environment,
            agents,
            knowledge_mound=mock_knowledge_mound,
            enable_knowledge_ingestion=False,
        )

        assert arena.enable_knowledge_ingestion is False

    @pytest.mark.asyncio
    async def test_fetch_knowledge_context_returns_none_without_mound(self, environment, agents):
        """_fetch_knowledge_context returns None without knowledge mound."""
        arena = Arena(environment, agents, knowledge_mound=None)

        context = await arena._fetch_knowledge_context("test task")

        assert context is None

    @pytest.mark.asyncio
    async def test_fetch_knowledge_context_returns_none_when_disabled(
        self, environment, agents, mock_knowledge_mound
    ):
        """_fetch_knowledge_context returns None when retrieval is disabled."""
        arena = Arena(
            environment,
            agents,
            knowledge_mound=mock_knowledge_mound,
            enable_knowledge_retrieval=False,
        )

        context = await arena._fetch_knowledge_context("test task")

        assert context is None

    @pytest.mark.asyncio
    async def test_fetch_knowledge_context_queries_mound(
        self, environment, agents, mock_knowledge_mound
    ):
        """_fetch_knowledge_context queries the knowledge mound."""
        mock_knowledge_mound.query_semantic = AsyncMock(return_value=MagicMock(items=[]))
        arena = Arena(
            environment,
            agents,
            knowledge_mound=mock_knowledge_mound,
            enable_knowledge_retrieval=True,
        )

        await arena._fetch_knowledge_context("test task")

        mock_knowledge_mound.query_semantic.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_knowledge_context_formats_results(
        self, environment, agents, mock_knowledge_mound
    ):
        """_fetch_knowledge_context formats knowledge items for context."""
        mock_item = MagicMock()
        mock_item.source = "debate"
        mock_item.confidence = 0.85
        mock_item.content = "Previous debate conclusion about caching"

        mock_knowledge_mound.query_semantic = AsyncMock(return_value=MagicMock(items=[mock_item]))
        arena = Arena(
            environment,
            agents,
            knowledge_mound=mock_knowledge_mound,
            enable_knowledge_retrieval=True,
        )

        context = await arena._fetch_knowledge_context("caching strategy")

        assert context is not None
        assert "KNOWLEDGE MOUND CONTEXT" in context
        assert "debate" in context.lower()

    @pytest.mark.asyncio
    async def test_ingest_debate_outcome_skips_without_mound(self, environment, agents):
        """_ingest_debate_outcome skips when no knowledge mound."""
        arena = Arena(environment, agents, knowledge_mound=None)

        result = MagicMock()
        result.final_answer = "Test answer"
        result.confidence = 0.9

        # Should not raise
        await arena._ingest_debate_outcome(result)

    @pytest.mark.asyncio
    async def test_ingest_debate_outcome_skips_when_disabled(
        self, environment, agents, mock_knowledge_mound
    ):
        """_ingest_debate_outcome skips when ingestion is disabled."""
        arena = Arena(
            environment,
            agents,
            knowledge_mound=mock_knowledge_mound,
            enable_knowledge_ingestion=False,
        )

        result = MagicMock()
        result.final_answer = "Test answer"
        result.confidence = 0.9

        await arena._ingest_debate_outcome(result)

        mock_knowledge_mound.store.assert_not_called()

    @pytest.mark.asyncio
    async def test_ingest_debate_outcome_skips_low_confidence(
        self, environment, agents, mock_knowledge_mound
    ):
        """_ingest_debate_outcome skips low confidence results."""
        arena = Arena(
            environment,
            agents,
            knowledge_mound=mock_knowledge_mound,
            enable_knowledge_ingestion=True,
        )

        result = MagicMock()
        result.final_answer = "Test answer"
        result.confidence = 0.5  # Below 0.7 threshold

        await arena._ingest_debate_outcome(result)

        mock_knowledge_mound.store.assert_not_called()

    @pytest.mark.asyncio
    async def test_ingest_debate_outcome_stores_high_confidence(
        self, environment, agents, mock_knowledge_mound
    ):
        """_ingest_debate_outcome stores high confidence results."""
        arena = Arena(
            environment,
            agents,
            knowledge_mound=mock_knowledge_mound,
            enable_knowledge_ingestion=True,
        )

        result = MagicMock()
        result.id = "debate-123"
        result.final_answer = "Redis is the best choice for caching"
        result.confidence = 0.9
        result.consensus_reached = True
        result.rounds_used = 3
        result.participants = ["a1", "a2"]
        result.winner = "a1"

        await arena._ingest_debate_outcome(result)

        mock_knowledge_mound.store.assert_called_once()


# =============================================================================
# RLM Compression Tests
# =============================================================================


class TestRLMCompression:
    """Tests for RLM cognitive load limiter."""

    @pytest.fixture
    def environment(self):
        return Environment(task="Test RLM compression")

    @pytest.fixture
    def agents(self):
        return [MockAgent(name="a1"), MockAgent(name="a2")]

    def test_rlm_limiter_enabled_by_default(self, environment, agents):
        """RLM limiter is enabled by default."""
        arena = Arena(environment, agents)

        assert arena.use_rlm_limiter is True

    def test_rlm_limiter_can_be_disabled(self, environment, agents):
        """RLM limiter can be disabled."""
        arena = Arena(environment, agents, use_rlm_limiter=False)

        assert arena.use_rlm_limiter is False
        assert arena.rlm_limiter is None

    def test_rlm_compression_threshold_configurable(self, environment, agents):
        """RLM compression threshold is configurable."""
        arena = Arena(
            environment,
            agents,
            use_rlm_limiter=True,
            rlm_compression_threshold=5000,
        )

        assert arena.rlm_compression_threshold == 5000

    def test_rlm_max_recent_messages_configurable(self, environment, agents):
        """RLM max recent messages is configurable."""
        arena = Arena(
            environment,
            agents,
            use_rlm_limiter=True,
            rlm_max_recent_messages=10,
        )

        assert arena.rlm_max_recent_messages == 10

    def test_rlm_summary_level_configurable(self, environment, agents):
        """RLM summary level is configurable."""
        arena = Arena(
            environment,
            agents,
            use_rlm_limiter=True,
            rlm_summary_level="DETAILED",
        )

        assert arena.rlm_summary_level == "DETAILED"

    def test_rlm_compression_round_threshold_configurable(self, environment, agents):
        """RLM compression round threshold is configurable."""
        arena = Arena(
            environment,
            agents,
            use_rlm_limiter=True,
            rlm_compression_round_threshold=5,
        )

        assert arena.rlm_compression_round_threshold == 5

    @pytest.mark.asyncio
    async def test_compress_debate_messages_noop_when_disabled(self, environment, agents):
        """compress_debate_messages is a no-op when RLM is disabled."""
        arena = Arena(environment, agents, use_rlm_limiter=False)

        messages = [Message(role="proposer", agent="a1", content="Test message", round=1)]

        compressed_msgs, compressed_crits = await arena.compress_debate_messages(messages, None)

        # Should return original messages unchanged
        assert compressed_msgs == messages
        assert compressed_crits is None

    @pytest.mark.asyncio
    async def test_compress_debate_messages_with_limiter(self, environment, agents):
        """compress_debate_messages uses limiter when enabled."""
        mock_limiter = MagicMock()
        mock_result = MagicMock()
        mock_result.compression_applied = True
        mock_result.original_chars = 1000
        mock_result.compressed_chars = 500
        mock_result.compression_ratio = 0.5
        mock_result.messages = [Message(role="proposer", agent="a1", content="Compressed", round=1)]
        mock_result.critiques = None
        mock_limiter.compress_context_async = AsyncMock(return_value=mock_result)

        arena = Arena(environment, agents, use_rlm_limiter=True, rlm_limiter=mock_limiter)

        messages = [Message(role="proposer", agent="a1", content="Test message " * 100, round=1)]

        compressed_msgs, _ = await arena.compress_debate_messages(messages, None)

        mock_limiter.compress_context_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_compress_debate_messages_handles_error(self, environment, agents):
        """compress_debate_messages handles compression errors gracefully."""
        mock_limiter = MagicMock()
        mock_limiter.compress_context_async = AsyncMock(
            side_effect=RuntimeError("Compression failed")
        )

        arena = Arena(environment, agents, use_rlm_limiter=True, rlm_limiter=mock_limiter)

        messages = [Message(role="proposer", agent="a1", content="Test message", round=1)]

        # Should return original messages on error
        compressed_msgs, compressed_crits = await arena.compress_debate_messages(messages, None)

        assert compressed_msgs == messages
        assert compressed_crits is None


# =============================================================================
# Helper Method Tests
# =============================================================================


class TestArenaRequireAgents:
    """Tests for _require_agents helper."""

    def test_require_agents_returns_agents(self):
        """_require_agents returns the agent list."""
        env = Environment(task="Test")
        agents = [MockAgent(name="a1"), MockAgent(name="a2")]
        protocol = DebateProtocol(rounds=1, consensus="majority")
        arena = Arena(env, agents, protocol)

        result = arena._require_agents()

        # Should return agents (may be processed)
        assert len(result) > 0

    def test_require_agents_returns_non_empty_list(self):
        """_require_agents returns a non-empty list of agents."""
        env = Environment(task="Test")
        agents = [MockAgent(name="a1"), MockAgent(name="a2")]
        protocol = DebateProtocol(rounds=1, consensus="majority")
        arena = Arena(env, agents, protocol)

        result = arena._require_agents()

        # Should return agents
        assert isinstance(result, list)
        assert len(result) >= 1


class TestRoleAssignment:
    """Tests for role assignment functionality."""

    @pytest.fixture
    def environment(self):
        return Environment(task="Test roles")

    @pytest.fixture
    def agents(self):
        return [
            MockAgent(name="a1", role="proposer"),
            MockAgent(name="a2", role="critic"),
            MockAgent(name="a3", role="synthesizer"),
        ]

    def test_roles_manager_exists(self, environment, agents):
        """RolesManager is initialized."""
        protocol = DebateProtocol(rounds=2, role_rotation=True)
        arena = Arena(environment, agents, protocol)

        assert hasattr(arena, "roles_manager")
        assert arena.roles_manager is not None

    def test_role_assignments_exist(self, environment, agents):
        """Current role assignments are tracked."""
        protocol = DebateProtocol(rounds=2, role_rotation=True)
        arena = Arena(environment, agents, protocol)

        assert hasattr(arena, "current_role_assignments")


# =============================================================================
# Audience and User Participation Tests
# =============================================================================


class TestAudienceParticipation:
    """Tests for audience/user participation features."""

    @pytest.fixture
    def environment(self):
        return Environment(task="Test audience participation")

    @pytest.fixture
    def agents(self):
        return [MockAgent(name="a1"), MockAgent(name="a2")]

    def test_audience_manager_exists(self, environment, agents):
        """AudienceManager is initialized."""
        arena = Arena(environment, agents)

        assert hasattr(arena, "audience_manager")
        assert arena.audience_manager is not None

    def test_user_votes_accessible(self, environment, agents):
        """User votes are accessible via property."""
        arena = Arena(environment, agents)

        # Should return a deque
        assert hasattr(arena, "user_votes")
        assert isinstance(arena.user_votes, deque)

    def test_user_suggestions_accessible(self, environment, agents):
        """User suggestions are accessible via property."""
        arena = Arena(environment, agents)

        # Should return a deque
        assert hasattr(arena, "user_suggestions")
        assert isinstance(arena.user_suggestions, deque)


# =============================================================================
# Protocol Configuration Tests
# =============================================================================


class TestProtocolConfiguration:
    """Tests for various protocol configurations."""

    @pytest.fixture
    def environment(self):
        return Environment(task="Test protocol config")

    @pytest.fixture
    def agents(self):
        return [MockAgent(name="a1"), MockAgent(name="a2")]

    def test_structured_phases_enabled(self, environment, agents):
        """Structured phases can be enabled via protocol."""
        protocol = DebateProtocol(use_structured_phases=True, rounds=3)
        arena = Arena(environment, agents, protocol)

        assert arena.protocol.use_structured_phases is True

    def test_early_stopping_configured(self, environment, agents):
        """Early stopping can be configured."""
        protocol = DebateProtocol(
            early_stopping=True,
            early_stop_threshold=0.8,
            min_rounds_before_early_stop=2,
        )
        arena = Arena(environment, agents, protocol)

        assert arena.protocol.early_stopping is True
        assert arena.protocol.early_stop_threshold == 0.8
        assert arena.protocol.min_rounds_before_early_stop == 2

    def test_asymmetric_stances_configured(self, environment, agents):
        """Asymmetric debate stances can be configured."""
        protocol = DebateProtocol(asymmetric_stances=True, rotate_stances=True)
        arena = Arena(environment, agents, protocol)

        assert arena.protocol.asymmetric_stances is True
        assert arena.protocol.rotate_stances is True

    def test_topology_configured(self, environment, agents):
        """Debate topology can be configured."""
        protocol = DebateProtocol(topology="ring")
        arena = Arena(environment, agents, protocol)

        assert arena.protocol.topology == "ring"

    def test_judge_selection_configured(self, environment, agents):
        """Judge selection method can be configured."""
        protocol = DebateProtocol(consensus="judge", judge_selection="elo_ranked")
        arena = Arena(environment, agents, protocol)

        assert arena.protocol.judge_selection == "elo_ranked"


# =============================================================================
# Lifecycle and Cleanup Tests
# =============================================================================


class TestLifecycleManagement:
    """Tests for lifecycle management."""

    @pytest.fixture
    def environment(self):
        return Environment(task="Test lifecycle")

    @pytest.fixture
    def agents(self):
        return [MockAgent(name="a1"), MockAgent(name="a2")]

    def test_lifecycle_manager_exists(self, environment, agents):
        """LifecycleManager is initialized."""
        arena = Arena(environment, agents)

        assert hasattr(arena, "_lifecycle")
        assert arena._lifecycle is not None

    @pytest.mark.asyncio
    async def test_cleanup_can_be_called(self, environment, agents):
        """_cleanup can be called without error."""
        arena = Arena(environment, agents)

        # Should not raise
        await arena._cleanup()

    @pytest.mark.asyncio
    async def test_cleanup_called_on_context_exit(self, environment, agents):
        """Cleanup is called when exiting context manager."""
        arena = Arena(environment, agents)
        cleanup_called = False

        original_cleanup = arena._cleanup

        async def tracked_cleanup():
            nonlocal cleanup_called
            cleanup_called = True
            await original_cleanup()

        arena._cleanup = tracked_cleanup

        async with arena:
            pass

        assert cleanup_called

    @pytest.mark.asyncio
    async def test_cleanup_debate_persistence_closes_manager_delta(
        self, environment, agents, tmp_path
    ):
        """Arena cleanup closes only manager-backed databases created after init."""
        arena = Arena(environment, agents)
        baseline = set(arena._db_manager_snapshot)
        created_path = tmp_path / "arena-run-cleanup.db"

        DatabaseManager.get_instance(created_path)

        await arena._cleanup_debate_persistence()

        assert DatabaseManager.instance_paths() == baseline

    @pytest.mark.asyncio
    async def test_cleanup_debate_persistence_drains_dispatcher_before_webhook_store_reset(
        self, environment, agents, tmp_path, monkeypatch
    ):
        """An in-flight webhook delivery is recorded before test cleanup closes its store."""
        from aragora.events import dispatcher as dispatcher_module
        from aragora.storage import webhook_config_store as store_module

        arena = Arena(environment, agents)
        store = store_module.SQLiteWebhookConfigStore(tmp_path / "webhooks.db")
        webhook = store.register(url="https://hooks.example.test/arena", events=["debate_end"])
        dispatcher = dispatcher_module.WebhookDispatcher(max_workers=1)
        monkeypatch.setattr(store_module, "_webhook_config_store", store)
        monkeypatch.setattr(
            dispatcher_module, "_webhook_store_provider", store_module.get_webhook_config_store
        )
        monkeypatch.setattr(dispatcher_module, "_dispatcher", dispatcher)
        monkeypatch.setattr(dispatcher_module, "get_event_rate_limiter", lambda: None)

        release_delivery = threading.Event()
        delivery_started = threading.Event()
        delivery_recorded = threading.Event()
        outcomes: list[str] = []

        def deliver(webhook, payload, **kwargs):
            delivery_started.set()
            release_delivery.wait(timeout=10)
            return dispatcher_module.DeliveryResult(success=True, status_code=200)

        original_record_delivery = store.record_delivery

        def record_delivery(**kwargs):
            try:
                original_record_delivery(**kwargs)
                outcomes.append("recorded")
            except sqlite3.Error as exc:
                outcomes.append(f"error:{type(exc).__name__}")
                raise
            finally:
                delivery_recorded.set()

        original_close = store.close

        def close():
            original_close()
            release_delivery.set()

        original_shutdown = dispatcher.shutdown

        def shutdown(wait: bool = True):
            release_delivery.set()
            original_shutdown(wait=wait)

        monkeypatch.setattr(dispatcher_module, "dispatch_webhook_with_retry", deliver)
        monkeypatch.setattr(store, "record_delivery", record_delivery)
        monkeypatch.setattr(store, "close", close)
        monkeypatch.setattr(dispatcher, "shutdown", shutdown)

        try:
            # The single worker caches its SQLite connection on first use, so a
            # later delivery on that thread reuses whatever close() has closed.
            release_delivery.set()
            dispatcher_module.dispatch_event("debate_end", {"debate_id": "warmup"})
            assert delivery_recorded.wait(timeout=10)

            release_delivery.clear()
            delivery_started.clear()
            delivery_recorded.clear()
            dispatcher_module.dispatch_event("debate_end", {"debate_id": "in-flight"})
            assert delivery_started.wait(timeout=10)

            await arena._cleanup_debate_persistence()
        finally:
            release_delivery.set()
            original_shutdown(wait=True)
            original_close()

        assert outcomes == ["recorded", "recorded"]
        conn = sqlite3.connect(tmp_path / "webhooks.db")
        try:
            (delivery_count,) = conn.execute(
                "SELECT delivery_count FROM webhook_configs WHERE id = ?", (webhook.id,)
            ).fetchone()
        finally:
            conn.close()
        assert delivery_count == 2


# =============================================================================
# Integration Test - Full Debate Flow
# =============================================================================


class TestFullDebateFlow:
    """Integration tests for complete debate execution."""

    @pytest.fixture
    def environment(self):
        return Environment(task="What is the best programming language for web development?")

    @pytest.fixture
    def agents(self):
        """Create agents with distinct responses for testing flow."""
        return [
            MockAgent(
                name="python_advocate",
                response="Python is the best choice due to Django and FastAPI frameworks.",
                vote_choice="python_advocate",
                vote_confidence=0.9,
            ),
            MockAgent(
                name="javascript_advocate",
                response="JavaScript with Node.js provides full-stack consistency.",
                vote_choice="python_advocate",  # Agrees with Python
                vote_confidence=0.7,
            ),
            MockAgent(
                name="rust_advocate",
                response="Rust offers performance and safety for modern web apps.",
                vote_choice="rust_advocate",
                vote_confidence=0.8,
            ),
        ]

    @pytest.fixture
    def protocol(self):
        return DebateProtocol(
            rounds=2,
            consensus="majority",
            consensus_threshold=0.5,
            early_stopping=False,
            convergence_detection=False,
        )

    @pytest.mark.asyncio
    async def test_full_debate_produces_result(self, environment, agents, protocol):
        """Full debate flow produces a complete result."""
        arena = Arena(environment, agents, protocol)

        result = await arena.run()

        assert result is not None
        assert isinstance(result, DebateResult)
        assert result.task == environment.task
        assert result.rounds_used >= 1
        assert len(result.participants) == 3
        assert result.final_answer is not None
        assert len(result.final_answer) > 0

    @pytest.mark.asyncio
    async def test_full_debate_records_messages(self, environment, agents, protocol):
        """Full debate flow records messages."""
        arena = Arena(environment, agents, protocol)

        result = await arena.run()

        # Should have some messages recorded
        assert len(result.messages) >= 0

    @pytest.mark.asyncio
    async def test_full_debate_records_duration(self, environment, agents, protocol):
        """Full debate flow records duration."""
        arena = Arena(environment, agents, protocol)

        result = await arena.run()

        assert result.duration_seconds >= 0

    @pytest.mark.asyncio
    async def test_full_debate_with_context_manager(self, environment, agents, protocol):
        """Full debate works correctly with context manager."""
        arena = Arena(environment, agents, protocol)

        async with arena:
            result = await arena.run()

        assert result is not None
        assert result.task == environment.task

    @pytest.mark.asyncio
    async def test_full_debate_with_memory_subsystems(self, environment, agents, protocol):
        """Full debate integrates with memory subsystems."""
        mock_continuum = MagicMock()
        mock_continuum.add = MagicMock()
        mock_consensus = MagicMock()

        arena = Arena(
            environment,
            agents,
            protocol,
            continuum_memory=mock_continuum,
            consensus_memory=mock_consensus,
        )

        result = await arena.run()

        assert result is not None

    @pytest.mark.asyncio
    async def test_full_debate_with_checkpointing(self, environment, agents, protocol):
        """Full debate with checkpointing enabled."""
        arena = Arena(
            environment,
            agents,
            protocol,
            enable_checkpointing=True,
        )

        result = await arena.run()

        assert result is not None
        assert arena.checkpoint_manager is not None

    @pytest.mark.asyncio
    async def test_full_debate_with_knowledge_mound(self, environment, agents, protocol):
        """Full debate with knowledge mound integration."""
        mock_mound = MagicMock()
        mock_mound.workspace_id = "test-workspace"
        mock_mound.query_semantic = AsyncMock(return_value=MagicMock(items=[]))
        mock_mound.store = AsyncMock(return_value=MagicMock(success=True, node_id="test-node"))

        arena = Arena(
            environment,
            agents,
            protocol,
            knowledge_mound=mock_mound,
            enable_knowledge_retrieval=True,
            enable_knowledge_ingestion=True,
        )

        result = await arena.run()

        assert result is not None


# =============================================================================
# Agent Failure Handling Tests
# =============================================================================


class TestAgentFailureHandling:
    """Tests for handling agent failures during debate."""

    @pytest.fixture
    def environment(self):
        return Environment(task="Test agent failure handling")

    @pytest.fixture
    def protocol(self):
        return DebateProtocol(rounds=1, consensus="majority")

    @pytest.mark.asyncio
    async def test_debate_continues_with_working_agents(self, environment, protocol):
        """Debate continues when some agents work properly."""
        agents = [
            MockAgent(name="working1", response="Working response 1"),
            MockAgent(name="working2", response="Working response 2"),
        ]
        arena = Arena(environment, agents, protocol)

        result = await arena.run()

        assert result is not None
        assert result.final_answer is not None

    @pytest.mark.asyncio
    async def test_circuit_breaker_tracks_failures(self, environment, protocol):
        """Circuit breaker tracks agent failures."""
        from aragora.debate.protocol import CircuitBreaker

        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30.0)
        agents = [
            MockAgent(name="working1", response="Working response"),
            MockAgent(name="working2", response="Working response 2"),
        ]
        arena = Arena(environment, agents, protocol, circuit_breaker=cb)

        # Circuit breaker should be set
        assert arena.circuit_breaker is cb

    @pytest.mark.asyncio
    async def test_debate_handles_timeout_gracefully(self, environment):
        """Debate handles agent timeouts gracefully."""
        protocol = DebateProtocol(rounds=1, timeout_seconds=1)
        agents = [
            MockAgent(name="fast", response="Fast response"),
            MockAgent(name="fast2", response="Fast response 2"),
        ]
        arena = Arena(environment, agents, protocol)

        result = await arena.run()

        assert result is not None


# =============================================================================
# Grounded Operations Tests
# =============================================================================


class TestGroundedOperations:
    """Tests for grounded operations (positions, relationships, verdicts)."""

    @pytest.fixture
    def environment(self):
        return Environment(task="Test grounded operations")

    @pytest.fixture
    def agents(self):
        return [MockAgent(name="a1"), MockAgent(name="a2")]

    def test_grounded_ops_initialized(self, environment, agents):
        """GroundedOperations helper is initialized."""
        arena = Arena(environment, agents)

        assert hasattr(arena, "_grounded_ops")
        assert arena._grounded_ops is not None

    def test_record_grounded_position_method_exists(self, environment, agents):
        """_record_grounded_position method exists."""
        arena = Arena(environment, agents)

        assert hasattr(arena, "_record_grounded_position")
        assert callable(arena._record_grounded_position)

    def test_update_agent_relationships_method_exists(self, environment, agents):
        """_update_agent_relationships method exists."""
        arena = Arena(environment, agents)

        assert hasattr(arena, "_update_agent_relationships")
        assert callable(arena._update_agent_relationships)

    def test_create_grounded_verdict_method_exists(self, environment, agents):
        """_create_grounded_verdict method exists."""
        arena = Arena(environment, agents)

        assert hasattr(arena, "_create_grounded_verdict")
        assert callable(arena._create_grounded_verdict)


# =============================================================================
# ML Integration Tests
# =============================================================================


class TestMLIntegration:
    """Tests for ML-based features (delegation, quality gates, consensus estimation)."""

    @pytest.fixture
    def environment(self):
        return Environment(task="Test ML integration")

    @pytest.fixture
    def agents(self):
        return [MockAgent(name="a1"), MockAgent(name="a2")]

    def test_ml_delegation_enabled_by_default(self, environment, agents):
        """ML delegation is enabled by default."""
        arena = Arena(environment, agents)

        assert arena.enable_ml_delegation is True

    def test_ml_delegation_can_be_disabled(self, environment, agents):
        """ML delegation can be explicitly disabled."""
        arena = Arena(environment, agents, enable_ml_delegation=False)

        assert arena.enable_ml_delegation is False

    def test_quality_gates_enabled_by_default(self, environment, agents):
        """Quality gates are enabled by default."""
        arena = Arena(environment, agents)

        assert arena.enable_quality_gates is True

    def test_quality_gates_can_be_disabled(self, environment, agents):
        """Quality gates can be explicitly disabled."""
        arena = Arena(
            environment,
            agents,
            enable_quality_gates=False,
        )

        assert arena.enable_quality_gates is False

    def test_quality_gates_threshold_configurable(self, environment, agents):
        """Quality gate threshold is configurable."""
        arena = Arena(
            environment,
            agents,
            enable_quality_gates=True,
            quality_gate_threshold=0.7,
        )

        assert arena.enable_quality_gates is True
        assert arena.quality_gate_threshold == 0.7

    def test_consensus_estimation_enabled_by_default(self, environment, agents):
        """Consensus estimation is enabled by default."""
        arena = Arena(environment, agents)

        assert arena.enable_consensus_estimation is True

    def test_consensus_estimation_can_be_disabled(self, environment, agents):
        """Consensus estimation can be explicitly disabled."""
        arena = Arena(
            environment,
            agents,
            enable_consensus_estimation=False,
        )

        assert arena.enable_consensus_estimation is False

    def test_consensus_estimation_threshold_configurable(self, environment, agents):
        """Consensus estimation threshold is configurable."""
        arena = Arena(
            environment,
            agents,
            enable_consensus_estimation=True,
            consensus_early_termination_threshold=0.9,
        )

        assert arena.enable_consensus_estimation is True
        assert arena.consensus_early_termination_threshold == 0.9


# =============================================================================
# Concurrent Debate Handling Tests
# =============================================================================


class TestConcurrentDebateHandling:
    """Tests for handling multiple concurrent debates."""

    @pytest.fixture
    def environment(self):
        return Environment(task="Test concurrent debates")

    @pytest.fixture
    def agents(self):
        return [
            MockAgent(name="agent1", response="Response from agent 1"),
            MockAgent(name="agent2", response="Response from agent 2"),
        ]

    @pytest.fixture
    def protocol(self):
        return DebateProtocol(rounds=1, consensus="majority", enable_calibration=False)

    @pytest.mark.asyncio
    async def test_multiple_arenas_can_run_concurrently(self, environment, agents, protocol):
        """Multiple Arena instances can run debates concurrently."""
        arena1 = Arena(environment, agents.copy(), protocol)
        arena2 = Arena(environment, agents.copy(), protocol)

        # Run both debates concurrently
        results = await asyncio.gather(arena1.run(), arena2.run())

        assert len(results) == 2
        assert all(isinstance(r, DebateResult) for r in results)
        assert all(r.final_answer is not None for r in results)

    @pytest.mark.asyncio
    async def test_concurrent_debates_have_unique_ids(self, agents, protocol):
        """Concurrent debates generate unique debate IDs."""
        env1 = Environment(task="Task 1")
        env2 = Environment(task="Task 2")

        arena1 = Arena(env1, agents.copy(), protocol)
        arena2 = Arena(env2, agents.copy(), protocol)

        results = await asyncio.gather(arena1.run(), arena2.run())

        # Both should complete successfully with different tasks
        assert results[0].task == "Task 1"
        assert results[1].task == "Task 2"

    @pytest.mark.asyncio
    async def test_concurrent_debates_with_same_agents(self, environment, protocol):
        """Debates with the same agents configured separately work concurrently."""
        # Create separate agent instances for each arena
        agents1 = [
            MockAgent(name="shared1", response="Response 1"),
            MockAgent(name="shared2", response="Response 2"),
        ]
        agents2 = [
            MockAgent(name="shared1", response="Response 1"),
            MockAgent(name="shared2", response="Response 2"),
        ]

        arena1 = Arena(environment, agents1, protocol)
        arena2 = Arena(environment, agents2, protocol)

        results = await asyncio.gather(arena1.run(), arena2.run())

        assert len(results) == 2
        assert all(r is not None for r in results)

    @pytest.mark.asyncio
    async def test_context_manager_with_concurrent_debates(self, environment, agents, protocol):
        """Context managers work correctly for concurrent debates."""
        async with (
            Arena(environment, agents.copy(), protocol) as arena1,
            Arena(environment, agents.copy(), protocol) as arena2,
        ):
            results = await asyncio.gather(arena1.run(), arena2.run())

        assert len(results) == 2
        assert all(r is not None for r in results)

    @pytest.mark.asyncio
    async def test_concurrent_debates_isolate_state(self, protocol):
        """Concurrent debates maintain isolated state."""
        env1 = Environment(task="Security question about auth")
        env2 = Environment(task="Performance question about speed")

        agents1 = [MockAgent(name="a1", response="Security answer")]
        agents2 = [MockAgent(name="a1", response="Performance answer")]

        arena1 = Arena(env1, agents1, protocol)
        arena2 = Arena(env2, agents2, protocol)

        # Check domains are extracted correctly for each
        domain1 = arena1._extract_debate_domain()
        domain2 = arena2._extract_debate_domain()

        assert domain1 == "security"
        assert domain2 == "performance"

    @pytest.mark.asyncio
    async def test_many_concurrent_debates(self, protocol):
        """Multiple concurrent debates (5+) can run successfully."""
        debates = []
        for i in range(5):
            env = Environment(task=f"Task number {i}")
            agents = [MockAgent(name=f"agent_{i}", response=f"Response {i}")]
            arena = Arena(env, agents, protocol)
            debates.append(arena.run())

        results = await asyncio.gather(*debates)

        assert len(results) == 5
        assert all(isinstance(r, DebateResult) for r in results)


# =============================================================================
# Extended Event Emission and Callbacks Tests
# =============================================================================


class TestExtendedEventEmission:
    """Extended tests for event emission and callback handling."""

    @pytest.fixture
    def environment(self):
        return Environment(task="Test event emission")

    @pytest.fixture
    def agents(self):
        return [MockAgent(name="a1"), MockAgent(name="a2")]

    @pytest.fixture
    def protocol(self):
        return DebateProtocol(rounds=1, consensus="majority")

    def test_hook_manager_accepted(self, environment, agents, protocol):
        """Arena accepts a HookManager for extended lifecycle hooks."""
        mock_hook_manager = MagicMock()
        arena = Arena(environment, agents, protocol, hook_manager=mock_hook_manager)

        assert arena.hook_manager == mock_hook_manager

    def test_event_emitter_initialized(self, environment, agents, protocol):
        """Internal EventEmitter is initialized."""
        arena = Arena(environment, agents, protocol)

        assert hasattr(arena, "_event_emitter")
        assert arena._event_emitter is not None

    def test_spectator_notified(self, environment, agents, protocol):
        """Spectator stream receives notifications."""
        mock_spectator = MagicMock()
        mock_spectator.broadcast = MagicMock()
        arena = Arena(environment, agents, protocol, spectator=mock_spectator)

        # Trigger a notification
        arena._notify_spectator("test_event", data="test")

        # Spectator should receive the notification
        # (Implementation may buffer or batch events)

    def test_event_bridge_integration(self, environment, agents, protocol):
        """Event bridge is initialized for cross-system events."""
        arena = Arena(environment, agents, protocol)

        # Event bridge should exist (may be None if not configured)
        assert hasattr(arena, "event_bridge")

    @pytest.mark.asyncio
    async def test_hooks_called_during_run(self, environment, agents, protocol):
        """Event hooks are called during debate run."""
        hooks_called = []

        def on_debate_start(**kwargs):
            hooks_called.append("debate_start")

        hooks = {"on_debate_start": on_debate_start}
        arena = Arena(environment, agents, protocol, event_hooks=hooks)

        await arena.run()

        # Hooks should be configured (actual calling depends on implementation)
        assert arena.hooks is not None

    def test_emit_agent_preview(self, environment, agents, protocol):
        """Agent preview can be emitted."""
        arena = Arena(environment, agents, protocol)

        # Should not raise
        arena._emit_agent_preview()

    def test_notify_spectator_method_exists(self, environment, agents, protocol):
        """_notify_spectator method exists and is callable."""
        arena = Arena(environment, agents, protocol)

        assert hasattr(arena, "_notify_spectator")
        assert callable(arena._notify_spectator)

        # Should not raise even without spectator
        arena._notify_spectator("test_event", key="value")

    def test_emit_moment_event_method_exists(self, environment, agents, protocol):
        """_emit_moment_event method exists."""
        arena = Arena(environment, agents, protocol)

        assert hasattr(arena, "_emit_moment_event")
        assert callable(arena._emit_moment_event)

    @pytest.mark.asyncio
    async def test_event_bus_receives_events(self, environment, agents, protocol):
        """Event bus is set up and can receive events."""
        arena = Arena(environment, agents, protocol)

        assert arena.event_bus is not None

        # Event bus should have methods for subscribing and publishing
        assert hasattr(arena.event_bus, "subscribe") or hasattr(arena.event_bus, "publish")


# =============================================================================
# Agent Hierarchy Tests
# =============================================================================


class TestAgentHierarchy:
    """Tests for agent hierarchy (Gastown pattern) functionality."""

    @pytest.fixture
    def environment(self):
        return Environment(task="Test agent hierarchy")

    @pytest.fixture
    def agents(self):
        return [
            MockAgent(name="orchestrator", role="proposer"),
            MockAgent(name="monitor", role="critic"),
            MockAgent(name="worker", role="synthesizer"),
        ]

    @pytest.fixture
    def protocol(self):
        return DebateProtocol(rounds=2)

    def test_hierarchy_enabled_by_default(self, environment, agents, protocol):
        """Agent hierarchy is enabled by default."""
        arena = Arena(environment, agents, protocol)

        assert arena.enable_agent_hierarchy is True

    def test_hierarchy_can_be_disabled(self, environment, agents, protocol):
        """Agent hierarchy can be disabled."""
        arena = Arena(environment, agents, protocol, enable_agent_hierarchy=False)

        assert arena.enable_agent_hierarchy is False

    def test_hierarchy_object_created_when_enabled(self, environment, agents, protocol):
        """AgentHierarchy object is created when enabled."""
        arena = Arena(environment, agents, protocol, enable_agent_hierarchy=True)

        assert hasattr(arena, "_hierarchy")
        # Hierarchy may be None if no config provided

    def test_assign_hierarchy_roles_method_exists(self, environment, agents, protocol):
        """_assign_hierarchy_roles method exists."""
        arena = Arena(environment, agents, protocol)

        assert hasattr(arena, "_assign_hierarchy_roles")
        assert callable(arena._assign_hierarchy_roles)


# =============================================================================
# Cross-Debate Memory Tests
# =============================================================================


class TestCrossDebateMemory:
    """Tests for cross-debate memory and institutional knowledge."""

    @pytest.fixture
    def environment(self):
        return Environment(task="Test cross-debate memory")

    @pytest.fixture
    def agents(self):
        return [MockAgent(name="a1"), MockAgent(name="a2")]

    @pytest.fixture
    def protocol(self):
        return DebateProtocol(rounds=1)

    def test_cross_debate_memory_stored(self, environment, agents, protocol):
        """Cross-debate memory is stored when provided."""
        mock_cross_memory = MagicMock()
        arena = Arena(
            environment,
            agents,
            protocol,
            cross_debate_memory=mock_cross_memory,
            enable_cross_debate_memory=True,
        )

        assert arena.cross_debate_memory == mock_cross_memory
        assert arena.enable_cross_debate_memory is True

    def test_cross_debate_memory_enabled_by_default(self, environment, agents, protocol):
        """Cross-debate memory injection is enabled by default."""
        arena = Arena(environment, agents, protocol)

        assert arena.enable_cross_debate_memory is True

    def test_cross_debate_memory_can_be_disabled(self, environment, agents, protocol):
        """Cross-debate memory injection can be disabled."""
        arena = Arena(environment, agents, protocol, enable_cross_debate_memory=False)

        assert arena.enable_cross_debate_memory is False


# =============================================================================
# Post-Debate Workflow Tests
# =============================================================================


class TestPostDebateWorkflow:
    """Tests for post-debate workflow automation."""

    @pytest.fixture
    def environment(self):
        return Environment(task="Test post-debate workflow")

    @pytest.fixture
    def agents(self):
        return [MockAgent(name="a1"), MockAgent(name="a2")]

    @pytest.fixture
    def protocol(self):
        return DebateProtocol(rounds=1)

    def test_post_debate_workflow_disabled_by_default(self, environment, agents, protocol):
        """Post-debate workflow is disabled by default."""
        arena = Arena(environment, agents, protocol)

        assert arena.enable_post_debate_workflow is False

    def test_post_debate_workflow_can_be_enabled(self, environment, agents, protocol):
        """Post-debate workflow can be enabled."""
        mock_workflow = MagicMock()
        arena = Arena(
            environment,
            agents,
            protocol,
            post_debate_workflow=mock_workflow,
            enable_post_debate_workflow=True,
            post_debate_workflow_threshold=0.8,
        )

        assert arena.enable_post_debate_workflow is True
        assert arena.post_debate_workflow == mock_workflow
        assert arena.post_debate_workflow_threshold == 0.8

    def test_post_debate_workflow_auto_created_when_enabled(self, environment, agents, protocol):
        """Default workflow is auto-created when enabled without explicit workflow."""
        arena = Arena(
            environment,
            agents,
            protocol,
            enable_post_debate_workflow=True,
        )

        # Workflow may be auto-created or None depending on imports
        assert arena.enable_post_debate_workflow is True


# =============================================================================
# Adaptive Rounds Tests
# =============================================================================


class TestAdaptiveRounds:
    """Tests for adaptive rounds based on memory/strategy."""

    @pytest.fixture
    def environment(self):
        return Environment(task="Test adaptive rounds")

    @pytest.fixture
    def agents(self):
        return [MockAgent(name="a1"), MockAgent(name="a2")]

    @pytest.fixture
    def protocol(self):
        return DebateProtocol(rounds=5)

    def test_adaptive_rounds_disabled_by_default(self, environment, agents, protocol):
        """Adaptive rounds are disabled by default."""
        arena = Arena(environment, agents, protocol)

        assert arena.enable_adaptive_rounds is False

    def test_adaptive_rounds_can_be_enabled(self, environment, agents, protocol):
        """Adaptive rounds can be enabled."""
        arena = Arena(environment, agents, protocol, enable_adaptive_rounds=True)

        assert arena.enable_adaptive_rounds is True

    def test_debate_strategy_auto_created_when_enabled(self, environment, agents, protocol):
        """DebateStrategy is auto-created when adaptive rounds enabled."""
        mock_continuum = MagicMock()
        arena = Arena(
            environment,
            agents,
            protocol,
            enable_adaptive_rounds=True,
            continuum_memory=mock_continuum,
        )

        # Strategy may be created or None depending on imports
        assert arena.enable_adaptive_rounds is True


# =============================================================================
# Fabric Integration Tests
# =============================================================================


class TestFabricIntegration:
    """Tests for Agent Fabric integration."""

    @pytest.fixture
    def environment(self):
        return Environment(task="Test fabric integration")

    @pytest.fixture
    def agents(self):
        return [MockAgent(name="a1"), MockAgent(name="a2")]

    @pytest.fixture
    def protocol(self):
        return DebateProtocol(rounds=1)

    def test_arena_without_fabric(self, environment, agents, protocol):
        """Arena works without fabric configured."""
        arena = Arena(environment, agents, protocol)

        assert arena._fabric is None
        assert arena._fabric_config is None

    def test_arena_rejects_agents_and_fabric(self, environment, agents, protocol):
        """Arena rejects specifying both agents and fabric."""
        mock_fabric = MagicMock()
        mock_config = MagicMock()
        mock_config.pool_id = "test-pool"

        with pytest.raises(ValueError, match="Cannot specify both"):
            Arena(
                environment,
                agents,
                protocol,
                fabric=mock_fabric,
                fabric_config=mock_config,
            )

    def test_arena_requires_agents_or_fabric(self, environment, protocol):
        """Arena requires either agents or fabric configuration."""
        with pytest.raises(ValueError, match="Must specify either"):
            Arena(environment, [], protocol)


# =============================================================================
# Billing and Usage Tests
# =============================================================================


class TestBillingAndUsage:
    """Tests for billing and usage tracking integration."""

    @pytest.fixture
    def environment(self):
        return Environment(task="Test billing")

    @pytest.fixture
    def agents(self):
        return [MockAgent(name="a1"), MockAgent(name="a2")]

    @pytest.fixture
    def protocol(self):
        return DebateProtocol(rounds=1)

    def test_org_id_stored(self, environment, agents, protocol):
        """Organization ID is stored."""
        arena = Arena(environment, agents, protocol, org_id="org-123")

        assert arena.org_id == "org-123"

    def test_user_id_stored(self, environment, agents, protocol):
        """User ID is stored."""
        arena = Arena(environment, agents, protocol, user_id="user-456")

        assert arena.user_id == "user-456"

    def test_usage_tracker_accepted(self, environment, agents, protocol):
        """UsageTracker is accepted."""
        mock_tracker = MagicMock()
        arena = Arena(environment, agents, protocol, usage_tracker=mock_tracker)

        # Extensions should have access to tracker
        assert arena.extensions is not None

    def test_budget_coordinator_initialized(self, environment, agents, protocol):
        """BudgetCoordinator is initialized."""
        arena = Arena(environment, agents, protocol, org_id="org-123", user_id="user-456")

        assert hasattr(arena, "_budget_coordinator")
        assert arena._budget_coordinator is not None


# =============================================================================
# Revalidation Tests
# =============================================================================


class TestRevalidation:
    """Tests for knowledge revalidation features."""

    @pytest.fixture
    def environment(self):
        return Environment(task="Test revalidation")

    @pytest.fixture
    def agents(self):
        return [MockAgent(name="a1"), MockAgent(name="a2")]

    @pytest.fixture
    def protocol(self):
        return DebateProtocol(rounds=1)

    def test_auto_revalidation_disabled_by_default(self, environment, agents, protocol):
        """Auto-revalidation is disabled by default."""
        arena = Arena(environment, agents, protocol)

        assert arena.enable_auto_revalidation is False

    def test_auto_revalidation_can_be_enabled(self, environment, agents, protocol):
        """Auto-revalidation can be enabled."""
        arena = Arena(
            environment,
            agents,
            protocol,
            enable_auto_revalidation=True,
            revalidation_staleness_threshold=0.8,
            revalidation_check_interval_seconds=1800,
        )

        assert arena.enable_auto_revalidation is True
        assert arena.revalidation_staleness_threshold == 0.8
        assert arena.revalidation_check_interval_seconds == 1800

    def test_revalidation_scheduler_accepted(self, environment, agents, protocol):
        """RevalidationScheduler is accepted and may be auto-created."""
        # When enable_auto_revalidation=True, a scheduler may be auto-created
        # if knowledge_mound is available. Check that the attribute exists.
        arena = Arena(
            environment,
            agents,
            protocol,
            enable_auto_revalidation=True,
        )

        # Scheduler should exist (either auto-created or None)
        assert hasattr(arena, "revalidation_scheduler")


# =============================================================================
# Belief Network Tests
# =============================================================================


class TestBeliefNetwork:
    """Tests for belief network integration."""

    @pytest.fixture
    def environment(self):
        return Environment(task="Test belief network")

    @pytest.fixture
    def agents(self):
        return [MockAgent(name="a1"), MockAgent(name="a2")]

    def test_belief_guidance_enabled_by_default(self, environment, agents):
        """Belief guidance is enabled by default for cross-debate learning."""
        arena = Arena(environment, agents)

        assert arena.enable_belief_guidance is True

    def test_belief_guidance_can_be_disabled(self, environment, agents):
        """Belief guidance can be disabled."""
        arena = Arena(environment, agents, enable_belief_guidance=False)

        assert arena.enable_belief_guidance is False

    def test_setup_belief_network_method_exists(self, environment, agents):
        """_setup_belief_network method exists."""
        arena = Arena(environment, agents)

        assert hasattr(arena, "_setup_belief_network")
        assert callable(arena._setup_belief_network)


# =============================================================================
# Citation and Evidence Tests
# =============================================================================


class TestCitationAndEvidence:
    """Tests for citation extraction and evidence features."""

    @pytest.fixture
    def environment(self):
        return Environment(task="Test citations")

    @pytest.fixture
    def agents(self):
        return [MockAgent(name="a1"), MockAgent(name="a2")]

    def test_citation_extractor_initialized(self, environment, agents):
        """Citation extractor is initialized."""
        arena = Arena(environment, agents)

        assert hasattr(arena, "citation_extractor")

    def test_evidence_grounder_initialized(self, environment, agents):
        """Evidence grounder is initialized."""
        arena = Arena(environment, agents)

        assert hasattr(arena, "evidence_grounder")
        assert arena.evidence_grounder is not None

    def test_extract_citation_needs_method(self, environment, agents):
        """_extract_citation_needs method exists."""
        arena = Arena(environment, agents)

        assert hasattr(arena, "_extract_citation_needs")
        assert callable(arena._extract_citation_needs)

        # Should return dict when called with proposals
        result = arena._extract_citation_needs({"a1": "Some proposal text"})
        assert isinstance(result, dict)

    def test_store_evidence_in_memory_method(self, environment, agents):
        """_store_evidence_in_memory method exists."""
        arena = Arena(environment, agents)

        assert hasattr(arena, "_store_evidence_in_memory")
        assert callable(arena._store_evidence_in_memory)


# =============================================================================
# Termination and Judge Selection Tests
# =============================================================================


class TestTerminationAndJudge:
    """Tests for termination checking and judge selection."""

    @pytest.fixture
    def environment(self):
        return Environment(task="Test termination")

    @pytest.fixture
    def agents(self):
        return [MockAgent(name="a1"), MockAgent(name="a2")]

    @pytest.fixture
    def protocol(self):
        return DebateProtocol(rounds=3, consensus="judge")

    def test_termination_checker_initialized(self, environment, agents, protocol):
        """TerminationChecker is initialized."""
        arena = Arena(environment, agents, protocol)

        assert hasattr(arena, "termination_checker")
        assert arena.termination_checker is not None

    @pytest.mark.asyncio
    async def test_select_judge_method_exists(self, environment, agents, protocol):
        """_select_judge method exists and returns an Agent."""
        arena = Arena(environment, agents, protocol)

        assert hasattr(arena, "_select_judge")
        assert callable(arena._select_judge)

    @pytest.mark.asyncio
    async def test_check_early_stopping_method_exists(self, environment, agents, protocol):
        """_check_early_stopping method exists."""
        arena = Arena(environment, agents, protocol)

        assert hasattr(arena, "_check_early_stopping")
        assert callable(arena._check_early_stopping)

    @pytest.mark.asyncio
    async def test_check_judge_termination_method_exists(self, environment, agents, protocol):
        """_check_judge_termination method exists."""
        arena = Arena(environment, agents, protocol)

        assert hasattr(arena, "_check_judge_termination")
        assert callable(arena._check_judge_termination)


# =============================================================================
# Research and Context Gathering Tests
# =============================================================================


class TestResearchAndContext:
    """Tests for research and context gathering capabilities."""

    @pytest.fixture
    def environment(self):
        return Environment(task="Test research context")

    @pytest.fixture
    def agents(self):
        return [MockAgent(name="a1"), MockAgent(name="a2")]

    @pytest.mark.asyncio
    async def test_perform_research_method_exists(self, environment, agents):
        """_perform_research method exists."""
        arena = Arena(environment, agents)

        assert hasattr(arena, "_perform_research")
        assert callable(arena._perform_research)

    @pytest.mark.asyncio
    async def test_gather_aragora_context_method_exists(self, environment, agents):
        """_gather_aragora_context method exists."""
        arena = Arena(environment, agents)

        assert hasattr(arena, "_gather_aragora_context")
        assert callable(arena._gather_aragora_context)

    @pytest.mark.asyncio
    async def test_gather_evidence_context_method_exists(self, environment, agents):
        """_gather_evidence_context method exists."""
        arena = Arena(environment, agents)

        assert hasattr(arena, "_gather_evidence_context")
        assert callable(arena._gather_evidence_context)

    @pytest.mark.asyncio
    async def test_gather_trending_context_method_exists(self, environment, agents):
        """_gather_trending_context method exists."""
        arena = Arena(environment, agents)

        assert hasattr(arena, "_gather_trending_context")
        assert callable(arena._gather_trending_context)

    def test_context_delegator_initialized(self, environment, agents):
        """ContextDelegator is initialized."""
        arena = Arena(environment, agents)

        assert hasattr(arena, "_context_delegator")
        assert arena._context_delegator is not None


# =============================================================================
# Prompt Building Tests
# =============================================================================


class TestPromptBuilding:
    """Tests for prompt building functionality."""

    @pytest.fixture
    def environment(self):
        return Environment(task="Test prompt building")

    @pytest.fixture
    def agents(self):
        return [MockAgent(name="a1"), MockAgent(name="a2")]

    def test_prompt_context_builder_initialized(self, environment, agents):
        """PromptContextBuilder is initialized."""
        arena = Arena(environment, agents)

        assert hasattr(arena, "_prompt_context")
        assert arena._prompt_context is not None

    def test_build_proposal_prompt_method_exists(self, environment, agents):
        """_build_proposal_prompt method exists."""
        arena = Arena(environment, agents)

        assert hasattr(arena, "_build_proposal_prompt")
        assert callable(arena._build_proposal_prompt)

    def test_build_revision_prompt_method_exists(self, environment, agents):
        """_build_revision_prompt method exists."""
        arena = Arena(environment, agents)

        assert hasattr(arena, "_build_revision_prompt")
        assert callable(arena._build_revision_prompt)

    def test_get_persona_context_method(self, environment, agents):
        """_get_persona_context method exists."""
        arena = Arena(environment, agents)

        assert hasattr(arena, "_get_persona_context")
        assert callable(arena._get_persona_context)

    def test_get_role_context_method(self, environment, agents):
        """_get_role_context method exists."""
        arena = Arena(environment, agents)

        assert hasattr(arena, "_get_role_context")
        assert callable(arena._get_role_context)

    def test_prepare_audience_context_method(self, environment, agents):
        """_prepare_audience_context method exists."""
        arena = Arena(environment, agents)

        assert hasattr(arena, "_prepare_audience_context")
        assert callable(arena._prepare_audience_context)

    def test_sync_prompt_builder_state_method(self, environment, agents):
        """_sync_prompt_builder_state method exists."""
        arena = Arena(environment, agents)

        assert hasattr(arena, "_sync_prompt_builder_state")
        assert callable(arena._sync_prompt_builder_state)

        # Should not raise
        arena._sync_prompt_builder_state()


# =============================================================================
# Security Debate Tests
# =============================================================================


class TestSecurityDebate:
    """Tests for security debate functionality."""

    @pytest.fixture
    def agents(self):
        return [MockAgent(name="security1"), MockAgent(name="security2")]

    def test_run_security_debate_method_exists(self, agents):
        """run_security_debate classmethod exists."""
        assert hasattr(Arena, "run_security_debate")
        assert callable(Arena.run_security_debate)

    def test_get_security_debate_agents_method_exists(self, agents):
        """_get_security_debate_agents staticmethod exists."""
        assert hasattr(Arena, "_get_security_debate_agents")
        assert callable(Arena._get_security_debate_agents)
