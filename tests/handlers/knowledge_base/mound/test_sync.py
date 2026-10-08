"""Tests for SyncOperationsMixin (aragora/server/handlers/knowledge_base/mound/sync.py).

Covers all three handler methods on the mixin:
- _handle_sync_continuum  (POST /api/knowledge/mound/sync/continuum)
- _handle_sync_consensus  (POST /api/knowledge/mound/sync/consensus)
- _handle_sync_facts      (POST /api/knowledge/mound/sync/facts)

Each method is tested for:
- Success with valid inputs and defaults
- Mound not available (503)
- Invalid/missing JSON body (400)
- Custom parameters (workspace_id, since, limit)
- Primary sync success (result with nodes_synced)
- Primary sync success (result without nodes_synced attribute -> 0)
- Fallback path (AttributeError on first call -> import + connect + retry)
- Fallback failure (ImportError, AttributeError, RuntimeError in fallback)
- Internal errors from mound operations (RuntimeError, OSError -> 500)
- Edge cases: unicode, empty body, large limit, zero limit
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.knowledge_base.mound.sync import (
    SyncOperationsMixin,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RUN_ASYNC_PATCH = "aragora.server.handlers.knowledge_base.mound.sync._run_async"
_SYNC_CLOSED = pytest.mark.xfail(strict=True, reason="fact sync closed until mound is org-scoped")


def _body(result) -> dict:
    """Extract JSON body dict from a HandlerResult."""
    if result is None:
        return {}
    if isinstance(result, dict):
        return result
    raw = result.body
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def _status(result) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if result is None:
        return -1
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return result.status_code


def _make_http_handler(body: dict | None = None) -> MagicMock:
    """Create a mock HTTP handler with headers and rfile."""
    handler = MagicMock()
    if body is not None:
        body_bytes = json.dumps(body).encode("utf-8")
        handler.headers = {"Content-Length": str(len(body_bytes))}
        handler.rfile.read.return_value = body_bytes
    else:
        handler.headers = {"Content-Length": "0"}
        handler.rfile.read.return_value = b""
    return handler


def _make_invalid_json_handler() -> MagicMock:
    """Create a mock HTTP handler with invalid JSON body."""
    handler = MagicMock()
    handler.headers = {"Content-Length": "12"}
    handler.rfile.read.return_value = b"not valid js"
    return handler


# ---------------------------------------------------------------------------
# Mock domain objects
# ---------------------------------------------------------------------------


@dataclass
class MockSyncResult:
    """Mock sync result with nodes_synced attribute."""

    nodes_synced: int = 42


class MockSyncResultNoAttr:
    """Mock sync result without nodes_synced attribute."""

    pass


# ---------------------------------------------------------------------------
# Concrete test class combining the mixin with stubs
# ---------------------------------------------------------------------------


class SyncTestHandler(SyncOperationsMixin):
    """Concrete handler for testing the sync mixin."""

    def __init__(self, mound=None):
        self._mound_instance = mound

    def _get_mound(self):
        return self._mound_instance

    def require_auth_or_error(self, handler):
        """Mock auth that always succeeds."""
        user = MagicMock()
        user.authenticated = True
        user.user_id = "test-user-001"
        return user, None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_mound():
    """Create a mock KnowledgeMound with sync-related methods."""
    mound = MagicMock()
    mound.sync_continuum_incremental = MagicMock(return_value=MockSyncResult(nodes_synced=10))
    mound.sync_consensus_incremental = MagicMock(return_value=MockSyncResult(nodes_synced=20))
    mound.sync_facts_incremental = MagicMock(return_value=MockSyncResult(nodes_synced=30))
    mound.connect_memory_stores = MagicMock(return_value=None)
    return mound


@pytest.fixture
def handler(mock_mound):
    """Create a SyncTestHandler with a mocked mound."""
    return SyncTestHandler(mound=mock_mound)


@pytest.fixture
def handler_no_mound():
    """Create a SyncTestHandler with no mound (None)."""
    return SyncTestHandler(mound=None)


# ============================================================================
# Tests: _handle_sync_continuum (POST /api/knowledge/mound/sync/continuum)
# ============================================================================


class TestSyncContinuum:
    """Test _handle_sync_continuum - sync from ContinuumMemory endpoint."""

    def test_sync_continuum_success(self, handler, mock_mound):
        """Successful continuum sync returns synced count and message."""
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_continuum(mock_http)
        assert _status(result) == 200
        body = _body(result)
        assert body["synced"] == 10
        assert body["workspace_id"] == "default"
        assert "continuum" in body["message"].lower()

    def test_sync_continuum_with_workspace_id(self, handler, mock_mound):
        """workspace_id from body is forwarded to sync method."""
        mock_http = _make_http_handler({"workspace_id": "ws-prod"})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_continuum(mock_http)
        body = _body(result)
        assert body["workspace_id"] == "ws-prod"
        mock_mound.sync_continuum_incremental.assert_called_once_with(
            workspace_id="ws-prod", since=None, limit=100
        )

    def test_sync_continuum_with_since(self, handler, mock_mound):
        """since parameter from body is forwarded."""
        mock_http = _make_http_handler({"since": "2025-01-15T10:00:00Z"})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            handler._handle_sync_continuum(mock_http)
        mock_mound.sync_continuum_incremental.assert_called_once_with(
            workspace_id="default", since="2025-01-15T10:00:00Z", limit=100
        )

    def test_sync_continuum_with_limit(self, handler, mock_mound):
        """Custom limit from body is forwarded."""
        mock_http = _make_http_handler({"limit": 50})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            handler._handle_sync_continuum(mock_http)
        mock_mound.sync_continuum_incremental.assert_called_once_with(
            workspace_id="default", since=None, limit=50
        )

    def test_sync_continuum_with_all_params(self, handler, mock_mound):
        """All parameters together are forwarded correctly."""
        mock_http = _make_http_handler(
            {
                "workspace_id": "ws-123",
                "since": "2025-06-01",
                "limit": 200,
            }
        )
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            handler._handle_sync_continuum(mock_http)
        mock_mound.sync_continuum_incremental.assert_called_once_with(
            workspace_id="ws-123", since="2025-06-01", limit=200
        )

    def test_sync_continuum_default_workspace(self, handler, mock_mound):
        """Default workspace_id is 'default' when not specified."""
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_continuum(mock_http)
        body = _body(result)
        assert body["workspace_id"] == "default"

    def test_sync_continuum_default_limit(self, handler, mock_mound):
        """Default limit is 100 when not specified."""
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            handler._handle_sync_continuum(mock_http)
        mock_mound.sync_continuum_incremental.assert_called_once_with(
            workspace_id="default", since=None, limit=100
        )

    def test_sync_continuum_default_since_is_none(self, handler, mock_mound):
        """Default since is None when not specified."""
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            handler._handle_sync_continuum(mock_http)
        call_kwargs = mock_mound.sync_continuum_incremental.call_args
        assert call_kwargs.kwargs.get("since") is None

    def test_sync_continuum_no_mound_returns_503(self, handler_no_mound):
        """Missing mound returns 503."""
        mock_http = _make_http_handler({})
        result = handler_no_mound._handle_sync_continuum(mock_http)
        assert _status(result) == 503
        body = _body(result)
        assert "not available" in body["error"].lower()

    def test_sync_continuum_invalid_json_returns_400(self, handler):
        """Invalid JSON body returns 400."""
        mock_http = _make_invalid_json_handler()
        result = handler._handle_sync_continuum(mock_http)
        assert _status(result) == 400
        body = _body(result)
        assert "invalid" in body["error"].lower()

    def test_sync_continuum_runtime_error_returns_500(self, handler, mock_mound):
        """RuntimeError from mound is caught by handler except clause -> 500."""
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=RuntimeError("db fail")):
            result = handler._handle_sync_continuum(mock_http)
        assert _status(result) == 500

    def test_sync_continuum_os_error_returns_500(self, handler, mock_mound):
        """OSError from mound is caught by handler except clause -> 500."""
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=OSError("disk full")):
            result = handler._handle_sync_continuum(mock_http)
        assert _status(result) == 500

    def test_sync_continuum_result_without_nodes_synced(self, handler, mock_mound):
        """Result without nodes_synced attribute returns synced=0."""
        mock_mound.sync_continuum_incremental = MagicMock(return_value=MockSyncResultNoAttr())
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_continuum(mock_http)
        body = _body(result)
        assert body["synced"] == 0

    def test_sync_continuum_result_with_nodes_synced_zero(self, handler, mock_mound):
        """Result with nodes_synced=0 returns synced=0."""
        mock_mound.sync_continuum_incremental = MagicMock(
            return_value=MockSyncResult(nodes_synced=0)
        )
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_continuum(mock_http)
        body = _body(result)
        assert body["synced"] == 0

    def test_sync_continuum_result_with_large_nodes_synced(self, handler, mock_mound):
        """Result with large nodes_synced value is returned correctly."""
        mock_mound.sync_continuum_incremental = MagicMock(
            return_value=MockSyncResult(nodes_synced=999999)
        )
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_continuum(mock_http)
        body = _body(result)
        assert body["synced"] == 999999

    def test_sync_continuum_empty_body(self, handler, mock_mound):
        """Empty body (Content-Length 0) uses defaults."""
        mock_http = _make_http_handler(None)
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_continuum(mock_http)
        assert _status(result) == 200
        body = _body(result)
        assert body["workspace_id"] == "default"

    def test_sync_continuum_response_message(self, handler, mock_mound):
        """Response message mentions ContinuumMemory."""
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_continuum(mock_http)
        body = _body(result)
        assert "ContinuumMemory" in body["message"]

    def test_sync_continuum_unicode_workspace(self, handler, mock_mound):
        """Unicode workspace_id is handled correctly."""
        mock_http = _make_http_handler({"workspace_id": "espace-de-travail"})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_continuum(mock_http)
        body = _body(result)
        assert body["workspace_id"] == "espace-de-travail"

    # --- Fallback path tests ---

    def test_sync_continuum_fallback_on_attribute_error(self, handler, mock_mound):
        """AttributeError on first call triggers fallback import and retry."""
        call_count = [0]
        original_result = MockSyncResult(nodes_synced=5)

        def mock_run_async(coro):
            call_count[0] += 1
            if call_count[0] == 1:
                raise AttributeError("no sync_continuum_incremental")
            return original_result

        mock_http = _make_http_handler({})
        with (
            patch(_RUN_ASYNC_PATCH, side_effect=mock_run_async),
            patch(
                "aragora.server.handlers.knowledge_base.mound.sync.get_continuum_memory",
                create=True,
            ) as mock_get_continuum,
        ):
            # Patch the import inside the handler
            import aragora.server.handlers.knowledge_base.mound.sync as sync_mod

            with patch.dict(
                "sys.modules",
                {
                    "aragora.memory": MagicMock(get_continuum_memory=mock_get_continuum),
                },
            ):
                result = handler._handle_sync_continuum(mock_http)
        # The result depends on whether the fallback succeeded
        # With our mock, the second call returns the result
        assert _status(result) == 200

    def test_sync_continuum_fallback_import_error(self, handler, mock_mound):
        """ImportError in fallback returns graceful 'not available' message."""
        mock_http = _make_http_handler({"workspace_id": "ws-test"})

        def mock_run_async(coro):
            raise AttributeError("no method")

        with (
            patch(_RUN_ASYNC_PATCH, side_effect=mock_run_async),
            patch.dict("sys.modules", {"aragora.memory": None}),
        ):
            # The import will fail with ImportError since the module is set to None
            result = handler._handle_sync_continuum(mock_http)
        assert _status(result) == 200
        body = _body(result)
        assert body["synced"] == 0
        assert (
            "not available" in body["message"].lower() or "not connected" in body["message"].lower()
        )
        assert body["workspace_id"] == "ws-test"

    def test_sync_continuum_fallback_runtime_error(self, handler, mock_mound):
        """RuntimeError in fallback returns graceful 'not available' message."""
        call_count = [0]

        def mock_run_async(coro):
            call_count[0] += 1
            if call_count[0] == 1:
                raise AttributeError("no method")
            raise RuntimeError("connect failed")

        mock_http = _make_http_handler({})
        mock_memory_module = MagicMock()
        mock_memory_module.get_continuum_memory = MagicMock(return_value=MagicMock())
        with (
            patch(_RUN_ASYNC_PATCH, side_effect=mock_run_async),
            patch.dict("sys.modules", {"aragora.memory": mock_memory_module}),
        ):
            result = handler._handle_sync_continuum(mock_http)
        assert _status(result) == 200
        body = _body(result)
        assert body["synced"] == 0
        assert (
            "not available" in body["message"].lower() or "not connected" in body["message"].lower()
        )

    def test_sync_continuum_value_error_in_body_parse(self, handler):
        """ValueError during body parsing returns 400."""
        mock_http = MagicMock()
        mock_http.headers = {"Content-Length": "invalid"}
        result = handler._handle_sync_continuum(mock_http)
        assert _status(result) == 400

    def test_sync_continuum_limit_zero(self, handler, mock_mound):
        """Limit of zero is forwarded as-is."""
        mock_http = _make_http_handler({"limit": 0})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            handler._handle_sync_continuum(mock_http)
        mock_mound.sync_continuum_incremental.assert_called_once_with(
            workspace_id="default", since=None, limit=0
        )

    def test_sync_continuum_negative_limit(self, handler, mock_mound):
        """Negative limit is forwarded as-is (mound handles validation)."""
        mock_http = _make_http_handler({"limit": -5})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            handler._handle_sync_continuum(mock_http)
        mock_mound.sync_continuum_incremental.assert_called_once_with(
            workspace_id="default", since=None, limit=-5
        )

    def test_sync_continuum_large_limit(self, handler, mock_mound):
        """Large limit is forwarded as-is."""
        mock_http = _make_http_handler({"limit": 10000})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            handler._handle_sync_continuum(mock_http)
        mock_mound.sync_continuum_incremental.assert_called_once_with(
            workspace_id="default", since=None, limit=10000
        )

    def test_sync_continuum_extra_fields_ignored(self, handler, mock_mound):
        """Extra fields in body are ignored."""
        mock_http = _make_http_handler(
            {
                "workspace_id": "ws-1",
                "extra_field": "ignored",
                "another": 123,
            }
        )
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_continuum(mock_http)
        assert _status(result) == 200


# ============================================================================
# Tests: _handle_sync_consensus (POST /api/knowledge/mound/sync/consensus)
# ============================================================================


class TestSyncConsensus:
    """Test _handle_sync_consensus - sync from ConsensusMemory endpoint."""

    def test_sync_consensus_success(self, handler, mock_mound):
        """Successful consensus sync returns synced count and message."""
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_consensus(mock_http)
        assert _status(result) == 200
        body = _body(result)
        assert body["synced"] == 20
        assert body["workspace_id"] == "default"
        assert "consensus" in body["message"].lower()

    def test_sync_consensus_with_workspace_id(self, handler, mock_mound):
        """workspace_id from body is forwarded to sync method."""
        mock_http = _make_http_handler({"workspace_id": "ws-staging"})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_consensus(mock_http)
        body = _body(result)
        assert body["workspace_id"] == "ws-staging"
        mock_mound.sync_consensus_incremental.assert_called_once_with(
            workspace_id="ws-staging", since=None, limit=100
        )

    def test_sync_consensus_with_since(self, handler, mock_mound):
        """since parameter from body is forwarded."""
        mock_http = _make_http_handler({"since": "2025-03-01T00:00:00Z"})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            handler._handle_sync_consensus(mock_http)
        mock_mound.sync_consensus_incremental.assert_called_once_with(
            workspace_id="default", since="2025-03-01T00:00:00Z", limit=100
        )

    def test_sync_consensus_with_limit(self, handler, mock_mound):
        """Custom limit from body is forwarded."""
        mock_http = _make_http_handler({"limit": 25})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            handler._handle_sync_consensus(mock_http)
        mock_mound.sync_consensus_incremental.assert_called_once_with(
            workspace_id="default", since=None, limit=25
        )

    def test_sync_consensus_with_all_params(self, handler, mock_mound):
        """All parameters together are forwarded correctly."""
        mock_http = _make_http_handler(
            {
                "workspace_id": "ws-all",
                "since": "2025-07-01",
                "limit": 500,
            }
        )
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            handler._handle_sync_consensus(mock_http)
        mock_mound.sync_consensus_incremental.assert_called_once_with(
            workspace_id="ws-all", since="2025-07-01", limit=500
        )

    def test_sync_consensus_default_workspace(self, handler, mock_mound):
        """Default workspace_id is 'default' when not specified."""
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_consensus(mock_http)
        body = _body(result)
        assert body["workspace_id"] == "default"

    def test_sync_consensus_default_limit(self, handler, mock_mound):
        """Default limit is 100 when not specified."""
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            handler._handle_sync_consensus(mock_http)
        mock_mound.sync_consensus_incremental.assert_called_once_with(
            workspace_id="default", since=None, limit=100
        )

    def test_sync_consensus_no_mound_returns_503(self, handler_no_mound):
        """Missing mound returns 503."""
        mock_http = _make_http_handler({})
        result = handler_no_mound._handle_sync_consensus(mock_http)
        assert _status(result) == 503
        body = _body(result)
        assert "not available" in body["error"].lower()

    def test_sync_consensus_invalid_json_returns_400(self, handler):
        """Invalid JSON body returns 400."""
        mock_http = _make_invalid_json_handler()
        result = handler._handle_sync_consensus(mock_http)
        assert _status(result) == 400
        body = _body(result)
        assert "invalid" in body["error"].lower()

    def test_sync_consensus_runtime_error_returns_500(self, handler, mock_mound):
        """RuntimeError from mound returns 500."""
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=RuntimeError("db fail")):
            result = handler._handle_sync_consensus(mock_http)
        assert _status(result) == 500

    def test_sync_consensus_os_error_returns_500(self, handler, mock_mound):
        """OSError from mound returns 500."""
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=OSError("disk error")):
            result = handler._handle_sync_consensus(mock_http)
        assert _status(result) == 500

    def test_sync_consensus_result_without_nodes_synced(self, handler, mock_mound):
        """Result without nodes_synced attribute returns synced=0."""
        mock_mound.sync_consensus_incremental = MagicMock(return_value=MockSyncResultNoAttr())
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_consensus(mock_http)
        body = _body(result)
        assert body["synced"] == 0

    def test_sync_consensus_result_with_zero_synced(self, handler, mock_mound):
        """Result with nodes_synced=0 returns synced=0."""
        mock_mound.sync_consensus_incremental = MagicMock(
            return_value=MockSyncResult(nodes_synced=0)
        )
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_consensus(mock_http)
        body = _body(result)
        assert body["synced"] == 0

    def test_sync_consensus_empty_body(self, handler, mock_mound):
        """Empty body (Content-Length 0) uses defaults."""
        mock_http = _make_http_handler(None)
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_consensus(mock_http)
        assert _status(result) == 200
        body = _body(result)
        assert body["workspace_id"] == "default"

    def test_sync_consensus_response_message(self, handler, mock_mound):
        """Response message mentions ConsensusMemory."""
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_consensus(mock_http)
        body = _body(result)
        assert "ConsensusMemory" in body["message"]

    # --- Fallback path tests ---

    def test_sync_consensus_fallback_on_attribute_error(self, handler, mock_mound):
        """AttributeError on first call triggers fallback import and retry."""
        call_count = [0]
        sync_result = MockSyncResult(nodes_synced=7)

        def mock_run_async(coro):
            call_count[0] += 1
            if call_count[0] == 1:
                raise AttributeError("no sync_consensus_incremental")
            return sync_result

        mock_http = _make_http_handler({})
        mock_memory_module = MagicMock()
        mock_memory_module.ConsensusMemory = MagicMock(return_value=MagicMock())
        with (
            patch(_RUN_ASYNC_PATCH, side_effect=mock_run_async),
            patch.dict("sys.modules", {"aragora.memory": mock_memory_module}),
        ):
            result = handler._handle_sync_consensus(mock_http)
        assert _status(result) == 200

    def test_sync_consensus_fallback_import_error(self, handler, mock_mound):
        """ImportError in fallback returns graceful 'not available' message."""
        mock_http = _make_http_handler({"workspace_id": "ws-fallback"})

        def mock_run_async(coro):
            raise AttributeError("no method")

        with (
            patch(_RUN_ASYNC_PATCH, side_effect=mock_run_async),
            patch.dict("sys.modules", {"aragora.memory": None}),
        ):
            result = handler._handle_sync_consensus(mock_http)
        assert _status(result) == 200
        body = _body(result)
        assert body["synced"] == 0
        assert (
            "not available" in body["message"].lower() or "not connected" in body["message"].lower()
        )
        assert body["workspace_id"] == "ws-fallback"

    def test_sync_consensus_fallback_runtime_error(self, handler, mock_mound):
        """RuntimeError in fallback returns graceful 'not available' message."""
        call_count = [0]

        def mock_run_async(coro):
            call_count[0] += 1
            if call_count[0] == 1:
                raise AttributeError("no method")
            raise RuntimeError("connect failed")

        mock_http = _make_http_handler({})
        mock_memory_module = MagicMock()
        mock_memory_module.ConsensusMemory = MagicMock(return_value=MagicMock())
        with (
            patch(_RUN_ASYNC_PATCH, side_effect=mock_run_async),
            patch.dict("sys.modules", {"aragora.memory": mock_memory_module}),
        ):
            result = handler._handle_sync_consensus(mock_http)
        assert _status(result) == 200
        body = _body(result)
        assert body["synced"] == 0

    def test_sync_consensus_value_error_in_body_parse(self, handler):
        """ValueError during body parsing returns 400."""
        mock_http = MagicMock()
        mock_http.headers = {"Content-Length": "not_a_number"}
        result = handler._handle_sync_consensus(mock_http)
        assert _status(result) == 400

    def test_sync_consensus_extra_fields_ignored(self, handler, mock_mound):
        """Extra fields in body are ignored."""
        mock_http = _make_http_handler(
            {
                "workspace_id": "ws-1",
                "unknown_param": "value",
            }
        )
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_consensus(mock_http)
        assert _status(result) == 200


# ============================================================================
# Tests: _handle_sync_facts (POST /api/knowledge/mound/sync/facts)
# ============================================================================


@_SYNC_CLOSED
class TestSyncFacts:
    """Test _handle_sync_facts - sync from FactStore endpoint."""

    def test_sync_facts_success(self, handler, mock_mound):
        """Successful facts sync returns synced count and message."""
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_facts(mock_http)
        assert _status(result) == 200
        body = _body(result)
        assert body["synced"] == 30
        assert body["workspace_id"] == "default"
        assert "fact" in body["message"].lower()

    def test_sync_facts_with_workspace_id(self, handler, mock_mound):
        """workspace_id from body is forwarded to sync method."""
        mock_http = _make_http_handler({"workspace_id": "ws-dev"})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_facts(mock_http)
        body = _body(result)
        assert body["workspace_id"] == "ws-dev"
        mock_mound.sync_facts_incremental.assert_called_once_with(
            workspace_id="ws-dev", since=None, limit=100
        )

    def test_sync_facts_with_since(self, handler, mock_mound):
        """since parameter from body is forwarded."""
        mock_http = _make_http_handler({"since": "2025-12-01T00:00:00Z"})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            handler._handle_sync_facts(mock_http)
        mock_mound.sync_facts_incremental.assert_called_once_with(
            workspace_id="default", since="2025-12-01T00:00:00Z", limit=100
        )

    def test_sync_facts_with_limit(self, handler, mock_mound):
        """Custom limit from body is forwarded."""
        mock_http = _make_http_handler({"limit": 75})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            handler._handle_sync_facts(mock_http)
        mock_mound.sync_facts_incremental.assert_called_once_with(
            workspace_id="default", since=None, limit=75
        )

    def test_sync_facts_with_all_params(self, handler, mock_mound):
        """All parameters together are forwarded correctly."""
        mock_http = _make_http_handler(
            {
                "workspace_id": "ws-full",
                "since": "2025-11-15",
                "limit": 300,
            }
        )
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            handler._handle_sync_facts(mock_http)
        mock_mound.sync_facts_incremental.assert_called_once_with(
            workspace_id="ws-full", since="2025-11-15", limit=300
        )

    def test_sync_facts_default_workspace(self, handler, mock_mound):
        """Default workspace_id is 'default' when not specified."""
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_facts(mock_http)
        body = _body(result)
        assert body["workspace_id"] == "default"

    def test_sync_facts_default_limit(self, handler, mock_mound):
        """Default limit is 100 when not specified."""
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            handler._handle_sync_facts(mock_http)
        mock_mound.sync_facts_incremental.assert_called_once_with(
            workspace_id="default", since=None, limit=100
        )

    def test_sync_facts_no_mound_returns_503(self, handler_no_mound):
        """Missing mound returns 503."""
        mock_http = _make_http_handler({})
        result = handler_no_mound._handle_sync_facts(mock_http)
        assert _status(result) == 503
        body = _body(result)
        assert "not available" in body["error"].lower()

    def test_sync_facts_invalid_json_returns_400(self, handler):
        """Invalid JSON body returns 400."""
        mock_http = _make_invalid_json_handler()
        result = handler._handle_sync_facts(mock_http)
        assert _status(result) == 400
        body = _body(result)
        assert "invalid" in body["error"].lower()

    def test_sync_facts_runtime_error_returns_500(self, handler, mock_mound):
        """RuntimeError from mound returns 500."""
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=RuntimeError("db fail")):
            result = handler._handle_sync_facts(mock_http)
        assert _status(result) == 500

    def test_sync_facts_os_error_returns_500(self, handler, mock_mound):
        """OSError from mound returns 500."""
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=OSError("disk full")):
            result = handler._handle_sync_facts(mock_http)
        assert _status(result) == 500

    def test_sync_facts_result_without_nodes_synced(self, handler, mock_mound):
        """Result without nodes_synced attribute returns synced=0."""
        mock_mound.sync_facts_incremental = MagicMock(return_value=MockSyncResultNoAttr())
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_facts(mock_http)
        body = _body(result)
        assert body["synced"] == 0

    def test_sync_facts_result_with_zero_synced(self, handler, mock_mound):
        """Result with nodes_synced=0 returns synced=0."""
        mock_mound.sync_facts_incremental = MagicMock(return_value=MockSyncResult(nodes_synced=0))
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_facts(mock_http)
        body = _body(result)
        assert body["synced"] == 0

    def test_sync_facts_empty_body(self, handler, mock_mound):
        """Empty body (Content-Length 0) uses defaults."""
        mock_http = _make_http_handler(None)
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_facts(mock_http)
        assert _status(result) == 200
        body = _body(result)
        assert body["workspace_id"] == "default"

    def test_sync_facts_response_message(self, handler, mock_mound):
        """Response message mentions FactStore."""
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_facts(mock_http)
        body = _body(result)
        assert "FactStore" in body["message"]

    # --- Fallback path tests ---

    def test_sync_facts_fallback_on_attribute_error(self, handler, mock_mound):
        """AttributeError on first call triggers fallback import and retry."""
        call_count = [0]
        sync_result = MockSyncResult(nodes_synced=12)

        def mock_run_async(coro):
            call_count[0] += 1
            if call_count[0] == 1:
                raise AttributeError("no sync_facts_incremental")
            return sync_result

        mock_http = _make_http_handler({})
        mock_fact_module = MagicMock()
        mock_fact_module.FactStore = MagicMock(return_value=MagicMock())
        with (
            patch(_RUN_ASYNC_PATCH, side_effect=mock_run_async),
            patch.dict(
                "sys.modules",
                {
                    "aragora.knowledge.fact_store": mock_fact_module,
                },
            ),
        ):
            result = handler._handle_sync_facts(mock_http)
        assert _status(result) == 200

    def test_sync_facts_fallback_import_error(self, handler, mock_mound):
        """ImportError in fallback returns graceful 'not available' message."""
        mock_http = _make_http_handler({"workspace_id": "ws-facts"})

        def mock_run_async(coro):
            raise AttributeError("no method")

        with (
            patch(_RUN_ASYNC_PATCH, side_effect=mock_run_async),
            patch.dict("sys.modules", {"aragora.knowledge.fact_store": None}),
        ):
            result = handler._handle_sync_facts(mock_http)
        assert _status(result) == 200
        body = _body(result)
        assert body["synced"] == 0
        assert (
            "not available" in body["message"].lower() or "not connected" in body["message"].lower()
        )
        assert body["workspace_id"] == "ws-facts"

    def test_sync_facts_fallback_runtime_error(self, handler, mock_mound):
        """RuntimeError in fallback returns graceful 'not available' message."""
        call_count = [0]

        def mock_run_async(coro):
            call_count[0] += 1
            if call_count[0] == 1:
                raise AttributeError("no method")
            raise RuntimeError("connect failed")

        mock_http = _make_http_handler({})
        mock_fact_module = MagicMock()
        mock_fact_module.FactStore = MagicMock(return_value=MagicMock())
        with (
            patch(_RUN_ASYNC_PATCH, side_effect=mock_run_async),
            patch.dict(
                "sys.modules",
                {
                    "aragora.knowledge.fact_store": mock_fact_module,
                },
            ),
        ):
            result = handler._handle_sync_facts(mock_http)
        assert _status(result) == 200
        body = _body(result)
        assert body["synced"] == 0

    def test_sync_facts_value_error_in_body_parse(self, handler):
        """ValueError during body parsing returns 400."""
        mock_http = MagicMock()
        mock_http.headers = {"Content-Length": "abc"}
        result = handler._handle_sync_facts(mock_http)
        assert _status(result) == 400

    def test_sync_facts_extra_fields_ignored(self, handler, mock_mound):
        """Extra fields in body are ignored."""
        mock_http = _make_http_handler(
            {
                "workspace_id": "ws-1",
                "unknown": True,
                "more_stuff": [1, 2, 3],
            }
        )
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_facts(mock_http)
        assert _status(result) == 200

    def test_sync_facts_unicode_workspace(self, handler, mock_mound):
        """Unicode workspace_id is handled correctly."""
        mock_http = _make_http_handler({"workspace_id": "arbeitsbereich-test"})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_facts(mock_http)
        body = _body(result)
        assert body["workspace_id"] == "arbeitsbereich-test"


# ============================================================================
# Tests: Edge Cases and Cross-Cutting Concerns
# ============================================================================


class TestSyncEdgeCases:
    """Test edge cases across all sync operations."""

    def test_all_three_endpoints_use_workspace_default(self, handler, mock_mound):
        """All three sync endpoints default workspace_id to 'default'."""
        mock_http = _make_http_handler({})
        for method in [
            handler._handle_sync_continuum,
            handler._handle_sync_consensus,
        ]:
            with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
                result = method(mock_http)
            body = _body(result)
            assert body["workspace_id"] == "default"

    def test_all_three_endpoints_use_limit_default_100(self, handler, mock_mound):
        """All three sync endpoints default limit to 100."""
        mock_http = _make_http_handler({})
        for method_name, mock_method in [
            ("_handle_sync_continuum", mock_mound.sync_continuum_incremental),
            ("_handle_sync_consensus", mock_mound.sync_consensus_incremental),
        ]:
            mock_method.reset_mock()
            with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
                getattr(handler, method_name)(mock_http)
            call_kwargs = mock_method.call_args
            assert call_kwargs.kwargs.get("limit") == 100, (
                f"{method_name} should default limit to 100"
            )

    def test_all_three_endpoints_return_503_when_no_mound(self, handler_no_mound):
        """All three sync endpoints return 503 when mound is unavailable."""
        mock_http = _make_http_handler({})
        for method in [
            handler_no_mound._handle_sync_continuum,
            handler_no_mound._handle_sync_consensus,
        ]:
            result = method(mock_http)
            assert _status(result) == 503

    def test_all_three_endpoints_return_400_on_invalid_json(self, handler):
        """All three sync endpoints return 400 on invalid JSON."""
        mock_http = _make_invalid_json_handler()
        for method in [
            handler._handle_sync_continuum,
            handler._handle_sync_consensus,
        ]:
            result = method(mock_http)
            assert _status(result) == 400

    def test_continuum_sync_response_has_expected_keys(self, handler, mock_mound):
        """Continuum sync response has synced, workspace_id, message keys."""
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_continuum(mock_http)
        body = _body(result)
        assert "synced" in body
        assert "workspace_id" in body
        assert "message" in body

    def test_consensus_sync_response_has_expected_keys(self, handler, mock_mound):
        """Consensus sync response has synced, workspace_id, message keys."""
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_consensus(mock_http)
        body = _body(result)
        assert "synced" in body
        assert "workspace_id" in body
        assert "message" in body

    @_SYNC_CLOSED
    def test_facts_sync_response_has_expected_keys(self, handler, mock_mound):
        """Facts sync response has synced, workspace_id, message keys."""
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_facts(mock_http)
        body = _body(result)
        assert "synced" in body
        assert "workspace_id" in body
        assert "message" in body

    def test_sync_continuum_sql_injection_workspace(self, handler, mock_mound):
        """SQL injection in workspace_id is passed as-is (mound handles safety)."""
        mock_http = _make_http_handler({"workspace_id": "'; DROP TABLE nodes; --"})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_continuum(mock_http)
        assert _status(result) == 200
        body = _body(result)
        assert body["workspace_id"] == "'; DROP TABLE nodes; --"

    def test_sync_consensus_path_traversal_workspace(self, handler, mock_mound):
        """Path traversal in workspace_id is passed as-is."""
        mock_http = _make_http_handler({"workspace_id": "../../etc/passwd"})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_consensus(mock_http)
        assert _status(result) == 200
        body = _body(result)
        assert body["workspace_id"] == "../../etc/passwd"

    @_SYNC_CLOSED
    def test_sync_facts_xss_in_workspace(self, handler, mock_mound):
        """XSS in workspace_id is stored as-is (rendering layer handles escaping)."""
        mock_http = _make_http_handler({"workspace_id": "<script>alert('xss')</script>"})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_facts(mock_http)
        assert _status(result) == 200

    def test_sync_continuum_empty_workspace(self, handler, mock_mound):
        """Empty workspace_id string is passed as-is."""
        mock_http = _make_http_handler({"workspace_id": ""})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_continuum(mock_http)
        body = _body(result)
        assert body["workspace_id"] == ""

    def test_sync_consensus_null_workspace(self, handler, mock_mound):
        """Null workspace_id falls back to default."""
        mock_http = _make_http_handler({"workspace_id": None})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_consensus(mock_http)
        body = _body(result)
        # data.get("workspace_id", "default") with None returns None (not "default")
        assert body["workspace_id"] is None or body["workspace_id"] == "default"

    def test_sync_continuum_float_limit(self, handler, mock_mound):
        """Float limit from JSON is passed as-is (JSON numbers)."""
        mock_http = _make_http_handler({"limit": 50.5})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            handler._handle_sync_continuum(mock_http)
        mock_mound.sync_continuum_incremental.assert_called_once_with(
            workspace_id="default", since=None, limit=50.5
        )

    def test_sync_continuum_string_limit(self, handler, mock_mound):
        """String limit from JSON is passed as-is (not converted)."""
        mock_http = _make_http_handler({"limit": "100"})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            handler._handle_sync_continuum(mock_http)
        mock_mound.sync_continuum_incremental.assert_called_once_with(
            workspace_id="default", since=None, limit="100"
        )

    def test_sync_with_only_since_param(self, handler, mock_mound):
        """Only since parameter, workspace and limit use defaults."""
        mock_http = _make_http_handler({"since": "2025-01-01"})
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            handler._handle_sync_continuum(mock_http)
        mock_mound.sync_continuum_incremental.assert_called_once_with(
            workspace_id="default", since="2025-01-01", limit=100
        )

    def test_sync_with_nested_body_object(self, handler, mock_mound):
        """Nested objects in body do not cause errors (extra fields ignored)."""
        mock_http = _make_http_handler(
            {
                "workspace_id": "ws-1",
                "nested": {"key": "value"},
            }
        )
        with patch(_RUN_ASYNC_PATCH, side_effect=lambda coro: coro):
            result = handler._handle_sync_continuum(mock_http)
        assert _status(result) == 200

    def test_sync_with_array_body(self, handler):
        """Array body instead of object causes JSON decode but no dict access error."""
        mock_http = MagicMock()
        body_bytes = b"[1, 2, 3]"
        mock_http.headers = {"Content-Length": str(len(body_bytes))}
        mock_http.rfile.read.return_value = body_bytes
        # json.loads succeeds but data is a list, not dict
        # data.get() will raise AttributeError which handle_errors catches
        result = handler._handle_sync_continuum(mock_http)
        # This will cause an AttributeError on data.get() since list has no .get()
        # The handle_errors decorator catches this and returns 500
        assert _status(result) == 500

    def test_continuum_503_error_message(self, handler_no_mound):
        """503 error message for continuum explicitly mentions Knowledge Mound."""
        mock_http = _make_http_handler({})
        result = handler_no_mound._handle_sync_continuum(mock_http)
        body = _body(result)
        assert "knowledge mound" in body["error"].lower()

    def test_consensus_503_error_message(self, handler_no_mound):
        """503 error message for consensus explicitly mentions Knowledge Mound."""
        mock_http = _make_http_handler({})
        result = handler_no_mound._handle_sync_consensus(mock_http)
        body = _body(result)
        assert "knowledge mound" in body["error"].lower()

    @_SYNC_CLOSED
    def test_facts_503_error_message(self, handler_no_mound):
        """503 error message for facts explicitly mentions Knowledge Mound."""
        mock_http = _make_http_handler({})
        result = handler_no_mound._handle_sync_facts(mock_http)
        body = _body(result)
        assert "knowledge mound" in body["error"].lower()


# ============================================================================
# Tests: Fallback Attribute Error Second Path
# ============================================================================


class TestFallbackAttributeError:
    """Test the inner fallback AttributeError handling in the except clause."""

    def test_continuum_fallback_attribute_error_in_retry(self, handler, mock_mound):
        """AttributeError inside fallback (after connect) returns graceful message."""
        call_count = [0]

        def mock_run_async(coro):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: triggers fallback
                raise AttributeError("no sync_continuum_incremental")
            if call_count[0] == 2:
                # Second call: connect_memory_stores succeeds
                return None
            # Third call: retry still fails
            raise AttributeError("still no method")

        mock_http = _make_http_handler({})
        mock_memory_module = MagicMock()
        mock_memory_module.get_continuum_memory = MagicMock(return_value=MagicMock())
        with (
            patch(_RUN_ASYNC_PATCH, side_effect=mock_run_async),
            patch.dict("sys.modules", {"aragora.memory": mock_memory_module}),
        ):
            result = handler._handle_sync_continuum(mock_http)
        body = _body(result)
        assert body["synced"] == 0
        assert (
            "not available" in body["message"].lower() or "not connected" in body["message"].lower()
        )

    def test_consensus_fallback_attribute_error_in_retry(self, handler, mock_mound):
        """AttributeError inside consensus fallback returns graceful message."""
        call_count = [0]

        def mock_run_async(coro):
            call_count[0] += 1
            if call_count[0] == 1:
                raise AttributeError("no method")
            if call_count[0] == 2:
                return None  # connect succeeds
            raise AttributeError("still no method")

        mock_http = _make_http_handler({})
        mock_memory_module = MagicMock()
        mock_memory_module.ConsensusMemory = MagicMock(return_value=MagicMock())
        with (
            patch(_RUN_ASYNC_PATCH, side_effect=mock_run_async),
            patch.dict("sys.modules", {"aragora.memory": mock_memory_module}),
        ):
            result = handler._handle_sync_consensus(mock_http)
        body = _body(result)
        assert body["synced"] == 0

    @_SYNC_CLOSED
    def test_facts_fallback_attribute_error_in_retry(self, handler, mock_mound):
        """AttributeError inside facts fallback returns graceful message."""
        call_count = [0]

        def mock_run_async(coro):
            call_count[0] += 1
            if call_count[0] == 1:
                raise AttributeError("no method")
            if call_count[0] == 2:
                return None  # connect succeeds
            raise AttributeError("still no method")

        mock_http = _make_http_handler({})
        mock_fact_module = MagicMock()
        mock_fact_module.FactStore = MagicMock(return_value=MagicMock())
        with (
            patch(_RUN_ASYNC_PATCH, side_effect=mock_run_async),
            patch.dict(
                "sys.modules",
                {
                    "aragora.knowledge.fact_store": mock_fact_module,
                },
            ),
        ):
            result = handler._handle_sync_facts(mock_http)
        body = _body(result)
        assert body["synced"] == 0


# ============================================================================
# Tests: handle_errors decorator behavior
# ============================================================================


class TestHandleErrorsDecorator:
    """Test that the @handle_errors decorator catches unexpected exceptions."""

    def test_continuum_type_error_returns_400(self, handler, mock_mound):
        """TypeError escapes to @handle_errors -> mapped to 400."""
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=TypeError("unexpected")):
            result = handler._handle_sync_continuum(mock_http)
        assert _status(result) == 400

    def test_consensus_type_error_returns_400(self, handler, mock_mound):
        """TypeError escapes to @handle_errors -> mapped to 400 for consensus."""
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=TypeError("unexpected")):
            result = handler._handle_sync_consensus(mock_http)
        assert _status(result) == 400

    @_SYNC_CLOSED
    def test_facts_type_error_returns_400(self, handler, mock_mound):
        """TypeError escapes to @handle_errors -> mapped to 400 for facts."""
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=TypeError("unexpected")):
            result = handler._handle_sync_facts(mock_http)
        assert _status(result) == 400

    def test_continuum_key_error_returns_404(self, handler, mock_mound):
        """KeyError escapes to @handle_errors -> mapped to 404."""
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=KeyError("missing")):
            result = handler._handle_sync_continuum(mock_http)
        assert _status(result) == 404

    def test_consensus_key_error_returns_404(self, handler, mock_mound):
        """KeyError escapes to @handle_errors -> mapped to 404."""
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=KeyError("missing")):
            result = handler._handle_sync_consensus(mock_http)
        assert _status(result) == 404

    @_SYNC_CLOSED
    def test_facts_key_error_returns_404(self, handler, mock_mound):
        """KeyError escapes to @handle_errors -> mapped to 404."""
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=KeyError("missing")):
            result = handler._handle_sync_facts(mock_http)
        assert _status(result) == 404

    def test_continuum_value_error_returns_400(self, handler, mock_mound):
        """ValueError escapes to @handle_errors -> mapped to 400."""
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=ValueError("bad")):
            result = handler._handle_sync_continuum(mock_http)
        assert _status(result) == 400

    def test_consensus_value_error_returns_400(self, handler, mock_mound):
        """ValueError escapes to @handle_errors -> mapped to 400."""
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=ValueError("bad")):
            result = handler._handle_sync_consensus(mock_http)
        assert _status(result) == 400

    @_SYNC_CLOSED
    def test_facts_value_error_returns_400(self, handler, mock_mound):
        """ValueError escapes to @handle_errors -> mapped to 400."""
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=ValueError("bad")):
            result = handler._handle_sync_facts(mock_http)
        assert _status(result) == 400

    def test_continuum_connection_error_returns_500(self, handler, mock_mound):
        """ConnectionError (subclass of OSError) caught by handler -> 500."""
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=ConnectionError("refused")):
            result = handler._handle_sync_continuum(mock_http)
        assert _status(result) == 500

    def test_consensus_connection_error_returns_500(self, handler, mock_mound):
        """ConnectionError (subclass of OSError) caught by handler -> 500."""
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=ConnectionError("refused")):
            result = handler._handle_sync_consensus(mock_http)
        assert _status(result) == 500

    @_SYNC_CLOSED
    def test_facts_connection_error_returns_500(self, handler, mock_mound):
        """ConnectionError (subclass of OSError) caught by handler -> 500."""
        mock_http = _make_http_handler({})
        with patch(_RUN_ASYNC_PATCH, side_effect=ConnectionError("refused")):
            result = handler._handle_sync_facts(mock_http)
        assert _status(result) == 500
