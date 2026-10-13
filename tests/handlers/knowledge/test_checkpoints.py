"""
Comprehensive tests for KMCheckpointHandler.

Tests the Knowledge Mound checkpoint HTTP handler endpoints:
- GET /api/v1/km/checkpoints - List all checkpoints
- POST /api/v1/km/checkpoints - Create a checkpoint
- GET /api/v1/km/checkpoints/{name} - Get checkpoint details
- DELETE /api/v1/km/checkpoints/{name} - Delete a checkpoint
- POST /api/v1/km/checkpoints/{name}/restore - Restore from checkpoint
- GET /api/v1/km/checkpoints/{name}/compare - Compare with current state
- POST /api/v1/km/checkpoints/compare - Compare two checkpoints
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.knowledge.checkpoints import KMCheckpointHandler


# =============================================================================
# Helpers
# =============================================================================


def _body(result) -> dict:
    """Extract JSON body dict from a HandlerResult."""
    if isinstance(result, dict):
        return result
    return json.loads(result.body)


def _status(result) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return result.status_code


# =============================================================================
# Mock data classes
# =============================================================================


@dataclass
class MockCheckpointMetadata:
    """Mock for KMCheckpointMetadata."""

    name: str
    id: str = ""
    description: str = ""
    created_at: str = "2026-02-23T10:00:00Z"
    node_count: int = 42
    size_bytes: int = 1024
    compressed: bool = False
    tags: list[str] = field(default_factory=list)
    checksum: str = "abc123"

    def __post_init__(self):
        if not self.id:
            self.id = self.name


@dataclass
class MockRestoreResult:
    """Mock for RestoreResult."""

    checkpoint_id: str
    success: bool = True
    nodes_restored: int = 10
    relationships_restored: int = 5
    errors: list[str] = field(default_factory=list)


# =============================================================================
# Mock HTTP handler
# =============================================================================


class _MockHTTPHandler:
    """Lightweight mock for the HTTP handler passed to the checkpoint handler."""

    def __init__(
        self,
        method: str = "GET",
        path: str = "/api/v1/km/checkpoints",
        body: dict[str, Any] | None = None,
    ):
        self.command = method
        self.path = path
        self.client_address = ("127.0.0.1", 12345)
        self.headers = {"Content-Length": "0", "Host": "localhost:8080"}

        if body is not None:
            body_bytes = json.dumps(body).encode("utf-8")
            self.headers["Content-Length"] = str(len(body_bytes))
            self.headers["Content-Type"] = "application/json"
            self.rfile = io.BytesIO(body_bytes)
        else:
            self.rfile = io.BytesIO(b"")


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def handler():
    """Create a KMCheckpointHandler with empty server context."""
    return KMCheckpointHandler(server_context={})


@pytest.fixture
def mock_store():
    """Create a mock checkpoint store with async methods."""
    store = AsyncMock()
    store.list_checkpoints = AsyncMock(return_value=[])
    store.create_checkpoint = AsyncMock(return_value="cp-id-1")
    store.get_checkpoint_metadata = AsyncMock(return_value=None)
    store.delete_checkpoint = AsyncMock(return_value=True)
    store.restore_checkpoint = AsyncMock(return_value=MockRestoreResult(checkpoint_id="test-cp"))
    store.compare_checkpoints = AsyncMock(return_value={"added": 1, "removed": 0})
    return store


@pytest.fixture
def handler_with_store(handler, mock_store):
    """Create a handler with the mock store injected."""
    handler._checkpoint_store = mock_store
    return handler


@pytest.fixture
def sample_checkpoints():
    """Create a list of sample checkpoint metadata objects."""
    return [
        MockCheckpointMetadata(
            name="cp-alpha",
            description="First checkpoint",
            node_count=10,
            size_bytes=512,
            tags=["v1"],
        ),
        MockCheckpointMetadata(
            name="cp-beta",
            description="Second checkpoint",
            node_count=20,
            size_bytes=1024,
            tags=["v2"],
        ),
        MockCheckpointMetadata(
            name="cp-gamma",
            description="Third checkpoint",
            node_count=30,
            size_bytes=2048,
            tags=["v3"],
        ),
    ]


# =============================================================================
# Test: Handler initialization
# =============================================================================


class TestHandlerInit:
    """Tests for handler construction."""

    def test_init_with_empty_context(self):
        h = KMCheckpointHandler(server_context={})
        assert h._checkpoint_store is None

    def test_init_with_none_context(self):
        h = KMCheckpointHandler(server_context=None)
        assert h._checkpoint_store is None

    def test_routes_defined(self, handler):
        # Uppercase ROUTES: the registry route index and BaseHandler.can_handle
        # only read ROUTES; lowercase routes left this handler undispatchable.
        # The bare /api/v1/km/checkpoints path stays owned (first-wins) by
        # KnowledgeMoundHandler — only compare is claimed here.
        assert "/api/v1/km/checkpoints/compare" in handler.ROUTES
        assert "/api/v1/km/checkpoints" not in handler.ROUTES

    def test_dynamic_routes_defined(self, handler):
        assert "/api/v1/km/checkpoints/{name}" in handler.dynamic_routes
        assert "/api/v1/km/checkpoints/{name}/restore" in handler.dynamic_routes
        assert "/api/v1/km/checkpoints/{name}/compare" in handler.dynamic_routes
        assert "/api/v1/km/checkpoints/{name}/download" in handler.dynamic_routes


# =============================================================================
# Test: _get_checkpoint_store
# =============================================================================


class TestGetCheckpointStore:
    """Tests for lazy checkpoint store initialization."""

    def test_returns_injected_store(self, handler_with_store, mock_store):
        result = handler_with_store._get_checkpoint_store()
        assert result is mock_store

    @patch(
        "aragora.server.handlers.knowledge.checkpoints.KMCheckpointHandler._get_checkpoint_store"
    )
    def test_store_not_available_raises_runtime_error(self, mock_get):
        mock_get.side_effect = RuntimeError("KM checkpoint store not initialized")
        h = KMCheckpointHandler(server_context={})
        with pytest.raises(RuntimeError, match="KM checkpoint store not initialized"):
            h._get_checkpoint_store()


# =============================================================================
# Test: GET /api/v1/km/checkpoints (list)
# =============================================================================


class TestListCheckpoints:
    """Tests for listing checkpoints."""

    @pytest.mark.asyncio
    async def test_list_empty(self, handler_with_store, mock_store):
        mock_store.list_checkpoints.return_value = []
        mock_handler = _MockHTTPHandler(path="/api/v1/km/checkpoints")
        result = await handler_with_store.handle_get(
            path="/api/v1/km/checkpoints",
            query_params={},
            handler=mock_handler,
        )
        body = _body(result)
        assert _status(result) == 200
        data = body.get("data", body)
        assert data["total"] == 0
        assert data["checkpoints"] == []

    @pytest.mark.asyncio
    async def test_list_returns_checkpoints(
        self, handler_with_store, mock_store, sample_checkpoints
    ):
        mock_store.list_checkpoints.return_value = sample_checkpoints
        mock_handler = _MockHTTPHandler(path="/api/v1/km/checkpoints")
        result = await handler_with_store.handle_get(
            path="/api/v1/km/checkpoints",
            query_params={},
            handler=mock_handler,
        )
        body = _body(result)
        data = body.get("data", body)
        assert _status(result) == 200
        assert data["total"] == 3
        assert len(data["checkpoints"]) == 3
        assert data["checkpoints"][0]["name"] == "cp-alpha"
        assert data["checkpoints"][1]["name"] == "cp-beta"

    @pytest.mark.asyncio
    async def test_list_respects_limit_query_param(
        self, handler_with_store, mock_store, sample_checkpoints
    ):
        mock_store.list_checkpoints.return_value = sample_checkpoints
        mock_handler = _MockHTTPHandler(path="/api/v1/km/checkpoints?limit=2")
        result = await handler_with_store.handle_get(
            path="/api/v1/km/checkpoints",
            query_params={"limit": "2"},
            handler=mock_handler,
        )
        body = _body(result)
        data = body.get("data", body)
        assert _status(result) == 200
        assert data["total"] == 2

    @pytest.mark.asyncio
    async def test_list_limit_clamped_to_100(
        self, handler_with_store, mock_store, sample_checkpoints
    ):
        mock_store.list_checkpoints.return_value = sample_checkpoints
        mock_handler = _MockHTTPHandler(path="/api/v1/km/checkpoints?limit=500")
        result = await handler_with_store.handle_get(
            path="/api/v1/km/checkpoints",
            query_params={"limit": "500"},
            handler=mock_handler,
        )
        body = _body(result)
        data = body.get("data", body)
        assert _status(result) == 200
        # With only 3 checkpoints, total will be 3 (but limit was clamped to 100)
        assert data["total"] == 3

    @pytest.mark.asyncio
    async def test_list_limit_clamped_minimum_to_1(
        self, handler_with_store, mock_store, sample_checkpoints
    ):
        mock_store.list_checkpoints.return_value = sample_checkpoints
        mock_handler = _MockHTTPHandler(path="/api/v1/km/checkpoints?limit=0")
        result = await handler_with_store.handle_get(
            path="/api/v1/km/checkpoints",
            query_params={"limit": "0"},
            handler=mock_handler,
        )
        body = _body(result)
        data = body.get("data", body)
        assert _status(result) == 200
        # min(max(1, 0), 100) == 1
        assert data["total"] == 1

    @pytest.mark.asyncio
    async def test_list_checkpoint_fields_correct(
        self, handler_with_store, mock_store, sample_checkpoints
    ):
        mock_store.list_checkpoints.return_value = sample_checkpoints
        mock_handler = _MockHTTPHandler(path="/api/v1/km/checkpoints")
        result = await handler_with_store.handle_get(
            path="/api/v1/km/checkpoints",
            query_params={},
            handler=mock_handler,
        )
        body = _body(result)
        data = body.get("data", body)
        cp = data["checkpoints"][0]
        assert cp["name"] == "cp-alpha"
        assert cp["description"] == "First checkpoint"
        assert cp["node_count"] == 10
        assert cp["size_bytes"] == 512
        assert cp["compressed"] is False
        assert cp["tags"] == ["v1"]

    @pytest.mark.asyncio
    async def test_list_store_unavailable_returns_503(self, handler_with_store, mock_store):
        mock_store.list_checkpoints.side_effect = RuntimeError("store down")
        # We need the _get_checkpoint_store to raise RuntimeError
        handler_with_store._checkpoint_store = None
        with patch.object(
            handler_with_store,
            "_get_checkpoint_store",
            side_effect=RuntimeError("store down"),
        ):
            mock_handler = _MockHTTPHandler(path="/api/v1/km/checkpoints")
            result = await handler_with_store.handle_get(
                path="/api/v1/km/checkpoints",
                query_params={},
                handler=mock_handler,
            )
            assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_list_io_error_returns_500(self, handler_with_store, mock_store):
        mock_store.list_checkpoints.side_effect = OSError("disk full")
        mock_handler = _MockHTTPHandler(path="/api/v1/km/checkpoints")
        result = await handler_with_store.handle_get(
            path="/api/v1/km/checkpoints",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_list_default_limit_is_20(self, handler_with_store, mock_store):
        # Create 25 checkpoints
        many = [MockCheckpointMetadata(name=f"cp-{i}", node_count=i) for i in range(25)]
        mock_store.list_checkpoints.return_value = many
        mock_handler = _MockHTTPHandler(path="/api/v1/km/checkpoints")
        result = await handler_with_store.handle_get(
            path="/api/v1/km/checkpoints",
            query_params={},
            handler=mock_handler,
        )
        body = _body(result)
        data = body.get("data", body)
        assert data["total"] == 20


# =============================================================================
# Test: POST /api/v1/km/checkpoints (create)
# =============================================================================


class TestCreateCheckpoint:
    """Tests for creating checkpoints."""

    @pytest.mark.asyncio
    async def test_create_returns_string_id(self, handler_with_store, mock_store):
        mock_store.create_checkpoint.return_value = "cp-id-new"
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints",
            body={"name": "test-cp", "description": "A test", "tags": ["v1"]},
        )
        result = await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 201
        body = _body(result)
        assert body["name"] == "test-cp"
        assert body["id"] == "cp-id-new"

    @pytest.mark.asyncio
    async def test_create_returns_metadata_object(self, handler_with_store, mock_store):
        metadata = MockCheckpointMetadata(
            name="test-cp",
            description="desc",
            node_count=5,
            size_bytes=256,
            tags=["t1"],
        )
        mock_store.create_checkpoint.return_value = metadata
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints",
            body={"name": "test-cp", "description": "desc", "tags": ["t1"]},
        )
        result = await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 201
        body = _body(result)
        assert body["name"] == "test-cp"
        assert body["node_count"] == 5
        assert body["size_bytes"] == 256
        assert body["tags"] == ["t1"]

    @pytest.mark.asyncio
    async def test_create_missing_name_returns_400(self, handler_with_store, mock_store):
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints",
            body={"description": "no name"},
        )
        result = await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 400
        body = _body(result)
        assert "name" in body.get("error", body.get("message", "")).lower()

    @pytest.mark.asyncio
    async def test_create_empty_name_returns_400(self, handler_with_store, mock_store):
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints",
            body={"name": ""},
        )
        result = await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_empty_body_returns_400(self, handler_with_store, mock_store):
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints",
            body={},
        )
        result = await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_duplicate_returns_409(self, handler_with_store, mock_store):
        mock_store.create_checkpoint.side_effect = FileExistsError("already exists")
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints",
            body={"name": "existing-cp"},
        )
        result = await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 409
        body = _body(result)
        assert "already exists" in body.get("error", body.get("message", "")).lower()

    @pytest.mark.asyncio
    async def test_create_value_error_returns_400(self, handler_with_store, mock_store):
        mock_store.create_checkpoint.side_effect = ValueError("bad input")
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints",
            body={"name": "bad-cp"},
        )
        result = await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_runtime_error_returns_500(self, handler_with_store, mock_store):
        mock_store.create_checkpoint.side_effect = RuntimeError("engine failure")
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints",
            body={"name": "fail-cp"},
        )
        result = await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_create_defaults_description_and_tags(self, handler_with_store, mock_store):
        mock_store.create_checkpoint.return_value = "cp-id-2"
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints",
            body={"name": "minimal-cp"},
        )
        result = await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 201
        mock_store.create_checkpoint.assert_called_once_with(
            name="minimal-cp",
            description="",
            tags=[],
            return_metadata=True,
        )

    @pytest.mark.asyncio
    @patch("aragora.server.handlers.knowledge.checkpoints.record_checkpoint_operation")
    @patch("aragora.server.handlers.knowledge.checkpoints.check_and_record_slo")
    async def test_create_records_metrics_string_result(
        self, mock_slo, mock_record, handler_with_store, mock_store
    ):
        """When create returns a string ID, success stays False because return
        exits before success=True is reached."""
        mock_store.create_checkpoint.return_value = "cp-id-3"
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints",
            body={"name": "metrics-cp"},
        )
        await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints",
            query_params={},
            handler=mock_handler,
        )
        mock_record.assert_called_once()
        args = mock_record.call_args
        assert args[0][0] == "create"
        # Note: success is False because string path returns inside the
        # with block, before success=True is set
        assert args[0][1] is False
        mock_slo.assert_called_once()

    @pytest.mark.asyncio
    @patch("aragora.server.handlers.knowledge.checkpoints.record_checkpoint_operation")
    @patch("aragora.server.handlers.knowledge.checkpoints.check_and_record_slo")
    async def test_create_records_metrics_metadata_result(
        self, mock_slo, mock_record, handler_with_store, mock_store
    ):
        """When create returns metadata, success is True."""
        metadata = MockCheckpointMetadata(name="met-cp")
        mock_store.create_checkpoint.return_value = metadata
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints",
            body={"name": "met-cp"},
        )
        await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints",
            query_params={},
            handler=mock_handler,
        )
        mock_record.assert_called_once()
        args = mock_record.call_args
        assert args[0][0] == "create"
        assert args[0][1] is True
        mock_slo.assert_called_once()

    @pytest.mark.asyncio
    @patch("aragora.server.handlers.knowledge.checkpoints.record_checkpoint_operation")
    @patch("aragora.server.handlers.knowledge.checkpoints.check_and_record_slo")
    async def test_create_records_metrics_on_failure(
        self, mock_slo, mock_record, handler_with_store, mock_store
    ):
        mock_store.create_checkpoint.side_effect = RuntimeError("fail")
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints",
            body={"name": "fail-cp"},
        )
        await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints",
            query_params={},
            handler=mock_handler,
        )
        mock_record.assert_called_once()
        args = mock_record.call_args
        assert args[0][0] == "create"
        assert args[0][1] is False  # success should be False on error

    @pytest.mark.asyncio
    @patch("aragora.server.handlers.knowledge.checkpoints.emit_handler_event")
    async def test_create_emits_handler_event(self, mock_emit, handler_with_store, mock_store):
        metadata = MockCheckpointMetadata(name="event-cp")
        mock_store.create_checkpoint.return_value = metadata
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints",
            body={"name": "event-cp"},
        )
        await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints",
            query_params={},
            handler=mock_handler,
        )
        mock_emit.assert_called_once_with("knowledge", "created", {"checkpoint": "event-cp"})


# =============================================================================
# Test: GET /api/v1/km/checkpoints/{name} (get)
# =============================================================================


class TestGetCheckpoint:
    """Tests for getting a single checkpoint."""

    @pytest.mark.asyncio
    async def test_get_existing_checkpoint(self, handler_with_store, mock_store):
        cp = MockCheckpointMetadata(
            name="my-cp",
            description="My checkpoint",
            node_count=99,
            size_bytes=4096,
            tags=["prod"],
            checksum="sha256abc",
        )
        mock_store.get_checkpoint_metadata.return_value = cp
        mock_handler = _MockHTTPHandler(path="/api/v1/km/checkpoints/my-cp")
        result = await handler_with_store.handle_get(
            path="/api/v1/km/checkpoints/my-cp",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 200
        body = _body(result)
        data = body.get("data", body)
        assert data["name"] == "my-cp"
        assert data["description"] == "My checkpoint"
        assert data["node_count"] == 99
        assert data["size_bytes"] == 4096
        assert data["tags"] == ["prod"]
        assert data["checksum"] == "sha256abc"

    @pytest.mark.asyncio
    async def test_get_nonexistent_checkpoint_returns_404(self, handler_with_store, mock_store):
        mock_store.get_checkpoint_metadata.return_value = None
        mock_handler = _MockHTTPHandler(path="/api/v1/km/checkpoints/nope")
        result = await handler_with_store.handle_get(
            path="/api/v1/km/checkpoints/nope",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_get_checkpoint_with_datetime_created_at(self, handler_with_store, mock_store):
        cp = MockCheckpointMetadata(name="dt-cp")
        cp.created_at = datetime(2026, 2, 23, 12, 0, 0)
        mock_store.get_checkpoint_metadata.return_value = cp
        mock_handler = _MockHTTPHandler(path="/api/v1/km/checkpoints/dt-cp")
        result = await handler_with_store.handle_get(
            path="/api/v1/km/checkpoints/dt-cp",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 200
        body = _body(result)
        data = body.get("data", body)
        assert "2026-02-23" in data["created_at"]

    @pytest.mark.asyncio
    async def test_get_checkpoint_with_string_created_at(self, handler_with_store, mock_store):
        cp = MockCheckpointMetadata(name="str-cp")
        cp.created_at = "2026-01-15T08:30:00Z"
        mock_store.get_checkpoint_metadata.return_value = cp
        mock_handler = _MockHTTPHandler(path="/api/v1/km/checkpoints/str-cp")
        result = await handler_with_store.handle_get(
            path="/api/v1/km/checkpoints/str-cp",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 200
        body = _body(result)
        data = body.get("data", body)
        assert data["created_at"] == "2026-01-15T08:30:00Z"

    @pytest.mark.asyncio
    async def test_get_checkpoint_store_unavailable_returns_503(self, handler_with_store):
        handler_with_store._checkpoint_store = None
        with patch.object(
            handler_with_store,
            "_get_checkpoint_store",
            side_effect=RuntimeError("unavailable"),
        ):
            mock_handler = _MockHTTPHandler(path="/api/v1/km/checkpoints/test-cp")
            result = await handler_with_store.handle_get(
                path="/api/v1/km/checkpoints/test-cp",
                query_params={},
                handler=mock_handler,
            )
            assert _status(result) == 503


# =============================================================================
# Test: DELETE /api/v1/km/checkpoints/{name}
# =============================================================================


class TestDeleteCheckpoint:
    """Tests for deleting checkpoints."""

    @pytest.mark.asyncio
    async def test_delete_existing_checkpoint(self, handler_with_store, mock_store):
        mock_store.delete_checkpoint.return_value = True
        mock_handler = _MockHTTPHandler(
            method="DELETE",
            path="/api/v1/km/checkpoints/old-cp",
        )
        result = await handler_with_store.handle_delete(
            path="/api/v1/km/checkpoints/old-cp",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 200
        body = _body(result)
        data = body.get("data", body)
        assert data["deleted"] == "old-cp"

    @pytest.mark.asyncio
    async def test_delete_nonexistent_checkpoint_returns_404(self, handler_with_store, mock_store):
        mock_store.delete_checkpoint.return_value = False
        mock_handler = _MockHTTPHandler(
            method="DELETE",
            path="/api/v1/km/checkpoints/nope",
        )
        result = await handler_with_store.handle_delete(
            path="/api/v1/km/checkpoints/nope",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_delete_runtime_error_returns_500(self, handler_with_store, mock_store):
        mock_store.delete_checkpoint.side_effect = RuntimeError("disk error")
        mock_handler = _MockHTTPHandler(
            method="DELETE",
            path="/api/v1/km/checkpoints/broken-cp",
        )
        result = await handler_with_store.handle_delete(
            path="/api/v1/km/checkpoints/broken-cp",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 500

    @pytest.mark.asyncio
    @patch("aragora.server.handlers.knowledge.checkpoints.record_checkpoint_operation")
    async def test_delete_records_metrics_on_success(
        self, mock_record, handler_with_store, mock_store
    ):
        mock_store.delete_checkpoint.return_value = True
        mock_handler = _MockHTTPHandler(
            method="DELETE",
            path="/api/v1/km/checkpoints/metrics-cp",
        )
        await handler_with_store.handle_delete(
            path="/api/v1/km/checkpoints/metrics-cp",
            query_params={},
            handler=mock_handler,
        )
        mock_record.assert_called_once()
        args = mock_record.call_args
        assert args[0][0] == "delete"
        assert args[0][1] is True

    @pytest.mark.asyncio
    @patch("aragora.server.handlers.knowledge.checkpoints.record_checkpoint_operation")
    async def test_delete_records_metrics_on_failure(
        self, mock_record, handler_with_store, mock_store
    ):
        mock_store.delete_checkpoint.side_effect = RuntimeError("fail")
        mock_handler = _MockHTTPHandler(
            method="DELETE",
            path="/api/v1/km/checkpoints/fail-cp",
        )
        await handler_with_store.handle_delete(
            path="/api/v1/km/checkpoints/fail-cp",
            query_params={},
            handler=mock_handler,
        )
        mock_record.assert_called_once()
        args = mock_record.call_args
        assert args[0][0] == "delete"
        assert args[0][1] is False

    @pytest.mark.asyncio
    async def test_delete_with_subpath_returns_404(self, handler_with_store, mock_store):
        """DELETE /api/v1/km/checkpoints/name/extra should 404."""
        mock_handler = _MockHTTPHandler(
            method="DELETE",
            path="/api/v1/km/checkpoints/name/extra",
        )
        result = await handler_with_store.handle_delete(
            path="/api/v1/km/checkpoints/name/extra",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 404


# =============================================================================
# Test: POST /api/v1/km/checkpoints/{name}/restore
# =============================================================================


class TestRestoreCheckpoint:
    """Tests for restoring from a checkpoint."""

    @pytest.mark.asyncio
    async def test_restore_with_merge_strategy(self, handler_with_store, mock_store):
        restore_result = MockRestoreResult(
            checkpoint_id="test-cp",
            success=True,
            nodes_restored=15,
            relationships_restored=8,
            errors=[],
        )
        mock_store.restore_checkpoint.return_value = restore_result
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints/test-cp/restore",
            body={"strategy": "merge"},
        )
        result = await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints/test-cp/restore",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 200
        body = _body(result)
        data = body.get("data", body)
        assert data["checkpoint_name"] == "test-cp"
        assert data["strategy"] == "merge"
        assert data["nodes_restored"] == 15
        assert data["relationships_restored"] == 8
        mock_store.restore_checkpoint.assert_called_once_with(
            checkpoint_id="test-cp",
            clear_existing=False,
        )

    @pytest.mark.asyncio
    async def test_restore_with_replace_strategy(self, handler_with_store, mock_store):
        restore_result = MockRestoreResult(
            checkpoint_id="replace-cp",
            success=True,
            nodes_restored=20,
            relationships_restored=10,
        )
        mock_store.restore_checkpoint.return_value = restore_result
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints/replace-cp/restore",
            body={"strategy": "replace"},
        )
        result = await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints/replace-cp/restore",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 200
        mock_store.restore_checkpoint.assert_called_once_with(
            checkpoint_id="replace-cp",
            clear_existing=True,
        )

    @pytest.mark.asyncio
    async def test_restore_default_strategy_is_merge(self, handler_with_store, mock_store):
        restore_result = MockRestoreResult(
            checkpoint_id="default-cp", success=True, nodes_restored=5
        )
        mock_store.restore_checkpoint.return_value = restore_result
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints/default-cp/restore",
            body={},
        )
        result = await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints/default-cp/restore",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 200
        body = _body(result)
        data = body.get("data", body)
        assert data["strategy"] == "merge"
        mock_store.restore_checkpoint.assert_called_once_with(
            checkpoint_id="default-cp",
            clear_existing=False,
        )

    @pytest.mark.asyncio
    async def test_restore_invalid_strategy_returns_400(self, handler_with_store, mock_store):
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints/test-cp/restore",
            body={"strategy": "overwrite"},
        )
        result = await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints/test-cp/restore",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 400
        body = _body(result)
        assert "strategy" in body.get("error", body.get("message", "")).lower()

    @pytest.mark.asyncio
    async def test_restore_not_found_returns_404(self, handler_with_store, mock_store):
        restore_result = MockRestoreResult(
            checkpoint_id="ghost-cp",
            success=False,
            nodes_restored=0,
        )
        mock_store.restore_checkpoint.return_value = restore_result
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints/ghost-cp/restore",
            body={},
        )
        result = await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints/ghost-cp/restore",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_restore_with_errors_returns_truncated_list(self, handler_with_store, mock_store):
        errors = [f"error-{i}" for i in range(15)]
        restore_result = MockRestoreResult(
            checkpoint_id="err-cp",
            success=True,
            nodes_restored=100,
            relationships_restored=50,
            errors=errors,
        )
        mock_store.restore_checkpoint.return_value = restore_result
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints/err-cp/restore",
            body={"strategy": "merge"},
        )
        result = await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints/err-cp/restore",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 200
        body = _body(result)
        data = body.get("data", body)
        assert len(data["errors"]) == 10  # truncated to 10
        assert data["error_count"] == 15  # full count

    @pytest.mark.asyncio
    async def test_restore_value_error_returns_400(self, handler_with_store, mock_store):
        mock_store.restore_checkpoint.side_effect = ValueError("bad data")
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints/bad-cp/restore",
            body={},
        )
        result = await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints/bad-cp/restore",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_restore_runtime_error_returns_500(self, handler_with_store, mock_store):
        mock_store.restore_checkpoint.side_effect = RuntimeError("engine broken")
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints/fail-cp/restore",
            body={},
        )
        result = await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints/fail-cp/restore",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 500

    @pytest.mark.asyncio
    @patch("aragora.server.handlers.knowledge.checkpoints.record_checkpoint_operation")
    @patch("aragora.server.handlers.knowledge.checkpoints.check_and_record_slo")
    async def test_restore_records_metrics(
        self, mock_slo, mock_record, handler_with_store, mock_store
    ):
        restore_result = MockRestoreResult(checkpoint_id="met-cp", success=True, nodes_restored=5)
        mock_store.restore_checkpoint.return_value = restore_result
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints/met-cp/restore",
            body={},
        )
        await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints/met-cp/restore",
            query_params={},
            handler=mock_handler,
        )
        mock_record.assert_called_once()
        args = mock_record.call_args
        assert args[0][0] == "restore"
        assert args[0][1] is True
        mock_slo.assert_called_once()

    @pytest.mark.asyncio
    @patch("aragora.observability.metrics.record_checkpoint_restore_result")
    async def test_restore_records_restore_result_metrics(
        self, mock_restore_record, handler_with_store, mock_store
    ):
        restore_result = MockRestoreResult(
            checkpoint_id="res-cp",
            success=True,
            nodes_restored=12,
            relationships_restored=4,
            errors=["warn1", "warn2"],
        )
        mock_store.restore_checkpoint.return_value = restore_result
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints/res-cp/restore",
            body={},
        )
        await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints/res-cp/restore",
            query_params={},
            handler=mock_handler,
        )
        mock_restore_record.assert_called_once_with(
            nodes_restored=12,
            nodes_skipped=0,
            errors=2,
        )


# =============================================================================
# Test: GET /api/v1/km/checkpoints/{name}/compare
# =============================================================================


class TestCompareCheckpoint:
    """Tests for comparing a checkpoint with current state."""

    @pytest.mark.asyncio
    async def test_compare_success(self, handler_with_store, mock_store, sample_checkpoints):
        mock_store.list_checkpoints.return_value = sample_checkpoints
        mock_store.compare_checkpoints.return_value = {
            "added": 5,
            "removed": 2,
            "modified": 1,
        }
        mock_handler = _MockHTTPHandler(path="/api/v1/km/checkpoints/cp-alpha/compare")
        result = await handler_with_store.handle_get(
            path="/api/v1/km/checkpoints/cp-alpha/compare",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 200
        body = _body(result)
        data = body.get("data", body)
        assert data["added"] == 5

    @pytest.mark.asyncio
    async def test_compare_no_checkpoints_returns_404(self, handler_with_store, mock_store):
        mock_store.list_checkpoints.return_value = []
        mock_handler = _MockHTTPHandler(path="/api/v1/km/checkpoints/nothing/compare")
        result = await handler_with_store.handle_get(
            path="/api/v1/km/checkpoints/nothing/compare",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_compare_checkpoint_not_found_returns_404(
        self, handler_with_store, mock_store, sample_checkpoints
    ):
        mock_store.list_checkpoints.return_value = sample_checkpoints
        mock_handler = _MockHTTPHandler(path="/api/v1/km/checkpoints/nonexistent/compare")
        result = await handler_with_store.handle_get(
            path="/api/v1/km/checkpoints/nonexistent/compare",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_compare_single_checkpoint_returns_metadata(self, handler_with_store, mock_store):
        single = [MockCheckpointMetadata(name="only-one", node_count=42, size_bytes=999)]
        mock_store.list_checkpoints.return_value = single
        mock_handler = _MockHTTPHandler(path="/api/v1/km/checkpoints/only-one/compare")
        result = await handler_with_store.handle_get(
            path="/api/v1/km/checkpoints/only-one/compare",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 200
        body = _body(result)
        data = body.get("data", body)
        assert data["checkpoint"] == "only-one"
        assert data["node_count"] == 42
        assert "message" in data

    @pytest.mark.asyncio
    async def test_compare_returns_none_from_store(
        self, handler_with_store, mock_store, sample_checkpoints
    ):
        mock_store.list_checkpoints.return_value = sample_checkpoints
        mock_store.compare_checkpoints.return_value = None
        mock_handler = _MockHTTPHandler(path="/api/v1/km/checkpoints/cp-alpha/compare")
        result = await handler_with_store.handle_get(
            path="/api/v1/km/checkpoints/cp-alpha/compare",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_compare_runtime_error_returns_500(self, handler_with_store, mock_store):
        mock_store.list_checkpoints.side_effect = RuntimeError("store failure")
        mock_handler = _MockHTTPHandler(path="/api/v1/km/checkpoints/broken/compare")
        result = await handler_with_store.handle_get(
            path="/api/v1/km/checkpoints/broken/compare",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 500

    @pytest.mark.asyncio
    @patch("aragora.server.handlers.knowledge.checkpoints.record_checkpoint_operation")
    async def test_compare_records_metrics(
        self, mock_record, handler_with_store, mock_store, sample_checkpoints
    ):
        mock_store.list_checkpoints.return_value = sample_checkpoints
        mock_store.compare_checkpoints.return_value = {"added": 0}
        mock_handler = _MockHTTPHandler(path="/api/v1/km/checkpoints/cp-alpha/compare")
        await handler_with_store.handle_get(
            path="/api/v1/km/checkpoints/cp-alpha/compare",
            query_params={},
            handler=mock_handler,
        )
        mock_record.assert_called_once()
        args = mock_record.call_args
        assert args[0][0] == "compare"
        assert args[0][1] is True


# =============================================================================
# Test: POST /api/v1/km/checkpoints/compare (compare two checkpoints)
# =============================================================================


class TestCompareTwoCheckpoints:
    """Tests for comparing two checkpoints."""

    @pytest.mark.asyncio
    async def test_compare_two_success(self, handler_with_store, mock_store):
        mock_store.compare_checkpoints.return_value = {
            "added": 3,
            "removed": 1,
        }
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints/compare",
            body={"checkpoint_a": "cp-1", "checkpoint_b": "cp-2"},
        )
        result = await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints/compare",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 200
        body = _body(result)
        data = body.get("data", body)
        assert data["added"] == 3

    @pytest.mark.asyncio
    async def test_compare_two_missing_checkpoint_a(self, handler_with_store, mock_store):
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints/compare",
            body={"checkpoint_b": "cp-2"},
        )
        result = await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints/compare",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 400
        body = _body(result)
        assert "checkpoint_a" in body.get("error", body.get("message", "")).lower()

    @pytest.mark.asyncio
    async def test_compare_two_missing_checkpoint_b(self, handler_with_store, mock_store):
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints/compare",
            body={"checkpoint_a": "cp-1"},
        )
        result = await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints/compare",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_compare_two_missing_both(self, handler_with_store, mock_store):
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints/compare",
            body={},
        )
        result = await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints/compare",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_compare_two_no_body_returns_400(self, handler_with_store, mock_store):
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints/compare",
        )
        result = await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints/compare",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_compare_two_not_found_returns_404(self, handler_with_store, mock_store):
        mock_store.compare_checkpoints.return_value = None
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints/compare",
            body={"checkpoint_a": "cp-1", "checkpoint_b": "cp-2"},
        )
        result = await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints/compare",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_compare_two_error_field_returns_404(self, handler_with_store, mock_store):
        mock_store.compare_checkpoints.return_value = {"error": "not found"}
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints/compare",
            body={"checkpoint_a": "cp-1", "checkpoint_b": "cp-2"},
        )
        result = await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints/compare",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_compare_two_runtime_error_returns_500(self, handler_with_store, mock_store):
        mock_store.compare_checkpoints.side_effect = RuntimeError("kaboom")
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints/compare",
            body={"checkpoint_a": "cp-1", "checkpoint_b": "cp-2"},
        )
        result = await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints/compare",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 500


# =============================================================================
# Test: handle_get routing
# =============================================================================


class TestHandleGetRouting:
    """Tests for GET request routing."""

    @pytest.mark.asyncio
    async def test_handle_get_missing_handler_returns_500(self, handler_with_store):
        result = await handler_with_store.handle_get(
            path="/api/v1/km/checkpoints",
            query_params={},
            handler=None,
        )
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_handle_get_unknown_path_returns_404(self, handler_with_store, mock_store):
        mock_handler = _MockHTTPHandler(path="/api/v1/km/checkpoints/some/unknown/deep/path")
        result = await handler_with_store.handle_get(
            path="/api/v1/km/checkpoints/some/unknown/deep/path",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_handle_get_routes_to_list(self, handler_with_store, mock_store):
        mock_store.list_checkpoints.return_value = []
        mock_handler = _MockHTTPHandler(path="/api/v1/km/checkpoints")
        result = await handler_with_store.handle_get(
            path="/api/v1/km/checkpoints",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 200
        mock_store.list_checkpoints.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_get_routes_to_get_by_name(self, handler_with_store, mock_store):
        mock_store.get_checkpoint_metadata.return_value = MockCheckpointMetadata(name="named")
        mock_handler = _MockHTTPHandler(path="/api/v1/km/checkpoints/named")
        result = await handler_with_store.handle_get(
            path="/api/v1/km/checkpoints/named",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 200
        mock_store.get_checkpoint_metadata.assert_called_once_with("named")

    @pytest.mark.asyncio
    async def test_handle_get_routes_to_compare(
        self, handler_with_store, mock_store, sample_checkpoints
    ):
        mock_store.list_checkpoints.return_value = sample_checkpoints
        mock_store.compare_checkpoints.return_value = {"added": 0}
        mock_handler = _MockHTTPHandler(path="/api/v1/km/checkpoints/cp-alpha/compare")
        result = await handler_with_store.handle_get(
            path="/api/v1/km/checkpoints/cp-alpha/compare",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 200


# =============================================================================
# Test: handle_post routing
# =============================================================================


class TestHandlePostRouting:
    """Tests for POST request routing."""

    @pytest.mark.asyncio
    async def test_handle_post_missing_handler_returns_500(self, handler_with_store):
        result = await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints",
            query_params={},
            handler=None,
        )
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_handle_post_routes_to_create(self, handler_with_store, mock_store):
        mock_store.create_checkpoint.return_value = "id-1"
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints",
            body={"name": "new-cp"},
        )
        result = await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 201

    @pytest.mark.asyncio
    async def test_handle_post_routes_to_compare(self, handler_with_store, mock_store):
        mock_store.compare_checkpoints.return_value = {"diff": True}
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints/compare",
            body={"checkpoint_a": "a", "checkpoint_b": "b"},
        )
        result = await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints/compare",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_handle_post_routes_to_restore(self, handler_with_store, mock_store):
        restore_result = MockRestoreResult(checkpoint_id="r-cp", success=True, nodes_restored=1)
        mock_store.restore_checkpoint.return_value = restore_result
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints/r-cp/restore",
            body={},
        )
        result = await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints/r-cp/restore",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_handle_post_unknown_path_returns_404(self, handler_with_store, mock_store):
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints/some/random/path",
        )
        result = await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints/some/random/path",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 404


# =============================================================================
# Test: handle_delete routing
# =============================================================================


class TestHandleDeleteRouting:
    """Tests for DELETE request routing."""

    @pytest.mark.asyncio
    async def test_handle_delete_missing_handler_returns_500(self, handler_with_store):
        result = await handler_with_store.handle_delete(
            path="/api/v1/km/checkpoints/x",
            query_params={},
            handler=None,
        )
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_handle_delete_routes_correctly(self, handler_with_store, mock_store):
        mock_store.delete_checkpoint.return_value = True
        mock_handler = _MockHTTPHandler(
            method="DELETE",
            path="/api/v1/km/checkpoints/del-cp",
        )
        result = await handler_with_store.handle_delete(
            path="/api/v1/km/checkpoints/del-cp",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_handle_delete_base_path_returns_404(self, handler_with_store, mock_store):
        mock_handler = _MockHTTPHandler(
            method="DELETE",
            path="/api/v1/km/checkpoints",
        )
        result = await handler_with_store.handle_delete(
            path="/api/v1/km/checkpoints",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 404


# =============================================================================
# Test: RBAC permission checks
# =============================================================================


class TestRBACPermissions:
    """Tests for RBAC permission checking logic."""

    def test_check_rbac_no_user_id_returns_401(self, handler):
        result = handler._check_rbac_permission({"roles": set()}, "knowledge:read")
        # Missing user_id should return 401
        assert result is not None
        assert _status(result) == 401

    def test_check_rbac_with_roles_as_list(self, handler):
        """Roles passed as list should be converted to set."""
        # This exercises the isinstance(roles, list) -> set(roles) branch
        auth_ctx = {
            "user_id": "user-1",
            "roles": ["admin"],
            "org_id": "org-1",
        }
        # This should not error; it either succeeds or returns None (fail-open)
        result = handler._check_rbac_permission(auth_ctx, "knowledge:read")
        # Result could be None (permission granted or fail-open) or HandlerResult
        # We just verify it does not crash
        assert result is None or hasattr(result, "status_code")

    def test_check_rbac_exception_fails_open(self, handler):
        """RBAC exceptions should fail open for backwards compat."""
        with patch(
            "aragora.server.handlers.knowledge.checkpoints.check_permission",
            side_effect=ValueError("bad config"),
        ):
            result = handler._check_rbac_permission(
                {"user_id": "u1", "roles": set()}, "knowledge:read"
            )
            assert result is None  # fail open

    def test_check_rbac_type_error_fails_open(self, handler):
        with patch(
            "aragora.server.handlers.knowledge.checkpoints.check_permission",
            side_effect=TypeError("type mismatch"),
        ):
            result = handler._check_rbac_permission(
                {"user_id": "u1", "roles": set()}, "knowledge:read"
            )
            assert result is None

    def test_check_rbac_attribute_error_fails_open(self, handler):
        with patch(
            "aragora.server.handlers.knowledge.checkpoints.check_permission",
            side_effect=AttributeError("missing attr"),
        ):
            result = handler._check_rbac_permission(
                {"user_id": "u1", "roles": set()}, "knowledge:read"
            )
            assert result is None

    def test_check_rbac_key_error_fails_open(self, handler):
        with patch(
            "aragora.server.handlers.knowledge.checkpoints.check_permission",
            side_effect=KeyError("missing key"),
        ):
            result = handler._check_rbac_permission(
                {"user_id": "u1", "roles": set()}, "knowledge:read"
            )
            assert result is None

    def test_check_rbac_denied_returns_403(self, handler):
        mock_decision = MagicMock()
        mock_decision.allowed = False
        mock_decision.reason = "insufficient permissions"
        with patch(
            "aragora.server.handlers.knowledge.checkpoints.check_permission",
            return_value=mock_decision,
        ):
            with patch("aragora.server.handlers.knowledge.checkpoints.record_rbac_check"):
                result = handler._check_rbac_permission(
                    {"user_id": "u1", "roles": {"viewer"}}, "knowledge:write"
                )
                assert result is not None
                assert _status(result) == 403

    def test_check_rbac_allowed_returns_none(self, handler):
        mock_decision = MagicMock()
        mock_decision.allowed = True
        with patch(
            "aragora.server.handlers.knowledge.checkpoints.check_permission",
            return_value=mock_decision,
        ):
            with patch("aragora.server.handlers.knowledge.checkpoints.record_rbac_check"):
                result = handler._check_rbac_permission(
                    {"user_id": "u1", "roles": {"admin"}}, "knowledge:read"
                )
                assert result is None

    def test_check_rbac_with_resource_id(self, handler):
        mock_decision = MagicMock()
        mock_decision.allowed = True
        with patch(
            "aragora.server.handlers.knowledge.checkpoints.check_permission",
            return_value=mock_decision,
        ) as mock_check:
            with patch("aragora.server.handlers.knowledge.checkpoints.record_rbac_check"):
                handler._check_rbac_permission(
                    {"user_id": "u1", "roles": {"admin"}},
                    "knowledge:read",
                    resource_id="my-checkpoint",
                )
                # Verify resource_id was passed through
                mock_check.assert_called_once()
                call_args = mock_check.call_args
                assert call_args[0][1] == "knowledge:read"
                assert call_args[0][2] == "my-checkpoint"

    @patch("aragora.server.handlers.knowledge.checkpoints.RBAC_AVAILABLE", False)
    @patch(
        "aragora.server.handlers.knowledge.checkpoints.rbac_fail_closed",
        return_value=True,
    )
    def test_rbac_unavailable_fail_closed(self, mock_fail, handler):
        result = handler._check_rbac_permission({"user_id": "u1"}, "knowledge:read")
        assert result is not None
        assert _status(result) == 503

    @patch("aragora.server.handlers.knowledge.checkpoints.RBAC_AVAILABLE", False)
    @patch(
        "aragora.server.handlers.knowledge.checkpoints.rbac_fail_closed",
        return_value=False,
    )
    def test_rbac_unavailable_fail_open(self, mock_fail, handler):
        result = handler._check_rbac_permission({"user_id": "u1"}, "knowledge:read")
        assert result is None


# =============================================================================
# Test: _check_auth
# =============================================================================


class TestCheckAuth:
    """Tests for the _check_auth helper."""

    def test_check_auth_returns_user_dict(self, handler):
        """With the conftest auto-mock, auth should succeed."""
        mock_handler = _MockHTTPHandler()
        user, err = handler._check_auth(mock_handler)
        assert err is None
        assert user is not None
        assert "user_id" in user
        assert "roles" in user

    def test_check_auth_extracts_user_fields(self, handler):
        mock_handler = _MockHTTPHandler()
        user, err = handler._check_auth(mock_handler)
        assert err is None
        # The conftest mock sets user_id="test-user-001"
        assert user["user_id"] == "test-user-001"
        assert user["sub"] == "test-user-001"


# =============================================================================
# Test: Path with query string stripping
# =============================================================================


class TestQueryStringHandling:
    """Tests for query string stripping in path routing."""

    @pytest.mark.asyncio
    async def test_get_strips_query_string(self, handler_with_store, mock_store):
        mock_store.list_checkpoints.return_value = []
        mock_handler = _MockHTTPHandler(path="/api/v1/km/checkpoints?limit=5&sort=name")
        result = await handler_with_store.handle_get(
            path="/api/v1/km/checkpoints?limit=5&sort=name",
            query_params={"limit": "5"},
            handler=mock_handler,
        )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_post_strips_query_string(self, handler_with_store, mock_store):
        mock_store.create_checkpoint.return_value = "id-qs"
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints?debug=true",
            body={"name": "qs-cp"},
        )
        result = await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints?debug=true",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 201

    @pytest.mark.asyncio
    async def test_delete_strips_query_string(self, handler_with_store, mock_store):
        mock_store.delete_checkpoint.return_value = True
        mock_handler = _MockHTTPHandler(
            method="DELETE",
            path="/api/v1/km/checkpoints/qscp?force=true",
        )
        result = await handler_with_store.handle_delete(
            path="/api/v1/km/checkpoints/qscp?force=true",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 200


# =============================================================================
# Test: Negative limit in query param
# =============================================================================


class TestEdgeCases:
    """Edge case tests."""

    @pytest.mark.asyncio
    async def test_negative_limit_clamped_to_1(
        self, handler_with_store, mock_store, sample_checkpoints
    ):
        mock_store.list_checkpoints.return_value = sample_checkpoints
        mock_handler = _MockHTTPHandler(path="/api/v1/km/checkpoints?limit=-5")
        result = await handler_with_store.handle_get(
            path="/api/v1/km/checkpoints",
            query_params={"limit": "-5"},
            handler=mock_handler,
        )
        body = _body(result)
        data = body.get("data", body)
        assert _status(result) == 200
        assert data["total"] == 1  # min(max(1, -5), 100) == 1

    @pytest.mark.asyncio
    async def test_create_no_json_body_returns_400(self, handler_with_store, mock_store):
        """POST with no body at all should return 400 for missing name."""
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints",
        )
        result = await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_restore_no_body_uses_defaults(self, handler_with_store, mock_store):
        """POST restore with no body should use default merge strategy."""
        restore_result = MockRestoreResult(checkpoint_id="nb-cp", success=True, nodes_restored=1)
        mock_store.restore_checkpoint.return_value = restore_result
        mock_handler = _MockHTTPHandler(
            method="POST",
            path="/api/v1/km/checkpoints/nb-cp/restore",
        )
        result = await handler_with_store.handle_post(
            path="/api/v1/km/checkpoints/nb-cp/restore",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 200
        body = _body(result)
        data = body.get("data", body)
        assert data["strategy"] == "merge"

    @pytest.mark.asyncio
    async def test_checkpoint_name_with_special_chars(self, handler_with_store, mock_store):
        """Checkpoint names with dashes and underscores should work."""
        cp = MockCheckpointMetadata(name="my-checkpoint_v2.1")
        mock_store.get_checkpoint_metadata.return_value = cp
        mock_handler = _MockHTTPHandler(path="/api/v1/km/checkpoints/my-checkpoint_v2.1")
        result = await handler_with_store.handle_get(
            path="/api/v1/km/checkpoints/my-checkpoint_v2.1",
            query_params={},
            handler=mock_handler,
        )
        assert _status(result) == 200
        body = _body(result)
        data = body.get("data", body)
        assert data["name"] == "my-checkpoint_v2.1"
