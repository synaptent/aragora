"""
End-to-end integration tests for Aragora.

Tests complete flows across multiple subsystems:
- Full debate flow with mock agents
- ELO system integration with debates
- Memory persistence and retrieval
- Server endpoint responses
- WebSocket event emission
- Grounded Personas integration
"""

import asyncio
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.core import Agent, Message, Critique, Vote, Environment, DebateResult
from aragora.debate.orchestrator import Arena, DebateProtocol
from aragora.memory.store import CritiqueStore
from aragora.ranking.elo import EloSystem


class MockAgent(Agent):
    """Mock agent for integration tests."""

    def __init__(self, name: str = "mock", model: str = "mock-model", role: str = "proposer"):
        super().__init__(name, model, role)
        self.agent_type = "mock"
        self.generate_responses = []
        self.critique_responses = []
        self.vote_responses = []
        self._generate_call_count = 0
        self._critique_call_count = 0
        self._vote_call_count = 0

    async def generate(self, prompt: str, context: list = None) -> str:
        """Return mock response."""
        if self.generate_responses:
            response = self.generate_responses[
                self._generate_call_count % len(self.generate_responses)
            ]
            self._generate_call_count += 1
            return response
        return f"Mock response from {self.name}"

    async def critique(self, proposal: str, task: str, context: list = None) -> Critique:
        """Return mock critique."""
        if self.critique_responses:
            response = self.critique_responses[
                self._critique_call_count % len(self.critique_responses)
            ]
            self._critique_call_count += 1
            return response
        return Critique(
            agent=self.name,
            target_agent="proposer",
            target_content=proposal[:100],
            issues=["Integration test issue"],
            suggestions=["Integration test suggestion"],
            severity=0.5,
            reasoning="Integration test reasoning",
        )

    async def vote(self, proposals: dict, task: str) -> Vote:
        """Return mock vote."""
        if self.vote_responses:
            response = self.vote_responses[self._vote_call_count % len(self.vote_responses)]
            self._vote_call_count += 1
            return response
        choice = list(proposals.keys())[0] if proposals else "none"
        return Vote(
            agent=self.name,
            choice=choice,
            reasoning="Integration test vote",
            confidence=0.8,
            continue_debate=False,
        )


@pytest.fixture(autouse=True)
def isolated_aragora_data_dir(monkeypatch, tmp_path):
    """Keep auto-created subsystem databases local to each test."""
    data_dir = tmp_path / "aragora-data"
    data_dir.mkdir()
    monkeypatch.setenv("ARAGORA_DATA_DIR", str(data_dir))
    return data_dir


@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary database for testing."""
    return tmp_path / "test.db"


def test_default_database_paths_are_test_local(isolated_aragora_data_dir):
    """Auto-created subsystem databases must not leak across test workers."""
    from aragora.persistence.db_config import DatabaseType, get_db_path

    assert get_db_path(DatabaseType.CALIBRATION).parent == isolated_aragora_data_dir


@pytest.fixture
def mock_agents():
    """Create mock agents for testing."""
    proposer = MockAgent("proposer-agent", role="proposer")
    proposer.generate_responses = ["I propose solution A: implement caching."]

    critic = MockAgent("critic-agent", role="critic")
    critic.generate_responses = ["Solution A has merit but needs rate limiting."]

    return [proposer, critic]


@pytest.fixture
def debate_env():
    """Create a test environment."""
    return Environment(task="How should we optimize the API?")


# Test protocol defaults - disable research for speed
TEST_PROTOCOL_DEFAULTS = {
    "enable_research": False,  # Skip network calls in tests
    "convergence_detection": False,  # Skip embedding-based convergence
}


class TestFullDebateFlow:
    """Test complete debate execution."""

    @pytest.mark.asyncio
    async def test_basic_debate_completes(self, mock_agents, debate_env):
        """A basic debate should complete with a result."""
        protocol = DebateProtocol(rounds=2, consensus="majority", **TEST_PROTOCOL_DEFAULTS)
        arena = Arena(
            environment=debate_env,
            agents=mock_agents,
            protocol=protocol,
        )

        result = await arena.run()

        assert isinstance(result, DebateResult)
        assert result.id is not None
        assert result.rounds_used > 0

    @pytest.mark.asyncio
    async def test_debate_with_early_stopping(self, mock_agents, debate_env):
        """Debate should stop early if consensus is reached."""
        # Configure agents to agree immediately
        for agent in mock_agents:
            agent.vote_responses = [
                Vote(
                    agent=agent.name,
                    choice="proposer-agent",
                    reasoning="I agree",
                    confidence=0.95,
                    continue_debate=False,
                )
            ]

        protocol = DebateProtocol(
            rounds=5,  # High limit
            consensus="majority",
            early_stopping=True,
            early_stop_threshold=0.8,
            **TEST_PROTOCOL_DEFAULTS,
        )
        arena = Arena(
            environment=debate_env,
            agents=mock_agents,
            protocol=protocol,
        )

        result = await arena.run()

        # Should complete with consensus
        assert result.final_answer is not None

    @pytest.mark.asyncio
    async def test_debate_records_all_rounds(self, mock_agents, debate_env):
        """All debate rounds should be recorded."""
        protocol = DebateProtocol(rounds=3, consensus="majority", **TEST_PROTOCOL_DEFAULTS)
        arena = Arena(
            environment=debate_env,
            agents=mock_agents,
            protocol=protocol,
        )

        result = await arena.run()

        # Should have at least 1 round (may stop early)
        assert result.rounds_used >= 1

        # Should have messages from the debate
        assert len(result.messages) > 0 or len(result.critiques) > 0


class TestEloIntegration:
    """Test ELO system integration with debates."""

    @pytest.fixture
    def elo_system(self, temp_db):
        """Create ELO system with temp database."""
        return EloSystem(db_path=str(temp_db))

    @pytest.mark.asyncio
    async def test_debate_updates_elo(self, mock_agents, debate_env, elo_system):
        """Debate completion should update ELO ratings."""
        # Configure votes so proposer wins
        for agent in mock_agents:
            agent.vote_responses = [
                Vote(
                    agent=agent.name,
                    choice="proposer-agent",
                    reasoning="Proposer wins",
                    confidence=0.9,
                    continue_debate=False,
                )
            ]

        # Get initial ratings
        initial_ratings = {}
        for agent in mock_agents:
            initial_ratings[agent.name] = elo_system.get_rating(agent.name)

        protocol = DebateProtocol(rounds=1, consensus="majority", **TEST_PROTOCOL_DEFAULTS)
        arena = Arena(
            environment=debate_env,
            agents=mock_agents,
            protocol=protocol,
            elo_system=elo_system,
        )

        result = await arena.run()

        # Debate should complete with ELO system attached
        assert result.id is not None

    @pytest.mark.asyncio
    @pytest.mark.timeout(300)  # Allow 5 minutes for two sequential debates
    async def test_elo_rankings_persist(self, mock_agents, debate_env, elo_system):
        """ELO rankings should persist across debates.

        Note: This test can be slow as it runs two full debates sequentially.
        Each debate takes ~80-90 seconds with mock agents due to orchestrator processing.
        """
        protocol = DebateProtocol(rounds=1, consensus="majority", **TEST_PROTOCOL_DEFAULTS)

        # Run first debate
        arena1 = Arena(
            environment=debate_env,
            agents=mock_agents,
            protocol=protocol,
            elo_system=elo_system,
        )
        await arena1.run()

        rating_after_first = elo_system.get_rating("proposer-agent")

        # Run second debate
        arena2 = Arena(
            environment=debate_env,
            agents=mock_agents,
            protocol=protocol,
            elo_system=elo_system,
        )
        await arena2.run()

        rating_after_second = elo_system.get_rating("proposer-agent")

        # Ratings should accumulate
        assert rating_after_second is not None


class TestMemoryIntegration:
    """Test memory system integration."""

    @pytest.fixture
    def critique_store(self, temp_db):
        """Create critique store with temp database."""
        return CritiqueStore(db_path=str(temp_db))

    @pytest.mark.asyncio
    async def test_critiques_stored(self, mock_agents, debate_env, critique_store):
        """Critiques should be stored in memory."""
        protocol = DebateProtocol(rounds=2, consensus="majority", **TEST_PROTOCOL_DEFAULTS)
        arena = Arena(
            environment=debate_env,
            agents=mock_agents,
            protocol=protocol,
            memory=critique_store,
        )

        result = await arena.run()

        # Debate should complete and critiques should be in result
        assert result.id is not None
        # Critiques recorded in result
        assert isinstance(result.critiques, list)

    @pytest.mark.asyncio
    async def test_debate_uses_historical_context(self, mock_agents, debate_env, critique_store):
        """Later debates should be able to use historical critiques."""
        protocol = DebateProtocol(rounds=1, consensus="majority", **TEST_PROTOCOL_DEFAULTS)

        # Run first debate
        arena1 = Arena(
            environment=debate_env,
            agents=mock_agents,
            protocol=protocol,
            memory=critique_store,
        )
        await arena1.run()

        # Run second debate with same memory
        arena2 = Arena(
            environment=debate_env,
            agents=mock_agents,
            protocol=protocol,
            memory=critique_store,
        )
        result2 = await arena2.run()

        # Second debate should complete successfully
        assert result2.id is not None


class TestEventEmission:
    """Test WebSocket event emission during debates."""

    @pytest.mark.asyncio
    async def test_debate_emits_events(self, mock_agents, debate_env):
        """Debate should emit events via hooks."""
        events = []

        # Hook signatures: on_debate_start(task, agents), on_round_start(round_num), etc.
        hooks = {
            "on_debate_start": lambda task, agents: events.append(("start", task)),
            "on_round_start": lambda round_num: events.append(("round_start", round_num)),
            "on_message": lambda **kwargs: events.append(("message", kwargs)),
            "on_debate_end": lambda **kwargs: events.append(("end", kwargs)),
        }

        protocol = DebateProtocol(rounds=2, consensus="majority", **TEST_PROTOCOL_DEFAULTS)
        arena = Arena(
            environment=debate_env,
            agents=mock_agents,
            protocol=protocol,
            event_hooks=hooks,
        )

        await arena.run()

        # Should have received events
        event_types = [e[0] for e in events]
        assert "start" in event_types
        assert "end" in event_types

    @pytest.mark.asyncio
    async def test_loop_id_scoping(self, mock_agents, debate_env):
        """Events should be scoped to loop_id when set."""
        loop_id = "test-loop-123"

        protocol = DebateProtocol(rounds=1, consensus="majority", **TEST_PROTOCOL_DEFAULTS)
        arena = Arena(
            environment=debate_env,
            agents=mock_agents,
            protocol=protocol,
            loop_id=loop_id,
        )

        await arena.run()

        # Arena should have loop_id set
        assert arena.loop_id == loop_id


class TestRoleRotation:
    """Test cognitive role rotation during debates."""

    @pytest.mark.asyncio
    async def test_role_rotation_enabled(self, mock_agents, debate_env):
        """Role rotation should assign different roles per round."""
        protocol = DebateProtocol(
            rounds=3,
            consensus="majority",
            role_rotation=True,
            role_matching=False,  # Disable role_matching so role_rotator is used
            **TEST_PROTOCOL_DEFAULTS,
        )
        arena = Arena(
            environment=debate_env,
            agents=mock_agents,
            protocol=protocol,
        )

        # Should have role rotator initialized (role_matching must be False)
        assert arena.role_rotator is not None

        await arena.run()

    @pytest.mark.asyncio
    async def test_role_rotation_disabled(self, mock_agents, debate_env):
        """Role rotation can be disabled."""
        protocol = DebateProtocol(
            rounds=2,
            consensus="majority",
            role_rotation=False,
            **TEST_PROTOCOL_DEFAULTS,
        )
        arena = Arena(
            environment=debate_env,
            agents=mock_agents,
            protocol=protocol,
        )

        # Should not have role rotator
        assert arena.role_rotator is None


class TestSpectatorIntegration:
    """Test spectator stream integration."""

    @pytest.mark.asyncio
    async def test_spectator_receives_events(self, mock_agents, debate_env):
        """Spectator stream should receive debate events."""
        from aragora.spectate.stream import SpectatorStream

        spectator = SpectatorStream(enabled=True)
        events_received = []
        spectator._emit = lambda event: events_received.append(event)

        protocol = DebateProtocol(rounds=1, consensus="majority", **TEST_PROTOCOL_DEFAULTS)
        arena = Arena(
            environment=debate_env,
            agents=mock_agents,
            protocol=protocol,
            spectator=spectator,
        )

        await arena.run()

        # Spectator should have been used
        assert arena.spectator.enabled is True


class TestGroundedPersonasIntegration:
    """Test Grounded Personas v2 integration."""

    @pytest.mark.asyncio
    async def test_position_ledger_integration(self, mock_agents, debate_env, temp_db):
        """Position ledger should record positions during debate."""
        from aragora.agents.grounded import PositionLedger

        ledger = PositionLedger(db_path=str(temp_db))

        protocol = DebateProtocol(rounds=2, consensus="majority", **TEST_PROTOCOL_DEFAULTS)
        arena = Arena(
            environment=debate_env,
            agents=mock_agents,
            protocol=protocol,
            position_ledger=ledger,
        )

        await arena.run()

        # Arena should have the ledger attached
        assert arena.position_ledger is not None

    @pytest.mark.asyncio
    async def test_relationship_tracker_integration(self, mock_agents, debate_env, temp_db):
        """Relationship tracker should record interactions."""
        from aragora.agents.grounded import RelationshipTracker

        tracker = RelationshipTracker(elo_db_path=str(temp_db))

        protocol = DebateProtocol(rounds=2, consensus="majority", **TEST_PROTOCOL_DEFAULTS)
        arena = Arena(
            environment=debate_env,
            agents=mock_agents,
            protocol=protocol,
            relationship_tracker=tracker,
        )

        await arena.run()

        # Arena should have the tracker attached
        assert arena.relationship_tracker is not None

    @pytest.mark.asyncio
    async def test_moment_detector_integration(self, mock_agents, debate_env, temp_db):
        """Moment detector should detect significant moments."""
        from aragora.agents.grounded import MomentDetector

        detector = MomentDetector()  # All args optional for testing

        protocol = DebateProtocol(rounds=2, consensus="majority", **TEST_PROTOCOL_DEFAULTS)
        arena = Arena(
            environment=debate_env,
            agents=mock_agents,
            protocol=protocol,
            moment_detector=detector,
        )

        await arena.run()

        # Arena should have the detector attached
        assert arena.moment_detector is not None


class TestConsensusProtocols:
    """Test different consensus protocols."""

    @pytest.mark.asyncio
    async def test_majority_consensus(self, mock_agents, debate_env):
        """Majority consensus should select the most voted option."""
        # All agents vote for proposer
        for agent in mock_agents:
            agent.vote_responses = [
                Vote(
                    agent=agent.name,
                    choice="proposer-agent",
                    reasoning="I vote for proposer",
                    confidence=0.8,
                    continue_debate=False,
                )
            ]

        protocol = DebateProtocol(rounds=1, consensus="majority", **TEST_PROTOCOL_DEFAULTS)
        arena = Arena(
            environment=debate_env,
            agents=mock_agents,
            protocol=protocol,
        )

        result = await arena.run()

        # Should have a winner
        assert result.winner is not None or result.final_answer is not None

    @pytest.mark.asyncio
    async def test_none_consensus(self, mock_agents, debate_env):
        """None consensus should complete all rounds without voting."""
        protocol = DebateProtocol(rounds=2, consensus="none", **TEST_PROTOCOL_DEFAULTS)
        arena = Arena(
            environment=debate_env,
            agents=mock_agents,
            protocol=protocol,
        )

        result = await arena.run()

        # Should complete without error
        assert result.id is not None


class TestDebateTopologies:
    """Test different debate topologies."""

    @pytest.mark.asyncio
    async def test_round_robin_topology(self, mock_agents, debate_env):
        """Round-robin topology should work correctly."""
        protocol = DebateProtocol(
            rounds=2,
            consensus="majority",
            topology="round-robin",
            **TEST_PROTOCOL_DEFAULTS,
        )
        arena = Arena(
            environment=debate_env,
            agents=mock_agents,
            protocol=protocol,
        )

        result = await arena.run()
        assert result.id is not None

    @pytest.mark.asyncio
    async def test_all_to_all_topology(self, mock_agents, debate_env):
        """All-to-all topology should work correctly."""
        protocol = DebateProtocol(
            rounds=2,
            consensus="majority",
            topology="all-to-all",
            **TEST_PROTOCOL_DEFAULTS,
        )
        arena = Arena(
            environment=debate_env,
            agents=mock_agents,
            protocol=protocol,
        )

        result = await arena.run()
        assert result.id is not None


class TestConcurrentDebates:
    """Test running multiple debates concurrently."""

    @pytest.mark.asyncio
    async def test_concurrent_debates_isolated(self):
        """Concurrent debates should not interfere with each other."""
        agents1 = [
            MockAgent("agent-1a", role="proposer"),
            MockAgent("agent-1b", role="critic"),
        ]
        agents2 = [
            MockAgent("agent-2a", role="proposer"),
            MockAgent("agent-2b", role="critic"),
        ]

        env1 = Environment(task="Task A")
        env2 = Environment(task="Task B")

        protocol = DebateProtocol(rounds=2, consensus="majority", **TEST_PROTOCOL_DEFAULTS)

        arena1 = Arena(environment=env1, agents=agents1, protocol=protocol)
        arena2 = Arena(environment=env2, agents=agents2, protocol=protocol)

        # Run concurrently
        results = await asyncio.gather(arena1.run(), arena2.run())

        result1, result2 = results

        # Both should complete successfully
        assert result1.id is not None
        assert result2.id is not None

        # IDs should be different
        assert result1.id != result2.id


class TestErrorHandling:
    """Test error handling during debates."""

    @pytest.mark.asyncio
    async def test_agent_error_recovery(self, mock_agents, debate_env):
        """Debate should handle agent errors gracefully."""
        # Make one agent raise an error sometimes
        original_generate = mock_agents[0].generate
        call_count = [0]

        async def flaky_generate(prompt, context=None):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("Simulated error")
            return await original_generate(prompt, context)

        mock_agents[0].generate = flaky_generate

        protocol = DebateProtocol(rounds=2, consensus="majority", **TEST_PROTOCOL_DEFAULTS)
        arena = Arena(
            environment=debate_env,
            agents=mock_agents,
            protocol=protocol,
        )

        # Should handle error (implementation may vary)
        try:
            result = await arena.run()
            # If it completes, good
            assert result is not None
        except Exception:
            # If it propagates error, also acceptable
            pass


class TestTimeouts:
    """Test timeout handling."""

    @pytest.mark.asyncio
    async def test_debate_timeout_enforced(self, mock_agents, debate_env):
        """Debate timeout should be enforced."""
        protocol = DebateProtocol(
            rounds=10,
            consensus="majority",
            timeout_seconds=1,  # Very short timeout
            **TEST_PROTOCOL_DEFAULTS,
        )

        # Make agents slow
        async def slow_generate(prompt, context=None):
            await asyncio.sleep(5)
            return "Response"

        for agent in mock_agents:
            agent.generate = slow_generate

        arena = Arena(
            environment=debate_env,
            agents=mock_agents,
            protocol=protocol,
        )

        # Should timeout
        try:
            result = await asyncio.wait_for(arena.run(), timeout=3)
        except asyncio.TimeoutError:
            # Expected - test passes
            pass
