"""
Tests for ReplayAPI resource.

Tests cover:
- ReplayAPI.list() and list_async() for listing replays
- ReplayAPI.get() and get_async() for retrieving a replay
- ReplayAPI.delete() and delete_async() for deleting a replay
- Absence of the unserved export() and export_async() methods
- Response extraction logic for dict-wrapped and raw responses
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from aragora.client.client import AragoraClient
from aragora.client.models import Replay, ReplaySummary
from aragora.client.resources.replay import ReplayAPI


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_client() -> AragoraClient:
    """Create a mock AragoraClient."""
    client = MagicMock(spec=AragoraClient)
    return client


@pytest.fixture
def replay_api(mock_client: AragoraClient) -> ReplayAPI:
    """Create a ReplayAPI with mock client."""
    return ReplayAPI(mock_client)


@pytest.fixture
def sample_timestamp() -> str:
    """Sample ISO timestamp for tests."""
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def sample_replay_summary(sample_timestamp: str) -> dict:
    """Sample replay summary dict as returned by the API."""
    return {
        "replay_id": "rpl-001",
        "debate_id": "deb-100",
        "task": "Evaluate rate limiting strategies",
        "created_at": sample_timestamp,
        "duration_seconds": 120,
        "agent_count": 3,
        "round_count": 2,
    }


@pytest.fixture
def sample_replay(sample_timestamp: str) -> dict:
    """Sample full replay dict as returned by the API."""
    return {
        "replay_id": "rpl-001",
        "debate_id": "deb-100",
        "task": "Evaluate rate limiting strategies",
        "agents": ["claude", "gpt-4", "gemini"],
        "events": [
            {
                "event_type": "round_start",
                "timestamp": sample_timestamp,
                "agent_id": None,
                "content": "Round 1 started",
            },
            {
                "event_type": "agent_message",
                "timestamp": sample_timestamp,
                "agent_id": "claude",
                "content": "I propose token bucket...",
            },
        ],
        "consensus": {
            "reached": True,
            "agreement": 0.9,
            "final_answer": "Use token bucket with sliding window",
        },
        "created_at": sample_timestamp,
        "duration_seconds": 120,
    }


# ============================================================================
# ReplayAPI.list() Tests
# ============================================================================


class TestReplayAPIList:
    """Tests for ReplayAPI.list() method."""

    def test_list_basic(
        self,
        replay_api: ReplayAPI,
        mock_client: MagicMock,
        sample_replay_summary: dict,
    ):
        """Test list() returns ReplaySummary objects."""
        mock_client._get.return_value = {"replays": [sample_replay_summary]}

        result = replay_api.list()

        assert len(result) == 1
        assert isinstance(result[0], ReplaySummary)
        assert result[0].replay_id == "rpl-001"
        assert result[0].debate_id == "deb-100"
        assert result[0].agent_count == 3
        mock_client._get.assert_called_once_with("/api/replays", params={"limit": 20})

    def test_list_with_custom_limit(
        self,
        replay_api: ReplayAPI,
        mock_client: MagicMock,
    ):
        """Test list() passes custom limit parameter."""
        mock_client._get.return_value = {"replays": []}

        replay_api.list(limit=5)

        call_args = mock_client._get.call_args
        assert call_args[1]["params"]["limit"] == 5

    def test_list_with_debate_id_filter(
        self,
        replay_api: ReplayAPI,
        mock_client: MagicMock,
    ):
        """Test list() passes debate_id filter."""
        mock_client._get.return_value = {"replays": []}

        replay_api.list(debate_id="deb-filter")

        call_args = mock_client._get.call_args
        params = call_args[1]["params"]
        assert params["debate_id"] == "deb-filter"
        assert params["limit"] == 20

    def test_list_without_debate_id_omits_param(
        self,
        replay_api: ReplayAPI,
        mock_client: MagicMock,
    ):
        """Test list() omits debate_id when not provided."""
        mock_client._get.return_value = {"replays": []}

        replay_api.list()

        call_args = mock_client._get.call_args
        params = call_args[1]["params"]
        assert "debate_id" not in params

    def test_list_handles_array_response(
        self,
        replay_api: ReplayAPI,
        mock_client: MagicMock,
        sample_replay_summary: dict,
    ):
        """Test list() handles raw array response (no 'replays' wrapper)."""
        mock_client._get.return_value = [sample_replay_summary]

        result = replay_api.list()

        assert len(result) == 1
        assert result[0].replay_id == "rpl-001"

    def test_list_empty(
        self,
        replay_api: ReplayAPI,
        mock_client: MagicMock,
    ):
        """Test list() returns empty list when no replays."""
        mock_client._get.return_value = {"replays": []}

        result = replay_api.list()

        assert result == []

    def test_list_multiple_replays(
        self,
        replay_api: ReplayAPI,
        mock_client: MagicMock,
        sample_timestamp: str,
    ):
        """Test list() returns multiple ReplaySummary objects."""
        summaries = [
            {
                "replay_id": f"rpl-{i}",
                "debate_id": f"deb-{i}",
                "task": f"Task {i}",
                "created_at": sample_timestamp,
                "duration_seconds": i * 60,
                "agent_count": 2,
                "round_count": i,
            }
            for i in range(3)
        ]
        mock_client._get.return_value = {"replays": summaries}

        result = replay_api.list()

        assert len(result) == 3
        assert result[0].replay_id == "rpl-0"
        assert result[2].replay_id == "rpl-2"
        assert result[2].duration_seconds == 120


# ============================================================================
# ReplayAPI.list_async() Tests
# ============================================================================


class TestReplayAPIListAsync:
    """Tests for ReplayAPI.list_async() method."""

    @pytest.mark.asyncio
    async def test_list_async_basic(
        self,
        replay_api: ReplayAPI,
        mock_client: MagicMock,
        sample_replay_summary: dict,
    ):
        """Test list_async() returns ReplaySummary objects."""
        mock_client._get_async = AsyncMock(return_value={"replays": [sample_replay_summary]})

        result = await replay_api.list_async()

        assert len(result) == 1
        assert isinstance(result[0], ReplaySummary)
        assert result[0].replay_id == "rpl-001"

    @pytest.mark.asyncio
    async def test_list_async_with_debate_id(
        self,
        replay_api: ReplayAPI,
        mock_client: MagicMock,
    ):
        """Test list_async() passes debate_id filter."""
        mock_client._get_async = AsyncMock(return_value={"replays": []})

        await replay_api.list_async(limit=10, debate_id="deb-async")

        call_args = mock_client._get_async.call_args
        params = call_args[1]["params"]
        assert params["limit"] == 10
        assert params["debate_id"] == "deb-async"

    @pytest.mark.asyncio
    async def test_list_async_handles_array_response(
        self,
        replay_api: ReplayAPI,
        mock_client: MagicMock,
        sample_replay_summary: dict,
    ):
        """Test list_async() handles raw array response."""
        mock_client._get_async = AsyncMock(return_value=[sample_replay_summary])

        result = await replay_api.list_async()

        assert len(result) == 1
        assert result[0].replay_id == "rpl-001"


# ============================================================================
# ReplayAPI.get() Tests
# ============================================================================


class TestReplayAPIGet:
    """Tests for ReplayAPI.get() method."""

    def test_get_replay(
        self,
        replay_api: ReplayAPI,
        mock_client: MagicMock,
        sample_replay: dict,
    ):
        """Test get() retrieves full replay."""
        mock_client._get.return_value = sample_replay

        result = replay_api.get("rpl-001")

        assert isinstance(result, Replay)
        assert result.replay_id == "rpl-001"
        assert result.debate_id == "deb-100"
        assert result.task == "Evaluate rate limiting strategies"
        assert len(result.agents) == 3
        assert len(result.events) == 2
        assert result.consensus is not None
        assert result.consensus.reached is True
        assert result.duration_seconds == 120
        mock_client._get.assert_called_once_with("/api/replays/rpl-001")

    def test_get_replay_minimal(
        self,
        replay_api: ReplayAPI,
        mock_client: MagicMock,
        sample_timestamp: str,
    ):
        """Test get() with minimal replay data."""
        mock_client._get.return_value = {
            "replay_id": "rpl-min",
            "debate_id": "deb-min",
            "task": "Minimal replay",
            "created_at": sample_timestamp,
        }

        result = replay_api.get("rpl-min")

        assert result.replay_id == "rpl-min"
        assert result.agents == []
        assert result.events == []
        assert result.consensus is None

    def test_get_constructs_correct_url(
        self,
        replay_api: ReplayAPI,
        mock_client: MagicMock,
        sample_timestamp: str,
    ):
        """Test get() constructs the correct URL path."""
        mock_client._get.return_value = {
            "replay_id": "rpl-url-test",
            "debate_id": "deb-url",
            "task": "URL test",
            "created_at": sample_timestamp,
        }

        replay_api.get("rpl-url-test")

        mock_client._get.assert_called_once_with("/api/replays/rpl-url-test")


# ============================================================================
# ReplayAPI.get_async() Tests
# ============================================================================


class TestReplayAPIGetAsync:
    """Tests for ReplayAPI.get_async() method."""

    @pytest.mark.asyncio
    async def test_get_async(
        self,
        replay_api: ReplayAPI,
        mock_client: MagicMock,
        sample_replay: dict,
    ):
        """Test get_async() retrieves full replay."""
        mock_client._get_async = AsyncMock(return_value=sample_replay)

        result = await replay_api.get_async("rpl-001")

        assert isinstance(result, Replay)
        assert result.replay_id == "rpl-001"
        assert len(result.events) == 2
        mock_client._get_async.assert_called_once_with("/api/replays/rpl-001")


# ============================================================================
# ReplayAPI.delete() Tests
# ============================================================================


class TestReplayAPIDelete:
    """Tests for ReplayAPI.delete() method."""

    def test_delete_returns_true(
        self,
        replay_api: ReplayAPI,
        mock_client: MagicMock,
    ):
        """Test delete() returns True on success."""
        mock_client._delete.return_value = None

        result = replay_api.delete("rpl-del")

        assert result is True
        mock_client._delete.assert_called_once_with("/api/replays/rpl-del")

    def test_delete_constructs_correct_url(
        self,
        replay_api: ReplayAPI,
        mock_client: MagicMock,
    ):
        """Test delete() constructs the correct URL path."""
        mock_client._delete.return_value = None

        replay_api.delete("rpl-special-id")

        mock_client._delete.assert_called_once_with("/api/replays/rpl-special-id")


# ============================================================================
# ReplayAPI.delete_async() Tests
# ============================================================================


class TestReplayAPIDeleteAsync:
    """Tests for ReplayAPI.delete_async() method."""

    @pytest.mark.asyncio
    async def test_delete_async_returns_true(
        self,
        replay_api: ReplayAPI,
        mock_client: MagicMock,
    ):
        """Test delete_async() returns True on success."""
        mock_client._delete_async = AsyncMock(return_value=None)

        result = await replay_api.delete_async("rpl-async-del")

        assert result is True
        mock_client._delete_async.assert_called_once_with("/api/replays/rpl-async-del")


# ============================================================================
# Unserved export route
# ============================================================================


class TestReplayAPIUnservedExportRemoved:
    """No server route serves GET /api/replays/{replay_id}/export, so the client has no export."""

    @pytest.mark.parametrize("name", ["export", "export_async"])
    def test_export_methods_absent(self, replay_api: ReplayAPI, name: str):
        assert not hasattr(ReplayAPI, name)
        with pytest.raises(AttributeError):
            getattr(replay_api, name)

    @pytest.mark.parametrize(
        "name", ["list", "list_async", "get", "get_async", "delete", "delete_async"]
    )
    def test_served_methods_remain(self, name: str):
        assert callable(getattr(ReplayAPI, name))


# ============================================================================
# Integration-like Tests
# ============================================================================


class TestReplayAPIIntegration:
    """Integration-like tests combining multiple ReplayAPI operations."""

    def test_list_then_get_workflow(
        self,
        replay_api: ReplayAPI,
        mock_client: MagicMock,
        sample_timestamp: str,
        sample_replay: dict,
    ):
        """Test listing replays then getting full details."""
        # Step 1: List replays
        mock_client._get.return_value = {
            "replays": [
                {
                    "replay_id": "rpl-001",
                    "debate_id": "deb-100",
                    "task": "Rate limiting strategies",
                    "created_at": sample_timestamp,
                    "duration_seconds": 120,
                    "agent_count": 3,
                    "round_count": 2,
                },
            ]
        }
        summaries = replay_api.list()
        assert len(summaries) == 1
        replay_id = summaries[0].replay_id

        # Step 2: Get full replay
        mock_client._get.return_value = sample_replay
        full_replay = replay_api.get(replay_id)
        assert full_replay.replay_id == replay_id
        assert len(full_replay.events) == 2

    def test_get_then_delete_workflow(
        self,
        replay_api: ReplayAPI,
        mock_client: MagicMock,
        sample_replay: dict,
    ):
        """Test getting, then deleting a replay."""
        # Get
        mock_client._get.return_value = sample_replay
        replay = replay_api.get("rpl-001")
        assert replay.replay_id == "rpl-001"

        # Delete
        mock_client._delete.return_value = None
        deleted = replay_api.delete("rpl-001")
        assert deleted is True

    def test_list_filtered_by_debate(
        self,
        replay_api: ReplayAPI,
        mock_client: MagicMock,
        sample_timestamp: str,
    ):
        """Test filtering replays by debate_id."""
        target_debate = "deb-specific"
        mock_client._get.return_value = {
            "replays": [
                {
                    "replay_id": "rpl-filtered",
                    "debate_id": target_debate,
                    "task": "Filtered task",
                    "created_at": sample_timestamp,
                }
            ]
        }

        result = replay_api.list(debate_id=target_debate)

        assert len(result) == 1
        assert result[0].debate_id == target_debate
        call_args = mock_client._get.call_args
        assert call_args[1]["params"]["debate_id"] == target_debate
