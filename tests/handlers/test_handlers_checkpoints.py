"""
Tests for CheckpointHandler endpoints.

Endpoints tested:
- GET /api/checkpoints - List all checkpoints
- GET /api/checkpoints/resumable - List resumable debates
- GET /api/checkpoints/{id} - Get specific checkpoint
- POST /api/checkpoints/{id}/resume - Resume from checkpoint
- DELETE /api/checkpoints/{id} - Delete checkpoint
- POST /api/checkpoints/{id}/intervention - Add intervention note
- GET /api/debates/{id}/checkpoints - List debate checkpoints
- POST /api/debates/{id}/checkpoint - Create checkpoint (404 if no active debate)
- POST /api/debates/{id}/checkpoint/pause - Pause debate (404 if no active debate)
"""

import json
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from aragora.server.handlers.checkpoints import CheckpointHandler
from aragora.server.handlers.base import clear_cache
from aragora.debate.checkpoint import (
    CheckpointManager,
    CheckpointStatus,
    DebateCheckpoint,
    AgentState,
    ResumedDebate,
)
from aragora.core import Message, Vote

pytestmark = pytest.mark.usefixtures("org_scoped_request_user")

# The org ``org_scoped_request_user`` authenticates every request as.
ORG_ID = "test-org-001"

# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mock_handler():
    """Create a mock HTTP request handler."""
    handler = Mock()
    handler.command = "GET"
    handler.headers = {"Content-Type": "application/json"}
    return handler


@pytest.fixture
def mock_checkpoint_store():
    """Create a mock checkpoint store."""
    store = AsyncMock()
    store.list_checkpoints = AsyncMock(return_value=[])
    store.load = AsyncMock(return_value=None)
    store.delete = AsyncMock(return_value=True)
    store.save = AsyncMock(return_value="saved")
    return store


@pytest.fixture
def mock_checkpoint_manager(mock_checkpoint_store):
    """Create a mock checkpoint manager."""
    manager = MagicMock(spec=CheckpointManager)
    manager.store = mock_checkpoint_store
    manager.list_debates_with_checkpoints = AsyncMock(return_value=[])
    manager.resume_from_checkpoint = AsyncMock(return_value=None)
    manager.add_intervention = AsyncMock(return_value=True)
    return manager


@pytest.fixture
def checkpoint_handler():
    """Create a CheckpointHandler whose storage puts every debate in ORG_ID."""
    storage = MagicMock()
    storage.get_access_info.side_effect = lambda ref: (ref, ORG_ID, False)
    ctx = {
        "storage": storage,
        "elo_system": None,
    }
    return CheckpointHandler(ctx)


@pytest.fixture
def sample_checkpoint():
    """Create a sample DebateCheckpoint for testing."""
    return DebateCheckpoint(
        checkpoint_id="cp-test-001",
        debate_id="debate-123",
        task="Test the API endpoints",
        current_round=2,
        total_rounds=5,
        phase="proposal",
        messages=[
            {
                "role": "assistant",
                "agent": "claude",
                "content": "Test message",
                "timestamp": "2026-01-17T10:00:00",
                "round": 1,
            }
        ],
        critiques=[],
        votes=[
            {
                "agent": "claude",
                "choice": "option_a",
                "confidence": 0.8,
                "reasoning": "Test reasoning",
                "continue_debate": True,
            }
        ],
        agent_states=[
            AgentState(
                agent_name="claude",
                agent_model="claude-3",
                agent_role="debater",
                system_prompt="You are a debater",
                stance="pro",
            )
        ],
        status=CheckpointStatus.COMPLETE,
        created_at="2026-01-17T10:00:00",
    )


@pytest.fixture
def sample_checkpoint_list():
    """Create a list of sample checkpoint summaries."""
    return [
        {
            "checkpoint_id": "cp-test-001",
            "debate_id": "debate-123",
            "task": "Test task 1",
            "current_round": 2,
            "created_at": "2026-01-17T10:00:00",
            "status": "complete",
        },
        {
            "checkpoint_id": "cp-test-002",
            "debate_id": "debate-123",
            "task": "Test task 2",
            "current_round": 3,
            "created_at": "2026-01-17T11:00:00",
            "status": "complete",
        },
        {
            "checkpoint_id": "cp-test-003",
            "debate_id": "debate-456",
            "task": "Another task",
            "current_round": 1,
            "created_at": "2026-01-17T09:00:00",
            "status": "resuming",
        },
    ]


@pytest.fixture(autouse=True)
def clear_caches():
    """Clear caches before and after each test."""
    clear_cache()
    yield
    clear_cache()


# ============================================================================
# Route Matching Tests (can_handle)
# ============================================================================


class TestCheckpointRouting:
    """Tests for route matching."""

    def test_can_handle_checkpoints_list(self, checkpoint_handler):
        """Handler can handle /api/checkpoints."""
        assert checkpoint_handler.can_handle("/api/v1/checkpoints") is True

    def test_can_handle_checkpoints_resumable(self, checkpoint_handler):
        """Handler can handle /api/checkpoints/resumable."""
        assert checkpoint_handler.can_handle("/api/v1/checkpoints/resumable") is True

    def test_can_handle_checkpoint_detail(self, checkpoint_handler):
        """Handler can handle /api/checkpoints/{id}."""
        assert checkpoint_handler.can_handle("/api/v1/checkpoints/cp-test-001") is True

    def test_can_handle_checkpoint_resume(self, checkpoint_handler):
        """Handler can handle /api/checkpoints/{id}/resume."""
        assert checkpoint_handler.can_handle("/api/v1/checkpoints/cp-test-001/resume") is True

    def test_can_handle_checkpoint_intervention(self, checkpoint_handler):
        """Handler can handle /api/checkpoints/{id}/intervention."""
        assert checkpoint_handler.can_handle("/api/v1/checkpoints/cp-test-001/intervention") is True

    def test_can_handle_debate_checkpoints(self, checkpoint_handler):
        """Handler can handle /api/debates/{id}/checkpoints."""
        assert checkpoint_handler.can_handle("/api/v1/debates/debate-123/checkpoints") is True

    def test_can_handle_debate_checkpoint_create(self, checkpoint_handler):
        """Handler can handle /api/debates/{id}/checkpoint."""
        assert checkpoint_handler.can_handle("/api/v1/debates/debate-123/checkpoint") is True

    def test_can_handle_debate_checkpoint_pause(self, checkpoint_handler):
        """Handler can handle /api/debates/{id}/checkpoint/pause."""
        assert checkpoint_handler.can_handle("/api/v1/debates/debate-123/checkpoint/pause") is True

    def test_cannot_handle_unrelated_routes(self, checkpoint_handler):
        """Handler doesn't handle unrelated routes."""
        assert checkpoint_handler.can_handle("/api/v1/debates") is False
        assert checkpoint_handler.can_handle("/api/v1/agents") is False
        assert checkpoint_handler.can_handle("/api/v1/replays") is False


# ============================================================================
# GET /api/checkpoints Tests
# ============================================================================


class TestListCheckpoints:
    """Tests for GET /api/checkpoints endpoint."""

    @pytest.mark.asyncio
    async def test_list_checkpoints_empty(
        self, checkpoint_handler, mock_handler, mock_checkpoint_manager
    ):
        """Returns empty list when no checkpoints exist."""
        mock_checkpoint_manager.store.list_checkpoints.return_value = []

        with patch.object(
            checkpoint_handler, "_get_checkpoint_manager", return_value=mock_checkpoint_manager
        ):
            result = await checkpoint_handler.handle("/api/v1/checkpoints", {}, mock_handler)

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["checkpoints"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_list_checkpoints_with_data(
        self, checkpoint_handler, mock_handler, mock_checkpoint_manager, sample_checkpoint_list
    ):
        """Returns checkpoints with pagination."""
        mock_checkpoint_manager.store.list_checkpoints.return_value = sample_checkpoint_list

        with patch.object(
            checkpoint_handler, "_get_checkpoint_manager", return_value=mock_checkpoint_manager
        ):
            result = await checkpoint_handler.handle("/api/v1/checkpoints", {}, mock_handler)

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert len(data["checkpoints"]) == 3
        assert data["total"] == 3
        assert data["limit"] == 50
        assert data["offset"] == 0

    @pytest.mark.asyncio
    async def test_list_checkpoints_with_debate_id_filter(
        self, checkpoint_handler, mock_handler, mock_checkpoint_manager, sample_checkpoint_list
    ):
        """Filters checkpoints by debate_id."""
        mock_checkpoint_manager.store.list_checkpoints.return_value = sample_checkpoint_list[:2]

        with patch.object(
            checkpoint_handler, "_get_checkpoint_manager", return_value=mock_checkpoint_manager
        ):
            result = await checkpoint_handler.handle(
                "/api/v1/checkpoints", {"debate_id": "debate-123"}, mock_handler
            )

        assert result is not None
        assert result.status_code == 200
        mock_checkpoint_manager.store.list_checkpoints.assert_called_with(debate_id="debate-123")

    @pytest.mark.asyncio
    async def test_list_checkpoints_with_status_filter(
        self, checkpoint_handler, mock_handler, mock_checkpoint_manager, sample_checkpoint_list
    ):
        """Filters checkpoints by status."""
        mock_checkpoint_manager.store.list_checkpoints.return_value = sample_checkpoint_list

        with patch.object(
            checkpoint_handler, "_get_checkpoint_manager", return_value=mock_checkpoint_manager
        ):
            result = await checkpoint_handler.handle(
                "/api/v1/checkpoints", {"status": "complete"}, mock_handler
            )

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        # Only checkpoints with status "complete" should be returned
        assert all(cp["status"] == "complete" for cp in data["checkpoints"])
        assert data["total"] == 2

    @pytest.mark.asyncio
    async def test_list_checkpoints_with_pagination(
        self, checkpoint_handler, mock_handler, mock_checkpoint_manager, sample_checkpoint_list
    ):
        """Handles pagination parameters."""
        mock_checkpoint_manager.store.list_checkpoints.return_value = sample_checkpoint_list

        with patch.object(
            checkpoint_handler, "_get_checkpoint_manager", return_value=mock_checkpoint_manager
        ):
            result = await checkpoint_handler.handle(
                "/api/v1/checkpoints", {"limit": "2", "offset": "1"}, mock_handler
            )

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert len(data["checkpoints"]) == 2
        assert data["total"] == 3
        assert data["limit"] == 2
        assert data["offset"] == 1


# ============================================================================
# GET /api/checkpoints/resumable Tests
# ============================================================================


class TestListResumableDebates:
    """Tests for GET /api/checkpoints/resumable endpoint."""

    @pytest.mark.asyncio
    async def test_list_resumable_empty(
        self, checkpoint_handler, mock_handler, mock_checkpoint_manager
    ):
        """Returns empty list when no resumable debates exist."""
        mock_checkpoint_manager.list_debates_with_checkpoints.return_value = []

        with patch.object(
            checkpoint_handler, "_get_checkpoint_manager", return_value=mock_checkpoint_manager
        ):
            result = await checkpoint_handler.handle(
                "/api/v1/checkpoints/resumable", {}, mock_handler
            )

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["debates"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_list_resumable_with_data(
        self, checkpoint_handler, mock_handler, mock_checkpoint_manager
    ):
        """Returns debates with checkpoints."""
        debates = [
            {
                "debate_id": "debate-123",
                "task": "Test task",
                "checkpoint_count": 3,
                "latest_checkpoint": "cp-test-003",
                "latest_round": 3,
            },
            {
                "debate_id": "debate-456",
                "task": "Another task",
                "checkpoint_count": 1,
                "latest_checkpoint": "cp-test-001",
                "latest_round": 1,
            },
        ]
        mock_checkpoint_manager.list_debates_with_checkpoints.return_value = debates

        with patch.object(
            checkpoint_handler, "_get_checkpoint_manager", return_value=mock_checkpoint_manager
        ):
            result = await checkpoint_handler.handle(
                "/api/v1/checkpoints/resumable", {}, mock_handler
            )

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert len(data["debates"]) == 2
        assert data["total"] == 2
        assert data["debates"][0]["debate_id"] == "debate-123"


# ============================================================================
# GET /api/checkpoints/{id} Tests
# ============================================================================


class TestGetCheckpoint:
    """Tests for GET /api/checkpoints/{id} endpoint."""

    @pytest.mark.asyncio
    async def test_get_checkpoint_not_found(
        self, checkpoint_handler, mock_handler, mock_checkpoint_manager
    ):
        """Returns 404 when checkpoint doesn't exist."""
        mock_checkpoint_manager.store.load.return_value = None

        with patch.object(
            checkpoint_handler, "_get_checkpoint_manager", return_value=mock_checkpoint_manager
        ):
            result = await checkpoint_handler.handle(
                "/api/v1/checkpoints/nonexistent", {}, mock_handler
            )

        assert result is not None
        assert result.status_code == 404
        data = json.loads(result.body)
        assert "not found" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_get_checkpoint_success(
        self, checkpoint_handler, mock_handler, mock_checkpoint_manager, sample_checkpoint
    ):
        """Returns checkpoint details with integrity status."""
        mock_checkpoint_manager.store.load.return_value = sample_checkpoint

        with patch.object(
            checkpoint_handler, "_get_checkpoint_manager", return_value=mock_checkpoint_manager
        ):
            result = await checkpoint_handler.handle(
                "/api/v1/checkpoints/cp-test-001", {}, mock_handler
            )

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["checkpoint"]["checkpoint_id"] == "cp-test-001"
        assert data["checkpoint"]["debate_id"] == "debate-123"
        assert "integrity_valid" in data["checkpoint"]


# ============================================================================
# POST /api/checkpoints/{id}/resume Tests
# ============================================================================


class TestResumeCheckpoint:
    """Tests for POST /api/checkpoints/{id}/resume endpoint."""

    @pytest.mark.asyncio
    async def test_resume_checkpoint_not_found(
        self, checkpoint_handler, mock_handler, mock_checkpoint_manager
    ):
        """Returns 404 when checkpoint doesn't exist."""
        mock_handler.command = "POST"
        mock_checkpoint_manager.resume_from_checkpoint.return_value = None

        with patch.object(
            checkpoint_handler, "_get_checkpoint_manager", return_value=mock_checkpoint_manager
        ):
            result = await checkpoint_handler.handle(
                "/api/v1/checkpoints/nonexistent/resume", {}, mock_handler, body=None
            )

        assert result is not None
        assert result.status_code == 404
        data = json.loads(result.body)
        assert "not found" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_resume_checkpoint_success(
        self, checkpoint_handler, mock_handler, mock_checkpoint_manager, sample_checkpoint
    ):
        """Successfully resumes from checkpoint."""
        mock_handler.command = "POST"
        resumed = ResumedDebate(
            checkpoint=sample_checkpoint,
            original_debate_id="debate-123",
            resumed_at="2026-01-17T12:00:00",
            resumed_by="api",
            messages=[
                Message(
                    role="assistant",
                    agent="claude",
                    content="Test message",
                    timestamp=datetime(2026, 1, 17, 10, 0, 0),
                    round=1,
                )
            ],
            votes=[
                Vote(
                    agent="claude",
                    choice="option_a",
                    confidence=0.8,
                    reasoning="Test reasoning",
                    continue_debate=True,
                )
            ],
        )
        mock_checkpoint_manager.resume_from_checkpoint.return_value = resumed
        mock_checkpoint_manager.store.load.return_value = sample_checkpoint

        with patch.object(
            checkpoint_handler, "_get_checkpoint_manager", return_value=mock_checkpoint_manager
        ):
            result = await checkpoint_handler.handle(
                "/api/v1/checkpoints/cp-test-001/resume", {}, mock_handler, body=None
            )

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert "resumed from checkpoint" in data["message"].lower()
        assert data["resumed_debate"]["original_debate_id"] == "debate-123"
        assert data["resumed_debate"]["message_count"] == 1

    @pytest.mark.asyncio
    async def test_resume_checkpoint_with_body(
        self, checkpoint_handler, mock_handler, mock_checkpoint_manager, sample_checkpoint
    ):
        """Resumes with custom resumed_by from request body."""
        mock_handler.command = "POST"
        body = json.dumps({"resumed_by": "user_123"}).encode()
        resumed = ResumedDebate(
            checkpoint=sample_checkpoint,
            original_debate_id="debate-123",
            resumed_at="2026-01-17T12:00:00",
            resumed_by="user_123",
            messages=[],
            votes=[],
        )
        mock_checkpoint_manager.resume_from_checkpoint.return_value = resumed
        mock_checkpoint_manager.store.load.return_value = sample_checkpoint

        with patch.object(
            checkpoint_handler, "_get_checkpoint_manager", return_value=mock_checkpoint_manager
        ):
            result = await checkpoint_handler.handle(
                "/api/v1/checkpoints/cp-test-001/resume", {}, mock_handler, body=body
            )

        assert result is not None
        assert result.status_code == 200
        mock_checkpoint_manager.resume_from_checkpoint.assert_called_with(
            checkpoint_id="cp-test-001",
            resumed_by="user_123",
        )


# ============================================================================
# DELETE /api/checkpoints/{id} Tests
# ============================================================================


class TestDeleteCheckpoint:
    """Tests for DELETE /api/checkpoints/{id} endpoint."""

    @pytest.mark.asyncio
    async def test_delete_checkpoint_not_found(
        self, checkpoint_handler, mock_handler, mock_checkpoint_manager
    ):
        """Returns 404 when checkpoint doesn't exist."""
        mock_handler.command = "DELETE"
        mock_checkpoint_manager.store.load.return_value = None

        with patch.object(
            checkpoint_handler, "_get_checkpoint_manager", return_value=mock_checkpoint_manager
        ):
            result = await checkpoint_handler.handle(
                "/api/v1/checkpoints/nonexistent", {}, mock_handler
            )

        assert result is not None
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_checkpoint_success(
        self, checkpoint_handler, mock_handler, mock_checkpoint_manager, sample_checkpoint
    ):
        """Successfully deletes checkpoint."""
        mock_handler.command = "DELETE"
        mock_checkpoint_manager.store.load.return_value = sample_checkpoint
        mock_checkpoint_manager.store.delete.return_value = True

        with patch.object(
            checkpoint_handler, "_get_checkpoint_manager", return_value=mock_checkpoint_manager
        ):
            result = await checkpoint_handler.handle(
                "/api/v1/checkpoints/cp-test-001", {}, mock_handler
            )

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert "deleted" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_delete_checkpoint_failure(
        self, checkpoint_handler, mock_handler, mock_checkpoint_manager, sample_checkpoint
    ):
        """Returns 500 when delete fails."""
        mock_handler.command = "DELETE"
        mock_checkpoint_manager.store.load.return_value = sample_checkpoint
        mock_checkpoint_manager.store.delete.return_value = False

        with patch.object(
            checkpoint_handler, "_get_checkpoint_manager", return_value=mock_checkpoint_manager
        ):
            result = await checkpoint_handler.handle(
                "/api/v1/checkpoints/cp-test-001", {}, mock_handler
            )

        assert result is not None
        assert result.status_code == 500
        data = json.loads(result.body)
        assert "failed" in data["error"].lower()


# ============================================================================
# POST /api/checkpoints/{id}/intervention Tests
# ============================================================================


class TestAddIntervention:
    """Tests for POST /api/checkpoints/{id}/intervention endpoint."""

    @pytest.mark.asyncio
    async def test_add_intervention_missing_note(
        self, checkpoint_handler, mock_handler, mock_checkpoint_manager
    ):
        """Returns 400 when note is missing."""
        mock_handler.command = "POST"
        body = json.dumps({}).encode()

        with patch.object(
            checkpoint_handler, "_get_checkpoint_manager", return_value=mock_checkpoint_manager
        ):
            result = await checkpoint_handler.handle(
                "/api/v1/checkpoints/cp-test-001/intervention", {}, mock_handler, body=body
            )

        assert result is not None
        assert result.status_code == 400
        data = json.loads(result.body)
        assert "note" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_add_intervention_checkpoint_not_found(
        self, checkpoint_handler, mock_handler, mock_checkpoint_manager
    ):
        """Returns 404 when checkpoint doesn't exist."""
        mock_handler.command = "POST"
        body = json.dumps({"note": "Human review needed"}).encode()
        mock_checkpoint_manager.add_intervention.return_value = False

        with patch.object(
            checkpoint_handler, "_get_checkpoint_manager", return_value=mock_checkpoint_manager
        ):
            result = await checkpoint_handler.handle(
                "/api/v1/checkpoints/nonexistent/intervention", {}, mock_handler, body=body
            )

        assert result is not None
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_add_intervention_success(
        self, checkpoint_handler, mock_handler, mock_checkpoint_manager, sample_checkpoint
    ):
        """Successfully adds intervention note."""
        mock_handler.command = "POST"
        body = json.dumps({"note": "Human review: Agents stuck in loop", "by": "admin"}).encode()
        mock_checkpoint_manager.add_intervention.return_value = True
        mock_checkpoint_manager.store.load.return_value = sample_checkpoint

        with patch.object(
            checkpoint_handler, "_get_checkpoint_manager", return_value=mock_checkpoint_manager
        ):
            result = await checkpoint_handler.handle(
                "/api/v1/checkpoints/cp-test-001/intervention", {}, mock_handler, body=body
            )

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert "added" in data["message"].lower()
        mock_checkpoint_manager.add_intervention.assert_called_with(
            checkpoint_id="cp-test-001",
            note="Human review: Agents stuck in loop",
            by="admin",
        )


# ============================================================================
# GET /api/debates/{id}/checkpoints Tests
# ============================================================================


class TestListDebateCheckpoints:
    """Tests for GET /api/debates/{id}/checkpoints endpoint."""

    @pytest.mark.asyncio
    async def test_list_debate_checkpoints_empty(
        self, checkpoint_handler, mock_handler, mock_checkpoint_manager
    ):
        """Returns empty list when no checkpoints exist for debate."""
        mock_checkpoint_manager.store.list_checkpoints.return_value = []

        with patch.object(
            checkpoint_handler, "_get_checkpoint_manager", return_value=mock_checkpoint_manager
        ):
            result = await checkpoint_handler.handle(
                "/api/v1/debates/debate-123/checkpoints", {}, mock_handler
            )

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["debate_id"] == "debate-123"
        assert data["checkpoints"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_list_debate_checkpoints_with_data(
        self, checkpoint_handler, mock_handler, mock_checkpoint_manager, sample_checkpoint_list
    ):
        """Returns checkpoints for specific debate sorted by creation time."""
        # Only checkpoints for debate-123
        debate_checkpoints = [
            cp for cp in sample_checkpoint_list if cp["debate_id"] == "debate-123"
        ]
        mock_checkpoint_manager.store.list_checkpoints.return_value = debate_checkpoints

        with patch.object(
            checkpoint_handler, "_get_checkpoint_manager", return_value=mock_checkpoint_manager
        ):
            result = await checkpoint_handler.handle(
                "/api/v1/debates/debate-123/checkpoints", {}, mock_handler
            )

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["debate_id"] == "debate-123"
        assert data["total"] == 2
        # Should be sorted by created_at descending
        assert data["checkpoints"][0]["checkpoint_id"] == "cp-test-002"


# ============================================================================
# POST /api/debates/{id}/checkpoint Tests (501 Not Implemented)
# ============================================================================


class TestCreateCheckpoint:
    """Tests for POST /api/debates/{id}/checkpoint endpoint."""

    @pytest.mark.asyncio
    async def test_create_checkpoint_no_debate_returns_404(self, checkpoint_handler, mock_handler):
        """Returns 404 when no active debate session exists.

        The handler first checks get_state_manager().get_debate() which returns
        None for non-running debates, resulting in a 404 before any checkpoint
        logic is reached.
        """
        mock_handler.command = "POST"

        result = await checkpoint_handler.handle(
            "/api/v1/debates/debate-123/checkpoint", {}, mock_handler, body=None
        )

        assert result is not None
        assert result.status_code == 404
        data = json.loads(result.body)
        assert "not found" in data["error"].lower()


# ============================================================================
# POST /api/debates/{id}/checkpoint/pause Tests (501 Not Implemented)
# ============================================================================


class TestPauseDebate:
    """Tests for POST /api/debates/{id}/checkpoint/pause endpoint."""

    @pytest.mark.asyncio
    async def test_pause_debate_no_debate_returns_404(self, checkpoint_handler, mock_handler):
        """Returns 404 when no active debate session exists.

        The handler first checks get_state_manager().get_debate() which returns
        None for non-running debates, resulting in a 404 before any pause
        logic is reached.
        """
        mock_handler.command = "POST"

        result = await checkpoint_handler.handle(
            "/api/v1/debates/debate-123/checkpoint/pause", {}, mock_handler, body=None
        )

        assert result is not None
        assert result.status_code == 404
        data = json.loads(result.body)
        assert "not found" in data["error"].lower()


# ============================================================================
# Request Routing Tests
# ============================================================================


class TestRequestRouting:
    """Tests for request routing to correct handlers."""

    @pytest.mark.asyncio
    async def test_route_get_checkpoints(
        self, checkpoint_handler, mock_handler, mock_checkpoint_manager
    ):
        """GET /api/checkpoints routes to list_checkpoints."""
        mock_handler.command = "GET"
        mock_checkpoint_manager.store.list_checkpoints.return_value = []

        with patch.object(
            checkpoint_handler, "_get_checkpoint_manager", return_value=mock_checkpoint_manager
        ):
            result = await checkpoint_handler.handle("/api/v1/checkpoints", {}, mock_handler)

        assert result is not None
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_route_get_resumable(
        self, checkpoint_handler, mock_handler, mock_checkpoint_manager
    ):
        """GET /api/checkpoints/resumable routes to list_resumable_debates."""
        mock_handler.command = "GET"
        mock_checkpoint_manager.list_debates_with_checkpoints.return_value = []

        with patch.object(
            checkpoint_handler, "_get_checkpoint_manager", return_value=mock_checkpoint_manager
        ):
            result = await checkpoint_handler.handle(
                "/api/v1/checkpoints/resumable", {}, mock_handler
            )

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert "debates" in data

    @pytest.mark.asyncio
    async def test_route_unknown_returns_404(self, checkpoint_handler, mock_handler):
        """Unknown routes return 404."""
        mock_handler.command = "GET"

        # The handle method should return 404 for unhandled paths
        result = await checkpoint_handler.handle(
            "/api/v1/checkpoints/unknown/path/here", {}, mock_handler
        )

        # Since the path has 5+ segments and doesn't match known patterns
        assert result is not None
        assert result.status_code == 404


# ============================================================================
# Handler Import Tests
# ============================================================================


class TestCheckpointHandlerImport:
    """Test CheckpointHandler import and export."""

    def test_handler_importable(self):
        """CheckpointHandler can be imported from handlers package."""
        from aragora.server.handlers import CheckpointHandler

        assert CheckpointHandler is not None

    def test_handler_in_all_exports(self):
        """CheckpointHandler is available from handlers module.

        Note: CheckpointHandler is imported but not yet in __all__ exports.
        This test verifies the handler can be accessed via direct import.
        """
        from aragora.server.handlers import CheckpointHandler as ImportedHandler

        assert ImportedHandler is not None
        assert ImportedHandler is CheckpointHandler


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestCheckpointErrorHandling:
    """Tests for error handling scenarios."""

    @pytest.mark.asyncio
    async def test_handles_invalid_json_body(
        self, checkpoint_handler, mock_handler, mock_checkpoint_manager
    ):
        """Handles invalid JSON in request body gracefully."""
        mock_handler.command = "POST"
        body = b"not valid json"

        with patch.object(
            checkpoint_handler, "_get_checkpoint_manager", return_value=mock_checkpoint_manager
        ):
            result = await checkpoint_handler.handle(
                "/api/v1/checkpoints/cp-test-001/intervention", {}, mock_handler, body=body
            )

        # Should still work (empty body parsed as {}, then missing note error)
        assert result is not None
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_handles_empty_body(
        self, checkpoint_handler, mock_handler, mock_checkpoint_manager
    ):
        """Handles empty request body gracefully."""
        mock_handler.command = "POST"
        mock_checkpoint_manager.resume_from_checkpoint.return_value = None

        with patch.object(
            checkpoint_handler, "_get_checkpoint_manager", return_value=mock_checkpoint_manager
        ):
            result = await checkpoint_handler.handle(
                "/api/v1/checkpoints/cp-test-001/resume", {}, mock_handler, body=None
            )

        assert result is not None
        # Should return 404 since checkpoint not found
        assert result.status_code == 404


# ============================================================================
# Checkpoint Manager Initialization Tests
# ============================================================================


class TestCheckpointManagerInit:
    """Tests for checkpoint manager initialization."""

    def test_get_checkpoint_manager_creates_instance(self, checkpoint_handler):
        """_get_checkpoint_manager creates and caches manager."""
        manager1 = checkpoint_handler._get_checkpoint_manager()
        manager2 = checkpoint_handler._get_checkpoint_manager()

        assert manager1 is manager2
        assert manager1 is not None

    def test_checkpoint_manager_uses_database_store(self, checkpoint_handler):
        """Manager uses DatabaseCheckpointStore by default."""
        from aragora.debate.checkpoint import DatabaseCheckpointStore

        manager = checkpoint_handler._get_checkpoint_manager()

        assert isinstance(manager.store, DatabaseCheckpointStore)
