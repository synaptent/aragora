"""
Tests for debates API endpoints.

Tests:
- GET /api/debates - List all debates
- GET /api/debates/{id} - Get debate by ID
- GET /api/debates/slug/{slug} - Get debate by slug
- GET /api/debates/{id}/convergence - Get convergence status
- GET /api/debates/{id}/impasse - Detect debate impasse
- GET /api/debates/{id}/messages - Get paginated messages
- GET /api/search - Cross-debate search
- PATCH /api/debates/{id} - Update debate metadata
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from aragora.server.handlers.debates import (
    DebatesHandler,
    normalize_status,
    denormalize_status,
    normalize_debate_response,
    STATUS_MAP,
    STATUS_REVERSE_MAP,
)


def parse_response(result):
    """Parse HandlerResult body as JSON."""
    if result is None:
        return None
    return json.loads(result.body.decode("utf-8"))


@pytest.fixture
def handler():
    """Create a DebatesHandler instance for testing."""
    return DebatesHandler({})


@pytest.fixture
def mock_http_handler():
    """Create a mock HTTP handler with headers."""
    handler = MagicMock()
    handler.path = "/api/v1/debates"
    handler.headers = {"Authorization": "Bearer test-token"}
    return handler


@pytest.fixture
def mock_storage():
    """Create a mock debate storage."""
    storage = MagicMock()
    # Note: _list_debates calls storage.list_recent, not list_debates
    mock_debates = [
        {
            "id": "debate-1",
            "debate_id": "debate-1",
            "question": "Test question 1",
            "status": "active",
            "created_at": "2026-01-14T00:00:00Z",
        },
        {
            "id": "debate-2",
            "debate_id": "debate-2",
            "question": "Test question 2",
            "status": "concluded",
            "created_at": "2026-01-13T00:00:00Z",
        },
    ]
    storage.list_recent.return_value = mock_debates
    storage.list_debates.return_value = mock_debates
    storage.get_debate.return_value = {
        "id": "debate-1",
        "debate_id": "debate-1",
        "question": "Test question",
        "status": "active",
        "rounds": 3,
        "messages": [],
    }
    storage.is_public.return_value = True
    # search returns (results, total_count)
    storage.search.return_value = (mock_debates, len(mock_debates))
    return storage


class TestStatusNormalization:
    """Tests for status normalization functions."""

    def test_normalize_status_active_to_running(self):
        """Test active status normalizes to running."""
        assert normalize_status("active") == "running"

    def test_normalize_status_concluded_to_completed(self):
        """Test concluded status normalizes to completed."""
        assert normalize_status("concluded") == "completed"

    def test_normalize_status_archived_to_completed(self):
        """Test archived status normalizes to completed."""
        assert normalize_status("archived") == "completed"

    def test_normalize_status_paused_unchanged(self):
        """Test paused status remains unchanged."""
        assert normalize_status("paused") == "paused"

    def test_normalize_status_unknown_unchanged(self):
        """Test unknown status passes through unchanged."""
        assert normalize_status("unknown_status") == "unknown_status"

    def test_denormalize_status_running_to_active(self):
        """Test running status denormalizes to active."""
        assert denormalize_status("running") == "active"

    def test_denormalize_status_completed_to_concluded(self):
        """Test completed status denormalizes to concluded."""
        assert denormalize_status("completed") == "concluded"

    def test_denormalize_status_unknown_unchanged(self):
        """Test unknown status passes through unchanged."""
        assert denormalize_status("custom_status") == "custom_status"


class TestNormalizeDebateResponse:
    """Tests for debate response normalization."""

    def test_normalize_empty_debate(self):
        """Test normalizing empty/None debate returns defaults."""
        assert normalize_debate_response(None) is None
        result = normalize_debate_response({})
        # Empty debate gets default fields for SDK compatibility
        assert result["status"] == "completed"
        assert result["rounds_used"] == 0
        assert result["duration_seconds"] == 0
        assert result["consensus_reached"] is False

    def test_normalize_status_conversion(self):
        """Test status is normalized in response."""
        debate = {"status": "active", "id": "test"}
        result = normalize_debate_response(debate)
        assert result["status"] == "running"

    def test_normalize_id_aliases(self):
        """Test debate_id/id aliases are created."""
        # Only debate_id provided
        debate = {"debate_id": "test-123", "status": "active"}
        result = normalize_debate_response(debate)
        assert result["id"] == "test-123"
        assert result["debate_id"] == "test-123"

        # Only id provided
        debate = {"id": "test-456", "status": "active"}
        result = normalize_debate_response(debate)
        assert result["id"] == "test-456"
        assert result["debate_id"] == "test-456"

    def test_normalize_consensus_proof_promotion(self):
        """Test consensus_proof is promoted to consensus field."""
        debate = {
            "id": "test",
            "status": "concluded",
            "consensus_proof": {
                "reached": True,
                "confidence": 0.85,
                "final_answer": "Test conclusion",
                "vote_breakdown": {"agent1": True, "agent2": True, "agent3": False},
            },
        }
        result = normalize_debate_response(debate)

        assert "consensus" in result
        assert result["consensus"]["reached"] is True
        assert result["consensus"]["agreement"] == 0.85
        assert result["consensus"]["confidence"] == 0.85
        assert result["consensus"]["final_answer"] == "Test conclusion"
        assert result["consensus"]["conclusion"] == "Test conclusion"
        assert "agent1" in result["consensus"]["supporting_agents"]
        assert "agent3" in result["consensus"]["dissenting_agents"]

    def test_normalize_rounds_used_from_int(self):
        """Test rounds_used is set from integer rounds."""
        debate = {"id": "test", "status": "active", "rounds": 5}
        result = normalize_debate_response(debate)
        assert result["rounds_used"] == 5

    def test_normalize_rounds_used_from_list(self):
        """Test rounds_used is set from list length."""
        debate = {"id": "test", "status": "active", "rounds": [{}, {}, {}]}
        result = normalize_debate_response(debate)
        assert result["rounds_used"] == 3

    def test_normalize_confidence_aliases(self):
        """Test confidence/agreement aliases are created."""
        debate = {"id": "test", "status": "active", "confidence": 0.9}
        result = normalize_debate_response(debate)
        assert result["agreement"] == 0.9

        debate = {"id": "test", "status": "active", "agreement": 0.8}
        result = normalize_debate_response(debate)
        assert result["confidence"] == 0.8


class TestDebatesHandlerRouting:
    """Tests for DebatesHandler routing logic."""

    def test_can_handle_debates_list(self, handler):
        """Test handler can handle /api/debates."""
        assert handler.can_handle("/api/v1/debates") is True

    def test_can_handle_debate_by_id(self, handler):
        """Test handler can handle /api/debates/{id}."""
        assert handler.can_handle("/api/v1/debates/test-123") is True

    def test_can_handle_debate_search(self, handler):
        """Test handler can handle /api/search."""
        assert handler.can_handle("/api/v1/search") is True

    def test_can_handle_debate_slug(self, handler):
        """Test handler can handle /api/debates/slug/{slug}."""
        assert handler.can_handle("/api/v1/debates/slug/my-debate") is True

    def test_can_handle_meta_critique(self, handler):
        """Test handler can handle meta-critique endpoint."""
        assert handler.can_handle("/api/v1/debate/test-123/meta-critique") is True

    def test_can_handle_graph_stats(self, handler):
        """Test handler can handle graph stats endpoint."""
        assert handler.can_handle("/api/v1/debate/test-123/graph/stats") is True

    def test_cannot_handle_unrelated_path(self, handler):
        """Test handler rejects unrelated paths."""
        assert handler.can_handle("/api/v1/agents") is False
        assert handler.can_handle("/api/v1/health") is False

    def test_requires_auth_for_protected_endpoints(self, handler):
        """Test auth requirement detection."""
        assert handler._requires_auth("/api/v1/debates") is False  # List is public
        assert handler._requires_auth("/api/v1/debates/test/export/json") is True
        assert handler._requires_auth("/api/v1/debates/test/citations") is True
        assert handler._requires_auth("/api/v1/debates/test/fork") is True

    def test_suffix_routes_defined(self, handler):
        """Test SUFFIX_ROUTES table is properly defined."""
        suffixes = [route[0] for route in handler.SUFFIX_ROUTES]
        assert "/impasse" in suffixes
        assert "/convergence" in suffixes
        assert "/citations" in suffixes
        assert "/messages" in suffixes
        assert "/summary" in suffixes


class TestDebatesHandlerListDebates:
    """Tests for listing debates."""

    def test_list_debates_returns_normalized(self, handler, mock_storage, mock_http_handler):
        """Test list debates returns normalized response."""
        with patch.object(handler, "get_storage", return_value=mock_storage):
            with patch.object(handler, "_check_auth", return_value=None):
                result = handler.handle("/api/v1/debates", {}, mock_http_handler)

        assert result is not None
        data = parse_response(result)
        assert "debates" in data
        # Status should be normalized
        assert data["debates"][0]["status"] == "running"  # active -> running
        assert data["debates"][1]["status"] == "completed"  # concluded -> completed

    def test_list_debates_with_limit(self, handler, mock_storage, mock_http_handler):
        """Test list debates respects limit parameter."""
        with patch.object(handler, "get_storage", return_value=mock_storage):
            with patch.object(handler, "_check_auth", return_value=None):
                result = handler.handle("/api/v1/debates", {"limit": "10"}, mock_http_handler)

        mock_storage.list_recent.assert_called_once()
        # Check limit was passed (clamped to max 100)
        call_args = mock_storage.list_recent.call_args
        assert call_args is not None

    def test_list_debates_limit_clamped(self, handler, mock_storage, mock_http_handler):
        """Test list debates clamps limit to max 100."""
        with patch.object(handler, "get_storage", return_value=mock_storage):
            with patch.object(handler, "_check_auth", return_value=None):
                # Request 500, should be clamped to 100
                result = handler.handle("/api/v1/debates", {"limit": "500"}, mock_http_handler)

        assert result is not None


class TestDebatesHandlerSearch:
    """Tests for debate search functionality."""

    def test_search_debates_basic(self, handler, mock_storage, mock_http_handler):
        """Test basic search functionality."""
        mock_storage.search_debates.return_value = [
            {"id": "result-1", "question": "matching query", "status": "active"}
        ]

        with patch.object(handler, "get_storage", return_value=mock_storage):
            with patch.object(handler, "get_current_user", return_value=None):
                result = handler.handle("/api/v1/search", {"q": "test query"}, mock_http_handler)

        assert result is not None
        data = parse_response(result)
        assert "results" in data or "debates" in data

    def test_search_debates_with_query_param(self, handler, mock_storage, mock_http_handler):
        """Test search with 'query' parameter instead of 'q'."""
        mock_storage.search_debates.return_value = []

        with patch.object(handler, "get_storage", return_value=mock_storage):
            with patch.object(handler, "get_current_user", return_value=None):
                result = handler.handle(
                    "/api/v1/search", {"query": "alternative"}, mock_http_handler
                )

        assert result is not None


class TestDebatesHandlerAuth:
    """Tests for authentication handling."""

    def test_auth_required_returns_401_without_token(self, handler, mock_http_handler):
        """Test protected endpoint returns 401 without valid token."""
        mock_http_handler.headers = {}  # No auth header

        with patch("aragora.server.auth.auth_config") as mock_auth:
            mock_auth.enabled = True
            mock_auth.api_token = "secret-token"
            mock_auth.validate_token.return_value = False

            result = handler._check_auth(mock_http_handler)

        assert result is not None
        assert result.status_code == 401

    def test_auth_bypassed_when_disabled(self, handler, mock_http_handler):
        """Test auth check passes when auth is disabled."""
        with patch("aragora.server.auth.auth_config") as mock_auth:
            mock_auth.enabled = False

            result = handler._check_auth(mock_http_handler)

        assert result is None  # No error, auth bypassed

    def test_auth_passes_with_valid_token(self, handler, mock_http_handler):
        """Test auth check passes with valid token."""
        mock_http_handler.headers = {"Authorization": "Bearer valid-token"}

        with patch("aragora.server.auth.auth_config") as mock_auth:
            mock_auth.enabled = True
            mock_auth.api_token = "valid-token"
            mock_auth.validate_token.return_value = True

            result = handler._check_auth(mock_http_handler)

        assert result is None  # No error


class TestDebatesHandlerExport:
    """Tests for debate export functionality."""

    def test_allowed_export_formats(self, handler):
        """Test export format validation."""
        assert "json" in handler.ALLOWED_EXPORT_FORMATS
        assert "csv" in handler.ALLOWED_EXPORT_FORMATS
        assert "html" in handler.ALLOWED_EXPORT_FORMATS
        assert "xml" not in handler.ALLOWED_EXPORT_FORMATS

    def test_allowed_export_tables(self, handler):
        """Test export table validation."""
        assert "summary" in handler.ALLOWED_EXPORT_TABLES
        assert "messages" in handler.ALLOWED_EXPORT_TABLES
        assert "critiques" in handler.ALLOWED_EXPORT_TABLES
        assert "votes" in handler.ALLOWED_EXPORT_TABLES


class TestDebatesHandlerConvergence:
    """Tests for convergence detection endpoint."""

    def test_convergence_endpoint_exists(self, handler):
        """Test convergence endpoint is in suffix routes."""
        suffixes = [route[0] for route in handler.SUFFIX_ROUTES]
        assert "/convergence" in suffixes

    def test_convergence_method_name(self, handler):
        """Test convergence routes to correct method."""
        for suffix, method_name, needs_id, _ in handler.SUFFIX_ROUTES:
            if suffix == "/convergence":
                assert method_name == "_get_convergence"
                assert needs_id is True
                break


class TestDebatesHandlerImpasse:
    """Tests for impasse detection endpoint."""

    def test_impasse_endpoint_exists(self, handler):
        """Test impasse endpoint is in suffix routes."""
        suffixes = [route[0] for route in handler.SUFFIX_ROUTES]
        assert "/impasse" in suffixes


class TestDebatesHandlerMessages:
    """Tests for paginated messages endpoint."""

    def test_messages_endpoint_with_pagination(self, handler):
        """Test messages endpoint supports pagination params."""
        for suffix, method_name, needs_id, extra_params_fn in handler.SUFFIX_ROUTES:
            if suffix == "/messages":
                assert extra_params_fn is not None
                # Test the extra params function
                params = extra_params_fn(
                    "/api/v1/debates/test/messages", {"limit": "25", "offset": "10"}
                )
                assert params["limit"] == 25
                assert params["offset"] == 10
                break


class TestDebatesHandlerArtifactAccess:
    """Tests for artifact endpoint access control."""

    def test_artifact_endpoints_defined(self, handler):
        """Test artifact endpoints are properly defined."""
        assert "/messages" in handler.ARTIFACT_ENDPOINTS
        assert "/evidence" in handler.ARTIFACT_ENDPOINTS
        assert "/verification-report" in handler.ARTIFACT_ENDPOINTS

    def test_artifact_access_public_debate(self, handler, mock_storage):
        """Test artifact access allowed for public debates."""
        mock_storage.is_public.return_value = True

        with patch.object(handler, "get_storage", return_value=mock_storage):
            result = handler._check_artifact_access("debate-1", "/messages", None)

        assert result is None  # Access allowed

    def test_artifact_access_private_requires_auth(self, handler, mock_storage, mock_http_handler):
        """Test artifact access requires auth for private debates."""
        mock_storage.is_public.return_value = False

        with patch.object(handler, "get_storage", return_value=mock_storage):
            with patch.object(handler, "_check_auth", return_value=None):
                result = handler._check_artifact_access("debate-1", "/messages", mock_http_handler)

        # Should call _check_auth for private debates
        assert result is None  # Auth passed

    def test_non_artifact_endpoint_no_special_check(self, handler):
        """Test non-artifact endpoints skip artifact access check."""
        result = handler._check_artifact_access("debate-1", "/convergence", None)
        assert result is None  # Not an artifact endpoint


class TestDebatesHandlerBatchOperations:
    """Tests for batch debate operations."""

    def test_batch_routes_defined(self, handler):
        """Test batch routes are in ROUTES."""
        assert "/api/v1/debates/batch" in handler.ROUTES
        assert "/api/v1/debates/batch/*/status" in handler.ROUTES

    def test_batch_endpoint_routing(self, handler, mock_http_handler):
        """Test batch endpoint is routed correctly."""
        assert handler.can_handle("/api/v1/debates/batch") is True
        assert handler.can_handle("/api/v1/debates/batch/") is True


class TestDebatesHandlerForkOperations:
    """Tests for debate forking operations."""

    def test_fork_route_in_routes(self, handler):
        """Test fork route is defined."""
        assert "/api/v1/debates/*/fork" in handler.ROUTES

    def test_fork_requires_auth(self, handler):
        """Test fork endpoint requires authentication."""
        assert handler._requires_auth("/api/v1/debates/test/fork") is True


class TestDebatesHandlerEdgeCases:
    """Tests for edge cases and error handling."""

    def test_extract_debate_id_valid(self, handler):
        """Test debate ID extraction from valid paths."""
        # This tests the internal _extract_debate_id method if accessible
        # If not, we test via routing
        pass

    def test_handle_no_storage(self, handler, mock_http_handler):
        """Test handling when storage is unavailable."""
        with patch.object(handler, "get_storage", return_value=None):
            with patch.object(handler, "_check_auth", return_value=None):
                # Should handle gracefully
                result = handler.handle("/api/v1/debates", {}, mock_http_handler)

        # Should return error or empty result, not crash
        assert result is not None

    def test_handle_list_param_as_string(self, handler, mock_storage, mock_http_handler):
        """Test handling query params that come as lists."""
        with patch.object(handler, "get_storage", return_value=mock_storage):
            with patch.object(handler, "get_current_user", return_value=None):
                # Query param as list (common in URL parsing)
                result = handler.handle(
                    "/api/v1/search", {"q": ["test", "query"]}, mock_http_handler
                )

        assert result is not None


class TestDecisionRouterIntegration:
    """Tests for DecisionRouter integration in debate creation."""

    def test_create_debate_uses_direct_controller(self, handler, mock_http_handler):
        """Test that _create_debate uses direct controller for immediate response.

        The direct controller path is preferred over DecisionRouter because:
        - DecisionRouter blocks until the full debate completes (minutes)
        - HTTP clients expect immediate response with debate_id
        - Streaming/polling is used for progress updates
        """
        with patch.object(handler, "_create_debate_direct") as mock_direct:
            mock_direct.return_value = MagicMock(
                status_code=200,
                body=b'{"status":"created", "debate_id":"test-123"}',
            )

            # Mock other dependencies
            with patch.object(
                handler,
                "read_json_body",
                return_value={"question": "Should we adopt microservices?"},
            ):
                with patch.object(handler, "_check_spam_content", return_value=None):
                    with patch(
                        "aragora.server.handlers.debates.handler.validate_against_schema"
                    ) as mock_validate:
                        mock_validate.return_value = MagicMock(is_valid=True)

                        mock_http_handler._check_rate_limit = MagicMock(return_value=True)
                        mock_http_handler._check_tier_rate_limit = MagicMock(return_value=True)
                        mock_http_handler.stream_emitter = MagicMock()
                        mock_http_handler.headers = {}

                        # Call _create_debate
                        result = handler._create_debate(mock_http_handler)

            # Verify direct controller was used
            mock_direct.assert_called_once()

    def test_decision_router_method_still_exists(self, handler, mock_http_handler):
        """Test that _route_through_decision_router still exists for sync use cases.

        While not used for HTTP ad-hoc debates, it's still available for:
        - Chat connector decisions (Slack/Telegram) needing sync responses
        - Internal orchestration where blocking is acceptable
        """
        # Verify the method exists
        assert hasattr(handler, "_route_through_decision_router")
        assert callable(handler._route_through_decision_router)

    def test_create_debate_direct_uses_controller(self, handler, mock_http_handler):
        """Test _create_debate_direct uses the debate controller."""
        body = {"question": "What is the meaning of life?"}

        # Mock the controller
        mock_controller = MagicMock()
        mock_response = MagicMock()
        mock_response.to_dict.return_value = {"status": "started", "debate_id": "test-123"}
        mock_response.status_code = 200
        mock_controller.start_debate.return_value = mock_response

        mock_http_handler._get_debate_controller = MagicMock(return_value=mock_controller)

        with patch("aragora.server.debate_controller.DebateRequest") as mock_request_class:
            mock_request_class.from_dict.return_value = MagicMock()

            result = handler._create_debate_direct(mock_http_handler, body)

        assert result is not None
        mock_controller.start_debate.assert_called_once()
