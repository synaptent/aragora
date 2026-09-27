"""
Tests for aragora.persistence.supabase_client module.

Covers:
- SupabaseClient initialization and configuration
- NomicCycle operations (save, get, list)
- DebateArtifact operations (save, get, list)
- StreamEvent operations (save, batch save, get)
- AgentMetrics operations (save, get)
- Real-time subscriptions
- Analytics queries
"""

import os
from datetime import datetime
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from aragora.persistence.supabase_client import SupabaseClient, SUPABASE_AVAILABLE

from aragora.persistence.models import (
    NomicCycle,
    DebateArtifact,
    StreamEvent,
    AgentMetrics,
)


@pytest.fixture
def mock_supabase_client():
    """Create a mock Supabase client."""
    mock_client = MagicMock()
    mock_client.table = MagicMock(return_value=mock_client)
    mock_client.select = MagicMock(return_value=mock_client)
    mock_client.insert = MagicMock(return_value=mock_client)
    mock_client.update = MagicMock(return_value=mock_client)
    mock_client.eq = MagicMock(return_value=mock_client)
    mock_client.order = MagicMock(return_value=mock_client)
    mock_client.limit = MagicMock(return_value=mock_client)
    mock_client.offset = MagicMock(return_value=mock_client)
    mock_client.single = MagicMock(return_value=mock_client)
    mock_client.gte = MagicMock(return_value=mock_client)
    mock_client.execute = MagicMock()
    mock_client.channel = MagicMock()
    return mock_client


@pytest.fixture
def client_with_mock(mock_supabase_client):
    """Create a SupabaseClient with mocked Supabase client."""
    with patch.dict(
        os.environ, {"SUPABASE_URL": "https://test.supabase.co", "SUPABASE_KEY": "test-key"}
    ):
        with patch(
            "aragora.persistence.supabase_client.create_client", return_value=mock_supabase_client
        ):
            with patch("aragora.persistence.supabase_client.SUPABASE_AVAILABLE", True):
                client = SupabaseClient()
                return client


@pytest.fixture
def sample_cycle():
    """Create a sample NomicCycle."""
    return NomicCycle(
        id="cycle-123",
        loop_id="loop-456",
        cycle_number=1,
        phase="debate",
        stage="running",
        started_at=datetime(2024, 1, 1, 12, 0, 0),
        completed_at=None,
        success=None,
        git_commit="abc123",
        task_description="Test task",
        total_tasks=5,
        completed_tasks=2,
        error_message=None,
    )


@pytest.fixture
def sample_debate():
    """Create a sample DebateArtifact."""
    return DebateArtifact(
        id="debate-123",
        loop_id="loop-456",
        cycle_number=1,
        phase="debate",
        task="Discuss implementation",
        agents=["agent1", "agent2"],
        transcript=[{"role": "agent1", "content": "Hello"}],
        consensus_reached=True,
        confidence=0.85,
        winning_proposal="Proposal A",
        vote_tally={"agent1": 1, "agent2": 1},
        created_at=datetime(2024, 1, 1, 12, 0, 0),
    )


@pytest.fixture
def sample_event():
    """Create a sample StreamEvent."""
    return StreamEvent(
        id="event-123",
        loop_id="loop-456",
        cycle=1,
        event_type="agent_message",
        event_data={"content": "Test message"},
        agent="agent1",
        timestamp=datetime(2024, 1, 1, 12, 0, 0),
    )


@pytest.fixture
def sample_metrics():
    """Create sample AgentMetrics."""
    return AgentMetrics(
        id="metrics-123",
        loop_id="loop-456",
        cycle=1,
        agent_name="agent1",
        model="gpt-4",
        phase="debate",
        messages_sent=10,
        proposals_made=2,
        critiques_given=5,
        votes_won=1,
        votes_received=3,
        consensus_contributions=2,
        avg_response_time_ms=500.0,
        timestamp=datetime(2024, 1, 1, 12, 0, 0),
    )


class TestSupabaseClientInitialization:
    """Tests for SupabaseClient initialization."""

    def test_init_without_credentials(self):
        """Client should initialize with client=None if no credentials."""
        # Remove only SUPABASE_* keys rather than stubbing os.environ.get:
        # constructing the client triggers the lazy supabase -> websockets
        # import, and websockets.frames evaluates
        # int(os.environ.get("WEBSOCKETS_MAX_LOG_SIZE", "75")) at import time,
        # which raises TypeError if get() is forced to return None globally.
        env_without_supabase = {
            k: v for k, v in os.environ.items() if not k.startswith("SUPABASE_")
        }
        with patch.dict(os.environ, env_without_supabase, clear=True):
            client = SupabaseClient(url=None, key=None)
            # Either client is None or is_configured is False
            assert not client.is_configured or client.client is None

    def test_init_with_env_vars(self, mock_supabase_client):
        """Client should use environment variables."""
        with patch.dict(
            os.environ,
            {
                "SUPABASE_URL": "https://test.supabase.co",
                "SUPABASE_KEY": "test-key",
            },
        ):
            with patch(
                "aragora.persistence.supabase_client.create_client",
                return_value=mock_supabase_client,
            ):
                client = SupabaseClient()
                assert client.url == "https://test.supabase.co"
                assert client.key == "test-key"

    def test_init_with_explicit_args(self, mock_supabase_client):
        """Client should use explicit arguments over env vars."""
        with patch.dict(
            os.environ,
            {
                "SUPABASE_URL": "https://env.supabase.co",
                "SUPABASE_KEY": "env-key",
            },
        ):
            with patch(
                "aragora.persistence.supabase_client.create_client",
                return_value=mock_supabase_client,
            ):
                client = SupabaseClient(
                    url="https://explicit.supabase.co",
                    key="explicit-key",
                )
                assert client.url == "https://explicit.supabase.co"
                assert client.key == "explicit-key"

    def test_is_configured_true_with_client(self, client_with_mock):
        """is_configured should be True when client is set."""
        assert client_with_mock.is_configured is True

    def test_is_configured_false_without_client(self):
        """is_configured should be False when client is None."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("aragora.persistence.supabase_client.SUPABASE_AVAILABLE", True):
                client = SupabaseClient(url=None, key=None)
                assert client.is_configured is False


class TestNomicCycleOperations:
    """Tests for NomicCycle operations."""

    @pytest.mark.asyncio
    async def test_save_cycle_insert(self, client_with_mock, sample_cycle, mock_supabase_client):
        """save_cycle should insert new cycle without id."""
        sample_cycle.id = None
        mock_supabase_client.execute.return_value = MagicMock(data=[{"id": "new-id"}])

        result = await client_with_mock.save_cycle(sample_cycle)

        assert result == "new-id"
        mock_supabase_client.table.assert_called_with("nomic_cycles")

    @pytest.mark.asyncio
    async def test_save_cycle_update(self, client_with_mock, sample_cycle, mock_supabase_client):
        """save_cycle should update existing cycle with id."""
        mock_supabase_client.execute.return_value = MagicMock(data=[{"id": "cycle-123"}])

        result = await client_with_mock.save_cycle(sample_cycle)

        assert result == "cycle-123"

    @pytest.mark.asyncio
    async def test_save_cycle_not_configured(self, sample_cycle):
        """save_cycle should return None if not configured."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("aragora.persistence.supabase_client.SUPABASE_AVAILABLE", True):
                client = SupabaseClient(url=None, key=None)
                result = await client.save_cycle(sample_cycle)
                assert result is None

    @pytest.mark.asyncio
    async def test_save_cycle_exception(self, client_with_mock, sample_cycle, mock_supabase_client):
        """save_cycle should return None on exception."""
        mock_supabase_client.execute.side_effect = RuntimeError("Database error")

        result = await client_with_mock.save_cycle(sample_cycle)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_cycle_found(self, client_with_mock, mock_supabase_client):
        """get_cycle should return cycle when found."""
        mock_supabase_client.execute.return_value = MagicMock(
            data={
                "id": "cycle-123",
                "loop_id": "loop-456",
                "cycle_number": 1,
                "phase": "debate",
                "stage": "running",
                "started_at": "2024-01-01T12:00:00Z",
                "completed_at": None,
                "success": None,
            }
        )

        result = await client_with_mock.get_cycle("loop-456", 1)

        assert result is not None
        assert result.loop_id == "loop-456"
        assert result.cycle_number == 1

    @pytest.mark.asyncio
    async def test_get_cycle_not_found(self, client_with_mock, mock_supabase_client):
        """get_cycle should return None when not found."""
        mock_supabase_client.execute.return_value = MagicMock(data=None)

        result = await client_with_mock.get_cycle("loop-456", 999)

        assert result is None

    @pytest.mark.asyncio
    async def test_list_cycles(self, client_with_mock, mock_supabase_client):
        """list_cycles should return list of cycles."""
        mock_supabase_client.execute.return_value = MagicMock(
            data=[
                {
                    "id": "cycle-1",
                    "loop_id": "loop-456",
                    "cycle_number": 1,
                    "phase": "debate",
                    "started_at": "2024-01-01T12:00:00Z",
                },
                {
                    "id": "cycle-2",
                    "loop_id": "loop-456",
                    "cycle_number": 2,
                    "phase": "implement",
                    "started_at": "2024-01-02T12:00:00Z",
                },
            ]
        )

        result = await client_with_mock.list_cycles(loop_id="loop-456")

        assert len(result) == 2
        assert result[0].cycle_number == 1
        assert result[1].cycle_number == 2

    @pytest.mark.asyncio
    async def test_list_cycles_empty(self, client_with_mock, mock_supabase_client):
        """list_cycles should return empty list when none found."""
        mock_supabase_client.execute.return_value = MagicMock(data=[])

        result = await client_with_mock.list_cycles()

        assert result == []


class TestDebateArtifactOperations:
    """Tests for DebateArtifact operations."""

    @pytest.mark.asyncio
    async def test_save_debate(self, client_with_mock, sample_debate, mock_supabase_client):
        """save_debate should insert and return id."""
        mock_supabase_client.execute.return_value = MagicMock(data=[{"id": "debate-123"}])

        result = await client_with_mock.save_debate(sample_debate)

        assert result == "debate-123"
        mock_supabase_client.table.assert_called_with("debate_artifacts")

    @pytest.mark.asyncio
    async def test_save_debate_not_configured(self, sample_debate):
        """save_debate should return None if not configured."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("aragora.persistence.supabase_client.SUPABASE_AVAILABLE", True):
                client = SupabaseClient(url=None, key=None)
                result = await client.save_debate(sample_debate)
                assert result is None

    @pytest.mark.asyncio
    async def test_get_debate_found(self, client_with_mock, mock_supabase_client):
        """get_debate should return debate when found."""
        mock_supabase_client.execute.return_value = MagicMock(
            data={
                "id": "debate-123",
                "loop_id": "loop-456",
                "cycle_number": 1,
                "phase": "debate",
                "task": "Test task",
                "agents": ["agent1"],
                "transcript": [],
                "consensus_reached": True,
                "confidence": 0.8,
                "created_at": "2024-01-01T12:00:00Z",
            }
        )

        result = await client_with_mock.get_debate("debate-123")

        assert result is not None
        assert result.id == "debate-123"
        assert result.consensus_reached is True

    @pytest.mark.asyncio
    async def test_list_debates_with_filters(self, client_with_mock, mock_supabase_client):
        """list_debates should apply filters."""
        mock_supabase_client.execute.return_value = MagicMock(
            data=[
                {
                    "id": "debate-1",
                    "loop_id": "loop-456",
                    "cycle_number": 1,
                    "phase": "debate",
                    "task": "Task 1",
                    "agents": [],
                    "transcript": [],
                    "consensus_reached": True,
                    "confidence": 0.9,
                    "created_at": "2024-01-01T12:00:00Z",
                },
            ]
        )

        result = await client_with_mock.list_debates(loop_id="loop-456", phase="debate")

        assert len(result) == 1


class TestStreamEventOperations:
    """Tests for StreamEvent operations."""

    @pytest.mark.asyncio
    async def test_save_event(self, client_with_mock, sample_event, mock_supabase_client):
        """save_event should insert and return id."""
        mock_supabase_client.execute.return_value = MagicMock(data=[{"id": "event-123"}])

        result = await client_with_mock.save_event(sample_event)

        assert result == "event-123"
        mock_supabase_client.table.assert_called_with("stream_events")

    @pytest.mark.asyncio
    async def test_save_event_not_configured(self, sample_event):
        """save_event should return None if not configured."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("aragora.persistence.supabase_client.SUPABASE_AVAILABLE", True):
                client = SupabaseClient(url=None, key=None)
                result = await client.save_event(sample_event)
                assert result is None

    @pytest.mark.asyncio
    async def test_save_events_batch(self, client_with_mock, mock_supabase_client):
        """save_events_batch should insert multiple events."""
        events = [
            StreamEvent(
                loop_id="loop-456",
                cycle=1,
                event_type="message",
                event_data={},
                timestamp=datetime.now(),
            )
            for _ in range(3)
        ]
        mock_supabase_client.execute.return_value = MagicMock(data=[{}, {}, {}])

        result = await client_with_mock.save_events_batch(events)

        assert result == 3

    @pytest.mark.asyncio
    async def test_save_events_batch_empty(self, client_with_mock):
        """save_events_batch should return 0 for empty list."""
        result = await client_with_mock.save_events_batch([])
        assert result == 0

    @pytest.mark.asyncio
    async def test_get_events_with_filters(self, client_with_mock, mock_supabase_client):
        """get_events should apply all filters."""
        mock_supabase_client.execute.return_value = MagicMock(
            data=[
                {
                    "id": "event-1",
                    "loop_id": "loop-456",
                    "cycle": 1,
                    "event_type": "message",
                    "event_data": {},
                    "timestamp": "2024-01-01T12:00:00Z",
                },
            ]
        )

        result = await client_with_mock.get_events(
            loop_id="loop-456",
            cycle=1,
            event_type="message",
            since=datetime(2024, 1, 1),
        )

        assert len(result) == 1


class TestAgentMetricsOperations:
    """Tests for AgentMetrics operations."""

    @pytest.mark.asyncio
    async def test_save_metrics(self, client_with_mock, sample_metrics, mock_supabase_client):
        """save_metrics should insert and return id."""
        mock_supabase_client.execute.return_value = MagicMock(data=[{"id": "metrics-123"}])

        result = await client_with_mock.save_metrics(sample_metrics)

        assert result == "metrics-123"
        mock_supabase_client.table.assert_called_with("agent_metrics")

    @pytest.mark.asyncio
    async def test_save_metrics_not_configured(self, sample_metrics):
        """save_metrics should return None if not configured."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("aragora.persistence.supabase_client.SUPABASE_AVAILABLE", True):
                client = SupabaseClient(url=None, key=None)
                result = await client.save_metrics(sample_metrics)
                assert result is None

    @pytest.mark.asyncio
    async def test_get_agent_stats(self, client_with_mock, mock_supabase_client):
        """get_agent_stats should return list of metrics."""
        mock_supabase_client.execute.return_value = MagicMock(
            data=[
                {
                    "id": "metrics-1",
                    "loop_id": "loop-456",
                    "cycle": 1,
                    "agent_name": "agent1",
                    "model": "gpt-4",
                    "phase": "debate",
                    "messages_sent": 10,
                    "proposals_made": 2,
                    "critiques_given": 5,
                    "votes_won": 1,
                    "votes_received": 3,
                    "consensus_contributions": 2,
                    "avg_response_time_ms": 500.0,
                    "timestamp": "2024-01-01T12:00:00Z",
                },
            ]
        )

        result = await client_with_mock.get_agent_stats("agent1")

        assert len(result) == 1
        assert result[0].agent_name == "agent1"
        assert result[0].messages_sent == 10


class TestRealtimeSubscriptions:
    """Tests for real-time subscription functionality."""

    def test_subscribe_to_events(self, client_with_mock, mock_supabase_client):
        """subscribe_to_events should create channel subscription."""
        mock_channel = MagicMock()
        mock_channel.on_postgres_changes = MagicMock(return_value=mock_channel)
        mock_channel.subscribe = MagicMock()
        mock_supabase_client.channel.return_value = mock_channel

        callback = MagicMock()
        result = client_with_mock.subscribe_to_events("loop-456", callback)

        assert result is not None
        mock_supabase_client.channel.assert_called_with("events:loop-456")

    def test_subscribe_to_events_not_configured(self):
        """subscribe_to_events should return None if not configured."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("aragora.persistence.supabase_client.SUPABASE_AVAILABLE", True):
                client = SupabaseClient(url=None, key=None)
                result = client.subscribe_to_events("loop-456", lambda x: None)
                assert result is None


class TestAnalyticsQueries:
    """Tests for analytics query functionality."""

    @pytest.mark.asyncio
    async def test_get_loop_summary(self, client_with_mock, mock_supabase_client):
        """get_loop_summary should calculate statistics."""
        # Mock cycles response
        cycles_data = [
            {
                "id": "cycle-1",
                "loop_id": "loop-456",
                "cycle_number": 1,
                "phase": "debate",
                "started_at": "2024-01-01T12:00:00Z",
                "success": True,
            },
            {
                "id": "cycle-2",
                "loop_id": "loop-456",
                "cycle_number": 2,
                "phase": "implement",
                "started_at": "2024-01-02T12:00:00Z",
                "success": False,
            },
        ]

        # Mock debates response
        debates_data = [
            {
                "id": "debate-1",
                "loop_id": "loop-456",
                "cycle_number": 1,
                "phase": "debate",
                "task": "Task 1",
                "agents": [],
                "transcript": [],
                "consensus_reached": True,
                "confidence": 0.9,
                "created_at": "2024-01-01T12:00:00Z",
            },
            {
                "id": "debate-2",
                "loop_id": "loop-456",
                "cycle_number": 2,
                "phase": "debate",
                "task": "Task 2",
                "agents": [],
                "transcript": [],
                "consensus_reached": False,
                "confidence": 0.5,
                "created_at": "2024-01-02T12:00:00Z",
            },
        ]

        mock_supabase_client.execute.side_effect = [
            MagicMock(data=cycles_data),  # list_cycles
            MagicMock(data=debates_data),  # list_debates
        ]

        result = await client_with_mock.get_loop_summary("loop-456")

        assert result["loop_id"] == "loop-456"
        assert result["total_cycles"] == 2
        assert result["successful_cycles"] == 1
        assert result["total_debates"] == 2
        assert result["consensus_rate"] == 0.5

    @pytest.mark.asyncio
    async def test_get_loop_summary_not_configured(self):
        """get_loop_summary should return empty dict if not configured."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("aragora.persistence.supabase_client.SUPABASE_AVAILABLE", True):
                client = SupabaseClient(url=None, key=None)
                result = await client.get_loop_summary("loop-456")
                assert result == {}

    @pytest.mark.asyncio
    async def test_get_loop_summary_exception(self, client_with_mock, mock_supabase_client):
        """get_loop_summary should handle exceptions from sub-queries gracefully."""
        # list_cycles and list_debates catch exceptions and return empty lists,
        # so get_loop_summary returns stats computed from empty data
        mock_supabase_client.execute.side_effect = RuntimeError("Database error")

        result = await client_with_mock.get_loop_summary("loop-456")

        # With empty cycles/debates, should still return valid structure
        assert result["loop_id"] == "loop-456"
        assert result["total_cycles"] == 0
        assert result["total_debates"] == 0


class TestDictToModelConversions:
    """Tests for database dict to model conversions."""

    def test_dict_to_cycle_with_all_fields(self, client_with_mock):
        """_dict_to_cycle should handle all fields."""
        data = {
            "id": "cycle-123",
            "loop_id": "loop-456",
            "cycle_number": 5,
            "phase": "verify",
            "stage": "testing",
            "started_at": "2024-01-01T12:00:00Z",
            "completed_at": "2024-01-01T13:00:00Z",
            "success": True,
            "git_commit": "abc123",
            "task_description": "Test task",
            "total_tasks": 10,
            "completed_tasks": 8,
            "error_message": None,
        }

        result = client_with_mock._dict_to_cycle(data)

        assert result.id == "cycle-123"
        assert result.cycle_number == 5
        assert result.phase == "verify"
        assert result.success is True
        assert result.total_tasks == 10

    def test_dict_to_cycle_with_invalid_datetime(self, client_with_mock):
        """_dict_to_cycle should handle invalid datetime gracefully."""
        data = {
            "id": "cycle-123",
            "loop_id": "loop-456",
            "cycle_number": 1,
            "phase": "debate",
            "started_at": "invalid-date",
            "completed_at": "also-invalid",
        }

        result = client_with_mock._dict_to_cycle(data)

        # Should use fallback datetime
        assert result.started_at is not None
        assert result.completed_at is None

    def test_dict_to_debate(self, client_with_mock):
        """_dict_to_debate should convert all fields."""
        data = {
            "id": "debate-123",
            "loop_id": "loop-456",
            "cycle_number": 1,
            "phase": "debate",
            "task": "Test task",
            "agents": ["agent1", "agent2"],
            "transcript": [{"role": "agent1", "content": "Hello"}],
            "consensus_reached": True,
            "confidence": 0.95,
            "winning_proposal": "Proposal A",
            "vote_tally": {"agent1": 1},
            "created_at": "2024-01-01T12:00:00Z",
        }

        result = client_with_mock._dict_to_debate(data)

        assert result.id == "debate-123"
        assert result.consensus_reached is True
        assert result.confidence == 0.95
        assert len(result.agents) == 2

    def test_dict_to_event(self, client_with_mock):
        """_dict_to_event should convert all fields."""
        data = {
            "id": "event-123",
            "loop_id": "loop-456",
            "cycle": 1,
            "event_type": "agent_message",
            "event_data": {"content": "Test"},
            "agent": "agent1",
            "timestamp": "2024-01-01T12:00:00Z",
        }

        result = client_with_mock._dict_to_event(data)

        assert result.id == "event-123"
        assert result.event_type == "agent_message"
        assert result.agent == "agent1"

    def test_dict_to_metrics(self, client_with_mock):
        """_dict_to_metrics should convert all fields."""
        data = {
            "id": "metrics-123",
            "loop_id": "loop-456",
            "cycle": 1,
            "agent_name": "agent1",
            "model": "gpt-4",
            "phase": "debate",
            "messages_sent": 10,
            "proposals_made": 2,
            "critiques_given": 5,
            "votes_won": 1,
            "votes_received": 3,
            "consensus_contributions": 2,
            "avg_response_time_ms": 500.0,
            "timestamp": "2024-01-01T12:00:00Z",
        }

        result = client_with_mock._dict_to_metrics(data)

        assert result.id == "metrics-123"
        assert result.agent_name == "agent1"
        assert result.messages_sent == 10
        assert result.avg_response_time_ms == 500.0


class TestSupabaseNotAvailable:
    """Tests when supabase package is not installed."""

    def test_init_without_supabase_package(self):
        """Client should handle missing supabase package gracefully."""
        with patch("aragora.persistence.supabase_client.SUPABASE_AVAILABLE", False):
            # Re-import to get new behavior
            client = SupabaseClient()
            assert client.client is None
            assert not client.is_configured


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_save_debate_no_data_returned(
        self, client_with_mock, sample_debate, mock_supabase_client
    ):
        """save_debate should return None if no data in response."""
        mock_supabase_client.execute.return_value = MagicMock(data=None)

        result = await client_with_mock.save_debate(sample_debate)

        assert result is None

    @pytest.mark.asyncio
    async def test_save_events_batch_exception(self, client_with_mock, mock_supabase_client):
        """save_events_batch should return 0 on exception."""
        events = [
            StreamEvent(
                loop_id="loop-456",
                cycle=1,
                event_type="message",
                event_data={},
                timestamp=datetime.now(),
            )
        ]
        mock_supabase_client.execute.side_effect = RuntimeError("Batch insert failed")

        result = await client_with_mock.save_events_batch(events)

        assert result == 0

    @pytest.mark.asyncio
    async def test_get_events_exception(self, client_with_mock, mock_supabase_client):
        """get_events should return empty list on exception."""
        mock_supabase_client.execute.side_effect = RuntimeError("Query failed")

        result = await client_with_mock.get_events("loop-456")

        assert result == []

    @pytest.mark.asyncio
    async def test_get_agent_stats_exception(self, client_with_mock, mock_supabase_client):
        """get_agent_stats should return empty list on exception."""
        mock_supabase_client.execute.side_effect = RuntimeError("Query failed")

        result = await client_with_mock.get_agent_stats("agent1")

        assert result == []

    def test_subscribe_to_events_exception(self, client_with_mock, mock_supabase_client):
        """subscribe_to_events should return None on exception."""
        mock_supabase_client.channel.side_effect = RuntimeError("Channel creation failed")

        result = client_with_mock.subscribe_to_events("loop-456", lambda x: None)

        assert result is None
