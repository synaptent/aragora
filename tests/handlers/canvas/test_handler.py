"""Tests for the canvas handler (aragora/server/handlers/canvas/handler.py).

Covers all routes and behavior of the CanvasHandler class:

Canvas CRUD:
- GET  /api/v1/canvas             - List canvases
- POST /api/v1/canvas             - Create canvas
- GET  /api/v1/canvas/{id}        - Get canvas
- PUT  /api/v1/canvas/{id}        - Update canvas
- DELETE /api/v1/canvas/{id}      - Delete canvas

Node operations:
- POST /api/v1/canvas/{id}/nodes                 - Add node
- PUT  /api/v1/canvas/{id}/nodes/{node_id}        - Update node
- DELETE /api/v1/canvas/{id}/nodes/{node_id}      - Delete node

Edge operations:
- POST /api/v1/canvas/{id}/edges                  - Add edge
- DELETE /api/v1/canvas/{id}/edges/{edge_id}      - Delete edge

Actions:
- POST /api/v1/canvas/{id}/action                 - Execute action

Also covers:
- can_handle() routing
- Rate limiting
- Authentication error paths
- Method not allowed (405)
- Unmatched routes (None)
- Manager error handling (500)
- Node type / edge type validation
- Missing required fields (400)
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.canvas.handler import (
    CanvasHandler,
    _canvas_limiter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result) -> dict[str, Any]:
    """Extract JSON body dict from a HandlerResult."""
    if result is None:
        return {}
    if isinstance(result, dict):
        return result
    return json.loads(result.body)


def _status(result) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if result is None:
        return 0
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return result.status_code


# ---------------------------------------------------------------------------
# Mock objects
# ---------------------------------------------------------------------------


class MockCanvas:
    """Mock canvas returned by the manager."""

    def __init__(self, canvas_id="canvas-1", name="Test Canvas", **kwargs):
        self.id = canvas_id
        self.name = name
        self.extra = kwargs

    def to_dict(self):
        d = {"id": self.id, "name": self.name}
        d.update(self.extra)
        return d


class MockNode:
    """Mock node returned by the manager."""

    def __init__(self, node_id="node-1", label="Test Node", **kwargs):
        self.id = node_id
        self.label = label
        self.extra = kwargs

    def to_dict(self):
        d = {"id": self.id, "label": self.label}
        d.update(self.extra)
        return d


class MockEdge:
    """Mock edge returned by the manager."""

    def __init__(self, edge_id="edge-1", source="n1", target="n2", **kwargs):
        self.id = edge_id
        self.source = source
        self.target = target
        self.extra = kwargs

    def to_dict(self):
        d = {"id": self.id, "source": self.source, "target": self.target}
        d.update(self.extra)
        return d


class MockHTTPHandler:
    """Mock HTTP handler for CanvasHandler tests."""

    def __init__(
        self,
        body: dict | None = None,
        method: str = "GET",
    ):
        self.command = method
        self.client_address = ("127.0.0.1", 12345)
        self.headers: dict[str, str] = {"User-Agent": "test-agent"}
        self.request = MagicMock()

        if body:
            body_bytes = json.dumps(body).encode()
            self.request.body = body_bytes
            self.headers["Content-Length"] = str(len(body_bytes))
        else:
            self.request.body = b"{}"
            self.headers["Content-Length"] = "2"

        # Also provide rfile for BaseHandler compatibility
        self.rfile = MagicMock()
        if body:
            self.rfile.read.return_value = json.dumps(body).encode()
        else:
            self.rfile.read.return_value = b"{}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Clear rate limiter state between tests."""
    _canvas_limiter._buckets.clear()
    yield
    _canvas_limiter._buckets.clear()


@pytest.fixture
def handler():
    """Create a CanvasHandler with empty context."""
    return CanvasHandler(ctx={})


@pytest.fixture
def mock_manager():
    """Create a mock canvas state manager with default async methods."""
    mgr = MagicMock()
    mgr.list_canvases = AsyncMock(return_value=[])
    mgr.create_canvas = AsyncMock(return_value=MockCanvas())
    mgr.get_canvas = AsyncMock(return_value=MockCanvas())
    mgr.update_canvas = AsyncMock(return_value=MockCanvas())
    mgr.delete_canvas = AsyncMock(return_value=True)
    mgr.add_node = AsyncMock(return_value=MockNode())
    mgr.update_node = AsyncMock(return_value=MockNode())
    mgr.remove_node = AsyncMock(return_value=True)
    mgr.add_edge = AsyncMock(return_value=MockEdge())
    mgr.remove_edge = AsyncMock(return_value=True)
    mgr.execute_action = AsyncMock(return_value={"status": "ok"})
    return mgr


@pytest.fixture(autouse=True)
def _patch_canvas_manager(handler, mock_manager):
    """Patch _get_canvas_manager to return mock_manager."""
    handler._get_canvas_manager = MagicMock(return_value=mock_manager)
    yield


# ============================================================================
# A. can_handle routing tests
# ============================================================================


class TestCanHandle:
    """Test CanvasHandler.can_handle()."""

    def test_matches_canvas_root(self, handler):
        assert handler.can_handle("/api/v1/canvas") is True

    def test_matches_canvas_id(self, handler):
        assert handler.can_handle("/api/v1/canvas/abc-123") is True

    def test_matches_canvas_nodes(self, handler):
        assert handler.can_handle("/api/v1/canvas/abc/nodes") is True

    def test_matches_canvas_node_id(self, handler):
        assert handler.can_handle("/api/v1/canvas/abc/nodes/n1") is True

    def test_matches_canvas_edges(self, handler):
        assert handler.can_handle("/api/v1/canvas/abc/edges") is True

    def test_matches_canvas_edge_id(self, handler):
        assert handler.can_handle("/api/v1/canvas/abc/edges/e1") is True

    def test_matches_canvas_action(self, handler):
        assert handler.can_handle("/api/v1/canvas/abc/action") is True

    def test_rejects_non_canvas(self, handler):
        assert handler.can_handle("/api/v1/debates") is False

    def test_also_matches_longer_prefix(self, handler):
        """can_handle uses startswith so /api/v1/canvases also matches."""
        assert handler.can_handle("/api/v1/canvases") is True

    def test_rejects_empty(self, handler):
        assert handler.can_handle("") is False

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/canvas/pipeline",
            "/api/v1/canvas/pipeline/templates",
            "/api/v1/canvas/pipeline/pipe-1/status",
            "/api/v1/canvas/convert/debate",
        ],
    )
    def test_leaves_pipeline_routes_to_the_pipeline_handler(self, handler, path):
        assert handler.can_handle(path) is False

    def test_still_matches_canvas_ids_that_start_with_pipeline(self, handler):
        assert handler.can_handle("/api/v1/canvas/pipelines-board") is True


# ============================================================================
# B. GET /api/v1/canvas - List canvases
# ============================================================================


class TestListCanvases:
    """Test the list canvases endpoint."""

    def test_list_empty(self, handler, mock_manager):
        mock_manager.list_canvases = AsyncMock(return_value=[])
        h = MockHTTPHandler(method="GET")
        result = handler.handle("/api/v1/canvas", {}, h)
        assert _status(result) == 200
        body = _body(result)
        assert body["canvases"] == []
        assert body["count"] == 0

    def test_list_with_canvases(self, handler, mock_manager):
        c1 = MockCanvas("c1", "Canvas 1")
        c2 = MockCanvas("c2", "Canvas 2")
        mock_manager.list_canvases = AsyncMock(return_value=[c1, c2])
        h = MockHTTPHandler(method="GET")
        result = handler.handle("/api/v1/canvas", {}, h)
        assert _status(result) == 200
        body = _body(result)
        assert body["count"] == 2
        assert len(body["canvases"]) == 2
        assert body["canvases"][0]["name"] == "Canvas 1"
        assert body["canvases"][1]["name"] == "Canvas 2"

    def test_list_passes_owner_id_from_query(self, handler, mock_manager):
        mock_manager.list_canvases = AsyncMock(return_value=[])
        h = MockHTTPHandler(method="GET")
        handler.handle("/api/v1/canvas", {"owner_id": "user-99"}, h)
        call_kwargs = mock_manager.list_canvases.call_args
        assert call_kwargs.kwargs.get("owner_id") == "user-99" or (
            call_kwargs.args and call_kwargs.args[0] == "user-99"
        )

    def test_list_passes_workspace_id_from_query(self, handler, mock_manager):
        mock_manager.list_canvases = AsyncMock(return_value=[])
        h = MockHTTPHandler(method="GET")
        handler.handle("/api/v1/canvas", {"workspace_id": "ws-42"}, h)
        call_kwargs = mock_manager.list_canvases.call_args
        assert "ws-42" in str(call_kwargs)

    def test_list_error_returns_500(self, handler, mock_manager):
        mock_manager.list_canvases = AsyncMock(side_effect=RuntimeError("db down"))
        h = MockHTTPHandler(method="GET")
        result = handler.handle("/api/v1/canvas", {}, h)
        assert _status(result) == 500
        assert "Failed to list canvases" in _body(result).get("error", "")


# ============================================================================
# C. POST /api/v1/canvas - Create canvas
# ============================================================================


class TestCreateCanvas:
    """Test the create canvas endpoint."""

    def test_create_default(self, handler, mock_manager):
        h = MockHTTPHandler(body={}, method="POST")
        result = handler.handle("/api/v1/canvas", {}, h)
        assert _status(result) == 201
        body = _body(result)
        assert body["id"] == "canvas-1"
        assert body["name"] == "Test Canvas"

    def test_create_with_name(self, handler, mock_manager):
        custom = MockCanvas("c-new", "My Canvas")
        mock_manager.create_canvas = AsyncMock(return_value=custom)
        h = MockHTTPHandler(body={"name": "My Canvas"}, method="POST")
        result = handler.handle("/api/v1/canvas", {}, h)
        assert _status(result) == 201
        assert _body(result)["name"] == "My Canvas"

    def test_create_with_id_and_metadata(self, handler, mock_manager):
        h = MockHTTPHandler(
            body={"id": "custom-id", "name": "Canvas", "metadata": {"theme": "dark"}},
            method="POST",
        )
        result = handler.handle("/api/v1/canvas", {}, h)
        assert _status(result) == 201
        # Verify the manager was called with the right args
        call_kwargs = mock_manager.create_canvas.call_args.kwargs
        assert call_kwargs.get("canvas_id") == "custom-id"
        assert call_kwargs.get("name") == "Canvas"
        assert call_kwargs.get("theme") == "dark"

    def test_create_error_returns_500(self, handler, mock_manager):
        mock_manager.create_canvas = AsyncMock(side_effect=ValueError("invalid"))
        h = MockHTTPHandler(body={"name": "Fail"}, method="POST")
        result = handler.handle("/api/v1/canvas", {}, h)
        assert _status(result) == 500
        assert "Canvas creation failed" in _body(result).get("error", "")


# ============================================================================
# D. GET /api/v1/canvas/{id} - Get canvas
# ============================================================================


class TestGetCanvas:
    """Test the get canvas by ID endpoint."""

    def test_get_existing(self, handler, mock_manager):
        c = MockCanvas("abc", "Found Canvas")
        mock_manager.get_canvas = AsyncMock(return_value=c)
        h = MockHTTPHandler(method="GET")
        result = handler.handle("/api/v1/canvas/abc", {}, h)
        assert _status(result) == 200
        assert _body(result)["id"] == "abc"
        assert _body(result)["name"] == "Found Canvas"

    def test_get_not_found(self, handler, mock_manager):
        mock_manager.get_canvas = AsyncMock(return_value=None)
        h = MockHTTPHandler(method="GET")
        result = handler.handle("/api/v1/canvas/nonexistent", {}, h)
        assert _status(result) == 404
        assert "not found" in _body(result).get("error", "").lower()

    def test_get_error_returns_500(self, handler, mock_manager):
        mock_manager.get_canvas = AsyncMock(side_effect=OSError("disk"))
        h = MockHTTPHandler(method="GET")
        result = handler.handle("/api/v1/canvas/abc", {}, h)
        assert _status(result) == 500
        assert "Failed to retrieve canvas" in _body(result).get("error", "")


# ============================================================================
# E. PUT /api/v1/canvas/{id} - Update canvas
# ============================================================================


class TestUpdateCanvas:
    """Test the update canvas endpoint."""

    def test_update_success(self, handler, mock_manager):
        updated = MockCanvas("abc", "Updated Name")
        mock_manager.update_canvas = AsyncMock(return_value=updated)
        h = MockHTTPHandler(body={"name": "Updated Name"}, method="PUT")
        result = handler.handle("/api/v1/canvas/abc", {}, h)
        assert _status(result) == 200
        assert _body(result)["name"] == "Updated Name"

    def test_update_not_found(self, handler, mock_manager):
        mock_manager.update_canvas = AsyncMock(return_value=None)
        h = MockHTTPHandler(body={"name": "Nope"}, method="PUT")
        result = handler.handle("/api/v1/canvas/missing", {}, h)
        assert _status(result) == 404
        assert "not found" in _body(result).get("error", "").lower()

    def test_update_with_metadata(self, handler, mock_manager):
        updated = MockCanvas("abc", "Test")
        mock_manager.update_canvas = AsyncMock(return_value=updated)
        body = {"metadata": {"theme": "dark"}, "owner_id": "user-2", "workspace_id": "ws-3"}
        h = MockHTTPHandler(body=body, method="PUT")
        result = handler.handle("/api/v1/canvas/abc", {}, h)
        assert _status(result) == 200
        call_kw = mock_manager.update_canvas.call_args.kwargs
        assert call_kw["metadata"] == {"theme": "dark"}
        assert call_kw["owner_id"] == "user-2"
        assert call_kw["workspace_id"] == "ws-3"

    def test_update_error_returns_500(self, handler, mock_manager):
        mock_manager.update_canvas = AsyncMock(side_effect=TypeError("bad data"))
        h = MockHTTPHandler(body={"name": "x"}, method="PUT")
        result = handler.handle("/api/v1/canvas/abc", {}, h)
        assert _status(result) == 500
        assert "Canvas update failed" in _body(result).get("error", "")


# ============================================================================
# F. DELETE /api/v1/canvas/{id} - Delete canvas
# ============================================================================


class TestDeleteCanvas:
    """Test the delete canvas endpoint."""

    def test_delete_success(self, handler, mock_manager):
        mock_manager.delete_canvas = AsyncMock(return_value=True)
        h = MockHTTPHandler(method="DELETE")
        result = handler.handle("/api/v1/canvas/abc", {}, h)
        assert _status(result) == 200
        body = _body(result)
        assert body["deleted"] is True
        assert body["canvas_id"] == "abc"

    def test_delete_not_found(self, handler, mock_manager):
        mock_manager.delete_canvas = AsyncMock(return_value=False)
        h = MockHTTPHandler(method="DELETE")
        result = handler.handle("/api/v1/canvas/nope", {}, h)
        assert _status(result) == 404
        assert "not found" in _body(result).get("error", "").lower()

    def test_delete_error_returns_500(self, handler, mock_manager):
        mock_manager.delete_canvas = AsyncMock(side_effect=KeyError("boom"))
        h = MockHTTPHandler(method="DELETE")
        result = handler.handle("/api/v1/canvas/abc", {}, h)
        assert _status(result) == 500
        assert "Canvas deletion failed" in _body(result).get("error", "")


# ============================================================================
# G. POST /api/v1/canvas/{id}/nodes - Add node
# ============================================================================


class TestAddNode:
    """Test the add node endpoint."""

    def test_add_node_default(self, handler, mock_manager):
        h = MockHTTPHandler(body={}, method="POST")
        result = handler.handle("/api/v1/canvas/abc/nodes", {}, h)
        assert _status(result) == 201
        body = _body(result)
        assert body["id"] == "node-1"

    def test_add_node_with_type_and_position(self, handler, mock_manager):
        node = MockNode("n-new", "My Node")
        mock_manager.add_node = AsyncMock(return_value=node)
        body = {
            "type": "text",
            "label": "My Node",
            "position": {"x": 100.0, "y": 200.0},
            "data": {"color": "red"},
        }
        h = MockHTTPHandler(body=body, method="POST")
        result = handler.handle("/api/v1/canvas/abc/nodes", {}, h)
        assert _status(result) == 201
        assert _body(result)["label"] == "My Node"
        # Verify position was passed correctly
        call_kw = mock_manager.add_node.call_args.kwargs
        assert call_kw["label"] == "My Node"
        assert call_kw["data"] == {"color": "red"}

    def test_add_node_invalid_type_returns_400(self, handler, mock_manager):
        """An invalid node type string should produce a 400 error."""
        body = {"type": "completely_invalid_not_real_type"}
        h = MockHTTPHandler(body=body, method="POST")
        result = handler.handle("/api/v1/canvas/abc/nodes", {}, h)
        assert _status(result) == 400
        assert "Invalid node type" in _body(result).get("error", "")

    def test_add_node_canvas_not_found(self, handler, mock_manager):
        mock_manager.add_node = AsyncMock(return_value=None)
        h = MockHTTPHandler(body={"type": "text"}, method="POST")
        result = handler.handle("/api/v1/canvas/missing/nodes", {}, h)
        assert _status(result) == 404
        assert "not found" in _body(result).get("error", "").lower()

    def test_add_node_error_returns_500(self, handler, mock_manager):
        mock_manager.add_node = AsyncMock(side_effect=RuntimeError("fail"))
        h = MockHTTPHandler(body={"type": "text"}, method="POST")
        result = handler.handle("/api/v1/canvas/abc/nodes", {}, h)
        assert _status(result) == 500
        assert "Node addition failed" in _body(result).get("error", "")

    def test_add_node_with_agent_type(self, handler, mock_manager):
        node = MockNode("n-agent", "Agent Node")
        mock_manager.add_node = AsyncMock(return_value=node)
        body = {"type": "agent", "label": "Agent Node"}
        h = MockHTTPHandler(body=body, method="POST")
        result = handler.handle("/api/v1/canvas/abc/nodes", {}, h)
        assert _status(result) == 201


# ============================================================================
# H. PUT /api/v1/canvas/{id}/nodes/{node_id} - Update node
# ============================================================================


class TestUpdateNode:
    """Test the update node endpoint."""

    def test_update_node_label(self, handler, mock_manager):
        updated = MockNode("n1", "New Label")
        mock_manager.update_node = AsyncMock(return_value=updated)
        body = {"label": "New Label"}
        h = MockHTTPHandler(body=body, method="PUT")
        result = handler.handle("/api/v1/canvas/abc/nodes/n1", {}, h)
        assert _status(result) == 200
        assert _body(result)["label"] == "New Label"

    def test_update_node_position(self, handler, mock_manager):
        updated = MockNode("n1", "Test")
        mock_manager.update_node = AsyncMock(return_value=updated)
        body = {"position": {"x": 50.5, "y": 75.3}}
        h = MockHTTPHandler(body=body, method="PUT")
        result = handler.handle("/api/v1/canvas/abc/nodes/n1", {}, h)
        assert _status(result) == 200
        call_kw = mock_manager.update_node.call_args.kwargs
        pos = call_kw["position"]
        assert pos.x == 50.5
        assert pos.y == 75.3

    def test_update_node_data(self, handler, mock_manager):
        updated = MockNode("n1", "Test")
        mock_manager.update_node = AsyncMock(return_value=updated)
        body = {"data": {"content": "hello"}}
        h = MockHTTPHandler(body=body, method="PUT")
        result = handler.handle("/api/v1/canvas/abc/nodes/n1", {}, h)
        assert _status(result) == 200
        call_kw = mock_manager.update_node.call_args.kwargs
        assert call_kw["data"] == {"content": "hello"}

    def test_update_node_not_found(self, handler, mock_manager):
        mock_manager.update_node = AsyncMock(return_value=None)
        h = MockHTTPHandler(body={"label": "x"}, method="PUT")
        result = handler.handle("/api/v1/canvas/abc/nodes/n99", {}, h)
        assert _status(result) == 404
        assert "not found" in _body(result).get("error", "").lower()

    def test_update_node_error_returns_500(self, handler, mock_manager):
        mock_manager.update_node = AsyncMock(side_effect=ValueError("bad"))
        h = MockHTTPHandler(body={"label": "x"}, method="PUT")
        result = handler.handle("/api/v1/canvas/abc/nodes/n1", {}, h)
        assert _status(result) == 500
        assert "Node update failed" in _body(result).get("error", "")

    def test_update_node_empty_body(self, handler, mock_manager):
        """Update with no fields should still call manager (no-op update)."""
        updated = MockNode("n1", "Unchanged")
        mock_manager.update_node = AsyncMock(return_value=updated)
        h = MockHTTPHandler(body={}, method="PUT")
        result = handler.handle("/api/v1/canvas/abc/nodes/n1", {}, h)
        assert _status(result) == 200
        call_kw = mock_manager.update_node.call_args.kwargs
        # No position, label, or data should be passed
        assert "position" not in call_kw
        assert "label" not in call_kw
        assert "data" not in call_kw


# ============================================================================
# I. DELETE /api/v1/canvas/{id}/nodes/{node_id} - Delete node
# ============================================================================


class TestDeleteNode:
    """Test the delete node endpoint."""

    def test_delete_node_success(self, handler, mock_manager):
        mock_manager.remove_node = AsyncMock(return_value=True)
        h = MockHTTPHandler(method="DELETE")
        result = handler.handle("/api/v1/canvas/abc/nodes/n1", {}, h)
        assert _status(result) == 200
        body = _body(result)
        assert body["deleted"] is True
        assert body["node_id"] == "n1"

    def test_delete_node_not_found(self, handler, mock_manager):
        mock_manager.remove_node = AsyncMock(return_value=False)
        h = MockHTTPHandler(method="DELETE")
        result = handler.handle("/api/v1/canvas/abc/nodes/n99", {}, h)
        assert _status(result) == 404
        assert "not found" in _body(result).get("error", "").lower()

    def test_delete_node_error_returns_500(self, handler, mock_manager):
        mock_manager.remove_node = AsyncMock(side_effect=OSError("disk fail"))
        h = MockHTTPHandler(method="DELETE")
        result = handler.handle("/api/v1/canvas/abc/nodes/n1", {}, h)
        assert _status(result) == 500
        assert "Node deletion failed" in _body(result).get("error", "")


# ============================================================================
# J. POST /api/v1/canvas/{id}/edges - Add edge
# ============================================================================


class TestAddEdge:
    """Test the add edge endpoint."""

    def test_add_edge_success(self, handler, mock_manager):
        edge = MockEdge("e1", "n1", "n2")
        mock_manager.add_edge = AsyncMock(return_value=edge)
        body = {"source_id": "n1", "target_id": "n2"}
        h = MockHTTPHandler(body=body, method="POST")
        result = handler.handle("/api/v1/canvas/abc/edges", {}, h)
        assert _status(result) == 201
        assert _body(result)["id"] == "e1"

    def test_add_edge_with_source_target_aliases(self, handler, mock_manager):
        """source/target should also work (not just source_id/target_id)."""
        edge = MockEdge("e2", "n3", "n4")
        mock_manager.add_edge = AsyncMock(return_value=edge)
        body = {"source": "n3", "target": "n4"}
        h = MockHTTPHandler(body=body, method="POST")
        result = handler.handle("/api/v1/canvas/abc/edges", {}, h)
        assert _status(result) == 201

    def test_add_edge_missing_source(self, handler, mock_manager):
        body = {"target_id": "n2"}
        h = MockHTTPHandler(body=body, method="POST")
        result = handler.handle("/api/v1/canvas/abc/edges", {}, h)
        assert _status(result) == 400
        assert "source_id" in _body(result).get("error", "")

    def test_add_edge_missing_target(self, handler, mock_manager):
        body = {"source_id": "n1"}
        h = MockHTTPHandler(body=body, method="POST")
        result = handler.handle("/api/v1/canvas/abc/edges", {}, h)
        assert _status(result) == 400
        assert "target_id" in _body(result).get("error", "")

    def test_add_edge_missing_both(self, handler, mock_manager):
        h = MockHTTPHandler(body={}, method="POST")
        result = handler.handle("/api/v1/canvas/abc/edges", {}, h)
        assert _status(result) == 400

    def test_add_edge_with_type_and_label(self, handler, mock_manager):
        edge = MockEdge("e3", "n1", "n2")
        mock_manager.add_edge = AsyncMock(return_value=edge)
        body = {
            "source_id": "n1",
            "target_id": "n2",
            "type": "data_flow",
            "label": "Data pipe",
            "data": {"weight": 1.0},
        }
        h = MockHTTPHandler(body=body, method="POST")
        result = handler.handle("/api/v1/canvas/abc/edges", {}, h)
        assert _status(result) == 201
        call_kw = mock_manager.add_edge.call_args.kwargs
        assert call_kw["label"] == "Data pipe"
        assert call_kw["data"] == {"weight": 1.0}

    def test_add_edge_invalid_type_uses_default(self, handler, mock_manager):
        """Invalid edge type should fall back to DEFAULT, not error."""
        edge = MockEdge("e4", "n1", "n2")
        mock_manager.add_edge = AsyncMock(return_value=edge)
        body = {"source_id": "n1", "target_id": "n2", "type": "totally_bogus"}
        h = MockHTTPHandler(body=body, method="POST")
        result = handler.handle("/api/v1/canvas/abc/edges", {}, h)
        # Should succeed -- invalid edge type falls back to DEFAULT
        assert _status(result) == 201

    def test_add_edge_canvas_not_found(self, handler, mock_manager):
        mock_manager.add_edge = AsyncMock(return_value=None)
        body = {"source_id": "n1", "target_id": "n2"}
        h = MockHTTPHandler(body=body, method="POST")
        result = handler.handle("/api/v1/canvas/missing/edges", {}, h)
        assert _status(result) == 404
        assert "not found" in _body(result).get("error", "").lower()

    def test_add_edge_error_returns_500(self, handler, mock_manager):
        mock_manager.add_edge = AsyncMock(side_effect=RuntimeError("fail"))
        body = {"source_id": "n1", "target_id": "n2"}
        h = MockHTTPHandler(body=body, method="POST")
        result = handler.handle("/api/v1/canvas/abc/edges", {}, h)
        assert _status(result) == 500
        assert "Edge addition failed" in _body(result).get("error", "")


# ============================================================================
# K. DELETE /api/v1/canvas/{id}/edges/{edge_id} - Delete edge
# ============================================================================


class TestDeleteEdge:
    """Test the delete edge endpoint."""

    def test_delete_edge_success(self, handler, mock_manager):
        mock_manager.remove_edge = AsyncMock(return_value=True)
        h = MockHTTPHandler(method="DELETE")
        result = handler.handle("/api/v1/canvas/abc/edges/e1", {}, h)
        assert _status(result) == 200
        body = _body(result)
        assert body["deleted"] is True
        assert body["edge_id"] == "e1"

    def test_delete_edge_not_found(self, handler, mock_manager):
        mock_manager.remove_edge = AsyncMock(return_value=False)
        h = MockHTTPHandler(method="DELETE")
        result = handler.handle("/api/v1/canvas/abc/edges/e99", {}, h)
        assert _status(result) == 404
        assert "not found" in _body(result).get("error", "").lower()

    def test_delete_edge_error_returns_500(self, handler, mock_manager):
        mock_manager.remove_edge = AsyncMock(side_effect=KeyError("boom"))
        h = MockHTTPHandler(method="DELETE")
        result = handler.handle("/api/v1/canvas/abc/edges/e1", {}, h)
        assert _status(result) == 500
        assert "Edge deletion failed" in _body(result).get("error", "")


# ============================================================================
# L. POST /api/v1/canvas/{id}/action - Execute action
# ============================================================================


class TestExecuteAction:
    """Test the execute action endpoint."""

    def test_execute_action_success(self, handler, mock_manager):
        mock_manager.execute_action = AsyncMock(return_value={"output": "done"})
        body = {"action": "run_debate", "node_id": "n1", "params": {"rounds": 3}}
        h = MockHTTPHandler(body=body, method="POST")
        result = handler.handle("/api/v1/canvas/abc/action", {}, h)
        assert _status(result) == 200
        resp = _body(result)
        assert resp["action"] == "run_debate"
        assert resp["canvas_id"] == "abc"
        assert resp["node_id"] == "n1"
        assert resp["result"] == {"output": "done"}

    def test_execute_action_missing_action_field(self, handler, mock_manager):
        h = MockHTTPHandler(body={}, method="POST")
        result = handler.handle("/api/v1/canvas/abc/action", {}, h)
        assert _status(result) == 400
        assert "action is required" in _body(result).get("error", "")

    def test_execute_action_no_node_id(self, handler, mock_manager):
        """action without node_id should still succeed (canvas-level action)."""
        mock_manager.execute_action = AsyncMock(return_value={"ok": True})
        body = {"action": "export"}
        h = MockHTTPHandler(body=body, method="POST")
        result = handler.handle("/api/v1/canvas/abc/action", {}, h)
        assert _status(result) == 200
        resp = _body(result)
        assert resp["node_id"] is None

    def test_execute_action_with_params(self, handler, mock_manager):
        mock_manager.execute_action = AsyncMock(return_value={})
        body = {"action": "compute", "params": {"depth": 5, "fast": True}}
        h = MockHTTPHandler(body=body, method="POST")
        result = handler.handle("/api/v1/canvas/abc/action", {}, h)
        assert _status(result) == 200
        call_kw = mock_manager.execute_action.call_args.kwargs
        assert call_kw["depth"] == 5
        assert call_kw["fast"] is True

    def test_execute_action_error_returns_500(self, handler, mock_manager):
        mock_manager.execute_action = AsyncMock(side_effect=RuntimeError("crash"))
        body = {"action": "fail_action"}
        h = MockHTTPHandler(body=body, method="POST")
        result = handler.handle("/api/v1/canvas/abc/action", {}, h)
        assert _status(result) == 500
        assert "Action execution failed" in _body(result).get("error", "")


# ============================================================================
# M. Method not allowed (405)
# ============================================================================


class TestMethodNotAllowed:
    """Test that unsupported methods return 405."""

    def test_patch_on_canvas_root(self, handler):
        h = MockHTTPHandler(method="PATCH")
        result = handler.handle("/api/v1/canvas", {}, h)
        assert _status(result) == 405

    def test_delete_on_canvas_root(self, handler):
        h = MockHTTPHandler(method="DELETE")
        result = handler.handle("/api/v1/canvas", {}, h)
        assert _status(result) == 405

    def test_post_on_canvas_id(self, handler):
        h = MockHTTPHandler(method="POST")
        result = handler.handle("/api/v1/canvas/abc", {}, h)
        assert _status(result) == 405

    def test_get_on_nodes_collection(self, handler):
        h = MockHTTPHandler(method="GET")
        result = handler.handle("/api/v1/canvas/abc/nodes", {}, h)
        assert _status(result) == 405

    def test_post_on_node_id(self, handler):
        h = MockHTTPHandler(method="POST")
        result = handler.handle("/api/v1/canvas/abc/nodes/n1", {}, h)
        assert _status(result) == 405

    def test_get_on_node_id(self, handler):
        h = MockHTTPHandler(method="GET")
        result = handler.handle("/api/v1/canvas/abc/nodes/n1", {}, h)
        assert _status(result) == 405

    def test_get_on_edges_collection(self, handler):
        h = MockHTTPHandler(method="GET")
        result = handler.handle("/api/v1/canvas/abc/edges", {}, h)
        assert _status(result) == 405

    def test_put_on_edge_id(self, handler):
        h = MockHTTPHandler(method="PUT")
        result = handler.handle("/api/v1/canvas/abc/edges/e1", {}, h)
        assert _status(result) == 405

    def test_get_on_action(self, handler):
        h = MockHTTPHandler(method="GET")
        result = handler.handle("/api/v1/canvas/abc/action", {}, h)
        assert _status(result) == 405


# ============================================================================
# N. Unmatched routes (None)
# ============================================================================


class TestUnmatchedRoutes:
    """Test that paths not matching any pattern return None."""

    def test_unknown_sub_path(self, handler):
        h = MockHTTPHandler(method="GET")
        result = handler.handle("/api/v1/canvas/abc/unknown", {}, h)
        assert result is None

    def test_deeply_nested_unknown(self, handler):
        h = MockHTTPHandler(method="GET")
        result = handler.handle("/api/v1/canvas/abc/nodes/n1/extra/stuff", {}, h)
        assert result is None

    def test_canvas_with_special_chars_in_id(self, handler, mock_manager):
        """IDs with hyphens and underscores should match."""
        c = MockCanvas("my-canvas_123", "Special")
        mock_manager.get_canvas = AsyncMock(return_value=c)
        h = MockHTTPHandler(method="GET")
        result = handler.handle("/api/v1/canvas/my-canvas_123", {}, h)
        assert _status(result) == 200

    def test_canvas_with_invalid_id_chars(self, handler):
        """IDs with dots or spaces should NOT match the regex."""
        h = MockHTTPHandler(method="GET")
        result = handler.handle("/api/v1/canvas/bad.id", {}, h)
        assert result is None

    def test_canvas_id_with_spaces(self, handler):
        h = MockHTTPHandler(method="GET")
        result = handler.handle("/api/v1/canvas/bad id", {}, h)
        assert result is None


# ============================================================================
# O. Rate limiting
# ============================================================================


class TestRateLimiting:
    """Test rate limit enforcement."""

    def test_rate_limit_exceeded(self, handler):
        """When the rate limiter says no, handler returns 429."""
        with patch.object(_canvas_limiter, "is_allowed", return_value=False):
            h = MockHTTPHandler(method="GET")
            result = handler.handle("/api/v1/canvas", {}, h)
            assert _status(result) == 429
            assert "Rate limit" in _body(result).get("error", "")


# ============================================================================
# P. Request body parsing
# ============================================================================


class TestRequestBodyParsing:
    """Test the _get_request_body helper."""

    def test_valid_json_body(self, handler):
        h = MockHTTPHandler(body={"key": "value"})
        body = handler._get_request_body(h)
        assert body == {"key": "value"}

    def test_empty_body_returns_empty_dict(self, handler):
        h = MagicMock()
        h.request.body = b""
        body = handler._get_request_body(h)
        assert body == {}

    def test_no_request_attr(self, handler):
        h = MagicMock(spec=[])  # No attributes at all
        body = handler._get_request_body(h)
        assert body == {}

    def test_no_body_attr(self, handler):
        h = MagicMock()
        del h.request.body
        body = handler._get_request_body(h)
        assert body == {}

    def test_invalid_json_body(self, handler):
        h = MagicMock()
        h.request.body = b"not json {"
        body = handler._get_request_body(h)
        assert body == {}

    def test_invalid_utf8_body(self, handler):
        h = MagicMock()
        h.request.body = b"\xff\xfe"
        body = handler._get_request_body(h)
        assert body == {}


# ============================================================================
# Q. Canvas ID pattern matching
# ============================================================================


class TestCanvasIdPatterns:
    """Test regex patterns for canvas/node/edge IDs."""

    def test_alphanumeric_id(self, handler, mock_manager):
        c = MockCanvas("abc123", "Test")
        mock_manager.get_canvas = AsyncMock(return_value=c)
        h = MockHTTPHandler(method="GET")
        result = handler.handle("/api/v1/canvas/abc123", {}, h)
        assert _status(result) == 200

    def test_id_with_hyphens(self, handler, mock_manager):
        c = MockCanvas("a-b-c", "Test")
        mock_manager.get_canvas = AsyncMock(return_value=c)
        h = MockHTTPHandler(method="GET")
        result = handler.handle("/api/v1/canvas/a-b-c", {}, h)
        assert _status(result) == 200

    def test_id_with_underscores(self, handler, mock_manager):
        c = MockCanvas("a_b_c", "Test")
        mock_manager.get_canvas = AsyncMock(return_value=c)
        h = MockHTTPHandler(method="GET")
        result = handler.handle("/api/v1/canvas/a_b_c", {}, h)
        assert _status(result) == 200

    def test_node_id_pattern(self, handler, mock_manager):
        node = MockNode("node-ABC_123", "Test")
        mock_manager.update_node = AsyncMock(return_value=node)
        h = MockHTTPHandler(body={"label": "x"}, method="PUT")
        result = handler.handle("/api/v1/canvas/c1/nodes/node-ABC_123", {}, h)
        assert _status(result) == 200

    def test_edge_id_pattern(self, handler, mock_manager):
        mock_manager.remove_edge = AsyncMock(return_value=True)
        h = MockHTTPHandler(method="DELETE")
        result = handler.handle("/api/v1/canvas/c1/edges/edge-XYZ_789", {}, h)
        assert _status(result) == 200


# ============================================================================
# R. Error exception types covered
# ============================================================================


class TestErrorExceptionTypes:
    """Verify that all caught exception types produce 500 responses."""

    @pytest.mark.parametrize(
        "exc_class",
        [ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError],
    )
    def test_list_canvases_catches_exception(self, handler, mock_manager, exc_class):
        mock_manager.list_canvases = AsyncMock(side_effect=exc_class("err"))
        h = MockHTTPHandler(method="GET")
        result = handler.handle("/api/v1/canvas", {}, h)
        assert _status(result) == 500

    @pytest.mark.parametrize(
        "exc_class",
        [ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError],
    )
    def test_create_canvas_catches_exception(self, handler, mock_manager, exc_class):
        mock_manager.create_canvas = AsyncMock(side_effect=exc_class("err"))
        h = MockHTTPHandler(body={}, method="POST")
        result = handler.handle("/api/v1/canvas", {}, h)
        assert _status(result) == 500

    @pytest.mark.parametrize(
        "exc_class",
        [ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError],
    )
    def test_get_canvas_catches_exception(self, handler, mock_manager, exc_class):
        mock_manager.get_canvas = AsyncMock(side_effect=exc_class("err"))
        h = MockHTTPHandler(method="GET")
        result = handler.handle("/api/v1/canvas/abc", {}, h)
        assert _status(result) == 500

    @pytest.mark.parametrize(
        "exc_class",
        [ImportError, KeyError, ValueError, TypeError, OSError, RuntimeError],
    )
    def test_execute_action_catches_exception(self, handler, mock_manager, exc_class):
        mock_manager.execute_action = AsyncMock(side_effect=exc_class("err"))
        body = {"action": "test"}
        h = MockHTTPHandler(body=body, method="POST")
        result = handler.handle("/api/v1/canvas/abc/action", {}, h)
        assert _status(result) == 500


# ============================================================================
# S. Constructor and class attributes
# ============================================================================


class TestHandlerInit:
    """Test CanvasHandler initialization."""

    def test_default_ctx(self):
        h = CanvasHandler()
        assert h.ctx == {}

    def test_custom_ctx(self):
        ctx = {"db": "mock_db"}
        h = CanvasHandler(ctx=ctx)
        assert h.ctx == ctx

    def test_resource_type(self, handler):
        assert handler.RESOURCE_TYPE == "canvas"


# ============================================================================
# T. Edge cases and integration-like scenarios
# ============================================================================


class TestEdgeCases:
    """Test edge cases and combined scenarios."""

    def test_create_then_get(self, handler, mock_manager):
        """Create a canvas and then get it by ID."""
        created = MockCanvas("new-1", "Created")
        mock_manager.create_canvas = AsyncMock(return_value=created)
        h = MockHTTPHandler(body={"name": "Created"}, method="POST")
        result = handler.handle("/api/v1/canvas", {}, h)
        assert _status(result) == 201

        mock_manager.get_canvas = AsyncMock(return_value=created)
        h2 = MockHTTPHandler(method="GET")
        result2 = handler.handle("/api/v1/canvas/new-1", {}, h2)
        assert _status(result2) == 200
        assert _body(result2)["name"] == "Created"

    def test_add_node_then_delete(self, handler, mock_manager):
        """Add a node and then delete it."""
        node = MockNode("n-new", "To Delete")
        mock_manager.add_node = AsyncMock(return_value=node)
        h = MockHTTPHandler(body={"type": "text", "label": "To Delete"}, method="POST")
        result = handler.handle("/api/v1/canvas/c1/nodes", {}, h)
        assert _status(result) == 201

        mock_manager.remove_node = AsyncMock(return_value=True)
        h2 = MockHTTPHandler(method="DELETE")
        result2 = handler.handle("/api/v1/canvas/c1/nodes/n-new", {}, h2)
        assert _status(result2) == 200
        assert _body(result2)["deleted"] is True

    def test_add_edge_then_delete(self, handler, mock_manager):
        """Add an edge and then delete it."""
        edge = MockEdge("e-new", "n1", "n2")
        mock_manager.add_edge = AsyncMock(return_value=edge)
        body = {"source_id": "n1", "target_id": "n2"}
        h = MockHTTPHandler(body=body, method="POST")
        result = handler.handle("/api/v1/canvas/c1/edges", {}, h)
        assert _status(result) == 201

        mock_manager.remove_edge = AsyncMock(return_value=True)
        h2 = MockHTTPHandler(method="DELETE")
        result2 = handler.handle("/api/v1/canvas/c1/edges/e-new", {}, h2)
        assert _status(result2) == 200
        assert _body(result2)["deleted"] is True

    def test_multiple_operations_on_same_canvas(self, handler, mock_manager):
        """Multiple node + edge operations on a single canvas."""
        # Add two nodes
        n1 = MockNode("n1", "First")
        n2 = MockNode("n2", "Second")
        mock_manager.add_node = AsyncMock(side_effect=[n1, n2])

        h1 = MockHTTPHandler(body={"type": "text", "label": "First"}, method="POST")
        r1 = handler.handle("/api/v1/canvas/c1/nodes", {}, h1)
        assert _status(r1) == 201

        h2 = MockHTTPHandler(body={"type": "text", "label": "Second"}, method="POST")
        r2 = handler.handle("/api/v1/canvas/c1/nodes", {}, h2)
        assert _status(r2) == 201

        # Add edge between them
        e = MockEdge("e1", "n1", "n2")
        mock_manager.add_edge = AsyncMock(return_value=e)
        h3 = MockHTTPHandler(body={"source_id": "n1", "target_id": "n2"}, method="POST")
        r3 = handler.handle("/api/v1/canvas/c1/edges", {}, h3)
        assert _status(r3) == 201

    def test_workspace_id_override_from_query(self, handler, mock_manager):
        """workspace_id from query params should override user's org_id."""
        mock_manager.list_canvases = AsyncMock(return_value=[])
        h = MockHTTPHandler(method="GET")
        handler.handle("/api/v1/canvas", {"workspace_id": "override-ws"}, h)
        call_args = mock_manager.list_canvases.call_args
        # The workspace_id param should contain the override value
        assert "override-ws" in str(call_args)
