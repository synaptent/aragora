"""Tests for ActionCanvasHandler REST API."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
from typing import Any

import pytest

from aragora.canvas.manager import CanvasStateManager
from aragora.server.handlers.action_canvas import ActionCanvasHandler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler():
    return ActionCanvasHandler(ctx={})


@pytest.fixture(autouse=True)
def _isolated_action_canvas_store(tmp_path, monkeypatch):
    """Back the global action-canvas store with a per-test database.

    The default store is ``action_canvas.db`` in the shared data directory.
    xdist workers that create that file concurrently race on the WAL-mode
    switch and fail with ``sqlite3.OperationalError: database is locked``.
    """
    from aragora.canvas import action_store
    from aragora.storage.schema import DatabaseManager

    store = action_store.ActionCanvasStore(tmp_path / "action_canvas.db")
    monkeypatch.setattr(action_store, "_action_canvas_store", store)
    yield store
    DatabaseManager.close_instances([str(store.db_path)])


@pytest.fixture
def mock_request():
    """Create a mock HTTP handler object."""

    def _make(method: str = "GET", body: dict | None = None):
        h = MagicMock()
        h.command = method
        h.client_address = ("127.0.0.1", 12345)
        h.headers = {"X-Forwarded-For": "127.0.0.1"}
        h.request = MagicMock()
        h.request.body = json.dumps(body).encode() if body else None
        h.auth_user = MagicMock()
        h.auth_user.user_id = "test-user"
        h.auth_user.org_id = "test-org"
        h.auth_user.roles = {"admin"}
        return h

    return _make


# ---------------------------------------------------------------------------
# Route matching tests
# ---------------------------------------------------------------------------


class TestRouteMatching:
    """can_handle() and routing tests."""

    def test_can_handle_actions_root(self, handler):
        assert handler.can_handle("/api/v1/actions") is True

    def test_can_handle_actions_with_id(self, handler):
        assert handler.can_handle("/api/v1/actions/test-123") is True

    def test_can_handle_actions_nodes(self, handler):
        assert handler.can_handle("/api/v1/actions/test-123/nodes") is True

    def test_can_handle_actions_edges(self, handler):
        assert handler.can_handle("/api/v1/actions/test-123/edges") is True

    def test_can_handle_actions_export(self, handler):
        assert handler.can_handle("/api/v1/actions/test-123/export") is True

    def test_can_handle_actions_advance(self, handler):
        assert handler.can_handle("/api/v1/actions/test-123/advance") is True

    def test_cannot_handle_other(self, handler):
        assert handler.can_handle("/api/v1/debates") is False
        assert handler.can_handle("/api/v1/ideas") is False
        assert handler.can_handle("/api/v1/goals") is False

    def test_routes_unknown_path(self, handler):
        result = handler._route_request(
            "/api/v1/actions/test/unknown/path",
            "GET",
            {},
            {},
            "u1",
            "ws1",
            MagicMock(),
        )
        assert result is None

    def test_method_not_allowed_list(self, handler):
        result = handler._route_request(
            "/api/v1/actions",
            "DELETE",
            {},
            {},
            "u1",
            "ws1",
            MagicMock(),
        )
        assert result is not None
        status = getattr(result, "status_code", getattr(result, "status", None))
        if status:
            assert status == 405


# ---------------------------------------------------------------------------
# Canvas CRUD tests
# ---------------------------------------------------------------------------


class TestListCanvases:
    """_list_canvases tests."""

    @patch("aragora.canvas.action_store.get_action_canvas_store")
    def test_list_empty(self, mock_get_store, handler):
        mock_store = MagicMock()
        mock_store.list_canvases.return_value = []
        mock_get_store.return_value = mock_store

        ctx = MagicMock()
        result = handler._list_canvases(ctx, {}, "u1", "ws1")
        assert result is not None

    @patch("aragora.canvas.action_store.get_action_canvas_store")
    def test_list_with_results(self, mock_get_store, handler):
        mock_store = MagicMock()
        mock_store.list_canvases.return_value = [
            {"id": "ac-1", "name": "Sprint 1"},
            {"id": "ac-2", "name": "Sprint 2"},
        ]
        mock_get_store.return_value = mock_store

        ctx = MagicMock()
        result = handler._list_canvases(ctx, {}, "u1", "ws1")
        assert result is not None

    @patch("aragora.canvas.action_store.get_action_canvas_store")
    def test_list_with_source_filter(self, mock_get_store, handler):
        mock_store = MagicMock()
        mock_store.list_canvases.return_value = []
        mock_get_store.return_value = mock_store

        ctx = MagicMock()
        result = handler._list_canvases(ctx, {"source_canvas_id": "goals-abc"}, "u1", "ws1")
        assert result is not None
        mock_store.list_canvases.assert_called_once()


class TestCreateCanvas:
    """_create_canvas tests."""

    @patch("aragora.canvas.action_store.get_action_canvas_store")
    def test_create(self, mock_get_store, handler):
        mock_store = MagicMock()
        mock_store.save_canvas.return_value = {"id": "ac-new", "name": "Test"}
        mock_get_store.return_value = mock_store

        ctx = MagicMock()
        result = handler._create_canvas(
            ctx,
            {"name": "Sprint Planning"},
            "u1",
            "ws1",
        )
        assert result is not None
        mock_store.save_canvas.assert_called_once()

    @patch("aragora.canvas.action_store.get_action_canvas_store")
    def test_create_with_source(self, mock_get_store, handler):
        mock_store = MagicMock()
        mock_store.save_canvas.return_value = {"id": "ac-new", "name": "Test"}
        mock_get_store.return_value = mock_store

        ctx = MagicMock()
        result = handler._create_canvas(
            ctx,
            {"name": "From Goals", "source_canvas_id": "goals-123"},
            "u1",
            "ws1",
        )
        assert result is not None


class TestGetCanvas:
    """_get_canvas tests."""

    @patch("aragora.canvas.action_store.get_action_canvas_store")
    def test_not_found(self, mock_get_store, handler):
        mock_store = MagicMock()
        mock_store.load_canvas.return_value = None
        mock_get_store.return_value = mock_store

        with patch.object(handler, "_get_canvas_manager"):
            ctx = MagicMock()
            result = handler._get_canvas(ctx, "missing", "u1")
            assert result is not None
            status = getattr(result, "status_code", getattr(result, "status", None))
            if status:
                assert status == 404

    @patch("aragora.canvas.action_store.get_action_canvas_store")
    def test_rehydrates_persisted_snapshot(self, mock_get_store, handler):
        mock_store = MagicMock()
        mock_store.load_canvas.return_value = {
            "id": "ac-1",
            "name": "Sprint 1",
            "owner_id": "u1",
            "workspace_id": "ws-1",
            "metadata": {"stage": "actions", "state_snapshot_version": 1},
            "nodes": [
                {
                    "id": "node-1",
                    "type": "workflow",
                    "position": {"x": 12, "y": 34},
                    "label": "Ship receipts",
                    "data": {"stage": "actions"},
                }
            ],
            "edges": [],
        }
        mock_store.update_canvas.return_value = None
        mock_get_store.return_value = mock_store

        with patch.object(handler, "_get_canvas_manager", return_value=CanvasStateManager()):
            ctx = MagicMock()
            result = handler._get_canvas(ctx, "ac-1", "u1")
            assert result is not None

        body = json.loads(result.body.decode("utf-8"))
        assert body["nodes"][0]["id"] == "node-1"
        assert body["edges"] == []


class TestDeleteCanvas:
    """_delete_canvas tests."""

    @patch("aragora.canvas.action_store.get_action_canvas_store")
    def test_delete_success(self, mock_get_store, handler):
        mock_store = MagicMock()
        mock_store.delete_canvas.return_value = True
        mock_get_store.return_value = mock_store

        ctx = MagicMock()
        result = handler._delete_canvas(ctx, "ac-1", "u1")
        assert result is not None

    @patch("aragora.canvas.action_store.get_action_canvas_store")
    def test_delete_not_found(self, mock_get_store, handler):
        mock_store = MagicMock()
        mock_store.delete_canvas.return_value = False
        mock_get_store.return_value = mock_store

        ctx = MagicMock()
        result = handler._delete_canvas(ctx, "missing", "u1")
        assert result is not None


class TestUpdateCanvas:
    """_update_canvas tests."""

    @patch("aragora.canvas.action_store.get_action_canvas_store")
    def test_update(self, mock_get_store, handler):
        mock_store = MagicMock()
        mock_store.update_canvas.return_value = {"id": "ac-1", "name": "Updated"}
        mock_get_store.return_value = mock_store

        ctx = MagicMock()
        result = handler._update_canvas(ctx, "ac-1", {"name": "Updated"}, "u1")
        assert result is not None


# ---------------------------------------------------------------------------
# Node CRUD tests
# ---------------------------------------------------------------------------


class TestAddNode:
    """_add_node tests."""

    def test_invalid_action_type(self, handler):
        with patch.object(handler, "_get_canvas_manager"):
            ctx = MagicMock()
            result = handler._add_node(
                ctx,
                "c1",
                {"action_type": "INVALID_TYPE"},
                "u1",
            )
            assert result is not None
            status = getattr(result, "status_code", getattr(result, "status", None))
            if status:
                assert status == 400

    @patch("aragora.canvas.action_store.get_action_canvas_store")
    def test_valid_action_types(self, mock_get_store, handler):
        """All ActionNodeType values should be accepted."""
        from aragora.canvas.stages import ActionNodeType

        mock_store = MagicMock()
        mock_store.load_canvas.return_value = {
            "id": "c1",
            "metadata": {"stage": "actions", "state_snapshot_version": 1},
        }
        mock_get_store.return_value = mock_store

        for action_type in ActionNodeType:
            with patch.object(handler, "_get_canvas_manager") as mock_mgr:
                manager = MagicMock()
                mock_mgr.return_value = manager
                with patch.object(handler, "_get_or_restore_canvas", return_value=MagicMock()):
                    with patch.object(handler, "_persist_canvas_state"):
                        with patch.object(handler, "_run_async") as mock_run:
                            node_mock = MagicMock()
                            node_mock.to_dict.return_value = {"id": "n1"}
                            mock_run.return_value = node_mock
                            ctx = MagicMock()
                            result = handler._add_node(
                                ctx,
                                "c1",
                                {"action_type": action_type.value, "label": "test"},
                                "u1",
                            )
                            assert result is not None


class TestUpdateNode:
    """_update_node tests."""

    def test_update_node_not_found(self, handler):
        with patch.object(handler, "_get_canvas_manager"):
            with patch.object(handler, "_run_async", return_value=None):
                ctx = MagicMock()
                result = handler._update_node(
                    ctx,
                    "c1",
                    "n1",
                    {"label": "Updated"},
                    "u1",
                )
                assert result is not None


class TestStoreIsolation:
    """Unmocked store access stays private to the running test."""

    def test_unmocked_store_uses_per_test_database(self, handler, tmp_path):
        store = handler._get_store()
        assert store.db_path.parent == tmp_path


class TestDeleteNode:
    """_delete_node tests."""

    def test_delete_node_not_found(self, handler):
        with patch.object(handler, "_get_canvas_manager"):
            with patch.object(handler, "_run_async", return_value=False):
                ctx = MagicMock()
                result = handler._delete_node(ctx, "c1", "n1", "u1")
                assert result is not None


# ---------------------------------------------------------------------------
# Edge CRUD tests
# ---------------------------------------------------------------------------


class TestAddEdge:
    """_add_edge tests."""

    def test_missing_source(self, handler):
        with patch.object(handler, "_get_canvas_manager"):
            ctx = MagicMock()
            result = handler._add_edge(
                ctx,
                "c1",
                {"target_id": "n2"},
                "u1",
            )
            assert result is not None
            status = getattr(result, "status_code", getattr(result, "status", None))
            if status:
                assert status == 400

    def test_missing_target(self, handler):
        with patch.object(handler, "_get_canvas_manager"):
            ctx = MagicMock()
            result = handler._add_edge(
                ctx,
                "c1",
                {"source_id": "n1"},
                "u1",
            )
            assert result is not None
            status = getattr(result, "status_code", getattr(result, "status", None))
            if status:
                assert status == 400


class TestDeleteEdge:
    """_delete_edge tests."""

    def test_delete_edge_not_found(self, handler):
        with patch.object(handler, "_get_canvas_manager"):
            with patch.object(handler, "_run_async", return_value=False):
                ctx = MagicMock()
                result = handler._delete_edge(ctx, "c1", "e1", "u1")
                assert result is not None


# ---------------------------------------------------------------------------
# Export & Advance tests
# ---------------------------------------------------------------------------


class TestExportCanvas:
    """_export_canvas tests."""

    def test_export_not_found(self, handler):
        with patch.object(handler, "_get_canvas_manager") as mock_mgr:
            manager = MagicMock()
            mock_mgr.return_value = manager
            with patch.object(handler, "_run_async", return_value=None):
                ctx = MagicMock()
                result = handler._export_canvas(ctx, "missing", "u1")
                assert result is not None


class TestAdvanceToOrchestration:
    """_advance_to_orchestration tests."""

    @patch("aragora.canvas.action_store.get_action_canvas_store")
    def test_canvas_not_found(self, mock_get_store, handler):
        mock_store = MagicMock()
        mock_store.load_canvas.return_value = None
        mock_get_store.return_value = mock_store

        ctx = MagicMock()
        result = handler._advance_to_orchestration(ctx, "missing", {}, "u1")
        assert result is not None
        status = getattr(result, "status_code", getattr(result, "status", None))
        if status:
            assert status == 404

    @patch("aragora.canvas.action_store.get_action_canvas_store")
    def test_advance_requires_live_canvas_state(self, mock_get_store, handler):
        mock_store = MagicMock()
        mock_store.load_canvas.return_value = {
            "id": "ac-1",
            "name": "Sprint 1",
            "metadata": {"stage": "actions"},
        }
        mock_get_store.return_value = mock_store

        with patch.object(handler, "_get_canvas_manager"):
            with patch.object(handler, "_run_async", return_value=None):
                ctx = MagicMock()
                result = handler._advance_to_orchestration(ctx, "ac-1", {}, "u1")
                assert result is not None
                status = getattr(result, "status_code", getattr(result, "status", None))
                if status:
                    assert status == 409

    @patch("aragora.canvas.action_store.get_action_canvas_store")
    def test_advance_materializes_orchestration_canvas(self, mock_get_store, handler):
        mock_store = MagicMock()
        mock_store.load_canvas.return_value = {
            "id": "ac-1",
            "name": "Sprint 1",
            "workspace_id": "ws-1",
            "metadata": {"stage": "actions"},
        }
        mock_get_store.return_value = mock_store

        orchestration_store = MagicMock()
        orchestration_store.save_canvas.return_value = {
            "id": "orch-1",
            "name": "Sprint 1 Orchestration",
            "metadata": {"stage": "orchestration", "source_canvas_id": "ac-1"},
        }

        source_canvas = MagicMock()
        source_canvas.nodes = {}
        source_canvas.edges = {}

        orchestration_canvas = MagicMock()
        orchestration_canvas.id = "orch-1"
        orchestration_canvas.name = "Sprint 1 Orchestration"
        orchestration_canvas.metadata = {"stage": "orchestration", "source_canvas_id": "ac-1"}
        orchestration_canvas.nodes = {}
        orchestration_canvas.edges = {}

        live_orchestration = MagicMock()
        live_orchestration.nodes = orchestration_canvas.nodes
        live_orchestration.edges = orchestration_canvas.edges
        live_orchestration.metadata = orchestration_canvas.metadata

        with patch.object(
            handler, "_get_orchestration_store", return_value=orchestration_store, create=True
        ):
            with patch.object(
                handler,
                "_build_orchestration_canvas",
                return_value=orchestration_canvas,
                create=True,
            ):
                with patch.object(handler, "_get_canvas_manager"):
                    with patch.object(
                        handler, "_run_async", side_effect=[source_canvas, live_orchestration]
                    ):
                        ctx = MagicMock()
                        result = handler._advance_to_orchestration(ctx, "ac-1", {}, "u1")
                        assert result is not None

        orchestration_store.save_canvas.assert_called_once()
        body = json.loads(result.body.decode("utf-8"))
        assert body["source_stage"] == "actions"
        assert body["target_stage"] == "orchestration"
        assert body["source_canvas_id"] == "ac-1"
        assert body["orchestration_canvas_id"] == "orch-1"
        assert body["status"] == "created"


# ---------------------------------------------------------------------------
# Rate limit tests
# ---------------------------------------------------------------------------


class TestRateLimit:
    """Rate limiting tests."""

    @patch("aragora.server.handlers.action_canvas._actions_limiter")
    def test_rate_limit_blocks(self, mock_limiter, handler, mock_request):
        mock_limiter.is_allowed.return_value = False
        result = handler.handle("/api/v1/actions", {}, mock_request("GET"))
        assert result is not None
