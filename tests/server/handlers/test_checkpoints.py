"""
Tests for the checkpoints handler - debate checkpoint management.

Tests:
- Route handling (can_handle)
- List checkpoints endpoint
- List resumable debates endpoint
- Get checkpoint details
- Resume from checkpoint
- Delete checkpoint
- Create checkpoint for debate
- Pause debate and checkpoint
- Error handling
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from aragora.server.handlers.checkpoints import CheckpointHandler

# The org the auto-auth fixture authenticates every request as.
ORG_ID = "test-org-001"


@pytest.fixture
def checkpoint_handler():
    """Create a checkpoint handler whose storage puts every debate in ORG_ID."""
    storage = MagicMock()
    storage.get_access_info.side_effect = lambda ref: (ref, ORG_ID, False)
    ctx = {"storage": storage, "elo_system": None}
    handler = CheckpointHandler(ctx)
    return handler


def owned_checkpoint(debate_id: str = "deb-1") -> MagicMock:
    """A checkpoint of a debate the caller's org owns."""
    checkpoint = MagicMock()
    checkpoint.debate_id = debate_id
    return checkpoint


@pytest.fixture
def mock_http_handler():
    """Create a mock HTTP handler."""
    mock = MagicMock()
    mock.client_address = ("127.0.0.1", 12345)
    mock.headers = {"Content-Type": "application/json"}
    mock.command = "GET"
    return mock


def make_post_handler(body: dict = None, method: str = "POST") -> MagicMock:
    """Create a mock HTTP handler with optional JSON body."""
    mock = MagicMock()
    mock.client_address = ("127.0.0.1", 12345)
    mock.command = method
    if body:
        body_bytes = json.dumps(body).encode()
        mock.headers = {"Content-Type": "application/json", "Content-Length": str(len(body_bytes))}
        mock.request_body = body_bytes
    else:
        mock.headers = {"Content-Type": "application/json"}
        mock.request_body = b"{}"
    return mock


class TestCheckpointHandlerRouting:
    """Tests for CheckpointHandler route matching."""

    def test_can_handle_checkpoints_list(self, checkpoint_handler):
        """Test that handler recognizes /api/checkpoints route."""
        assert checkpoint_handler.can_handle("/api/v1/checkpoints") is True

    def test_can_handle_checkpoints_resumable(self, checkpoint_handler):
        """Test that handler recognizes /api/checkpoints/resumable route."""
        assert checkpoint_handler.can_handle("/api/v1/checkpoints/resumable") is True

    def test_can_handle_checkpoint_by_id(self, checkpoint_handler):
        """Test that handler recognizes /api/checkpoints/{id} route."""
        assert checkpoint_handler.can_handle("/api/v1/checkpoints/cp-123") is True
        assert checkpoint_handler.can_handle("/api/v1/checkpoints/abc-def-ghi") is True

    def test_can_handle_checkpoint_resume(self, checkpoint_handler):
        """Test that handler recognizes /api/checkpoints/{id}/resume route."""
        assert checkpoint_handler.can_handle("/api/v1/checkpoints/cp-123/resume") is True

    def test_can_handle_debate_checkpoints(self, checkpoint_handler):
        """Test that handler recognizes /api/debates/{id}/checkpoints route."""
        assert checkpoint_handler.can_handle("/api/v1/debates/deb-123/checkpoints") is True

    def test_can_handle_debate_checkpoint_create(self, checkpoint_handler):
        """Test that handler recognizes /api/debates/{id}/checkpoint route."""
        assert checkpoint_handler.can_handle("/api/v1/debates/deb-123/checkpoint") is True

    def test_can_handle_debate_checkpoint_pause(self, checkpoint_handler):
        """Test that handler recognizes /api/debates/{id}/checkpoint/pause route."""
        assert checkpoint_handler.can_handle("/api/v1/debates/deb-123/checkpoint/pause") is True

    def test_cannot_handle_unknown_path(self, checkpoint_handler):
        """Test that handler rejects unknown paths."""
        assert checkpoint_handler.can_handle("/api/v1/unknown") is False
        assert checkpoint_handler.can_handle("/api/v1/debates") is False
        # Note: /api/debates/123 without /checkpoint is NOT handled by this handler
        assert checkpoint_handler.can_handle("/api/v1/debates/123") is False


class TestListCheckpoints:
    """Tests for GET /api/checkpoints endpoint."""

    @pytest.mark.asyncio
    async def test_list_checkpoints_empty(self, checkpoint_handler, mock_http_handler):
        """List checkpoints should return empty list when no checkpoints exist."""
        mock_store = AsyncMock()
        mock_store.list_checkpoints = AsyncMock(return_value=[])

        with patch.object(checkpoint_handler, "_get_checkpoint_manager") as mock_mgr:
            mock_mgr.return_value.store = mock_store
            result = await checkpoint_handler.handle("/api/v1/checkpoints", {}, mock_http_handler)

        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        assert "checkpoints" in body
        assert body["checkpoints"] == []
        assert body["total"] == 0

    @pytest.mark.asyncio
    async def test_list_checkpoints_with_data(self, checkpoint_handler, mock_http_handler):
        """List checkpoints should return checkpoint data."""
        checkpoints = [
            {"id": "cp-1", "debate_id": "deb-1", "status": "complete"},
            {"id": "cp-2", "debate_id": "deb-2", "status": "resuming"},
        ]
        mock_store = AsyncMock()
        mock_store.list_checkpoints = AsyncMock(return_value=checkpoints)

        with patch.object(checkpoint_handler, "_get_checkpoint_manager") as mock_mgr:
            mock_mgr.return_value.store = mock_store
            result = await checkpoint_handler.handle("/api/v1/checkpoints", {}, mock_http_handler)

        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        assert len(body["checkpoints"]) == 2
        assert body["total"] == 2

    @pytest.mark.asyncio
    async def test_list_checkpoints_with_status_filter(self, checkpoint_handler, mock_http_handler):
        """List checkpoints should filter by status."""
        checkpoints = [
            {"id": "cp-1", "debate_id": "deb-1", "status": "complete"},
            {"id": "cp-2", "debate_id": "deb-1", "status": "resuming"},
            {"id": "cp-3", "debate_id": "deb-2", "status": "complete"},
        ]
        mock_store = AsyncMock()
        mock_store.list_checkpoints = AsyncMock(return_value=checkpoints)

        with patch.object(checkpoint_handler, "_get_checkpoint_manager") as mock_mgr:
            mock_mgr.return_value.store = mock_store
            result = await checkpoint_handler.handle(
                "/api/v1/checkpoints", {"status": "complete"}, mock_http_handler
            )

        assert result is not None
        body = json.loads(result.body)
        assert len(body["checkpoints"]) == 2
        assert all(cp["status"] == "complete" for cp in body["checkpoints"])

    @pytest.mark.asyncio
    async def test_list_checkpoints_with_pagination(self, checkpoint_handler, mock_http_handler):
        """List checkpoints should support pagination."""
        checkpoints = [{"id": f"cp-{i}", "debate_id": f"deb-{i}"} for i in range(10)]
        mock_store = AsyncMock()
        mock_store.list_checkpoints = AsyncMock(return_value=checkpoints)

        with patch.object(checkpoint_handler, "_get_checkpoint_manager") as mock_mgr:
            mock_mgr.return_value.store = mock_store
            result = await checkpoint_handler.handle(
                "/api/v1/checkpoints", {"limit": "3", "offset": "2"}, mock_http_handler
            )

        assert result is not None
        body = json.loads(result.body)
        assert len(body["checkpoints"]) == 3
        assert body["total"] == 10
        assert body["limit"] == 3
        assert body["offset"] == 2


class TestListResumableDebates:
    """Tests for GET /api/checkpoints/resumable endpoint."""

    @pytest.mark.asyncio
    async def test_list_resumable_debates_empty(self, checkpoint_handler, mock_http_handler):
        """List resumable debates should return empty list when none exist."""
        with patch.object(checkpoint_handler, "_get_checkpoint_manager") as mock_mgr:
            mock_mgr.return_value.list_debates_with_checkpoints = AsyncMock(return_value=[])
            result = await checkpoint_handler.handle(
                "/api/v1/checkpoints/resumable", {}, mock_http_handler
            )

        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["debates"] == []
        assert body["total"] == 0

    @pytest.mark.asyncio
    async def test_list_resumable_debates_with_data(self, checkpoint_handler, mock_http_handler):
        """List resumable debates should return debate data."""
        debates = [
            {"debate_id": "deb-1", "checkpoint_count": 2},
            {"debate_id": "deb-2", "checkpoint_count": 1},
        ]
        with patch.object(checkpoint_handler, "_get_checkpoint_manager") as mock_mgr:
            mock_mgr.return_value.list_debates_with_checkpoints = AsyncMock(return_value=debates)
            result = await checkpoint_handler.handle(
                "/api/v1/checkpoints/resumable", {}, mock_http_handler
            )

        assert result is not None
        body = json.loads(result.body)
        assert len(body["debates"]) == 2
        assert body["total"] == 2


class TestGetCheckpoint:
    """Tests for GET /api/checkpoints/{id} endpoint."""

    @pytest.mark.asyncio
    async def test_get_checkpoint_success(self, checkpoint_handler, mock_http_handler):
        """Get checkpoint should return checkpoint details."""
        mock_checkpoint = owned_checkpoint()
        mock_checkpoint.to_dict.return_value = {
            "id": "cp-123",
            "debate_id": "deb-1",
            "status": "complete",
        }
        mock_checkpoint.verify_integrity.return_value = True

        mock_store = AsyncMock()
        mock_store.load = AsyncMock(return_value=mock_checkpoint)

        with patch.object(checkpoint_handler, "_get_checkpoint_manager") as mock_mgr:
            mock_mgr.return_value.store = mock_store
            result = await checkpoint_handler.handle(
                "/api/v1/checkpoints/cp-123", {}, mock_http_handler
            )

        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["checkpoint"]["id"] == "cp-123"
        assert body["checkpoint"]["integrity_valid"] is True

    @pytest.mark.asyncio
    async def test_get_checkpoint_not_found(self, checkpoint_handler, mock_http_handler):
        """Get checkpoint should return 404 for non-existent checkpoint."""
        mock_store = AsyncMock()
        mock_store.load = AsyncMock(return_value=None)

        with patch.object(checkpoint_handler, "_get_checkpoint_manager") as mock_mgr:
            mock_mgr.return_value.store = mock_store
            result = await checkpoint_handler.handle(
                "/api/v1/checkpoints/nonexistent", {}, mock_http_handler
            )

        assert result is not None
        assert result.status_code == 404
        body = json.loads(result.body)
        assert "error" in body


class TestResumeCheckpoint:
    """Tests for POST /api/checkpoints/{id}/resume endpoint."""

    @pytest.mark.asyncio
    async def test_resume_checkpoint_success(self, checkpoint_handler):
        """Resume checkpoint should return resumed debate info."""
        mock_resumed = MagicMock()
        mock_resumed.original_debate_id = "deb-1"
        mock_resumed.resumed_at = "2024-01-01T00:00:00Z"
        mock_resumed.resumed_by = "user-1"
        mock_resumed.checkpoint.current_round = 2
        mock_resumed.checkpoint.total_rounds = 5
        mock_resumed.checkpoint.task = "Test task"
        mock_resumed.messages = ["msg1", "msg2"]
        mock_resumed.votes = []

        handler = make_post_handler({"resumed_by": "user-1"})

        with patch.object(checkpoint_handler, "_get_checkpoint_manager") as mock_mgr:
            mock_mgr.return_value.store.load = AsyncMock(return_value=owned_checkpoint())
            mock_mgr.return_value.resume_from_checkpoint = AsyncMock(return_value=mock_resumed)
            result = await checkpoint_handler.handle(
                "/api/v1/checkpoints/cp-123/resume", {}, handler, b'{"resumed_by": "user-1"}'
            )

        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["resumed_debate"]["original_debate_id"] == "deb-1"
        assert body["resumed_debate"]["checkpoint_id"] == "cp-123"

    @pytest.mark.asyncio
    async def test_resume_checkpoint_not_found(self, checkpoint_handler):
        """Resume checkpoint should return 404 for non-existent checkpoint."""
        handler = make_post_handler({})

        with patch.object(checkpoint_handler, "_get_checkpoint_manager") as mock_mgr:
            mock_mgr.return_value.store.load = AsyncMock(return_value=None)
            mock_mgr.return_value.resume_from_checkpoint = AsyncMock(return_value=None)
            result = await checkpoint_handler.handle(
                "/api/v1/checkpoints/nonexistent/resume", {}, handler, b"{}"
            )

        assert result is not None
        assert result.status_code == 404


class TestDeleteCheckpoint:
    """Tests for DELETE /api/checkpoints/{id} endpoint."""

    @pytest.mark.asyncio
    async def test_delete_checkpoint_success(self, checkpoint_handler):
        """Delete checkpoint should succeed for existing checkpoint."""
        mock_checkpoint = owned_checkpoint()
        mock_store = AsyncMock()
        mock_store.load = AsyncMock(return_value=mock_checkpoint)
        mock_store.delete = AsyncMock(return_value=True)

        handler = make_post_handler(method="DELETE")

        with patch.object(checkpoint_handler, "_get_checkpoint_manager") as mock_mgr:
            mock_mgr.return_value.store = mock_store
            result = await checkpoint_handler.handle("/api/v1/checkpoints/cp-123", {}, handler)

        assert result is not None
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_checkpoint_not_found(self, checkpoint_handler):
        """Delete checkpoint should return 404 for non-existent checkpoint."""
        mock_store = AsyncMock()
        mock_store.load = AsyncMock(return_value=None)

        handler = make_post_handler(method="DELETE")

        with patch.object(checkpoint_handler, "_get_checkpoint_manager") as mock_mgr:
            mock_mgr.return_value.store = mock_store
            result = await checkpoint_handler.handle("/api/v1/checkpoints/nonexistent", {}, handler)

        assert result is not None
        assert result.status_code == 404


class TestDebateCheckpoints:
    """Tests for debate-specific checkpoint endpoints."""

    @pytest.mark.asyncio
    async def test_list_debate_checkpoints(self, checkpoint_handler, mock_http_handler):
        """List checkpoints for a specific debate."""
        checkpoints = [
            {"id": "cp-1", "debate_id": "deb-123"},
            {"id": "cp-2", "debate_id": "deb-123"},
        ]
        mock_store = AsyncMock()
        mock_store.list_checkpoints = AsyncMock(return_value=checkpoints)

        with patch.object(checkpoint_handler, "_get_checkpoint_manager") as mock_mgr:
            mock_mgr.return_value.store = mock_store
            result = await checkpoint_handler.handle(
                "/api/v1/debates/deb-123/checkpoints", {}, mock_http_handler
            )

        assert result is not None
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_other_org_checkpoint_is_not_found(self, checkpoint_handler, mock_http_handler):
        """A checkpoint of another org's debate gets the same 404 as a missing one."""
        checkpoint_handler.ctx["storage"].get_access_info.side_effect = lambda ref: (
            ref,
            "other-org",
            False,
        )
        mock_store = AsyncMock()
        mock_store.load = AsyncMock(return_value=owned_checkpoint())

        with patch.object(checkpoint_handler, "_get_checkpoint_manager") as mock_mgr:
            mock_mgr.return_value.store = mock_store
            result = await checkpoint_handler.handle(
                "/api/v1/checkpoints/cp-123", {}, mock_http_handler
            )

        assert result.status_code == 404
        assert json.loads(result.body) == {"error": "Checkpoint not found", "code": "not_found"}


class TestNotFoundHandling:
    """Tests for 404 handling of unmatched routes."""

    @pytest.mark.asyncio
    async def test_unknown_path_returns_404(self, checkpoint_handler, mock_http_handler):
        """Unknown paths should return 404."""
        # Note: can_handle returns True for this path, so handle() gets called
        # and should return 404 for unknown sub-paths
        result = await checkpoint_handler.handle(
            "/api/v1/checkpoints/cp-123/unknown", {}, mock_http_handler
        )

        assert result is not None
        assert result.status_code == 404
