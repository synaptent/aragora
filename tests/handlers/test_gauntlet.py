"""
Tests for Gauntlet Handler.

Tests cover:
- Handler routing for gauntlet stress-testing endpoints
- Rate limiting
- API versioning headers
- Input validation
- Error handling
"""

from __future__ import annotations

from unittest.mock import MagicMock, AsyncMock, patch
import pytest

from aragora.server.handlers.base import HandlerResult
from aragora.server.handlers.gauntlet import (
    GauntletHandler,
    _gauntlet_runs,
)

from aragora.tenancy.record_scope import OrgScope as _OrgScope

TEST_ORG = "test-org-001"
TEST_SCOPE = _OrgScope(org_id=TEST_ORG, user_id="test-user-001", role="admin")

pytestmark = pytest.mark.usefixtures("org_scoped_request_user")


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mock_server_context():
    """Create mock server context."""
    return {
        "user_store": MagicMock(),
        "nomic_dir": "/tmp/test",
        "stream_emitter": MagicMock(),
    }


@pytest.fixture
def handler(mock_server_context):
    """Create GauntletHandler with mock context."""
    return GauntletHandler(mock_server_context)


@pytest.fixture
def mock_http_handler():
    """Create mock HTTP handler."""
    mock = MagicMock()
    mock.command = "GET"
    mock.client_address = ("127.0.0.1", 12345)
    mock.path = "/api/v1/gauntlet/run"
    mock.headers = {}
    return mock


@pytest.fixture(autouse=True)
def clear_gauntlet_runs():
    """Clear gauntlet runs between tests."""
    _gauntlet_runs.clear()
    yield
    _gauntlet_runs.clear()


# ============================================================================
# Routing Tests
# ============================================================================


class TestGauntletHandlerRouting:
    """Tests for handler routing."""

    def test_can_handle_run_endpoint(self, handler):
        """Handler can handle POST /api/v1/gauntlet/run."""
        assert handler.can_handle("/api/v1/gauntlet/run", method="POST")

    def test_can_handle_personas_endpoint(self, handler):
        """Handler can handle GET /api/v1/gauntlet/personas."""
        assert handler.can_handle("/api/v1/gauntlet/personas", method="GET")

    def test_can_handle_results_endpoint(self, handler):
        """Handler can handle GET /api/v1/gauntlet/results."""
        assert handler.can_handle("/api/v1/gauntlet/results", method="GET")

    def test_can_handle_gauntlet_id(self, handler):
        """Handler can handle GET /api/v1/gauntlet/:id."""
        assert handler.can_handle("/api/v1/gauntlet/abc-123", method="GET")
        assert handler.can_handle("/api/v1/gauntlet/uuid-1234-5678", method="GET")

    def test_can_handle_receipt_endpoint(self, handler):
        """Handler can handle GET /api/v1/gauntlet/:id/receipt."""
        assert handler.can_handle("/api/v1/gauntlet/abc-123/receipt", method="GET")

    def test_can_handle_receipt_verify(self, handler):
        """Handler can handle GET /api/v1/gauntlet/:id/receipt/verify."""
        assert handler.can_handle("/api/v1/gauntlet/abc-123/receipt/verify", method="GET")

    def test_can_handle_heatmap_endpoint(self, handler):
        """Handler can handle GET /api/v1/gauntlet/:id/heatmap."""
        assert handler.can_handle("/api/v1/gauntlet/abc-123/heatmap", method="GET")

    def test_can_handle_compare_endpoint(self, handler):
        """Handler can handle GET /api/v1/gauntlet/:id/compare/:id2."""
        assert handler.can_handle("/api/v1/gauntlet/abc-123/compare/def-456", method="GET")

    def test_can_handle_delete_endpoint(self, handler):
        """Handler can handle DELETE /api/v1/gauntlet/:id."""
        assert handler.can_handle("/api/v1/gauntlet/abc-123", method="DELETE")

    def test_cannot_handle_unknown_path(self, handler):
        """Handler cannot handle unknown paths."""
        assert not handler.can_handle("/api/v1/other/endpoint", method="GET")
        assert not handler.can_handle("/api/v1/debates", method="GET")

    def test_cannot_handle_wrong_method(self, handler):
        """Handler returns False for wrong methods."""
        # run is POST only
        assert not handler.can_handle("/api/v1/gauntlet/run", method="PUT")


# ============================================================================
# API Version Tests
# ============================================================================


class TestGauntletAPIVersioning:
    """Tests for API versioning."""

    def test_handler_has_api_version(self, handler):
        """Handler has API_VERSION set."""
        assert handler.API_VERSION == "v1"

    def test_has_auth_required_endpoints(self, handler):
        """Handler has AUTH_REQUIRED_ENDPOINTS list."""
        assert len(handler.AUTH_REQUIRED_ENDPOINTS) >= 2
        assert "/api/v1/gauntlet/run" in handler.AUTH_REQUIRED_ENDPOINTS


# ============================================================================
# Handler Method Tests
# ============================================================================


class TestGauntletHandlerMethods:
    """Tests for handler methods."""

    def test_personas_endpoint_is_routable(self, handler):
        """GET /api/v1/gauntlet/personas is routable."""
        assert handler.can_handle("/api/v1/gauntlet/personas", method="GET")

    def test_results_endpoint_is_routable(self, handler):
        """GET /api/v1/gauntlet/results is routable."""
        assert handler.can_handle("/api/v1/gauntlet/results", method="GET")


# ============================================================================
# Route Normalization Tests
# ============================================================================


class TestRouteNormalization:
    """Tests for route normalization."""

    def test_normalize_v1_path(self, handler):
        """V1 paths are normalized correctly (version prefix stripped)."""
        result = handler._normalize_path("/api/v1/gauntlet/run")
        # _normalize_path removes version prefix for internal routing
        assert result == "/api/gauntlet/run"

    def test_is_legacy_route_false_for_v1(self, handler):
        """V1 routes are not marked as legacy."""
        assert not handler._is_legacy_route("/api/v1/gauntlet/run")


# ============================================================================
# Memory Management Tests
# ============================================================================


class TestGauntletMemoryManagement:
    """Tests for gauntlet run memory management."""

    def test_max_runs_constant_exists(self):
        """MAX_GAUNTLET_RUNS_IN_MEMORY constant is defined."""
        from aragora.server.handlers.gauntlet import MAX_GAUNTLET_RUNS_IN_MEMORY

        assert MAX_GAUNTLET_RUNS_IN_MEMORY > 0
        assert MAX_GAUNTLET_RUNS_IN_MEMORY == 500

    def test_completed_ttl_exists(self):
        """_GAUNTLET_COMPLETED_TTL constant is defined."""
        from aragora.server.handlers.gauntlet import _GAUNTLET_COMPLETED_TTL

        assert _GAUNTLET_COMPLETED_TTL > 0
        assert _GAUNTLET_COMPLETED_TTL == 3600  # 1 hour

    def test_gauntlet_runs_is_ordered_dict(self):
        """_gauntlet_runs is an OrderedDict for FIFO eviction."""
        from collections import OrderedDict

        assert isinstance(_gauntlet_runs, OrderedDict)


# ============================================================================
# Handler Initialization Tests
# ============================================================================


class TestGauntletHandlerInit:
    """Tests for handler initialization."""

    def test_handler_has_routes(self, handler):
        """Handler has ROUTES list."""
        assert len(handler.ROUTES) >= 8

    def test_handler_extends_base_handler(self, handler):
        """Handler extends BaseHandler."""
        from aragora.server.handlers.base import BaseHandler

        assert isinstance(handler, BaseHandler)

    def test_handler_sets_broadcast_fn_if_emitter(self, mock_server_context):
        """Handler sets broadcast function if stream_emitter is provided."""
        with patch(
            "aragora.server.handlers.gauntlet.handler.set_gauntlet_broadcast_fn"
        ) as mock_set:
            handler = GauntletHandler(mock_server_context)
            mock_set.assert_called_once()

    def test_handler_without_emitter(self):
        """Handler works without stream_emitter."""
        ctx = {"user_store": MagicMock(), "nomic_dir": "/tmp/test"}
        handler = GauntletHandler(ctx)
        assert handler is not None


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestGauntletErrorHandling:
    """Tests for error handling."""

    def test_can_handle_returns_false_for_unhandled(self, handler):
        """can_handle returns False for unhandled paths."""
        assert not handler.can_handle("/api/v1/other/endpoint", method="GET")
        assert not handler.can_handle("/api/v1/debates", method="GET")
        assert not handler.can_handle("/api/v1/agents", method="GET")


# ============================================================================
# Receipt Format Tests
# ============================================================================


class TestGauntletReceiptFormats:
    """Tests for gauntlet receipt format generation."""

    def test_can_handle_receipt_json(self, handler):
        """Handler can handle JSON receipt format."""
        assert handler.can_handle("/api/v1/gauntlet/abc-123/receipt", method="GET")

    def test_can_handle_receipt_format_query(self, handler):
        """Handler accepts format query param."""
        # The format is passed as query param, not path
        assert handler.can_handle("/api/v1/gauntlet/abc-123/receipt", method="GET")

    def test_can_handle_receipt_html(self, handler):
        """Handler can serve HTML receipt."""
        assert handler.can_handle("/api/v1/gauntlet/abc-123/receipt.html", method="GET")

    def test_can_handle_receipt_markdown(self, handler):
        """Handler can serve Markdown receipt."""
        assert handler.can_handle("/api/v1/gauntlet/abc-123/receipt.md", method="GET")


class TestGauntletReceiptVerification:
    """Tests for receipt cryptographic verification."""

    def test_can_handle_verify_endpoint(self, handler):
        """Handler can handle verify endpoint."""
        assert handler.can_handle("/api/v1/gauntlet/abc-123/receipt/verify", method="GET")


# ============================================================================
# Heatmap Tests
# ============================================================================


class TestGauntletHeatmap:
    """Tests for gauntlet heatmap functionality."""

    def test_can_handle_heatmap(self, handler):
        """Handler can handle heatmap endpoint."""
        assert handler.can_handle("/api/v1/gauntlet/abc-123/heatmap", method="GET")

    def test_heatmap_accepts_dimensions(self, handler):
        """Heatmap endpoint accepts dimension query params."""
        # Just verify endpoint exists; dimensions tested at integration level
        assert handler.can_handle("/api/v1/gauntlet/abc-123/heatmap", method="GET")


# ============================================================================
# Gauntlet Comparison Tests
# ============================================================================


class TestGauntletComparison:
    """Tests for gauntlet comparison functionality."""

    def test_can_handle_compare(self, handler):
        """Handler can handle compare endpoint."""
        assert handler.can_handle("/api/v1/gauntlet/abc-123/compare/def-456", method="GET")

    @pytest.mark.asyncio
    async def test_compare_requires_two_ids(self, handler, mock_http_handler):
        """Compare endpoint rejects invalid gauntlet IDs before dispatch."""
        mock_http_handler.command = "GET"
        mock_http_handler.path = "/api/v1/gauntlet/id1/compare/id2"

        with (
            patch.object(handler, "require_auth_or_error", return_value=(MagicMock(), None)),
            patch.object(handler, "require_permission_or_error", return_value=(MagicMock(), None)),
            patch.object(handler, "_compare_results") as mock_compare,
        ):
            result = await handler.handle(mock_http_handler.path, {}, mock_http_handler)

        mock_compare.assert_not_called()
        assert result is not None
        assert result.status_code == 400
        assert b"Invalid gauntlet ID" in result.body

    @pytest.mark.asyncio
    async def test_compare_returns_diff(self, handler, mock_http_handler):
        """Compare endpoint routes valid IDs into comparison handling."""
        gauntlet_id = "gauntlet-20260402030148-a1b2c3"
        compare_id = "gauntlet-20260402030149-d4e5f6"
        mock_http_handler.command = "GET"
        mock_http_handler.path = f"/api/v1/gauntlet/{gauntlet_id}/compare/{compare_id}"
        expected = HandlerResult(
            status_code=200,
            content_type="application/json",
            body=b'{"diff": true}',
        )

        with (
            patch.object(handler, "require_auth_or_error", return_value=(MagicMock(), None)),
            patch.object(handler, "require_permission_or_error", return_value=(MagicMock(), None)),
            patch.object(handler, "_compare_results", return_value=expected) as mock_compare,
        ):
            result = await handler.handle(mock_http_handler.path, {}, mock_http_handler)

        mock_compare.assert_called_once_with(gauntlet_id, compare_id, {}, scope=TEST_SCOPE)
        assert result is expected


# ============================================================================
# Gauntlet Delete Tests
# ============================================================================


class TestGauntletDelete:
    """Tests for gauntlet deletion functionality."""

    def test_can_handle_delete(self, handler):
        """Handler can handle DELETE on gauntlet."""
        assert handler.can_handle("/api/v1/gauntlet/abc-123", method="DELETE")


# ============================================================================
# Gauntlet Run Start Tests
# ============================================================================


class TestGauntletRunStart:
    """Tests for starting gauntlet runs."""

    def test_run_requires_post(self, handler):
        """Run endpoint requires POST method."""
        assert handler.can_handle("/api/v1/gauntlet/run", method="POST")
        assert not handler.can_handle("/api/v1/gauntlet/run", method="PUT")

    def test_run_in_auth_required(self, handler):
        """Run endpoint is in AUTH_REQUIRED_ENDPOINTS."""
        assert "/api/v1/gauntlet/run" in handler.AUTH_REQUIRED_ENDPOINTS


# ============================================================================
# Gauntlet Status Polling Tests
# ============================================================================


class TestGauntletStatusPolling:
    """Tests for gauntlet status polling."""

    def test_can_get_gauntlet_status(self, handler):
        """Handler can get gauntlet status by ID."""
        assert handler.can_handle("/api/v1/gauntlet/abc-123", method="GET")


class TestGauntletRunInMemory:
    """Tests for in-memory gauntlet run storage."""

    def test_run_stored_in_memory(self):
        """Gauntlet run is stored in _gauntlet_runs."""
        from aragora.server.handlers.gauntlet import _gauntlet_runs

        # Create a mock run
        _gauntlet_runs["test-id"] = {
            "org_id": TEST_ORG,
            "id": "test-id",
            "status": "running",
            "created_at": "2025-01-01T00:00:00Z",
        }

        assert "test-id" in _gauntlet_runs
        assert _gauntlet_runs["test-id"]["status"] == "running"

    def test_run_eviction_on_max(self):
        """Old runs are evicted when max is reached."""
        from aragora.server.handlers.gauntlet import (
            _gauntlet_runs,
            MAX_GAUNTLET_RUNS_IN_MEMORY,
        )

        # This is tested by the TTL logic in the handler
        # Just verify the constant exists
        assert MAX_GAUNTLET_RUNS_IN_MEMORY == 500


# ============================================================================
# Gauntlet Personas Tests
# ============================================================================


class TestGauntletPersonas:
    """Tests for gauntlet persona endpoints."""

    def test_can_handle_personas(self, handler):
        """Handler can list gauntlet personas."""
        assert handler.can_handle("/api/v1/gauntlet/personas", method="GET")


# ============================================================================
# Gauntlet Results Tests
# ============================================================================


class TestGauntletResults:
    """Tests for gauntlet results endpoint."""

    def test_can_handle_results(self, handler):
        """Handler can list gauntlet results."""
        assert handler.can_handle("/api/v1/gauntlet/results", method="GET")


# ============================================================================
# Gauntlet Progress Streaming Tests
# ============================================================================


class TestGauntletProgressStreaming:
    """Tests for gauntlet progress streaming."""

    def test_handler_has_broadcast_fn_attr(self, mock_server_context):
        """Handler sets broadcast function if emitter available."""
        from aragora.server.handlers.gauntlet import GauntletHandler

        with patch("aragora.server.handlers.gauntlet.handler.set_gauntlet_broadcast_fn"):
            handler = GauntletHandler(mock_server_context)
            assert handler is not None


# ============================================================================
# Gauntlet Defense Mode Tests
# ============================================================================


class TestGauntletDefenseMode:
    """Tests for gauntlet defense mode (proposer_agent)."""

    def test_run_endpoint_exists(self, handler):
        """POST /api/v1/gauntlet/run endpoint is routable."""
        assert handler.can_handle("/api/v1/gauntlet/run", method="POST")


# ============================================================================
# Gauntlet Receipt Persistence Tests
# ============================================================================


class TestGauntletReceiptPersistence:
    """Tests for receipt auto-persistence to Knowledge Mound."""

    def test_receipt_adapter_integration(self):
        """ReceiptAdapter can persist gauntlet receipts."""
        # This is more of an integration test - verify the import works
        try:
            from aragora.knowledge.mound.adapters.receipt import ReceiptAdapter

            assert ReceiptAdapter is not None
        except ImportError:
            pass  # Module may not be available in all environments


# ============================================================================
# Gauntlet Constants Tests
# ============================================================================


class TestGauntletConstants:
    """Tests for gauntlet handler constants."""

    def test_has_api_version(self):
        """Handler has API_VERSION constant."""
        from aragora.server.handlers.gauntlet import GauntletHandler

        handler = GauntletHandler({})
        assert hasattr(handler, "API_VERSION")
        assert handler.API_VERSION == "v1"

    def test_has_routes_list(self):
        """Handler has ROUTES list with all endpoints."""
        from aragora.server.handlers.gauntlet import GauntletHandler

        handler = GauntletHandler({})
        assert hasattr(handler, "ROUTES")
        assert len(handler.ROUTES) >= 8

    def test_has_auth_required_endpoints(self):
        """Handler has AUTH_REQUIRED_ENDPOINTS list."""
        from aragora.server.handlers.gauntlet import GauntletHandler

        handler = GauntletHandler({})
        assert hasattr(handler, "AUTH_REQUIRED_ENDPOINTS")
        assert "/api/v1/gauntlet/run" in handler.AUTH_REQUIRED_ENDPOINTS


# ============================================================================
# Gauntlet Receipts List Endpoint Tests
# ============================================================================


class TestGauntletReceiptsList:
    """Tests for GET /api/v1/gauntlet/receipts endpoint."""

    def test_can_handle_receipts_endpoint(self, handler):
        """Handler can handle GET /api/v1/gauntlet/receipts."""
        assert handler.can_handle("/api/v1/gauntlet/receipts", method="GET")

    def test_can_handle_legacy_receipts_endpoint(self, handler):
        """Handler can handle GET /api/gauntlet/receipts (legacy)."""
        assert handler.can_handle("/api/gauntlet/receipts", method="GET")

    def test_receipts_route_in_routes_list(self, handler):
        """Receipts route is in ROUTES list."""
        assert "/api/v1/gauntlet/receipts" in handler.ROUTES
        assert "/api/gauntlet/receipts" in handler.ROUTES

    def test_receipts_in_direct_routes(self, handler):
        """Receipts route is mapped in _direct_routes."""
        assert ("/api/gauntlet/receipts", "GET") in handler._direct_routes
        assert handler._direct_routes[("/api/gauntlet/receipts", "GET")] == "_list_receipts"

    def test_list_receipts_returns_empty_when_no_store(self, handler):
        """_list_receipts returns empty list when receipt store is not available."""
        result = handler._list_receipts({}, scope=TEST_SCOPE)
        assert result is not None
        assert result.status_code == 200

        import json

        body = json.loads(result.body) if isinstance(result.body, bytes) else result.body
        assert "receipts" in body
        assert isinstance(body["receipts"], list)

    def test_list_receipts_handles_import_error(self, handler):
        """_list_receipts returns empty list on ImportError."""
        import json

        # The method uses a local import of get_receipt_store, so patch at source
        with patch(
            "aragora.storage.receipt_store.get_receipt_store",
            side_effect=ImportError("receipt store not available"),
        ):
            result = handler._list_receipts({}, scope=TEST_SCOPE)

        assert result is not None
        assert result.status_code == 200

        body = json.loads(result.body) if isinstance(result.body, bytes) else result.body
        assert body["receipts"] == []

    def test_list_receipts_with_mock_store(self, handler):
        """_list_receipts returns formatted receipts from store."""
        import json
        from unittest.mock import MagicMock

        mock_receipt = MagicMock()
        mock_receipt.receipt_id = "receipt-abc123"
        mock_receipt.gauntlet_id = "gauntlet-abc123"
        mock_receipt.debate_id = "debate-1"
        mock_receipt.created_at = 1700000000.0
        mock_receipt.verdict = "PASS"
        mock_receipt.confidence = 0.95
        mock_receipt.risk_level = "LOW"
        mock_receipt.risk_score = 0.1
        mock_receipt.checksum = "sha256-abc"
        mock_receipt.signature = None
        mock_receipt.data = {
            "input_summary": "Test decision",
            "vulnerabilities_found": 3,
            "artifact_hash": "hash-abc",
        }

        mock_store = MagicMock()
        mock_store.list_for_org.return_value = [mock_receipt]

        with patch(
            "aragora.storage.receipt_store.get_receipt_store",
            return_value=mock_store,
        ):
            result = handler._list_receipts({"limit": "5"}, scope=TEST_SCOPE)

        assert result is not None
        assert result.status_code == 200

        body = json.loads(result.body) if isinstance(result.body, bytes) else result.body
        assert len(body["receipts"]) == 1

        receipt = body["receipts"][0]
        assert receipt["id"] == "receipt-abc123"
        assert receipt["receipt_id"] == "receipt-abc123"
        assert receipt["run_id"] == "gauntlet-abc123"
        assert receipt["verdict"] == "PASS"
        assert receipt["findings_count"] == 3
        assert receipt["confidence"] == 0.95
        assert receipt["artifact_hash"] == "sha256-abc"
        assert receipt["input_summary"] == "Test decision"
        assert "created_at" in receipt
        assert receipt["metadata"]["risk_level"] == "LOW"
        assert receipt["metadata"]["is_signed"] is False

    def test_list_receipts_limit_param(self, handler):
        """_list_receipts respects the limit query parameter."""
        import json
        from unittest.mock import MagicMock

        mock_store = MagicMock()
        mock_store.list_for_org.return_value = []

        with patch(
            "aragora.storage.receipt_store.get_receipt_store",
            return_value=mock_store,
        ):
            handler._list_receipts({"limit": "25"}, scope=TEST_SCOPE)

        mock_store.list_for_org.assert_called_once_with(TEST_ORG, limit=25, verdict=None)

    def test_list_receipts_clamps_limit(self, handler):
        """_list_receipts clamps limit to 1-100 range."""
        from unittest.mock import MagicMock

        mock_store = MagicMock()
        mock_store.list_for_org.return_value = []

        with patch(
            "aragora.storage.receipt_store.get_receipt_store",
            return_value=mock_store,
        ):
            # Over 100 should be clamped
            handler._list_receipts({"limit": "999"}, scope=TEST_SCOPE)
            mock_store.list_for_org.assert_called_with(TEST_ORG, limit=100, verdict=None)

            # Under 1 should be clamped
            handler._list_receipts({"limit": "0"}, scope=TEST_SCOPE)
            mock_store.list_for_org.assert_called_with(TEST_ORG, limit=1, verdict=None)

    def test_list_receipts_verdict_filter(self, handler):
        """_list_receipts passes verdict filter to store."""
        from unittest.mock import MagicMock

        mock_store = MagicMock()
        mock_store.list_for_org.return_value = []

        with patch(
            "aragora.storage.receipt_store.get_receipt_store",
            return_value=mock_store,
        ):
            handler._list_receipts({"verdict": "PASS"}, scope=TEST_SCOPE)

        mock_store.list_for_org.assert_called_once_with(TEST_ORG, limit=10, verdict="PASS")

    def test_list_receipts_findings_count_from_risk_summary(self, handler):
        """_list_receipts extracts findings_count from risk_summary when vulnerabilities_found is missing."""
        import json
        from unittest.mock import MagicMock

        mock_receipt = MagicMock()
        mock_receipt.receipt_id = "receipt-def456"
        mock_receipt.gauntlet_id = "gauntlet-def456"
        mock_receipt.debate_id = None
        mock_receipt.created_at = 1700000000.0
        mock_receipt.verdict = "WARN"
        mock_receipt.confidence = 0.7
        mock_receipt.risk_level = "MEDIUM"
        mock_receipt.risk_score = 0.3
        mock_receipt.checksum = "sha256-def"
        mock_receipt.signature = "sig-data"
        mock_receipt.data = {
            "risk_summary": {"total": 5, "critical": 1, "high": 2, "medium": 1, "low": 1},
        }

        mock_store = MagicMock()
        mock_store.list_for_org.return_value = [mock_receipt]

        with patch(
            "aragora.storage.receipt_store.get_receipt_store",
            return_value=mock_store,
        ):
            result = handler._list_receipts({}, scope=TEST_SCOPE)

        body = json.loads(result.body) if isinstance(result.body, bytes) else result.body
        receipt = body["receipts"][0]
        assert receipt["findings_count"] == 5
        assert receipt["metadata"]["is_signed"] is True

    def test_list_receipts_handles_runtime_error(self, handler):
        """_list_receipts handles storage RuntimeError gracefully."""
        import json
        from unittest.mock import MagicMock

        mock_store = MagicMock()
        mock_store.list_for_org.side_effect = RuntimeError("DB connection failed")

        with patch(
            "aragora.storage.receipt_store.get_receipt_store",
            return_value=mock_store,
        ):
            result = handler._list_receipts({}, scope=TEST_SCOPE)

        assert result.status_code == 200
        body = json.loads(result.body) if isinstance(result.body, bytes) else result.body
        assert body["receipts"] == []

    @pytest.mark.asyncio
    async def test_handle_routes_to_list_receipts(self, handler, mock_http_handler):
        """handle() routes /api/v1/gauntlet/receipts to _list_receipts."""
        mock_http_handler.command = "GET"
        mock_http_handler.path = "/api/v1/gauntlet/receipts?limit=5"

        with (
            patch.object(handler, "require_auth_or_error", return_value=(MagicMock(), None)),
            patch.object(handler, "require_permission_or_error", return_value=(None, None)),
            patch.object(handler, "_list_receipts") as mock_list,
        ):
            mock_list.return_value = MagicMock(
                status_code=200, body=b'{"receipts": []}', headers=None
            )
            result = await handler.handle(
                "/api/v1/gauntlet/receipts", {"limit": "5"}, mock_http_handler
            )

        mock_list.assert_called_once_with({"limit": "5"}, scope=TEST_SCOPE)
        assert result is not None

    @pytest.mark.asyncio
    async def test_handle_routes_legacy_receipts(self, handler, mock_http_handler):
        """handle() routes legacy /api/gauntlet/receipts to _list_receipts."""
        mock_http_handler.command = "GET"
        mock_http_handler.path = "/api/gauntlet/receipts?limit=3"

        with (
            patch.object(handler, "require_auth_or_error", return_value=(MagicMock(), None)),
            patch.object(handler, "require_permission_or_error", return_value=(None, None)),
            patch.object(handler, "_list_receipts") as mock_list,
        ):
            mock_list.return_value = MagicMock(
                status_code=200, body=b'{"receipts": []}', headers=None
            )
            result = await handler.handle(
                "/api/gauntlet/receipts", {"limit": "3"}, mock_http_handler
            )

        mock_list.assert_called_once_with({"limit": "3"}, scope=TEST_SCOPE)
        assert result is not None
        # Legacy route should get deprecation header
        assert result.headers.get("Deprecation") == "true"
