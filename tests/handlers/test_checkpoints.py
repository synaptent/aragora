"""Tests for checkpoint handler (aragora/server/handlers/checkpoints.py).

Covers all routes and behavior of the CheckpointHandler class:
- can_handle() routing for all checkpoint endpoints
- GET /api/v1/checkpoints - List all checkpoints with filtering
- GET /api/v1/checkpoints/resumable - List resumable debates
- GET /api/v1/checkpoints/{id} - Get checkpoint details
- POST /api/v1/checkpoints/{id}/resume - Resume from checkpoint
- DELETE /api/v1/checkpoints/{id} - Delete checkpoint
- POST /api/v1/checkpoints/{id}/intervention - Add intervention note
- GET /api/v1/debates/{id}/checkpoints - List checkpoints for a debate
- POST /api/v1/debates/{id}/checkpoint - Create checkpoint for debate
- POST /api/v1/debates/{id}/checkpoint/pause - Pause debate with checkpoint
- Error handling (not found, bad state, missing params)
- Rate limiting
- Edge cases (empty lists, pagination, message conversion)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.checkpoints import CheckpointHandler

pytestmark = pytest.mark.usefixtures("org_scoped_request_user")

# The org ``org_scoped_request_user`` authenticates every request as.
ORG_ID = "test-org-001"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result) -> dict:
    """Extract JSON body dict from a HandlerResult."""
    if isinstance(result, dict):
        return result
    raw = result.body
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def _status(result) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return result.status_code


# ---------------------------------------------------------------------------
# Mock objects
# ---------------------------------------------------------------------------


@dataclass
class MockDebateCheckpoint:
    """Mock DebateCheckpoint for testing."""

    checkpoint_id: str = "cp-debate01-001-abcd"
    debate_id: str = "debate-001"
    task: str = "Design a rate limiter"
    current_round: int = 2
    total_rounds: int = 5
    phase: str = "proposal"
    messages: list = field(default_factory=list)
    critiques: list = field(default_factory=list)
    votes: list = field(default_factory=list)
    agent_states: list = field(default_factory=list)
    current_consensus: str | None = None
    status: str = "complete"
    created_at: str = "2026-01-15T10:00:00"
    checksum: str = "abc123"
    metadata: dict | None = None
    resume_count: int = 0
    pending_intervention: bool = False
    intervention_notes: list = field(default_factory=list)
    _integrity_valid: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "debate_id": self.debate_id,
            "task": self.task,
            "current_round": self.current_round,
            "total_rounds": self.total_rounds,
            "phase": self.phase,
            "messages": self.messages,
            "critiques": self.critiques,
            "votes": self.votes,
            "status": self.status,
            "created_at": self.created_at,
            "checksum": self.checksum,
            "resume_count": self.resume_count,
            "pending_intervention": self.pending_intervention,
            "intervention_notes": self.intervention_notes,
        }

    def verify_integrity(self) -> bool:
        return self._integrity_valid


@dataclass
class MockResumedDebate:
    """Mock ResumedDebate for testing."""

    original_debate_id: str = "debate-001"
    resumed_at: str = "2026-01-15T12:00:00"
    resumed_by: str = "api"
    messages: list = field(default_factory=list)
    votes: list = field(default_factory=list)
    checkpoint: MockDebateCheckpoint = field(default_factory=MockDebateCheckpoint)


@dataclass
class MockDebateState:
    """Mock DebateState for create_checkpoint / pause_debate."""

    debate_id: str = "debate-001"
    task: str = "Design a rate limiter"
    status: str = "running"
    current_round: int = 2
    total_rounds: int = 5
    messages: list = field(default_factory=list)
    agents: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class MockMessageWithToDict:
    """Mock message with to_dict method."""

    def to_dict(self):
        return {"content": "message via to_dict", "role": "assistant"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_store():
    """Create a mock checkpoint store."""
    store = AsyncMock()
    store.list_checkpoints = AsyncMock(return_value=[])
    store.load = AsyncMock(return_value=MockDebateCheckpoint())
    store.save = AsyncMock(return_value="path/to/checkpoint")
    store.delete = AsyncMock(return_value=True)
    return store


@pytest.fixture
def mock_manager(mock_store):
    """Create a mock checkpoint manager."""
    manager = MagicMock()
    manager.store = mock_store
    manager.list_debates_with_checkpoints = AsyncMock(return_value=[])
    manager.resume_from_checkpoint = AsyncMock(return_value=None)
    manager.add_intervention = AsyncMock(return_value=True)
    manager.create_checkpoint = AsyncMock(return_value=MockDebateCheckpoint())
    return manager


@pytest.fixture
def mock_storage():
    """Debate storage in which every debate belongs to ORG_ID."""
    storage = MagicMock()
    storage.get_access_info.side_effect = lambda ref: (ref, ORG_ID, False)
    return storage


@pytest.fixture
def handler(mock_manager, mock_storage):
    """Create CheckpointHandler with mocked manager."""
    h = CheckpointHandler({"storage": mock_storage})
    h._checkpoint_manager = mock_manager
    return h


@pytest.fixture
def mock_http_handler():
    """Create mock HTTP handler with GET method."""
    mock = MagicMock()
    mock.command = "GET"
    mock.client_address = ("127.0.0.1", 12345)
    mock.path = "/api/v1/checkpoints"
    mock.headers = {}
    return mock


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset the module-level rate limiter between tests."""
    with patch("aragora.server.handlers.checkpoints._checkpoint_limiter") as mock_limiter:
        mock_limiter.is_allowed.return_value = True
        yield mock_limiter


# ---------------------------------------------------------------------------
# can_handle() routing
# ---------------------------------------------------------------------------


class TestCanHandle:
    """Tests for route matching via can_handle()."""

    def test_list_checkpoints(self, handler):
        assert handler.can_handle("/api/v1/checkpoints")

    def test_list_resumable(self, handler):
        assert handler.can_handle("/api/v1/checkpoints/resumable")

    def test_get_checkpoint_by_id(self, handler):
        assert handler.can_handle("/api/v1/checkpoints/cp-123")

    def test_resume_checkpoint(self, handler):
        assert handler.can_handle("/api/v1/checkpoints/cp-123/resume")

    def test_delete_checkpoint(self, handler):
        assert handler.can_handle("/api/v1/checkpoints/cp-123")

    def test_intervention(self, handler):
        assert handler.can_handle("/api/v1/checkpoints/cp-123/intervention")

    def test_debate_checkpoints(self, handler):
        assert handler.can_handle("/api/v1/debates/dbt-001/checkpoints")

    def test_create_debate_checkpoint(self, handler):
        assert handler.can_handle("/api/v1/debates/dbt-001/checkpoint")

    def test_pause_debate(self, handler):
        assert handler.can_handle("/api/v1/debates/dbt-001/checkpoint/pause")

    def test_unrelated_path_rejected(self, handler):
        assert not handler.can_handle("/api/v1/debates")

    def test_wrong_prefix_rejected(self, handler):
        assert not handler.can_handle("/api/v1/gauntlet/run")

    def test_debates_without_checkpoint_rejected(self, handler):
        assert not handler.can_handle("/api/v1/debates/dbt-001/status")


# ---------------------------------------------------------------------------
# GET /api/v1/checkpoints - List checkpoints
# ---------------------------------------------------------------------------


class TestListCheckpoints:
    """Tests for listing checkpoints with filtering and pagination."""

    @pytest.mark.asyncio
    async def test_list_empty(self, handler, mock_http_handler, mock_store):
        mock_store.list_checkpoints.return_value = []

        result = await handler.handle("/api/v1/checkpoints", {}, mock_http_handler)
        body = _body(result)
        assert _status(result) == 200
        assert body["checkpoints"] == []
        assert body["total"] == 0

    @pytest.mark.asyncio
    async def test_list_with_results(self, handler, mock_http_handler, mock_store):
        checkpoints = [
            {
                "checkpoint_id": "cp-001",
                "debate_id": "dbt-001",
                "task": "Task 1",
                "status": "complete",
                "current_round": 2,
                "created_at": "2026-01-15T10:00:00",
            },
            {
                "checkpoint_id": "cp-002",
                "debate_id": "dbt-002",
                "task": "Task 2",
                "status": "complete",
                "current_round": 3,
                "created_at": "2026-01-15T11:00:00",
            },
        ]
        mock_store.list_checkpoints.return_value = checkpoints

        result = await handler.handle("/api/v1/checkpoints", {}, mock_http_handler)
        body = _body(result)
        assert _status(result) == 200
        assert len(body["checkpoints"]) == 2
        assert body["total"] == 2

    @pytest.mark.asyncio
    async def test_list_with_debate_id_filter(self, handler, mock_http_handler, mock_store):
        mock_store.list_checkpoints.return_value = []

        result = await handler.handle(
            "/api/v1/checkpoints",
            {"debate_id": "dbt-001"},
            mock_http_handler,
        )
        body = _body(result)
        assert _status(result) == 200
        mock_store.list_checkpoints.assert_called_once_with(debate_id="dbt-001")

    @pytest.mark.asyncio
    async def test_list_with_status_filter(self, handler, mock_http_handler, mock_store):
        checkpoints = [
            {"checkpoint_id": "cp-001", "debate_id": "dbt-001", "status": "complete"},
            {"checkpoint_id": "cp-002", "debate_id": "dbt-001", "status": "expired"},
            {"checkpoint_id": "cp-003", "debate_id": "dbt-002", "status": "complete"},
        ]
        mock_store.list_checkpoints.return_value = checkpoints

        result = await handler.handle(
            "/api/v1/checkpoints",
            {"status": "complete"},
            mock_http_handler,
        )
        body = _body(result)
        assert _status(result) == 200
        assert body["total"] == 2
        assert len(body["checkpoints"]) == 2
        for cp in body["checkpoints"]:
            assert cp["status"] == "complete"

    @pytest.mark.asyncio
    async def test_list_drops_other_org_debates(
        self, handler, mock_http_handler, mock_store, mock_storage
    ):
        mock_storage.get_access_info.side_effect = lambda ref: (
            (ref, ORG_ID, False) if ref == "dbt-001" else (ref, "other-org", True)
        )
        mock_store.list_checkpoints.return_value = [
            {"checkpoint_id": "cp-001", "debate_id": "dbt-001", "status": "complete"},
            {"checkpoint_id": "cp-002", "debate_id": "dbt-002", "status": "complete"},
            {"checkpoint_id": "cp-003", "status": "complete"},
        ]

        result = await handler.handle("/api/v1/checkpoints", {}, mock_http_handler)
        body = _body(result)
        assert body["total"] == 1
        assert [cp["checkpoint_id"] for cp in body["checkpoints"]] == ["cp-001"]

    @pytest.mark.asyncio
    async def test_list_pagination(self, handler, mock_http_handler, mock_store):
        checkpoints = [
            {"checkpoint_id": f"cp-{i:03d}", "debate_id": "dbt-001", "status": "complete"}
            for i in range(10)
        ]
        mock_store.list_checkpoints.return_value = checkpoints

        result = await handler.handle(
            "/api/v1/checkpoints",
            {"limit": "3", "offset": "2"},
            mock_http_handler,
        )
        body = _body(result)
        assert _status(result) == 200
        assert body["total"] == 10
        assert body["limit"] == 3
        assert body["offset"] == 2
        assert len(body["checkpoints"]) == 3
        assert body["checkpoints"][0]["checkpoint_id"] == "cp-002"

    @pytest.mark.asyncio
    async def test_list_default_pagination(self, handler, mock_http_handler, mock_store):
        mock_store.list_checkpoints.return_value = []

        result = await handler.handle("/api/v1/checkpoints", {}, mock_http_handler)
        body = _body(result)
        assert body["limit"] == 50
        assert body["offset"] == 0


# ---------------------------------------------------------------------------
# GET /api/v1/checkpoints/resumable - List resumable debates
# ---------------------------------------------------------------------------


class TestListResumableDebates:
    """Tests for listing debates with resumable checkpoints."""

    @pytest.mark.asyncio
    async def test_list_resumable_empty(self, handler, mock_http_handler, mock_manager):
        mock_manager.list_debates_with_checkpoints.return_value = []

        result = await handler.handle("/api/v1/checkpoints/resumable", {}, mock_http_handler)
        body = _body(result)
        assert _status(result) == 200
        assert body["debates"] == []
        assert body["total"] == 0

    @pytest.mark.asyncio
    async def test_list_resumable_with_results(self, handler, mock_http_handler, mock_manager):
        debates = [
            {
                "debate_id": "dbt-001",
                "task": "Task 1",
                "checkpoint_count": 3,
                "latest_checkpoint": "cp-003",
                "latest_round": 5,
            },
            {
                "debate_id": "dbt-002",
                "task": "Task 2",
                "checkpoint_count": 1,
                "latest_checkpoint": "cp-004",
                "latest_round": 2,
            },
        ]
        mock_manager.list_debates_with_checkpoints.return_value = debates

        result = await handler.handle("/api/v1/checkpoints/resumable", {}, mock_http_handler)
        body = _body(result)
        assert _status(result) == 200
        assert len(body["debates"]) == 2
        assert body["total"] == 2


# ---------------------------------------------------------------------------
# GET /api/v1/checkpoints/{id} - Get checkpoint details
# ---------------------------------------------------------------------------


class TestGetCheckpoint:
    """Tests for getting a specific checkpoint."""

    @pytest.mark.asyncio
    async def test_get_checkpoint_success(self, handler, mock_http_handler, mock_store):
        checkpoint = MockDebateCheckpoint()
        mock_store.load.return_value = checkpoint

        result = await handler.handle(
            "/api/v1/checkpoints/cp-debate01-001-abcd",
            {},
            mock_http_handler,
        )
        body = _body(result)
        assert _status(result) == 200
        assert body["checkpoint"]["checkpoint_id"] == "cp-debate01-001-abcd"
        assert body["checkpoint"]["integrity_valid"] is True

    @pytest.mark.asyncio
    async def test_get_checkpoint_not_found(self, handler, mock_http_handler, mock_store):
        mock_store.load.return_value = None

        result = await handler.handle("/api/v1/checkpoints/nonexistent", {}, mock_http_handler)
        assert _status(result) == 404
        body = _body(result)
        assert "not found" in body.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_get_checkpoint_integrity_invalid(self, handler, mock_http_handler, mock_store):
        checkpoint = MockDebateCheckpoint(_integrity_valid=False)
        mock_store.load.return_value = checkpoint

        result = await handler.handle("/api/v1/checkpoints/cp-bad", {}, mock_http_handler)
        body = _body(result)
        assert _status(result) == 200
        assert body["checkpoint"]["integrity_valid"] is False


# ---------------------------------------------------------------------------
# POST /api/v1/checkpoints/{id}/resume - Resume from checkpoint
# ---------------------------------------------------------------------------


class TestResumeCheckpoint:
    """Tests for resuming a debate from checkpoint."""

    @pytest.mark.asyncio
    async def test_resume_success(self, handler, mock_http_handler, mock_manager):
        mock_http_handler.command = "POST"
        resumed = MockResumedDebate()
        mock_manager.resume_from_checkpoint.return_value = resumed

        body_data = json.dumps({"resumed_by": "user-123"}).encode()
        result = await handler.handle(
            "/api/v1/checkpoints/cp-001/resume",
            {},
            mock_http_handler,
            body=body_data,
        )
        body = _body(result)
        assert _status(result) == 200
        assert body["message"] == "Debate resumed from checkpoint"
        assert body["resumed_debate"]["original_debate_id"] == "debate-001"
        assert body["resumed_debate"]["checkpoint_id"] == "cp-001"
        assert body["resumed_debate"]["resumed_by"] == "api"
        mock_manager.resume_from_checkpoint.assert_called_once_with(
            checkpoint_id="cp-001",
            resumed_by="user-123",
        )

    @pytest.mark.asyncio
    async def test_resume_default_resumed_by(self, handler, mock_http_handler, mock_manager):
        mock_http_handler.command = "POST"
        resumed = MockResumedDebate()
        mock_manager.resume_from_checkpoint.return_value = resumed

        result = await handler.handle(
            "/api/v1/checkpoints/cp-001/resume",
            {},
            mock_http_handler,
            body=None,
        )
        assert _status(result) == 200
        mock_manager.resume_from_checkpoint.assert_called_once_with(
            checkpoint_id="cp-001",
            resumed_by="api",
        )

    @pytest.mark.asyncio
    async def test_resume_not_found(self, handler, mock_http_handler, mock_manager):
        mock_http_handler.command = "POST"
        mock_manager.resume_from_checkpoint.return_value = None

        result = await handler.handle(
            "/api/v1/checkpoints/cp-nonexistent/resume",
            {},
            mock_http_handler,
        )
        assert _status(result) == 404
        body = _body(result)
        assert (
            "not found" in body.get("error", "").lower()
            or "corrupted" in body.get("error", "").lower()
        )


# ---------------------------------------------------------------------------
# DELETE /api/v1/checkpoints/{id} - Delete checkpoint
# ---------------------------------------------------------------------------


class TestDeleteCheckpoint:
    """Tests for deleting a checkpoint."""

    @pytest.mark.asyncio
    async def test_delete_success(self, handler, mock_http_handler, mock_store):
        mock_http_handler.command = "DELETE"
        checkpoint = MockDebateCheckpoint()
        mock_store.load.return_value = checkpoint
        mock_store.delete.return_value = True

        result = await handler.handle("/api/v1/checkpoints/cp-001", {}, mock_http_handler)
        body = _body(result)
        assert _status(result) == 200
        assert "deleted" in body.get("message", "").lower()

    @pytest.mark.asyncio
    async def test_delete_not_found(self, handler, mock_http_handler, mock_store):
        mock_http_handler.command = "DELETE"
        mock_store.load.return_value = None

        result = await handler.handle("/api/v1/checkpoints/cp-nonexistent", {}, mock_http_handler)
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_delete_failure(self, handler, mock_http_handler, mock_store):
        mock_http_handler.command = "DELETE"
        checkpoint = MockDebateCheckpoint()
        mock_store.load.return_value = checkpoint
        mock_store.delete.return_value = False

        result = await handler.handle("/api/v1/checkpoints/cp-001", {}, mock_http_handler)
        assert _status(result) == 500
        body = _body(result)
        assert "failed" in body.get("error", "").lower()


# ---------------------------------------------------------------------------
# POST /api/v1/checkpoints/{id}/intervention - Add intervention
# ---------------------------------------------------------------------------


class TestAddIntervention:
    """Tests for adding intervention notes."""

    @pytest.mark.asyncio
    async def test_add_intervention_success(self, handler, mock_http_handler, mock_manager):
        mock_http_handler.command = "POST"
        mock_manager.add_intervention.return_value = True

        body_data = json.dumps({"note": "The debate is stuck", "by": "reviewer"}).encode()
        result = await handler.handle(
            "/api/v1/checkpoints/cp-001/intervention",
            {},
            mock_http_handler,
            body=body_data,
        )
        body = _body(result)
        assert _status(result) == 200
        assert body["message"] == "Intervention note added"
        assert body["checkpoint_id"] == "cp-001"
        mock_manager.add_intervention.assert_called_once_with(
            checkpoint_id="cp-001",
            note="The debate is stuck",
            by="reviewer",
        )

    @pytest.mark.asyncio
    async def test_add_intervention_default_by(self, handler, mock_http_handler, mock_manager):
        mock_http_handler.command = "POST"
        mock_manager.add_intervention.return_value = True

        body_data = json.dumps({"note": "Please review"}).encode()
        result = await handler.handle(
            "/api/v1/checkpoints/cp-001/intervention",
            {},
            mock_http_handler,
            body=body_data,
        )
        assert _status(result) == 200
        mock_manager.add_intervention.assert_called_once_with(
            checkpoint_id="cp-001",
            note="Please review",
            by="human",
        )

    @pytest.mark.asyncio
    async def test_add_intervention_missing_note(self, handler, mock_http_handler):
        mock_http_handler.command = "POST"

        body_data = json.dumps({"by": "reviewer"}).encode()
        result = await handler.handle(
            "/api/v1/checkpoints/cp-001/intervention",
            {},
            mock_http_handler,
            body=body_data,
        )
        assert _status(result) == 400
        body = _body(result)
        assert "note" in body.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_add_intervention_empty_body(self, handler, mock_http_handler):
        mock_http_handler.command = "POST"

        result = await handler.handle(
            "/api/v1/checkpoints/cp-001/intervention",
            {},
            mock_http_handler,
            body=None,
        )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_add_intervention_not_found(self, handler, mock_http_handler, mock_manager):
        mock_http_handler.command = "POST"
        mock_manager.add_intervention.return_value = False

        body_data = json.dumps({"note": "Review this"}).encode()
        result = await handler.handle(
            "/api/v1/checkpoints/cp-nonexistent/intervention",
            {},
            mock_http_handler,
            body=body_data,
        )
        assert _status(result) == 404


# ---------------------------------------------------------------------------
# GET /api/v1/debates/{id}/checkpoints - List debate checkpoints
# ---------------------------------------------------------------------------


class TestListDebateCheckpoints:
    """Tests for listing checkpoints of a specific debate."""

    @pytest.mark.asyncio
    async def test_list_debate_checkpoints_empty(self, handler, mock_http_handler, mock_store):
        mock_store.list_checkpoints.return_value = []

        result = await handler.handle("/api/v1/debates/dbt-001/checkpoints", {}, mock_http_handler)
        body = _body(result)
        assert _status(result) == 200
        assert body["debate_id"] == "dbt-001"
        assert body["checkpoints"] == []
        assert body["total"] == 0

    @pytest.mark.asyncio
    async def test_list_debate_checkpoints_with_results(
        self, handler, mock_http_handler, mock_store
    ):
        checkpoints = [
            {
                "checkpoint_id": "cp-001",
                "debate_id": "dbt-001",
                "created_at": "2026-01-15T10:00:00",
            },
            {
                "checkpoint_id": "cp-002",
                "debate_id": "dbt-001",
                "created_at": "2026-01-15T11:00:00",
            },
        ]
        mock_store.list_checkpoints.return_value = checkpoints

        result = await handler.handle("/api/v1/debates/dbt-001/checkpoints", {}, mock_http_handler)
        body = _body(result)
        assert _status(result) == 200
        assert body["debate_id"] == "dbt-001"
        assert body["total"] == 2
        mock_store.list_checkpoints.assert_called_once_with(debate_id="dbt-001")

    @pytest.mark.asyncio
    async def test_list_debate_checkpoints_sorted_desc(
        self, handler, mock_http_handler, mock_store
    ):
        """Checkpoints should be sorted by created_at descending."""
        checkpoints = [
            {"checkpoint_id": "cp-001", "created_at": "2026-01-15T10:00:00"},
            {"checkpoint_id": "cp-002", "created_at": "2026-01-15T12:00:00"},
            {"checkpoint_id": "cp-003", "created_at": "2026-01-15T11:00:00"},
        ]
        mock_store.list_checkpoints.return_value = checkpoints

        result = await handler.handle("/api/v1/debates/dbt-001/checkpoints", {}, mock_http_handler)
        body = _body(result)
        assert body["checkpoints"][0]["checkpoint_id"] == "cp-002"
        assert body["checkpoints"][1]["checkpoint_id"] == "cp-003"
        assert body["checkpoints"][2]["checkpoint_id"] == "cp-001"


# ---------------------------------------------------------------------------
# POST /api/v1/debates/{id}/checkpoint - Create checkpoint
# ---------------------------------------------------------------------------


class TestCreateCheckpoint:
    """Tests for creating a checkpoint for a running debate."""

    @pytest.mark.asyncio
    async def test_create_checkpoint_success(self, handler, mock_http_handler, mock_manager):
        mock_http_handler.command = "POST"
        debate_state = MockDebateState()

        with patch("aragora.server.state.get_state_manager") as mock_get_sm:
            mock_sm = MagicMock()
            mock_sm.get_debate.return_value = debate_state
            mock_get_sm.return_value = mock_sm

            result = await handler.handle(
                "/api/v1/debates/debate-001/checkpoint",
                {},
                mock_http_handler,
            )
        body = _body(result)
        assert _status(result) == 200
        assert body["success"] is True
        assert body["debate_id"] == "debate-001"
        assert body["phase"] == "manual"
        assert body["current_round"] == 2

    @pytest.mark.asyncio
    async def test_create_checkpoint_with_custom_phase(
        self, handler, mock_http_handler, mock_manager
    ):
        mock_http_handler.command = "POST"
        debate_state = MockDebateState()

        with patch("aragora.server.state.get_state_manager") as mock_get_sm:
            mock_sm = MagicMock()
            mock_sm.get_debate.return_value = debate_state
            mock_get_sm.return_value = mock_sm

            body_data = json.dumps({"phase": "critique", "note": "Manual save point"}).encode()
            result = await handler.handle(
                "/api/v1/debates/debate-001/checkpoint",
                {},
                mock_http_handler,
                body=body_data,
            )
        body = _body(result)
        assert _status(result) == 200
        assert body["phase"] == "critique"

    @pytest.mark.asyncio
    async def test_create_checkpoint_debate_not_found(self, handler, mock_http_handler):
        mock_http_handler.command = "POST"

        with patch("aragora.server.state.get_state_manager") as mock_get_sm:
            mock_sm = MagicMock()
            mock_sm.get_debate.return_value = None
            mock_get_sm.return_value = mock_sm

            result = await handler.handle(
                "/api/v1/debates/nonexistent/checkpoint",
                {},
                mock_http_handler,
            )
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_create_checkpoint_bad_state(self, handler, mock_http_handler):
        """Cannot checkpoint a completed debate."""
        mock_http_handler.command = "POST"
        debate_state = MockDebateState(status="completed")

        with patch("aragora.server.state.get_state_manager") as mock_get_sm:
            mock_sm = MagicMock()
            mock_sm.get_debate.return_value = debate_state
            mock_get_sm.return_value = mock_sm

            result = await handler.handle(
                "/api/v1/debates/debate-001/checkpoint",
                {},
                mock_http_handler,
            )
        assert _status(result) == 400
        body = _body(result)
        assert "completed" in body.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_create_checkpoint_paused_state_allowed(
        self, handler, mock_http_handler, mock_manager
    ):
        """Can checkpoint a paused debate."""
        mock_http_handler.command = "POST"
        debate_state = MockDebateState(status="paused")

        with patch("aragora.server.state.get_state_manager") as mock_get_sm:
            mock_sm = MagicMock()
            mock_sm.get_debate.return_value = debate_state
            mock_get_sm.return_value = mock_sm

            result = await handler.handle(
                "/api/v1/debates/debate-001/checkpoint",
                {},
                mock_http_handler,
            )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_create_checkpoint_initializing_allowed(
        self, handler, mock_http_handler, mock_manager
    ):
        """Can checkpoint an initializing debate."""
        mock_http_handler.command = "POST"
        debate_state = MockDebateState(status="initializing")

        with patch("aragora.server.state.get_state_manager") as mock_get_sm:
            mock_sm = MagicMock()
            mock_sm.get_debate.return_value = debate_state
            mock_get_sm.return_value = mock_sm

            result = await handler.handle(
                "/api/v1/debates/debate-001/checkpoint",
                {},
                mock_http_handler,
            )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_create_checkpoint_failed_state_rejected(self, handler, mock_http_handler):
        mock_http_handler.command = "POST"
        debate_state = MockDebateState(status="failed")

        with patch("aragora.server.state.get_state_manager") as mock_get_sm:
            mock_sm = MagicMock()
            mock_sm.get_debate.return_value = debate_state
            mock_get_sm.return_value = mock_sm

            result = await handler.handle(
                "/api/v1/debates/debate-001/checkpoint",
                {},
                mock_http_handler,
            )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_checkpoint_with_note(
        self, handler, mock_http_handler, mock_manager, mock_store
    ):
        """When note is provided, checkpoint metadata is updated and saved."""
        mock_http_handler.command = "POST"
        debate_state = MockDebateState()
        mock_cp = MockDebateCheckpoint()
        mock_cp.metadata = None
        mock_manager.create_checkpoint.return_value = mock_cp

        with patch("aragora.server.state.get_state_manager") as mock_get_sm:
            mock_sm = MagicMock()
            mock_sm.get_debate.return_value = debate_state
            mock_get_sm.return_value = mock_sm

            body_data = json.dumps({"note": "Save before lunch"}).encode()
            result = await handler.handle(
                "/api/v1/debates/debate-001/checkpoint",
                {},
                mock_http_handler,
                body=body_data,
            )
        assert _status(result) == 200
        # Verify the note was stored and checkpoint was saved again
        mock_store.save.assert_called_once_with(mock_cp)
        assert mock_cp.metadata["note"] == "Save before lunch"

    @pytest.mark.asyncio
    async def test_create_checkpoint_manager_error(self, handler, mock_http_handler, mock_manager):
        """When manager raises, returns 500."""
        mock_http_handler.command = "POST"
        debate_state = MockDebateState()
        mock_manager.create_checkpoint.side_effect = RuntimeError("DB error")

        with patch("aragora.server.state.get_state_manager") as mock_get_sm:
            mock_sm = MagicMock()
            mock_sm.get_debate.return_value = debate_state
            mock_get_sm.return_value = mock_sm

            result = await handler.handle(
                "/api/v1/debates/debate-001/checkpoint",
                {},
                mock_http_handler,
            )
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_create_checkpoint_message_conversion_dict(
        self, handler, mock_http_handler, mock_manager
    ):
        """Dict messages are passed through as-is."""
        mock_http_handler.command = "POST"
        debate_state = MockDebateState(messages=[{"content": "hello", "role": "user"}])

        with patch("aragora.server.state.get_state_manager") as mock_get_sm:
            mock_sm = MagicMock()
            mock_sm.get_debate.return_value = debate_state
            mock_get_sm.return_value = mock_sm

            result = await handler.handle(
                "/api/v1/debates/debate-001/checkpoint",
                {},
                mock_http_handler,
            )
        assert _status(result) == 200
        # Check messages were passed correctly to create_checkpoint
        call_kwargs = mock_manager.create_checkpoint.call_args[1]
        assert call_kwargs["messages"] == [{"content": "hello", "role": "user"}]

    @pytest.mark.asyncio
    async def test_create_checkpoint_message_conversion_to_dict(
        self, handler, mock_http_handler, mock_manager
    ):
        """Messages with to_dict() method are converted."""
        mock_http_handler.command = "POST"
        msg = MockMessageWithToDict()
        debate_state = MockDebateState(messages=[msg])

        with patch("aragora.server.state.get_state_manager") as mock_get_sm:
            mock_sm = MagicMock()
            mock_sm.get_debate.return_value = debate_state
            mock_get_sm.return_value = mock_sm

            result = await handler.handle(
                "/api/v1/debates/debate-001/checkpoint",
                {},
                mock_http_handler,
            )
        assert _status(result) == 200
        call_kwargs = mock_manager.create_checkpoint.call_args[1]
        assert call_kwargs["messages"] == [{"content": "message via to_dict", "role": "assistant"}]

    @pytest.mark.asyncio
    async def test_create_checkpoint_message_conversion_str(
        self, handler, mock_http_handler, mock_manager
    ):
        """Plain string messages are wrapped in content dict."""
        mock_http_handler.command = "POST"
        debate_state = MockDebateState(messages=["simple string message"])

        with patch("aragora.server.state.get_state_manager") as mock_get_sm:
            mock_sm = MagicMock()
            mock_sm.get_debate.return_value = debate_state
            mock_get_sm.return_value = mock_sm

            result = await handler.handle(
                "/api/v1/debates/debate-001/checkpoint",
                {},
                mock_http_handler,
            )
        assert _status(result) == 200
        call_kwargs = mock_manager.create_checkpoint.call_args[1]
        assert call_kwargs["messages"] == [{"content": "simple string message"}]


# ---------------------------------------------------------------------------
# POST /api/v1/debates/{id}/checkpoint/pause - Pause debate
# ---------------------------------------------------------------------------


class TestPauseDebate:
    """Tests for pausing a debate with checkpoint creation."""

    @pytest.mark.asyncio
    async def test_pause_success(self, handler, mock_http_handler, mock_manager):
        mock_http_handler.command = "POST"
        debate_state = MockDebateState()

        with (
            patch("aragora.server.state.get_state_manager") as mock_get_sm,
            patch(
                "aragora.server.handlers.debates.intervention.get_debate_state",
            ) as mock_int_state,
            patch(
                "aragora.server.handlers.debates.intervention.log_intervention",
            ),
        ):
            mock_sm = MagicMock()
            mock_sm.get_debate.return_value = debate_state
            mock_get_sm.return_value = mock_sm
            mock_int_state.return_value = {}

            result = await handler.handle(
                "/api/v1/debates/debate-001/checkpoint/pause",
                {},
                mock_http_handler,
            )
        body = _body(result)
        assert _status(result) == 200
        assert body["success"] is True
        assert body["status"] == "paused"
        assert body["debate_id"] == "debate-001"
        assert body["checkpoint_id"] is not None
        assert "hint" in body

    @pytest.mark.asyncio
    async def test_pause_debate_not_found(self, handler, mock_http_handler):
        mock_http_handler.command = "POST"

        with patch("aragora.server.state.get_state_manager") as mock_get_sm:
            mock_sm = MagicMock()
            mock_sm.get_debate.return_value = None
            mock_get_sm.return_value = mock_sm

            result = await handler.handle(
                "/api/v1/debates/nonexistent/checkpoint/pause",
                {},
                mock_http_handler,
            )
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_pause_bad_state_completed(self, handler, mock_http_handler):
        mock_http_handler.command = "POST"
        debate_state = MockDebateState(status="completed")

        with patch("aragora.server.state.get_state_manager") as mock_get_sm:
            mock_sm = MagicMock()
            mock_sm.get_debate.return_value = debate_state
            mock_get_sm.return_value = mock_sm

            result = await handler.handle(
                "/api/v1/debates/debate-001/checkpoint/pause",
                {},
                mock_http_handler,
            )
        assert _status(result) == 400
        body = _body(result)
        assert "completed" in body.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_pause_bad_state_paused(self, handler, mock_http_handler):
        """Cannot pause an already-paused debate."""
        mock_http_handler.command = "POST"
        debate_state = MockDebateState(status="paused")

        with patch("aragora.server.state.get_state_manager") as mock_get_sm:
            mock_sm = MagicMock()
            mock_sm.get_debate.return_value = debate_state
            mock_get_sm.return_value = mock_sm

            result = await handler.handle(
                "/api/v1/debates/debate-001/checkpoint/pause",
                {},
                mock_http_handler,
            )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_pause_initializing_allowed(self, handler, mock_http_handler, mock_manager):
        """Can pause an initializing debate."""
        mock_http_handler.command = "POST"
        debate_state = MockDebateState(status="initializing")

        with (
            patch("aragora.server.state.get_state_manager") as mock_get_sm,
            patch(
                "aragora.server.handlers.debates.intervention.get_debate_state",
            ) as mock_int_state,
            patch(
                "aragora.server.handlers.debates.intervention.log_intervention",
            ),
        ):
            mock_sm = MagicMock()
            mock_sm.get_debate.return_value = debate_state
            mock_get_sm.return_value = mock_sm
            mock_int_state.return_value = {}

            result = await handler.handle(
                "/api/v1/debates/debate-001/checkpoint/pause",
                {},
                mock_http_handler,
            )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_pause_without_checkpoint(self, handler, mock_http_handler, mock_manager):
        """Pause with create_checkpoint=false skips checkpoint creation."""
        mock_http_handler.command = "POST"
        debate_state = MockDebateState()

        with (
            patch("aragora.server.state.get_state_manager") as mock_get_sm,
            patch(
                "aragora.server.handlers.debates.intervention.get_debate_state",
            ) as mock_int_state,
            patch(
                "aragora.server.handlers.debates.intervention.log_intervention",
            ),
        ):
            mock_sm = MagicMock()
            mock_sm.get_debate.return_value = debate_state
            mock_get_sm.return_value = mock_sm
            mock_int_state.return_value = {}

            body_data = json.dumps({"create_checkpoint": False}).encode()
            result = await handler.handle(
                "/api/v1/debates/debate-001/checkpoint/pause",
                {},
                mock_http_handler,
                body=body_data,
            )
        body = _body(result)
        assert _status(result) == 200
        assert body["checkpoint_id"] is None
        # create_checkpoint should NOT have been called
        mock_manager.create_checkpoint.assert_not_called()

    @pytest.mark.asyncio
    async def test_pause_with_note(self, handler, mock_http_handler, mock_manager, mock_store):
        """Pause note is stored in checkpoint metadata."""
        mock_http_handler.command = "POST"
        debate_state = MockDebateState()
        mock_cp = MockDebateCheckpoint()
        mock_cp.metadata = None
        mock_manager.create_checkpoint.return_value = mock_cp

        with (
            patch("aragora.server.state.get_state_manager") as mock_get_sm,
            patch(
                "aragora.server.handlers.debates.intervention.get_debate_state",
            ) as mock_int_state,
            patch(
                "aragora.server.handlers.debates.intervention.log_intervention",
            ),
        ):
            mock_sm = MagicMock()
            mock_sm.get_debate.return_value = debate_state
            mock_get_sm.return_value = mock_sm
            mock_int_state.return_value = {}

            body_data = json.dumps({"note": "Lunch break"}).encode()
            result = await handler.handle(
                "/api/v1/debates/debate-001/checkpoint/pause",
                {},
                mock_http_handler,
                body=body_data,
            )
        assert _status(result) == 200
        assert mock_cp.metadata["pause_note"] == "Lunch break"
        mock_store.save.assert_called_once_with(mock_cp)

    @pytest.mark.asyncio
    async def test_pause_updates_debate_status(self, handler, mock_http_handler, mock_manager):
        """Pause sets the debate status to 'paused'."""
        mock_http_handler.command = "POST"
        debate_state = MockDebateState()

        with (
            patch("aragora.server.state.get_state_manager") as mock_get_sm,
            patch(
                "aragora.server.handlers.debates.intervention.get_debate_state",
            ) as mock_int_state,
            patch(
                "aragora.server.handlers.debates.intervention.log_intervention",
            ),
        ):
            mock_sm = MagicMock()
            mock_sm.get_debate.return_value = debate_state
            mock_get_sm.return_value = mock_sm
            mock_int_state.return_value = {}

            result = await handler.handle(
                "/api/v1/debates/debate-001/checkpoint/pause",
                {},
                mock_http_handler,
            )
        assert _status(result) == 200
        mock_sm.update_debate_status.assert_called_once_with("debate-001", status="paused")

    @pytest.mark.asyncio
    async def test_pause_checkpoint_error_still_succeeds(
        self, handler, mock_http_handler, mock_manager
    ):
        """Checkpoint creation failure during pause does not fail the pause."""
        mock_http_handler.command = "POST"
        debate_state = MockDebateState()
        mock_manager.create_checkpoint.side_effect = RuntimeError("DB error")

        with (
            patch("aragora.server.state.get_state_manager") as mock_get_sm,
            patch(
                "aragora.server.handlers.debates.intervention.get_debate_state",
            ) as mock_int_state,
            patch(
                "aragora.server.handlers.debates.intervention.log_intervention",
            ),
        ):
            mock_sm = MagicMock()
            mock_sm.get_debate.return_value = debate_state
            mock_get_sm.return_value = mock_sm
            mock_int_state.return_value = {}

            result = await handler.handle(
                "/api/v1/debates/debate-001/checkpoint/pause",
                {},
                mock_http_handler,
            )
        body = _body(result)
        assert _status(result) == 200
        assert body["checkpoint_id"] is None

    @pytest.mark.asyncio
    async def test_pause_intervention_import_error_tolerated(
        self, handler, mock_http_handler, mock_manager
    ):
        """ImportError from intervention module is tolerated."""
        mock_http_handler.command = "POST"
        debate_state = MockDebateState()

        with patch("aragora.server.state.get_state_manager") as mock_get_sm:
            mock_sm = MagicMock()
            mock_sm.get_debate.return_value = debate_state
            mock_get_sm.return_value = mock_sm

            # The intervention module import may fail -- the handler
            # catches ImportError and logs a warning
            result = await handler.handle(
                "/api/v1/debates/debate-001/checkpoint/pause",
                {},
                mock_http_handler,
            )
        # Should still succeed regardless
        assert _status(result) == 200


# ---------------------------------------------------------------------------
# Rate Limiting
# ---------------------------------------------------------------------------


class TestRateLimiting:
    """Tests for rate limit enforcement."""

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded(self, handler, mock_http_handler, reset_rate_limiter):
        reset_rate_limiter.is_allowed.return_value = False

        result = await handler.handle("/api/v1/checkpoints", {}, mock_http_handler)
        assert _status(result) == 429
        body = _body(result)
        assert "rate limit" in body.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_rate_limit_allowed(
        self, handler, mock_http_handler, mock_store, reset_rate_limiter
    ):
        reset_rate_limiter.is_allowed.return_value = True
        mock_store.list_checkpoints.return_value = []

        result = await handler.handle("/api/v1/checkpoints", {}, mock_http_handler)
        assert _status(result) == 200


# ---------------------------------------------------------------------------
# 404 Not Found Route
# ---------------------------------------------------------------------------


class TestNotFound:
    """Tests for unmatched routes returning 404."""

    @pytest.mark.asyncio
    async def test_unknown_method_on_checkpoints(self, handler, mock_http_handler):
        """PUT on /api/v1/checkpoints returns 404 (no PUT route defined)."""
        mock_http_handler.command = "PUT"

        result = await handler.handle("/api/v1/checkpoints", {}, mock_http_handler)
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_post_on_list_checkpoints(self, handler, mock_http_handler):
        """POST on /api/v1/checkpoints returns 404."""
        mock_http_handler.command = "POST"

        result = await handler.handle("/api/v1/checkpoints", {}, mock_http_handler)
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_delete_on_resume_path(self, handler, mock_http_handler):
        """DELETE on .../resume returns 404."""
        mock_http_handler.command = "DELETE"

        result = await handler.handle("/api/v1/checkpoints/cp-001/resume", {}, mock_http_handler)
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_get_on_debate_checkpoint_create(self, handler, mock_http_handler):
        """GET on /api/v1/debates/{id}/checkpoint returns 404 (needs POST)."""
        result = await handler.handle("/api/v1/debates/dbt-001/checkpoint", {}, mock_http_handler)
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_get_on_pause(self, handler, mock_http_handler):
        """GET on .../checkpoint/pause returns 404."""
        result = await handler.handle(
            "/api/v1/debates/dbt-001/checkpoint/pause",
            {},
            mock_http_handler,
        )
        assert _status(result) == 404


# ---------------------------------------------------------------------------
# Handler Initialization
# ---------------------------------------------------------------------------


class TestHandlerInit:
    """Tests for handler initialization."""

    def test_handler_extends_base_handler(self, handler):
        from aragora.server.handlers.base import BaseHandler

        assert isinstance(handler, BaseHandler)

    def test_handler_has_routes(self, handler):
        assert len(handler.ROUTES) >= 2

    def test_handler_creates_manager_lazily(self):
        h = CheckpointHandler({})
        assert h._checkpoint_manager is None

    def test_get_checkpoint_manager_creates_instance(self):
        with (
            patch("aragora.server.handlers.checkpoints.DatabaseCheckpointStore") as mock_db_store,
            patch("aragora.server.handlers.checkpoints.CheckpointManager") as mock_cm,
        ):
            mock_db_store.return_value = MagicMock()
            mock_cm.return_value = MagicMock()
            h = CheckpointHandler({})
            manager = h._get_checkpoint_manager()
            assert manager is not None
            mock_db_store.assert_called_once()
            mock_cm.assert_called_once()

    def test_get_checkpoint_manager_reuses_instance(self):
        h = CheckpointHandler({})
        mock_mgr = MagicMock()
        h._checkpoint_manager = mock_mgr
        assert h._get_checkpoint_manager() is mock_mgr


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_pagination_offset_beyond_total(self, handler, mock_http_handler, mock_store):
        """Offset beyond total returns empty list."""
        checkpoints = [
            {"checkpoint_id": f"cp-{i}", "debate_id": "dbt-001", "status": "complete"}
            for i in range(3)
        ]
        mock_store.list_checkpoints.return_value = checkpoints

        result = await handler.handle(
            "/api/v1/checkpoints",
            {"limit": "10", "offset": "100"},
            mock_http_handler,
        )
        body = _body(result)
        assert _status(result) == 200
        assert body["total"] == 3
        assert body["checkpoints"] == []

    @pytest.mark.asyncio
    async def test_status_filter_no_matches(self, handler, mock_http_handler, mock_store):
        """Status filter that matches nothing returns empty."""
        checkpoints = [
            {"checkpoint_id": "cp-001", "debate_id": "dbt-001", "status": "complete"},
        ]
        mock_store.list_checkpoints.return_value = checkpoints

        result = await handler.handle(
            "/api/v1/checkpoints",
            {"status": "corrupted"},
            mock_http_handler,
        )
        body = _body(result)
        assert body["total"] == 0
        assert body["checkpoints"] == []

    @pytest.mark.asyncio
    async def test_resume_with_modifications_body(self, handler, mock_http_handler, mock_manager):
        """Resume with modifications body is accepted (body parsed)."""
        mock_http_handler.command = "POST"
        resumed = MockResumedDebate()
        mock_manager.resume_from_checkpoint.return_value = resumed

        body_data = json.dumps(
            {
                "resumed_by": "admin",
                "modifications": {
                    "task": "Updated task",
                    "additional_rounds": 2,
                },
            }
        ).encode()
        result = await handler.handle(
            "/api/v1/checkpoints/cp-001/resume",
            {},
            mock_http_handler,
            body=body_data,
        )
        assert _status(result) == 200
        mock_manager.resume_from_checkpoint.assert_called_once_with(
            checkpoint_id="cp-001",
            resumed_by="admin",
        )

    @pytest.mark.asyncio
    async def test_empty_debate_messages_checkpointed(
        self, handler, mock_http_handler, mock_manager
    ):
        """Debate with no messages can be checkpointed."""
        mock_http_handler.command = "POST"
        debate_state = MockDebateState(messages=[])

        with patch("aragora.server.state.get_state_manager") as mock_get_sm:
            mock_sm = MagicMock()
            mock_sm.get_debate.return_value = debate_state
            mock_get_sm.return_value = mock_sm

            result = await handler.handle(
                "/api/v1/debates/debate-001/checkpoint",
                {},
                mock_http_handler,
            )
        assert _status(result) == 200
        call_kwargs = mock_manager.create_checkpoint.call_args[1]
        assert call_kwargs["messages"] == []

    @pytest.mark.asyncio
    async def test_context_with_none(self):
        """Handler accepts None context gracefully."""
        h = CheckpointHandler(None)
        assert h is not None
